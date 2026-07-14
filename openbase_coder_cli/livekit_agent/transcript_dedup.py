"""STT wrapper that drops duplicate final transcripts of one utterance.

Some streaming STT paths deliver the same utterance twice — an unformatted
end-of-turn transcript followed by a formatted one. Each final becomes a user
chat message, so one utterance spawns two LLM generations (the 2026-07-13
dispatcher double-response incidents). The primary fix is requesting a single
formatted final from the provider; this wrapper is the provider-agnostic
safety net, and it also gives final transcripts an always-on log excerpt.
"""

import logging
import time

from livekit.agents import stt as livekit_stt
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS, NOT_GIVEN

from openbase_coder_cli.livekit_agent.text_normalization import (
    normalize_spoken_text,
    normalized_text_hash,
)

logger = logging.getLogger(__name__)

FINAL_TRANSCRIPT_DEDUP_WINDOW_SECONDS = 2.0


class FinalTranscriptDedupSTT(livekit_stt.STT):
    """Wraps an STT so consecutive near-identical finals collapse into one."""

    def __init__(self, wrapped: livekit_stt.STT) -> None:
        super().__init__(capabilities=wrapped.capabilities)
        self._wrapped = wrapped
        self._wrapped.on("metrics_collected", self._forward_metrics)
        self._wrapped.on("error", self._forward_error)

    @property
    def label(self) -> str:
        return self._wrapped.label

    @property
    def model(self) -> str:
        return self._wrapped.model

    @property
    def provider(self) -> str:
        return self._wrapped.provider

    def _forward_metrics(self, metrics) -> None:
        self.emit("metrics_collected", metrics)

    def _forward_error(self, error) -> None:
        self.emit("error", error)

    async def _recognize_impl(
        self,
        buffer,
        *,
        language=NOT_GIVEN,
        conn_options=DEFAULT_API_CONNECT_OPTIONS,
    ) -> livekit_stt.SpeechEvent:
        return await self._wrapped.recognize(
            buffer,
            language=language,
            conn_options=conn_options,
        )

    def stream(
        self,
        *,
        language=NOT_GIVEN,
        conn_options=DEFAULT_API_CONNECT_OPTIONS,
    ):
        return FinalTranscriptDedupStream(
            self._wrapped.stream(language=language, conn_options=conn_options),
            provider=self.provider,
        )

    def prewarm(self) -> None:
        self._wrapped.prewarm()

    async def aclose(self) -> None:
        await self._wrapped.aclose()


class FinalTranscriptDedupStream:
    def __init__(self, stream, *, provider: str) -> None:
        self._stream = stream
        self._provider = provider
        self._last_final_normalized = ""
        self._last_final_at = 0.0

    @property
    def start_time_offset(self) -> float:
        return self._stream.start_time_offset

    @start_time_offset.setter
    def start_time_offset(self, value: float) -> None:
        self._stream.start_time_offset = value

    @property
    def start_time(self) -> float:
        return self._stream.start_time

    @start_time.setter
    def start_time(self, value: float) -> None:
        self._stream.start_time = value

    def push_frame(self, frame) -> None:
        self._stream.push_frame(frame)

    def flush(self) -> None:
        self._stream.flush()

    def end_input(self) -> None:
        self._stream.end_input()

    async def aclose(self) -> None:
        await self._stream.aclose()

    def __aiter__(self):
        return self

    async def __anext__(self):
        while True:
            event = await self._stream.__anext__()
            if event.type != livekit_stt.SpeechEventType.FINAL_TRANSCRIPT:
                return event
            text = event.alternatives[0].text if event.alternatives else ""
            normalized = normalize_spoken_text(text)
            now = time.monotonic()
            deduped = bool(
                normalized
                and normalized == self._last_final_normalized
                and now - self._last_final_at <= FINAL_TRANSCRIPT_DEDUP_WINDOW_SECONDS
            )
            logger.info(
                "dispatch_timing stage=stt_final_transcript provider=%s "
                "deduped=%s text_len=%d normalized_hash=%s text_excerpt=%r",
                self._provider,
                deduped,
                len(text),
                normalized_text_hash(text),
                text[:160],
            )
            if deduped:
                continue
            if normalized:
                self._last_final_normalized = normalized
                self._last_final_at = now
            return event

    async def __aenter__(self):
        await self._stream.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc, exc_tb) -> None:
        await self._stream.__aexit__(exc_type, exc, exc_tb)
