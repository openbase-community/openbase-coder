"""Prompt users toward the openbase-onboarding skill until it has been read.

The bundled ``openbase-onboarding`` skill instructs the reading agent to
create ``~/.openbase/onboarding-skill-read`` as soon as the skill is read,
even if onboarding is not completed. Until that marker exists, every user
message bound for the dispatcher gets a note appended requiring the agent
to ask the user to complete or skip onboarding; skipping creates the same
marker directly.
"""

from __future__ import annotations

from openbase_coder_cli.paths import ONBOARDING_SKILL_READ_MARKER_PATH

ONBOARDING_REMINDER = (
    "[Openbase system note: onboarding is pending on this machine — the "
    "openbase-onboarding skill has never been read here. Act on this in "
    "this reply: after addressing the user's message, ask them to choose "
    "between completing onboarding now and skipping it. Do not ignore this "
    "note or postpone the question. If they choose to complete it, read and "
    "follow the openbase-onboarding skill. If they choose to skip, create "
    "the empty marker file ~/.openbase/onboarding-skill-read yourself. "
    "Either action removes this note from future messages.]"
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
