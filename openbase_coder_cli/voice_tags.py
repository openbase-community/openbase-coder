"""The ``<voice>`` tag convention for live speech input.

When the user talks to an agent over a LiveKit voice session, what they say
is wrapped in ``<voice>`` tags before it becomes the turn prompt. The
``responding-to-voice-tag`` skill bundled with Openbase teaches agents —
the dispatcher and Super Agents alike, on any coding backend — how to respond
to voice-tagged input. This replaces the earlier per-backend injection of a
voice instructions file.
"""

from __future__ import annotations

VOICE_TAG_OPEN = "<voice>"
VOICE_TAG_CLOSE = "</voice>"


def wrap_voice_prompt(prompt: str) -> str:
    """Mark a turn prompt as a live speech transcription."""
    return f"{VOICE_TAG_OPEN}{prompt}{VOICE_TAG_CLOSE}"
