"""Shared logging helpers for LiveKit agent diagnostics."""

import hashlib

from livekit import rtc

from openbase_coder_cli.livekit_agent.config import (
    LIVEKIT_AUDIO_FRAME_LOG_EVERY,
    LIVEKIT_AUDIO_FRAME_LOG_FIRST,
    LIVEKIT_VERBOSE_LOGGING,
)


def _should_log_audio_frame(frame_count: int) -> bool:
    return LIVEKIT_VERBOSE_LOGGING and (
        frame_count <= LIVEKIT_AUDIO_FRAME_LOG_FIRST
        or LIVEKIT_AUDIO_FRAME_LOG_EVERY <= 1
        or frame_count % LIVEKIT_AUDIO_FRAME_LOG_EVERY == 0
    )


def _frame_duration_ms(frame: rtc.AudioFrame) -> int:
    sample_rate = getattr(frame, "sample_rate", 0) or 0
    samples_per_channel = getattr(frame, "samples_per_channel", 0) or 0
    if not sample_rate:
        return 0
    return int(samples_per_channel / sample_rate * 1000)


def _event_text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12] if text else ""
