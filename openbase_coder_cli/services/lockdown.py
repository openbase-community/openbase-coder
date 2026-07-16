"""Locked-down mode: no permission bypasses until the safe phrase is heard.

Locked-down mode is an Openbase setting (``console-settings.json``,
default off; onboarding offers to enable it). While it is enabled and not
unlocked, the machine-wide super-agents permission guard stays *restricted*,
so no Super Agents launch — from the dispatcher's MCP tools or from the
voice pipeline — can use ``--yolo``-style bypasses (``approvalPolicy:
never``, ``danger-full-access`` sandboxes, or Claude's
``bypassPermissions``); launches are downgraded to gated approvals instead.

The only unlock signal is the safe phrase heard in the *direct* STT
transcript of the live voice session. Agent-generated or paraphrased text
never unlocks: detection runs on the raw transcription events, before the
speech is handed to any model. Each new voice session re-arms the
restriction.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from super_agents.permission_guard import (
    read_permission_guard,
    write_permission_guard,
)

from openbase_coder_cli.services.console_settings import (
    get_lockdown_safe_phrase,
    get_locked_down_mode,
)

logger = logging.getLogger(__name__)

LOCKDOWN_GUARD_REASON = "Openbase locked-down mode"


def lockdown_restricted() -> bool:
    """Whether launches are currently restricted by locked-down mode."""
    if not get_locked_down_mode():
        return False
    return read_permission_guard().get("restricted") is True


def sync_lockdown_guard(*, relock: bool = False) -> bool:
    """Align the super-agents permission guard with the lockdown setting.

    With locked-down mode off, any lockdown-owned restriction is lifted.
    With it on, the guard is armed — except that an existing unlock is
    preserved unless ``relock`` is set (used when a new voice session
    starts). Returns whether the guard is restricted afterwards.
    """
    guard = read_permission_guard()
    if not get_locked_down_mode():
        if (
            guard.get("restricted") is True
            and guard.get("reason") == LOCKDOWN_GUARD_REASON
        ):
            write_permission_guard({**guard, "restricted": False})
            logger.info("Locked-down mode off; permission guard lifted.")
        return False
    if (
        not relock
        and guard.get("restricted") is False
        and guard.get("reason") == LOCKDOWN_GUARD_REASON
    ):
        return False
    write_permission_guard(
        {
            **guard,
            "restricted": True,
            "reason": LOCKDOWN_GUARD_REASON,
            "armedAt": _iso_now(),
        }
    )
    return True


def record_direct_transcript(transcript: str) -> bool:
    """Unlock the guard when the safe phrase appears in a final transcript.

    Must only ever be called with verbatim STT output. Returns True when
    this transcript just unlocked the guard.
    """
    if not get_locked_down_mode():
        return False
    phrase = get_lockdown_safe_phrase()
    if not phrase or not transcript_contains_phrase(transcript, phrase):
        return False
    guard = read_permission_guard()
    if guard.get("restricted") is not True:
        return False
    write_permission_guard(
        {
            **guard,
            "restricted": False,
            "reason": LOCKDOWN_GUARD_REASON,
            "unlockedAt": _iso_now(),
        }
    )
    logger.info(
        "Lockdown safe phrase heard in direct transcript; permission guard unlocked."
    )
    return True


def transcript_contains_phrase(transcript: str, phrase: str) -> bool:
    normalized_phrase = _normalize_speech(phrase)
    if not normalized_phrase:
        return False
    return normalized_phrase in _normalize_speech(transcript)


def _normalize_speech(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


def _iso_now() -> str:
    return (
        datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    )
