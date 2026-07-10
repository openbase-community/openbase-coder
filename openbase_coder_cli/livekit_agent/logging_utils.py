"""Shared logging helpers for LiveKit agent diagnostics."""

import hashlib
import re

from livekit import rtc

from openbase_coder_cli.livekit_agent.config import (
    LIVEKIT_AUDIO_FRAME_LOG_EVERY,
    LIVEKIT_AUDIO_FRAME_LOG_FIRST,
    LIVEKIT_VERBOSE_LOGGING,
)

_SECRET_VALUE_RE = re.compile(
    r"(?i)\b(authorization|x-api-key|api[_-]?key|token|access[_-]?token)"
    r"(['\"]?\s*[:=]\s*['\"]?)([^'\"\s,)}\]]+)"
)
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[-._~+/=A-Za-z0-9]+")
_QUERY_SECRET_RE = re.compile(
    r"(?i)([?&](?:api[_-]?key|token|access[_-]?token|machine[_-]?token)=)"
    r"([^&#\s]+)"
)


def redact_exception_text(value: object) -> str:
    """Return exception/log text with bearer tokens and auth headers removed."""
    text = str(value)
    text = _SECRET_VALUE_RE.sub(r"\1\2[redacted]", text)
    text = _BEARER_RE.sub("Bearer [redacted]", text)
    return _QUERY_SECRET_RE.sub(r"\1[redacted]", text)


def exception_chain_summary(exc: BaseException) -> str:
    """Compact, redacted summary of an exception and its causal chain."""
    items: list[str] = []
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        items.append(f"{type(current).__name__}: {redact_exception_text(current)}")
        current = current.__cause__ or current.__context__
    return " <- ".join(items)


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
