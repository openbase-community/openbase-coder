"""Prompt users toward the openbase-onboarding skill until it has been read.

The bundled ``openbase-onboarding`` skill instructs the reading agent to
create ``~/.openbase/onboarding-skill-read`` as soon as the skill is read,
even if onboarding is not completed. Until that marker exists, every user
message bound for the dispatcher gets a short note appended prompting the
agent to offer onboarding via that skill.
"""

from __future__ import annotations

from openbase_coder_cli.paths import ONBOARDING_SKILL_READ_MARKER_PATH

ONBOARDING_REMINDER = (
    "[Openbase system note: this user has not been onboarded yet — the "
    "openbase-onboarding skill has never been read on this machine. Unless "
    "the user's message clearly requires otherwise, offer to walk them "
    "through setup now, and if they agree, read and follow the "
    "openbase-onboarding skill. Reading that skill creates the marker file "
    "that removes this note from future messages.]"
)


def onboarding_skill_read() -> bool:
    """Whether the openbase-onboarding skill has been read on this machine."""
    return ONBOARDING_SKILL_READ_MARKER_PATH.exists()


def append_onboarding_reminder(prompt: str) -> str:
    """Append the onboarding reminder to a dispatcher-bound user message."""
    if onboarding_skill_read():
        return prompt
    if ONBOARDING_REMINDER in prompt:
        return prompt
    return f"{prompt}\n\n{ONBOARDING_REMINDER}"
