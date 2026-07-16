from __future__ import annotations

import asyncio
import hashlib
import re
from dataclasses import dataclass
from typing import Any

from openbase_coder_cli.livekit_agent.speech_formatter import (
    SpeechFormatOptions,
    format_for_speech,
)

LIVEKIT_DUPLICATE_TURN_GRACE_SECONDS = 1.5
SUPER_AGENT_IDENTITY_INSTRUCTION_PREFIX = "Super Agent thread name:"
LEGACY_SUPER_AGENT_IDENTITY_INSTRUCTION_PREFIX = "Super Agent name:"
SUPER_AGENT_AGENT_NAME_INSTRUCTION_PREFIX = "Your name is "


@dataclass
class _ActiveTurn:
    turn_id: str
    completed: asyncio.Future[dict[str, Any]]
    prompt: str
    started_at: float
    dispatch_id: str = ""
    delivered_text: str = ""
    agent_messages: list[str] | None = None


@dataclass
class _StartingTurn:
    prompt: str
    started_at: float
    task: asyncio.Task[dict[str, Any]]
    dispatch_id: str


def _is_no_active_turn_error(exc: BaseException) -> bool:
    message = str(exc).lower()
    return (
        isinstance(exc, RuntimeError)
        and "no active turn" in message
        and ("interrupt" in message or "steer" in message)
    )


def _super_agent_name(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    return " ".join(value.split()) or None


def _with_super_agent_identity_instructions(
    developer_instructions: str | None,
    name: str | None,
    agent_name: str | None = None,
) -> str | None:
    normalized_name = _super_agent_name(name)
    normalized_agent_name = _super_agent_name(agent_name)
    if not normalized_name and not normalized_agent_name:
        return developer_instructions
    identity_lines: list[str] = []
    if normalized_name:
        identity_lines.append(
            f"{SUPER_AGENT_IDENTITY_INSTRUCTION_PREFIX} {normalized_name}"
        )
    if normalized_agent_name:
        identity_lines.append(
            f"{SUPER_AGENT_AGENT_NAME_INSTRUCTION_PREFIX}{normalized_agent_name}."
        )
    base = _without_super_agent_identity_lines(developer_instructions)
    if not base:
        return "\n".join(identity_lines)
    return f"{base}\n\n{chr(10).join(identity_lines)}"


def _without_super_agent_identity_lines(value: str | None) -> str:
    if not value:
        return ""
    return "\n".join(
        line
        for line in value.strip().splitlines()
        if not _is_super_agent_identity_line(line)
    ).strip()


def _is_super_agent_identity_line(line: str) -> bool:
    stripped = line.strip()
    return (
        stripped.startswith(SUPER_AGENT_IDENTITY_INSTRUCTION_PREFIX)
        or stripped.startswith(LEGACY_SUPER_AGENT_IDENTITY_INSTRUCTION_PREFIX)
        or (
            stripped.startswith(SUPER_AGENT_AGENT_NAME_INSTRUCTION_PREFIX)
            and stripped.endswith(".")
        )
    )


def _is_turn_cannot_accept_steering_error(exc: BaseException) -> bool:
    message = str(exc).lower()
    return (
        isinstance(exc, RuntimeError)
        and "steer" in message
        and ("cannot accept" in message or "can't accept" in message)
    )


def _active_turn_id_mismatch(exc: BaseException) -> str | None:
    if not isinstance(exc, RuntimeError):
        return None

    match = re.search(
        r"expected active turn id `[^`]+` but found `([^`]+)`",
        str(exc),
        flags=re.IGNORECASE,
    )
    return match.group(1) if match else None


def _undelivered_suffix(delivered_text: str, current_text: str) -> str:
    """Return only the portion of current_text that has not been emitted yet."""
    if not current_text:
        return ""
    if not delivered_text:
        return current_text
    if current_text.startswith(delivered_text):
        return current_text[len(delivered_text) :]
    return current_text


def _normalize_prompt(text: str) -> str:
    text = re.sub(r"[^\w\s]", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip().lower()


def _prompt_debug_fields(prompt: str) -> dict[str, Any]:
    normalized = _normalize_prompt(prompt)
    return {
        "hash": hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12],
        "length": len(prompt),
        "excerpt": normalized[:90],
    }


def _speech_excerpt(text: str, *, max_chars: int = 1600) -> str:
    """Return a voice-safe version of a completed Codex response."""
    return format_for_speech(text, SpeechFormatOptions(max_chars=max_chars))
