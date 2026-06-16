from __future__ import annotations

import asyncio
import tempfile
import uuid
import wave
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from livekit import rtc
from livekit.agents import stt as livekit_stt
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS, NOT_GIVEN

STTProviderId = Literal["assemblyai", "deepgram", "local_mlx_whisper"]

ASSEMBLYAI_STT_PROVIDER_ID = "assemblyai"
DEEPGRAM_STT_PROVIDER_ID = "deepgram"
LOCAL_MLX_WHISPER_STT_PROVIDER_ID = "local_mlx_whisper"
DEFAULT_STT_PROVIDER_ID: STTProviderId = ASSEMBLYAI_STT_PROVIDER_ID
LOCAL_MLX_WHISPER_MODEL_ID = "mlx-community/whisper-small.en-mlx"
LOCAL_MLX_WHISPER_PROMPT = (
    "Openbase Coder voice coding vocabulary: Gabe, Openbase, Kokoro, Cartesia, "
    "Codex, LiveKit, TTS, STT, Python, React, TypeScript, Swift, Django, pytest, "
    "uv, pnpm, GitHub, pull request."
)


@dataclass(frozen=True)
class STTDownloadStatus:
    provider: STTProviderId
    ready: bool
    model: str
    detail: str | None = None

    def payload(self) -> dict[str, str | bool | None]:
        return asdict(self)


@dataclass(frozen=True)
class STTProviderOption:
    id: STTProviderId
    name: str
    local: bool
    model: str | None = None

    def payload(self) -> dict[str, str | bool | None]:
        return asdict(self)


STT_PROVIDER_OPTIONS: tuple[STTProviderOption, ...] = (
    STTProviderOption(ASSEMBLYAI_STT_PROVIDER_ID, "AssemblyAI", False),
    STTProviderOption(DEEPGRAM_STT_PROVIDER_ID, "Deepgram", False),
    STTProviderOption(
        LOCAL_MLX_WHISPER_STT_PROVIDER_ID,
        "Local MLX Whisper",
        True,
        LOCAL_MLX_WHISPER_MODEL_ID,
    ),
)


def normalize_stt_provider_id(provider_id: str | None) -> STTProviderId:
    normalized = (provider_id or DEFAULT_STT_PROVIDER_ID).strip().lower()
    if normalized in {"local", "mlx", "mlx_whisper"}:
        normalized = LOCAL_MLX_WHISPER_STT_PROVIDER_ID
    if normalized not in {provider.id for provider in STT_PROVIDER_OPTIONS}:
        raise ValueError(
            "STT provider must be one of: assemblyai, deepgram, local_mlx_whisper."
        )
    return normalized  # type: ignore[return-value]


def stt_provider_options_payload() -> list[dict[str, str | bool | None]]:
    return [provider.payload() for provider in STT_PROVIDER_OPTIONS]


def local_mlx_whisper_readiness() -> STTDownloadStatus:
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        return STTDownloadStatus(
            provider=LOCAL_MLX_WHISPER_STT_PROVIDER_ID,
            ready=False,
            model=LOCAL_MLX_WHISPER_MODEL_ID,
            detail="MLX Whisper dependencies are not installed.",
        )

    try:
        snapshot_download(LOCAL_MLX_WHISPER_MODEL_ID, local_files_only=True)
    except Exception:
        return STTDownloadStatus(
            provider=LOCAL_MLX_WHISPER_STT_PROVIDER_ID,
            ready=False,
            model=LOCAL_MLX_WHISPER_MODEL_ID,
            detail="Local MLX Whisper model is not downloaded.",
        )

    return STTDownloadStatus(
        provider=LOCAL_MLX_WHISPER_STT_PROVIDER_ID,
        ready=True,
        model=LOCAL_MLX_WHISPER_MODEL_ID,
    )


def download_local_mlx_whisper() -> STTDownloadStatus:
    from huggingface_hub import snapshot_download

    snapshot_download(LOCAL_MLX_WHISPER_MODEL_ID)
    return local_mlx_whisper_readiness()


class MLXWhisperSTT(livekit_stt.STT):
    def __init__(
        self,
        *,
        model: str = LOCAL_MLX_WHISPER_MODEL_ID,
        initial_prompt: str = LOCAL_MLX_WHISPER_PROMPT,
    ) -> None:
        super().__init__(
            capabilities=livekit_stt.STTCapabilities(
                streaming=False,
                interim_results=False,
            )
        )
        self._model = model
        self._initial_prompt = initial_prompt

    @property
    def model(self) -> str:
        return self._model

    @property
    def provider(self) -> str:
        return "MLX Whisper"

    async def _recognize_impl(
        self,
        buffer,
        *,
        language=NOT_GIVEN,
        conn_options=DEFAULT_API_CONNECT_OPTIONS,
    ) -> livekit_stt.SpeechEvent:
        text = await asyncio.to_thread(self._transcribe_buffer, buffer)
        return livekit_stt.SpeechEvent(
            type=livekit_stt.SpeechEventType.FINAL_TRANSCRIPT,
            request_id=f"mlx-whisper-{uuid.uuid4().hex}",
            alternatives=[
                livekit_stt.SpeechData(
                    language="en",
                    text=text,
                    confidence=1.0 if text else 0.0,
                )
            ],
        )

    def prewarm(self) -> None:
        import mlx_whisper

        mlx_whisper.load_models.load_model(self._model)

    def _transcribe_buffer(self, buffer) -> str:
        import mlx_whisper

        frame = rtc.combine_audio_frames(buffer)
        path = _write_frame_to_temp_wav(frame)
        try:
            result = mlx_whisper.transcribe(
                str(path),
                path_or_hf_repo=self._model,
                language="en",
                task="transcribe",
                initial_prompt=self._initial_prompt,
                verbose=False,
            )
        finally:
            path.unlink(missing_ok=True)
        return " ".join(str(result.get("text") or "").strip().split())


def _write_frame_to_temp_wav(frame: rtc.AudioFrame) -> Path:
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        path = Path(tmp.name)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(frame.num_channels)
        wav.setsampwidth(2)
        wav.setframerate(frame.sample_rate)
        wav.writeframes(frame.data.tobytes())
    return path
