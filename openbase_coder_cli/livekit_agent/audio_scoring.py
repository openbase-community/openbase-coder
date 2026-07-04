"""Brain score audio sampling: STT wrapper, chunk scorer, and score uploads."""

import asyncio
import contextlib
import json
import logging
import tempfile
import time
import uuid
import wave
from collections.abc import Mapping
from pathlib import Path

import aiohttp
from livekit import rtc
from livekit.agents import (
    stt as livekit_stt,
)
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS, NOT_GIVEN

from openbase_coder_cli.brain_score import (
    brain_score_token_configured,
    load_brain_score_token,
)
from openbase_coder_cli.livekit_agent.config import (
    BRAIN_SCORE_COOLDOWN_SECONDS,
    BRAIN_SCORE_ENABLED,
    BRAIN_SCORE_ENDPOINT,
    BRAIN_SCORE_INTERVAL_SECONDS,
    BRAIN_SCORE_LATITUDE,
    BRAIN_SCORE_LONGITUDE,
    BRAIN_SCORE_MIN_DURATION_SECONDS,
    BRAIN_SCORE_OUTPUT_PATH,
    BRAIN_SCORE_TOKEN_FILE,
)

logger = logging.getLogger(__name__)


def _load_brain_score_token() -> str:
    return load_brain_score_token()


def _brain_score_enabled() -> bool:
    return BRAIN_SCORE_ENABLED and brain_score_token_configured()


class BrainScoreSTT(livekit_stt.STT):
    """STT wrapper that samples incoming mic audio into periodic brain score uploads."""

    def __init__(self, wrapped: livekit_stt.STT) -> None:
        super().__init__(capabilities=wrapped.capabilities)
        self._wrapped = wrapped
        self._scorer = BrainScoreAudioScorer()
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
        return BrainScoreRecognizeStream(
            self._wrapped.stream(language=language, conn_options=conn_options),
            scorer=self._scorer,
        )

    def prewarm(self) -> None:
        self._wrapped.prewarm()

    async def aclose(self) -> None:
        await self._scorer.aclose()
        await self._wrapped.aclose()


class BrainScoreRecognizeStream:
    def __init__(self, stream, *, scorer: "BrainScoreAudioScorer") -> None:
        self._stream = stream
        self._scorer = scorer

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

    def push_frame(self, frame: rtc.AudioFrame) -> None:
        self._scorer.push_frame(frame)
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
        return await self._stream.__anext__()

    async def __aenter__(self):
        await self._stream.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc, exc_tb) -> None:
        await self._stream.__aexit__(exc_type, exc, exc_tb)


class BrainScoreAudioScorer:
    def __init__(
        self,
        *,
        interval_seconds: float = BRAIN_SCORE_INTERVAL_SECONDS,
        min_duration_seconds: float = BRAIN_SCORE_MIN_DURATION_SECONDS,
        cooldown_seconds: float = BRAIN_SCORE_COOLDOWN_SECONDS,
        output_path: Path = BRAIN_SCORE_OUTPUT_PATH,
        endpoint: str = BRAIN_SCORE_ENDPOINT,
    ) -> None:
        self._enabled = BRAIN_SCORE_ENABLED and interval_seconds > 0
        self._interval_seconds = interval_seconds
        self._min_duration_seconds = max(0.0, min_duration_seconds)
        self._cooldown_seconds = max(0.0, cooldown_seconds)
        self._output_path = output_path
        self._endpoint = endpoint
        self._frames: list[bytes] = []
        self._sample_rate: int | None = None
        self._num_channels: int | None = None
        self._samples_per_channel = 0
        self._chunk_index = 0
        self._tasks: set[asyncio.Task[None]] = set()
        self._disabled_reason_logged = False
        self._last_measurement_started_at = 0.0

    def push_frame(self, frame: rtc.AudioFrame) -> None:
        try:
            self._push_frame(frame)
        except Exception:
            logger.warning(
                "brain_score stage=schedule_failed endpoint=%s output_path=%s",
                self._endpoint,
                self._output_path,
                exc_info=True,
            )
            self._reset()

    def _push_frame(self, frame: rtc.AudioFrame) -> None:
        if not self._enabled:
            return

        sample_rate = int(getattr(frame, "sample_rate", 0) or 0)
        num_channels = int(getattr(frame, "num_channels", 0) or 0)
        samples_per_channel = int(getattr(frame, "samples_per_channel", 0) or 0)
        if sample_rate <= 0 or num_channels <= 0 or samples_per_channel <= 0:
            return

        if self._frames and (
            sample_rate != self._sample_rate or num_channels != self._num_channels
        ):
            self._schedule_current_chunk(reason="format_change")

        self._sample_rate = sample_rate
        self._num_channels = num_channels
        self._samples_per_channel += samples_per_channel
        self._frames.append(bytes(frame.data))

        if self._samples_per_channel / sample_rate >= self._interval_seconds:
            self._schedule_current_chunk(reason="interval")

    async def aclose(self) -> None:
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    def _schedule_current_chunk(self, *, reason: str) -> None:
        if not self._frames or self._sample_rate is None or self._num_channels is None:
            self._reset()
            return

        duration_seconds = self._samples_per_channel / self._sample_rate
        sample_rate = self._sample_rate
        num_channels = self._num_channels
        if duration_seconds < self._min_duration_seconds:
            logger.info(
                "brain_score stage=skipped reason=below_min_duration "
                "duration_seconds=%.3f min_duration_seconds=%.3f sample_rate=%d "
                "num_channels=%d trigger=%s endpoint=%s",
                duration_seconds,
                self._min_duration_seconds,
                sample_rate,
                num_channels,
                reason,
                self._endpoint,
            )
            self._reset()
            return

        cooldown_remaining = self._cooldown_remaining_seconds()
        if cooldown_remaining > 0:
            logger.info(
                "brain_score stage=skipped reason=cooldown "
                "remaining_seconds=%.3f cooldown_seconds=%.3f "
                "duration_seconds=%.3f sample_rate=%d num_channels=%d "
                "trigger=%s endpoint=%s output_path=%s",
                cooldown_remaining,
                self._cooldown_seconds,
                duration_seconds,
                sample_rate,
                num_channels,
                reason,
                self._endpoint,
                self._output_path,
            )
            self._reset()
            return

        token = _load_brain_score_token()
        if not token:
            if not self._disabled_reason_logged:
                logger.info(
                    "brain_score stage=disabled reason=missing_token token_file=%s endpoint=%s",
                    BRAIN_SCORE_TOKEN_FILE,
                    self._endpoint,
                )
                self._disabled_reason_logged = True
            self._reset()
            return

        wav_path = self._write_wav_chunk()
        self._chunk_index += 1
        chunk_index = self._chunk_index
        self._last_measurement_started_at = time.time()
        self._reset()

        task = asyncio.create_task(
            _upload_brain_score_chunk(
                wav_path=wav_path,
                token=token,
                endpoint=self._endpoint,
                output_path=self._output_path,
                chunk_index=chunk_index,
                duration_seconds=duration_seconds,
                sample_rate=sample_rate,
                num_channels=num_channels,
                reason=reason,
            )
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _write_wav_chunk(self) -> Path:
        assert self._sample_rate is not None
        assert self._num_channels is not None
        tmp = tempfile.NamedTemporaryFile(
            prefix="openbase-brain-score-",
            suffix=".wav",
            delete=False,
        )
        tmp_path = Path(tmp.name)
        tmp.close()
        with wave.open(str(tmp_path), "wb") as wav_file:
            wav_file.setnchannels(self._num_channels)
            wav_file.setsampwidth(2)
            wav_file.setframerate(self._sample_rate)
            wav_file.writeframes(b"".join(self._frames))
        return tmp_path

    def _reset(self) -> None:
        self._frames = []
        self._sample_rate = None
        self._num_channels = None
        self._samples_per_channel = 0

    def _cooldown_remaining_seconds(self) -> float:
        if self._cooldown_seconds <= 0:
            return 0.0

        now = time.time()
        last_measurement_at = max(
            self._last_measurement_started_at,
            _last_brain_score_update_at(self._output_path) or 0.0,
        )
        if last_measurement_at <= 0:
            return 0.0
        return max(0.0, self._cooldown_seconds - (now - last_measurement_at))


def _last_brain_score_update_at(path: Path) -> float | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    updated_at = payload.get("updated_at")
    if isinstance(updated_at, (int, float)):
        return float(updated_at)
    return None


async def _upload_brain_score_chunk(
    *,
    wav_path: Path,
    token: str,
    endpoint: str,
    output_path: Path,
    chunk_index: int,
    duration_seconds: float,
    sample_rate: int,
    num_channels: int,
    reason: str,
) -> None:
    started = time.monotonic()
    try:
        logger.info(
            "brain_score stage=upload_start chunk_index=%d endpoint=%s "
            "duration_seconds=%.3f sample_rate=%d num_channels=%d reason=%s "
            "output_path=%s",
            chunk_index,
            endpoint,
            duration_seconds,
            sample_rate,
            num_channels,
            reason,
            output_path,
        )
        form = aiohttp.FormData()
        if BRAIN_SCORE_LATITUDE:
            form.add_field("latitude", BRAIN_SCORE_LATITUDE)
        if BRAIN_SCORE_LONGITUDE:
            form.add_field("longitude", BRAIN_SCORE_LONGITUDE)
        form.add_field(
            "audio",
            wav_path.read_bytes(),
            filename="livekit-brain-score.wav",
            content_type="application/octet-stream",
        )
        async with aiohttp.ClientSession() as session:
            async with session.post(
                endpoint,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                },
                data=form,
                timeout=aiohttp.ClientTimeout(total=120),
            ) as response:
                response_text = await response.text()
                response_status = response.status
        try:
            response_payload = json.loads(response_text)
        except json.JSONDecodeError:
            response_payload = {}
        data = (
            response_payload.get("data") if isinstance(response_payload, dict) else {}
        )
        scores = data.get("scores") if isinstance(data, dict) else {}
        brain_readiness = (
            scores.get("brain_readiness") if isinstance(scores, dict) else {}
        )
        brs = brain_readiness.get("brs") if isinstance(brain_readiness, dict) else None
        response_status_code = (
            response_payload.get("statusCode")
            if isinstance(response_payload, dict)
            else None
        )
        response_message = (
            response_payload.get("message")
            if isinstance(response_payload, dict)
            else None
        )
        if response_status >= 400 or brs is None:
            logger.warning(
                "brain_score stage=score_failed chunk_index=%d brs=%s "
                "http_status=%s statusCode=%s message=%s endpoint=%s "
                "output_path=%s duration_seconds=%.3f elapsed_ms=%d "
                "response_text_len=%d",
                chunk_index,
                brs,
                response_status,
                response_status_code,
                response_message,
                endpoint,
                output_path,
                duration_seconds,
                int((time.monotonic() - started) * 1000),
                len(response_text),
            )
            return
        result = {
            "brs": brs,
            "http_status": response_status,
            "statusCode": response_status_code,
            "message": response_message,
            "session_id": data.get("session_id") if isinstance(data, dict) else None,
            "computed_at": data.get("computed_at") if isinstance(data, dict) else None,
            "chunk_index": chunk_index,
            "duration_seconds": duration_seconds,
            "sample_rate": sample_rate,
            "num_channels": num_channels,
            "updated_at": time.time(),
        }
        try:
            _write_brain_score_json(output_path, result)
        except Exception:
            logger.warning(
                "brain_score stage=write_failed chunk_index=%d brs=%s "
                "http_status=%s endpoint=%s output_path=%s duration_seconds=%.3f",
                chunk_index,
                brs,
                response_status,
                endpoint,
                output_path,
                duration_seconds,
                exc_info=True,
            )
            return
        logger.info(
            "brain_score stage=uploaded chunk_index=%d brs=%s http_status=%s "
            "duration_seconds=%.3f sample_rate=%d num_channels=%d reason=%s "
            "elapsed_ms=%d endpoint=%s output_path=%s",
            chunk_index,
            brs,
            response_status,
            duration_seconds,
            sample_rate,
            num_channels,
            reason,
            int((time.monotonic() - started) * 1000),
            endpoint,
            output_path,
        )
    except Exception:
        logger.warning(
            "brain_score stage=upload_failed chunk_index=%d endpoint=%s "
            "output_path=%s duration_seconds=%.3f elapsed_ms=%d",
            chunk_index,
            endpoint,
            output_path,
            duration_seconds,
            int((time.monotonic() - started) * 1000),
            exc_info=True,
        )
    finally:
        with contextlib.suppress(OSError):
            wav_path.unlink()


def _write_brain_score_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    tmp_path.replace(path)
