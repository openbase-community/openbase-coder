import asyncio
import contextlib
import hashlib
import json
import logging
import os
import tempfile
import time
import uuid
import wave
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from pathlib import Path

import aiohttp
import av
from dotenv import load_dotenv
from livekit import rtc
from livekit.agents import (
    Agent,
    AgentSession,
    AutoSubscribe,
    JobContext,
    JobProcess,
    cli,
    llm,
)
from livekit.agents import (
    AgentServer as LiveKitAgentServer,
)
from livekit.agents import (
    stt as livekit_stt,
)
from livekit.agents import (
    tts as livekit_tts,
)
from livekit.agents import (
    vad as livekit_vad,
)
from livekit.agents.llm.chat_context import ChatMessage
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS, NOT_GIVEN
from livekit.plugins import assemblyai, cartesia, deepgram, silero  # noqa: F401
from livekit.plugins.turn_detector.multilingual import MultilingualModel

from openbase_coder_cli.brain_score import (
    brain_score_token_configured,
    brain_score_token_file,
    load_brain_score_token,
)
from openbase_coder_cli.config.machine_token_manager import (
    MachineTokenError,
    MachineTokenManager,
)
from openbase_coder_cli.config.token_manager import (
    DEFAULT_WEB_BACKEND_URL,
    AuthLoginRequiredError,
    AuthTransientError,
)
from openbase_coder_cli.dispatcher_config import (
    codex_service_tier,
    dispatcher_voice,
    selected_stt_provider_id,
    selected_tts_provider_id,
)
from openbase_coder_cli.livekit_agent.speech_formatter import format_for_speech
from openbase_coder_cli.livekit_agent.super_agents_client import (
    SuperAgentsLiveKitClient,
)
from openbase_coder_cli.paths import (
    CODEX_DIRECT_LIVEKIT_INSTRUCTIONS_PATH,
    CODEX_DISPATCHER_CONFIG_PATH,
    CODEX_DISPATCHER_INSTRUCTIONS_PATH,
    OPENBASE_BASE_DIR,
)
from openbase_coder_cli.stt_providers import (
    ASSEMBLYAI_STT_PROVIDER_ID,
    DEEPGRAM_STT_PROVIDER_ID,
    LOCAL_MLX_WHISPER_STT_PROVIDER_ID,
    OPENBASE_CLOUD_STT_PROVIDER_ID,
    MLXWhisperSTT,
)
from openbase_coder_cli.tts_providers import (
    CARTESIA_PROVIDER_ID,
    DEFAULT_CARTESIA_ANNOUNCER_VOICE_ID,
    DEFAULT_CARTESIA_TTS_VOLUME,
    DEFAULT_CARTESIA_VOICE_ID,
    KOKORO_PROVIDER_ID,
    OPENBASE_CLOUD_TTS_PROVIDER_ID,
    get_tts_provider,
)

logger = logging.getLogger(__name__)


def _canonical_env_path() -> Path:
    """Path to the installed Openbase env file (the one the launchd/systemd
    wrapper sources). The agent's cwd is ``{workspace}/cli`` which has no
    ``.env``, so relying on a cwd-relative load silently picks up nothing."""
    try:
        from openbase_coder_cli.services.installation import InstallationConfig

        if InstallationConfig.exists():
            return Path(InstallationConfig.load().env_file).expanduser()
    except Exception:
        pass
    return OPENBASE_BASE_DIR / ".env"


def _load_openbase_env(*, override: bool = False) -> None:
    """Load env vars from the cwd ``.env`` (legacy) and the canonical installed
    env file. With ``override=True`` the on-disk values win, so a worker that
    started before a key was written to ``.env`` can self-heal on the next job
    instead of crash-looping on a now-stale environment."""
    load_dotenv(".env", override=override)
    load_dotenv(_canonical_env_path(), override=override)


_load_openbase_env()

os.environ.setdefault("LIVEKIT_URL", "ws://localhost:7880")
os.environ.setdefault("CODEX_APP_SERVER_URL", "ws://127.0.0.1:4500")
os.environ.setdefault("LIVEKIT_CODEX_THREAD_CWD", str(Path.home()))

CODEX_APP_SERVER_URL = os.environ["CODEX_APP_SERVER_URL"]
LIVEKIT_CODEX_THREAD_CWD = os.environ["LIVEKIT_CODEX_THREAD_CWD"]
ASSEMBLY_AI_API_KEY = os.getenv("ASSEMBLY_AI_API_KEY") or os.getenv(
    "ASSEMBLYAI_API_KEY"
)
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")
CARTESIA_API_KEY = os.getenv("CARTESIA_API_KEY")


def _refresh_audio_credentials() -> None:
    """Re-read audio provider keys from the on-disk env file.

    The worker process captures these once at import. If ``.env`` is written
    *after* the worker starts (e.g. a key or cloud token added during setup),
    the long-running process otherwise keeps a stale environment and every job
    crash-loops (e.g. ``Cartesia API key is required``). Refreshing per job lets
    it recover without a manual service restart."""
    global ASSEMBLY_AI_API_KEY, DEEPGRAM_API_KEY, CARTESIA_API_KEY
    _load_openbase_env(override=True)
    ASSEMBLY_AI_API_KEY = os.getenv("ASSEMBLY_AI_API_KEY") or os.getenv(
        "ASSEMBLYAI_API_KEY"
    )
    DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")
    CARTESIA_API_KEY = os.getenv("CARTESIA_API_KEY")


CARTESIA_VOICE_ID = os.getenv("CARTESIA_VOICE_ID", DEFAULT_CARTESIA_VOICE_ID)
CARTESIA_ANNOUNCER_VOICE_ID = os.getenv(
    "CARTESIA_ANNOUNCER_VOICE_ID", DEFAULT_CARTESIA_ANNOUNCER_VOICE_ID
)
WEB_BACKEND_URL = os.getenv(
    "OPENBASE_CODER_CLI_WEB_BACKEND_URL",
    DEFAULT_WEB_BACKEND_URL,
).rstrip("/")
OPENBASE_CLOUD_AUDIO_BASE_URL = os.getenv(
    "OPENBASE_CLOUD_AUDIO_BASE_URL",
    f"{WEB_BACKEND_URL}/api/openbase/audio",
).rstrip("/")
OPENBASE_CLOUD_AUDIO_CARTESIA_VERSION = os.getenv(
    "OPENBASE_CLOUD_AUDIO_CARTESIA_VERSION",
    "2026-03-01",
)


class OpenbaseCloudAudioAuthenticationError(RuntimeError):
    """Openbase Cloud audio requires a valid Openbase machine token."""


ANNOUNCER_TOPIC = "openbase.announcer.say"
VOICE_ROUTE_TOPIC = "openbase.voice.route"
ANNOUNCER_AUDIO_KIND = "audio_file"
SUPPORTED_AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".aac", ".ogg"}
ANNOUNCER_MAX_QUEUE_SIZE = int(os.getenv("LIVEKIT_ANNOUNCER_MAX_QUEUE_SIZE", "20"))
ANNOUNCER_SILENCE_GRACE_SECONDS = float(
    os.getenv("LIVEKIT_ANNOUNCER_SILENCE_GRACE_SECONDS", "0.5")
)
ANNOUNCER_STATE_WAIT_TIMEOUT_SECONDS = 0.1
LIVEKIT_DISPATCH_AGENT_NAME = os.environ.get(
    "LIVEKIT_DISPATCH_AGENT_NAME", "livekit-agent"
)
LIVEKIT_AGENT_HOST = os.getenv("LIVEKIT_AGENT_HOST", "127.0.0.1")
LIVEKIT_AGENT_PORT = int(os.getenv("LIVEKIT_AGENT_PORT", "8081"))
LIVEKIT_AGENT_LOAD_THRESHOLD_ENV = "LIVEKIT_AGENT_LOAD_THRESHOLD"
LIVEKIT_AGENT_NUM_IDLE_PROCESSES_ENV = "LIVEKIT_AGENT_NUM_IDLE_PROCESSES"
DEFAULT_LIVEKIT_DISPATCHER_CONFIG_PATH = CODEX_DISPATCHER_CONFIG_PATH
LIVEKIT_DISPATCHER_CONFIG_PATH = os.getenv(
    "LIVEKIT_DISPATCHER_CONFIG_PATH",
    str(DEFAULT_LIVEKIT_DISPATCHER_CONFIG_PATH),
)
DIRECT_LIVEKIT_INSTRUCTIONS_PATH_ENV = (
    "LIVEKIT_DIRECT_CODEX_DEVELOPER_INSTRUCTIONS_PATH"
)
DIRECT_LIVEKIT_INSTRUCTIONS_TEXT_ENV = "LIVEKIT_DIRECT_CODEX_DEVELOPER_INSTRUCTIONS"
DEFAULT_DIRECT_LIVEKIT_INSTRUCTIONS_PATH = (
    CODEX_DIRECT_LIVEKIT_INSTRUCTIONS_PATH
)
DIRECT_LIVEKIT_BUILTIN_DEVELOPER_INSTRUCTIONS = """
You are receiving direct user speech from a LiveKit voice session.
Keep final spoken responses concise and directly useful.
Avoid bulleted or itemized lists in spoken responses because text-to-speech reads repeated item markers badly. Prefer brief plain prose. When a list is genuinely clearer, use a short numbered list instead of bullets.
Do not read code, logs, stack traces, JSON, diffs, or long file paths aloud unless explicitly asked.
When code or logs matter, summarize their practical meaning in plain English.
If transcription is unclear, ask the user to confirm the intended request before acting.
When the user asks to return to dispatch, or you need to hand the voice session
back to dispatch, run:
openbase-coder exit-to-dispatch
Do not assume dispatcher responsibilities, delegation policy, or Super Agents coordination rules from these instructions.
""".strip()
DISPATCHER_BUILTIN_DEVELOPER_INSTRUCTIONS = """
You are the Openbase Coder LiveKit dispatcher for a private voice session.
Route voice sessions when the user asks to speak with an agent.
When creating or referring to a Super Agent for a thread name, derive the
agent's speaking name with:
openbase-coder super-agent-name "<thread name>"
When creating a Super Agent, pass that speaking name as the thread's agentName.
When the user asks to transfer to an agent by name, run:
openbase-coder user transfer-to-agent "<agent name>"
When the user asks to transfer by thread id, run:
openbase-coder user transfer-to-thread "<thread id>"
Keep spoken confirmations concise.
""".strip()
LIVEKIT_CODEX_THREAD_STATE_PATH = os.getenv("LIVEKIT_CODEX_THREAD_STATE_PATH")
LIVEKIT_CODEX_FRESH_THREAD_PER_SESSION = os.getenv(
    "LIVEKIT_CODEX_FRESH_THREAD_PER_SESSION", ""
).strip().lower() in {"1", "true", "yes", "on"}
LIVEKIT_CODEX_APPROVAL_POLICY = os.getenv("LIVEKIT_CODEX_APPROVAL_POLICY", "never")
LIVEKIT_CODEX_SANDBOX = os.getenv("LIVEKIT_CODEX_SANDBOX", "danger-full-access")
LIVEKIT_STT_PROVIDER = os.getenv("LIVEKIT_STT_PROVIDER", "assemblyai").lower()
LIVEKIT_VERBOSE_LOGGING = os.getenv("LIVEKIT_VERBOSE_LOGGING", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
LIVEKIT_CODEX_ACK_DELAY_SECONDS = float(
    os.getenv("LIVEKIT_CODEX_ACK_DELAY_SECONDS", "0") or 0
)
LIVEKIT_CODEX_ACK_MESSAGE = os.getenv("LIVEKIT_CODEX_ACK_MESSAGE", "Okay.").strip()
EXIT_TO_DISPATCH_PHRASE = "exit to dispatch"
EXIT_TO_DISPATCH_PHRASES = {
    EXIT_TO_DISPATCH_PHRASE,
    "to dispatch",
    "two dispatch",
}
BRAIN_SCORE_ENABLED = os.getenv(
    "OPENBASE_BRAIN_SCORE_ENABLED", "1"
).strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
BRAIN_SCORE_ENDPOINT = os.getenv(
    "OPENBASE_BRAIN_SCORE_ENDPOINT",
    "http://uat.api.getvibes.ai/api/v1/score/hackathon",
)
BRAIN_SCORE_INTERVAL_SECONDS = float(
    os.getenv("OPENBASE_BRAIN_SCORE_INTERVAL_SECONDS", "60") or 60
)
BRAIN_SCORE_MIN_DURATION_SECONDS = float(
    os.getenv("OPENBASE_BRAIN_SCORE_MIN_DURATION_SECONDS", "20") or 20
)
BRAIN_SCORE_COOLDOWN_SECONDS = float(
    os.getenv("OPENBASE_BRAIN_SCORE_COOLDOWN_SECONDS", "1800") or 1800
)
BRAIN_SCORE_OUTPUT_PATH = Path(
    os.getenv(
        "OPENBASE_BRAIN_SCORE_OUTPUT_PATH",
        str(Path.home() / ".openbase" / "brain_score.json"),
    )
).expanduser()
BRAIN_SCORE_TOKEN_FILE = brain_score_token_file()
BRAIN_SCORE_LATITUDE = os.getenv("OPENBASE_BRAIN_SCORE_LATITUDE", "").strip()
BRAIN_SCORE_LONGITUDE = os.getenv("OPENBASE_BRAIN_SCORE_LONGITUDE", "").strip()


def _optional_float_env(name: str) -> float | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        logger.warning("Ignoring invalid %s=%r", name, raw)
        return None
    if value <= 0:
        logger.warning("Ignoring non-positive %s=%r", name, raw)
        return None
    return value


def _optional_int_env(name: str) -> int | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        logger.warning("Ignoring invalid %s=%r", name, raw)
        return None
    if value < 0:
        logger.warning("Ignoring negative %s=%r", name, raw)
        return None
    return value


def _uses_local_voice_model() -> bool:
    return (
        selected_stt_provider_id() == LOCAL_MLX_WHISPER_STT_PROVIDER_ID
        or selected_tts_provider_id() == KOKORO_PROVIDER_ID
    )


def _livekit_agent_server_options() -> dict[str, float | int]:
    uses_local_model = _uses_local_voice_model()
    options: dict[str, float | int] = {}

    load_threshold = _optional_float_env(LIVEKIT_AGENT_LOAD_THRESHOLD_ENV)
    if load_threshold is not None:
        options["load_threshold"] = load_threshold
    elif uses_local_model:
        options["load_threshold"] = float("inf")

    num_idle_processes = _optional_int_env(LIVEKIT_AGENT_NUM_IDLE_PROCESSES_ENV)
    if num_idle_processes is not None:
        options["num_idle_processes"] = num_idle_processes
    elif uses_local_model:
        options["num_idle_processes"] = 1

    return options


@dataclass(frozen=True)
class CartesiaVoice:
    voice_id: str
    name: str
    provider: str = CARTESIA_PROVIDER_ID


def dispatcher_voice_config(
    *,
    config_path: str | Path | None = None,
) -> CartesiaVoice:
    configured = dispatcher_voice(
        Path(config_path or LIVEKIT_DISPATCHER_CONFIG_PATH).expanduser()
    )
    return CartesiaVoice(
        voice_id=configured["id"],
        name=configured["name"],
        provider=configured.get("provider", CARTESIA_PROVIDER_ID),
    )


def _voices_from_ids(voice_ids) -> tuple[CartesiaVoice, ...]:
    provider = get_tts_provider(CARTESIA_PROVIDER_ID)
    return tuple(
        CartesiaVoice(
            voice_id=voice_id,
            name=provider.voice_for_id(voice_id).name
            if provider.voice_for_id(voice_id)
            else f"Voice {index + 1}",
        )
        for index, voice_id in enumerate(voice_ids)
    )


SUPER_AGENT_VOICE_IDS = tuple(
    voice.id for voice in get_tts_provider(CARTESIA_PROVIDER_ID).super_agent_voices()
)
SUPER_AGENT_VOICES = _voices_from_ids(SUPER_AGENT_VOICE_IDS)


def _current_super_agent_voices() -> tuple[CartesiaVoice, ...]:
    provider = get_tts_provider(selected_tts_provider_id())
    if provider.provider_id != CARTESIA_PROVIDER_ID:
        return tuple(
            CartesiaVoice(
                voice_id=voice.id, name=voice.name, provider=provider.provider_id
            )
            for voice in provider.super_agent_voices()
        )
    voice_ids = tuple(voice.voice_id for voice in SUPER_AGENT_VOICES)
    if voice_ids == tuple(SUPER_AGENT_VOICE_IDS):
        return SUPER_AGENT_VOICES
    return tuple(
        CartesiaVoice(voice_id=voice.id, name=voice.name, provider=provider.provider_id)
        for voice in provider.super_agent_voices()
    )


def _normalize_spoken_command(text: str) -> str:
    return " ".join(
        "".join(char.lower() if char.isalnum() else " " for char in text).split()
    )


def _is_exit_to_dispatch_command(text: str) -> bool:
    normalized = _normalize_spoken_command(text)
    return any(phrase in normalized for phrase in EXIT_TO_DISPATCH_PHRASES)


def _load_dispatcher_developer_instructions() -> str | None:
    try:
        loaded = CODEX_DISPATCHER_INSTRUCTIONS_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        logger.warning(
            "Unable to read dispatcher instruction file %s",
            CODEX_DISPATCHER_INSTRUCTIONS_PATH,
            exc_info=True,
        )
    else:
        if loaded:
            return loaded

    return DISPATCHER_BUILTIN_DEVELOPER_INSTRUCTIONS


def load_direct_livekit_developer_instructions(
    *,
    env: dict[str, str] | None = None,
    default_path: Path | None = None,
) -> str:
    values = env if env is not None else os.environ
    explicit_path = values.get(DIRECT_LIVEKIT_INSTRUCTIONS_PATH_ENV, "").strip()
    if explicit_path:
        loaded = _read_instruction_file(Path(explicit_path).expanduser())
        if loaded:
            return loaded

    loaded = _read_instruction_file(
        default_path or DEFAULT_DIRECT_LIVEKIT_INSTRUCTIONS_PATH
    )
    if loaded:
        return loaded

    text = values.get(DIRECT_LIVEKIT_INSTRUCTIONS_TEXT_ENV, "").strip()
    if text:
        return text

    return DIRECT_LIVEKIT_BUILTIN_DEVELOPER_INSTRUCTIONS


def _read_instruction_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        content = path.read_text(encoding="utf-8").strip()
    except OSError:
        logger.warning(
            "Unable to read direct LiveKit instruction file %s", path, exc_info=True
        )
        return None
    return content or None


class CodexLLMStream(llm.LLMStream):
    """Bridge a LiveKit user turn to the shared Codex app-server thread."""

    def __init__(
        self,
        livekit_llm: "CodexLiveKitLLM",
        *,
        chat_ctx,
        tools,
        conn_options,
    ) -> None:
        super().__init__(
            livekit_llm,
            chat_ctx=chat_ctx,
            tools=tools,
            conn_options=conn_options,
        )
        self._message_id = f"codex-{uuid.uuid4()}"
        self._voice_router = livekit_llm.voice_router
        self._emitted_text = False

    def _latest_user_text(self) -> str:
        for item in reversed(self._chat_ctx.items):
            if isinstance(item, ChatMessage) and item.role == "user":
                return item.text_content or ""
        return ""

    async def _run(self) -> None:
        prompt = self._latest_user_text().strip()
        if not prompt:
            logger.info(
                "dispatch_timing stage=livekit_llm_empty_prompt message_id=%s",
                self._message_id,
            )
            return
        if self._voice_router.should_skip_proactively_steered_prompt(prompt):
            logger.info(
                "dispatch_timing stage=livekit_llm_prompt_already_steered "
                "message_id=%s prompt_len=%d prompt_hash=%s",
                self._message_id,
                len(prompt),
                hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12],
            )
            return
        logger.info(
            "dispatch_timing stage=livekit_llm_turn_start message_id=%s "
            "prompt_len=%d prompt_hash=%s active_thread_id=%s active_voice_id=%s",
            self._message_id,
            len(prompt),
            hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12],
            getattr(self._voice_router.active_client, "_thread_id", "") or "",
            self._voice_router.active_target_voice_id or "",
        )

        if _is_exit_to_dispatch_command(prompt):
            self._voice_router.exit_to_dispatch()
            self._emit_delta("Back to dispatch.")
            return

        ack_task: asyncio.Task[None] | None = None
        if LIVEKIT_CODEX_ACK_DELAY_SECONDS > 0 and LIVEKIT_CODEX_ACK_MESSAGE:
            ack_task = asyncio.create_task(self._emit_ack_after_delay())

        try:
            voice_client = self._voice_router.active_client
            result = await voice_client.run_turn(
                prompt,
                developer_instructions=load_direct_livekit_developer_instructions(),
            )
        finally:
            if ack_task is not None:
                ack_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await ack_task

        speech_text = result.get("_livekit_speech_text", "")
        turn_id = result.get("_livekit_turn_id", "")
        logger.info(
            "dispatch_timing stage=livekit_llm_turn_result message_id=%s "
            "turn_id=%s speech_len=%d speech_hash=%s event_channel_closed=%s",
            self._message_id,
            turn_id,
            len(speech_text),
            hashlib.sha256(speech_text.encode("utf-8")).hexdigest()[:12]
            if speech_text
            else "",
            self._event_ch.closed,
        )
        if speech_text and turn_id and not self._event_ch.closed:
            if self._voice_router.claim_speech(voice_client, turn_id):
                try:
                    self._emit_delta(speech_text)
                except Exception:
                    voice_client.release_speech_claim(turn_id)
                    raise

    def _emit_delta(self, text: str) -> None:
        self._event_ch.send_nowait(
            llm.ChatChunk(
                id=self._message_id,
                delta=llm.ChoiceDelta(role="assistant", content=text),
            )
        )
        self._emitted_text = True
        logger.info(
            "dispatch_timing stage=livekit_llm_delta_emitted message_id=%s "
            "text_len=%d text_hash=%s text_excerpt=%r",
            self._message_id,
            len(text),
            hashlib.sha256(text.encode("utf-8")).hexdigest()[:12],
            text[:160],
        )

    async def _emit_ack_after_delay(self) -> None:
        await asyncio.sleep(LIVEKIT_CODEX_ACK_DELAY_SECONDS)
        if self._emitted_text:
            return
        try:
            self._emit_delta(LIVEKIT_CODEX_ACK_MESSAGE)
        except Exception:
            logger.debug(
                "Skipped LiveKit Codex acknowledgement after channel close",
                exc_info=True,
            )


class CodexLiveKitLLM(llm.LLM):
    """LiveKit LLM wrapper backed by a shared Codex app-server thread."""

    def __init__(self, voice_router: "LiveKitVoiceRouter") -> None:
        super().__init__()
        self.voice_router = voice_router

    @property
    def model(self) -> str:
        return self.voice_router.active_client.model_name

    @property
    def provider(self) -> str:
        return "openai"

    def chat(
        self,
        *,
        chat_ctx,
        tools=None,
        conn_options=DEFAULT_API_CONNECT_OPTIONS,
        **kwargs,
    ) -> llm.LLMStream:
        return CodexLLMStream(
            self,
            chat_ctx=chat_ctx,
            tools=tools or [],
            conn_options=conn_options,
        )


class Assistant(Agent):
    """The LiveKit agent"""

    def __init__(self) -> None:
        super().__init__(
            instructions="",  # Instructions are not used due to LastMessageOnlyStream.
        )


LIVEKIT_AUDIO_FRAME_LOG_FIRST = int(os.getenv("LIVEKIT_AUDIO_FRAME_LOG_FIRST", "10"))
LIVEKIT_AUDIO_FRAME_LOG_EVERY = int(os.getenv("LIVEKIT_AUDIO_FRAME_LOG_EVERY", "10"))
PROACTIVE_STEER_PROMPT_CACHE_SECONDS = 120.0


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


class LoggingSTT(livekit_stt.STT):
    """Diagnostic STT wrapper that logs audio ingress and speech events."""

    def __init__(self, wrapped: livekit_stt.STT) -> None:
        super().__init__(capabilities=wrapped.capabilities)
        self._wrapped = wrapped
        self._stream_count = 0
        self._wrapped.on("metrics_collected", self._forward_metrics)
        self._wrapped.on("error", self._forward_error)
        logger.info(
            "dispatch_timing stage=stt_initialized provider=%s model=%s label=%s "
            "streaming=%s interim_results=%s diarization=%s aligned_transcript=%s "
            "offline_recognize=%s",
            self.provider,
            self.model,
            self.label,
            self.capabilities.streaming,
            self.capabilities.interim_results,
            self.capabilities.diarization,
            self.capabilities.aligned_transcript,
            self.capabilities.offline_recognize,
        )

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
        logger.info(
            "dispatch_timing stage=stt_recognize_start provider=%s model=%s "
            "language=%s conn_options=%s buffer_type=%s",
            self.provider,
            self.model,
            language if language is not NOT_GIVEN else "",
            type(conn_options).__name__,
            type(buffer).__name__,
        )
        event = await self._wrapped.recognize(
            buffer,
            language=language,
            conn_options=conn_options,
        )
        _log_stt_event(
            "stt_recognize_result", event, provider=self.provider, model=self.model
        )
        return event

    def stream(
        self,
        *,
        language=NOT_GIVEN,
        conn_options=DEFAULT_API_CONNECT_OPTIONS,
    ):
        self._stream_count += 1
        stream_id = f"stt-{self._stream_count}"
        logger.info(
            "dispatch_timing stage=stt_stream_create stream_id=%s provider=%s "
            "model=%s language=%s conn_options=%s",
            stream_id,
            self.provider,
            self.model,
            language if language is not NOT_GIVEN else "",
            type(conn_options).__name__,
        )
        return LoggingRecognizeStream(
            self._wrapped.stream(language=language, conn_options=conn_options),
            stream_id=stream_id,
            provider=self.provider,
            model=self.model,
        )

    def prewarm(self) -> None:
        logger.info(
            "dispatch_timing stage=stt_prewarm provider=%s model=%s",
            self.provider,
            self.model,
        )
        self._wrapped.prewarm()

    async def aclose(self) -> None:
        logger.info(
            "dispatch_timing stage=stt_close provider=%s model=%s streams_created=%d",
            self.provider,
            self.model,
            self._stream_count,
        )
        await self._wrapped.aclose()


class LoggingRecognizeStream:
    def __init__(self, stream, *, stream_id: str, provider: str, model: str) -> None:
        self._stream = stream
        self._stream_id = stream_id
        self._provider = provider
        self._model = model
        self._frame_count = 0
        self._sample_count = 0
        self._flush_count = 0
        self._event_count = 0

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
        self._frame_count += 1
        self._sample_count += getattr(frame, "samples_per_channel", 0) or 0
        if _should_log_audio_frame(self._frame_count):
            sample_rate = getattr(frame, "sample_rate", 0) or 0
            total_audio_ms = (
                int(self._sample_count / sample_rate * 1000) if sample_rate else 0
            )
            logger.info(
                "dispatch_timing stage=stt_audio_frame stream_id=%s provider=%s "
                "model=%s frame_count=%d sample_rate=%s num_channels=%s "
                "samples_per_channel=%s frame_duration_ms=%d total_audio_ms=%d",
                self._stream_id,
                self._provider,
                self._model,
                self._frame_count,
                getattr(frame, "sample_rate", ""),
                getattr(frame, "num_channels", ""),
                getattr(frame, "samples_per_channel", ""),
                _frame_duration_ms(frame),
                total_audio_ms,
            )
        self._stream.push_frame(frame)

    def flush(self) -> None:
        self._flush_count += 1
        logger.info(
            "dispatch_timing stage=stt_stream_flush stream_id=%s provider=%s "
            "model=%s flush_count=%d frame_count=%d sample_count=%d",
            self._stream_id,
            self._provider,
            self._model,
            self._flush_count,
            self._frame_count,
            self._sample_count,
        )
        self._stream.flush()

    def end_input(self) -> None:
        logger.info(
            "dispatch_timing stage=stt_stream_end_input stream_id=%s provider=%s "
            "model=%s frame_count=%d sample_count=%d flush_count=%d",
            self._stream_id,
            self._provider,
            self._model,
            self._frame_count,
            self._sample_count,
            self._flush_count,
        )
        self._stream.end_input()

    async def aclose(self) -> None:
        logger.info(
            "dispatch_timing stage=stt_stream_close stream_id=%s provider=%s "
            "model=%s frame_count=%d sample_count=%d event_count=%d flush_count=%d",
            self._stream_id,
            self._provider,
            self._model,
            self._frame_count,
            self._sample_count,
            self._event_count,
            self._flush_count,
        )
        await self._stream.aclose()

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            event = await self._stream.__anext__()
        except StopAsyncIteration:
            logger.info(
                "dispatch_timing stage=stt_stream_iter_end stream_id=%s provider=%s "
                "model=%s frame_count=%d sample_count=%d event_count=%d flush_count=%d",
                self._stream_id,
                self._provider,
                self._model,
                self._frame_count,
                self._sample_count,
                self._event_count,
                self._flush_count,
            )
            raise
        self._event_count += 1
        _log_stt_event(
            "stt_stream_event",
            event,
            provider=self._provider,
            model=self._model,
            stream_id=self._stream_id,
            event_count=self._event_count,
        )
        return event

    async def __aenter__(self):
        await self._stream.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc, exc_tb) -> None:
        await self._stream.__aexit__(exc_type, exc, exc_tb)


def _log_stt_event(
    stage: str,
    event: livekit_stt.SpeechEvent,
    *,
    provider: str,
    model: str,
    stream_id: str = "",
    event_count: int = 0,
) -> None:
    alternative = event.alternatives[0] if event.alternatives else None
    text = alternative.text if alternative is not None else ""
    usage = event.recognition_usage
    logger.info(
        "dispatch_timing stage=%s stream_id=%s provider=%s model=%s event_count=%d "
        "event_type=%s request_id=%s alternatives=%d text_len=%d text_hash=%s "
        "text_excerpt=%r language=%s confidence=%s speaker_id=%s "
        "speech_start_time=%s alt_start_time=%s alt_end_time=%s "
        "usage_audio_duration=%s usage_input_tokens=%s usage_output_tokens=%s",
        stage,
        stream_id,
        provider,
        model,
        event_count,
        event.type,
        event.request_id,
        len(event.alternatives),
        len(text),
        _event_text_hash(text),
        text[:160],
        getattr(alternative, "language", "") if alternative is not None else "",
        getattr(alternative, "confidence", "") if alternative is not None else "",
        getattr(alternative, "speaker_id", "") if alternative is not None else "",
        event.speech_start_time,
        getattr(alternative, "start_time", "") if alternative is not None else "",
        getattr(alternative, "end_time", "") if alternative is not None else "",
        getattr(usage, "audio_duration", "") if usage is not None else "",
        getattr(usage, "input_tokens", "") if usage is not None else "",
        getattr(usage, "output_tokens", "") if usage is not None else "",
    )


class LoggingVAD(livekit_vad.VAD):
    """Diagnostic VAD wrapper that logs audio ingress and speech boundary events."""

    def __init__(self, wrapped: livekit_vad.VAD) -> None:
        super().__init__(capabilities=wrapped.capabilities)
        self._wrapped = wrapped
        self._stream_count = 0
        self._wrapped.on("metrics_collected", self._forward_metrics)
        logger.info(
            "dispatch_timing stage=vad_initialized provider=%s model=%s "
            "update_interval=%s",
            self.provider,
            self.model,
            self.capabilities.update_interval,
        )

    @property
    def model(self) -> str:
        return self._wrapped.model

    @property
    def provider(self) -> str:
        return self._wrapped.provider

    def _forward_metrics(self, metrics) -> None:
        self.emit("metrics_collected", metrics)

    def stream(self):
        self._stream_count += 1
        stream_id = f"vad-{self._stream_count}"
        logger.info(
            "dispatch_timing stage=vad_stream_create stream_id=%s provider=%s model=%s",
            stream_id,
            self.provider,
            self.model,
        )
        return LoggingVADStream(
            self._wrapped.stream(),
            stream_id=stream_id,
            provider=self.provider,
            model=self.model,
        )


class LoggingVADStream:
    def __init__(self, stream, *, stream_id: str, provider: str, model: str) -> None:
        self._stream = stream
        self._stream_id = stream_id
        self._provider = provider
        self._model = model
        self._frame_count = 0
        self._sample_count = 0
        self._event_count = 0
        self._flush_count = 0

    def push_frame(self, frame: rtc.AudioFrame) -> None:
        self._frame_count += 1
        self._sample_count += getattr(frame, "samples_per_channel", 0) or 0
        if _should_log_audio_frame(self._frame_count):
            sample_rate = getattr(frame, "sample_rate", 0) or 0
            total_audio_ms = (
                int(self._sample_count / sample_rate * 1000) if sample_rate else 0
            )
            logger.info(
                "dispatch_timing stage=vad_audio_frame stream_id=%s provider=%s "
                "model=%s frame_count=%d sample_rate=%s num_channels=%s "
                "samples_per_channel=%s frame_duration_ms=%d total_audio_ms=%d",
                self._stream_id,
                self._provider,
                self._model,
                self._frame_count,
                getattr(frame, "sample_rate", ""),
                getattr(frame, "num_channels", ""),
                getattr(frame, "samples_per_channel", ""),
                _frame_duration_ms(frame),
                total_audio_ms,
            )
        self._stream.push_frame(frame)

    def flush(self) -> None:
        self._flush_count += 1
        logger.info(
            "dispatch_timing stage=vad_stream_flush stream_id=%s provider=%s "
            "model=%s flush_count=%d frame_count=%d sample_count=%d",
            self._stream_id,
            self._provider,
            self._model,
            self._flush_count,
            self._frame_count,
            self._sample_count,
        )
        self._stream.flush()

    def end_input(self) -> None:
        logger.info(
            "dispatch_timing stage=vad_stream_end_input stream_id=%s provider=%s "
            "model=%s frame_count=%d sample_count=%d flush_count=%d",
            self._stream_id,
            self._provider,
            self._model,
            self._frame_count,
            self._sample_count,
            self._flush_count,
        )
        self._stream.end_input()

    async def aclose(self) -> None:
        logger.info(
            "dispatch_timing stage=vad_stream_close stream_id=%s provider=%s "
            "model=%s frame_count=%d sample_count=%d event_count=%d flush_count=%d",
            self._stream_id,
            self._provider,
            self._model,
            self._frame_count,
            self._sample_count,
            self._event_count,
            self._flush_count,
        )
        await self._stream.aclose()

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            event = await self._stream.__anext__()
        except StopAsyncIteration:
            logger.info(
                "dispatch_timing stage=vad_stream_iter_end stream_id=%s provider=%s "
                "model=%s frame_count=%d sample_count=%d event_count=%d flush_count=%d",
                self._stream_id,
                self._provider,
                self._model,
                self._frame_count,
                self._sample_count,
                self._event_count,
                self._flush_count,
            )
            raise
        self._event_count += 1
        logger.info(
            "dispatch_timing stage=vad_stream_event stream_id=%s provider=%s "
            "model=%s event_count=%d event_type=%s samples_index=%s timestamp=%s "
            "speaking=%s probability=%s speech_duration=%s silence_duration=%s "
            "inference_duration=%s raw_accumulated_speech=%s raw_accumulated_silence=%s "
            "frames=%d",
            self._stream_id,
            self._provider,
            self._model,
            self._event_count,
            event.type,
            event.samples_index,
            event.timestamp,
            event.speaking,
            event.probability,
            event.speech_duration,
            event.silence_duration,
            event.inference_duration,
            event.raw_accumulated_speech,
            event.raw_accumulated_silence,
            len(event.frames),
        )
        return event


@dataclass(frozen=True)
class AnnouncerMessage:
    message_id: str
    text: str
    voice_id: str | None = None


@dataclass(frozen=True)
class AnnouncerAudioMessage:
    message_id: str
    audio_path: str


AnnouncerQueueItem = AnnouncerMessage | AnnouncerAudioMessage


@dataclass(frozen=True)
class QueuedAnnouncerItem:
    message: AnnouncerQueueItem
    enqueued_at: float


@dataclass(frozen=True)
class VoiceRouteCommand:
    action: str
    thread_id: str | None = None
    cwd: str | None = None
    label: str | None = None
    active_target_voice_id: str | None = None
    active_target_voice_name: str | None = None


def stable_super_agent_voice_id(
    thread_id: str | None,
    label: str | None = None,
) -> str | None:
    voice = stable_super_agent_voice(thread_id, label)
    return voice.voice_id if voice else None


def stable_super_agent_voice(
    thread_id: str | None,
    label: str | None = None,
) -> CartesiaVoice | None:
    voices = _current_super_agent_voices()
    if not voices:
        return None
    key = (thread_id or label or "").strip()
    if not key:
        return None
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    index = int.from_bytes(digest[:4], "big") % len(voices)
    return voices[index]


class VoiceSelectingTTS(livekit_tts.TTS):
    def __init__(
        self,
        *,
        default_voice_id: str,
        default_voice_name: str | None = None,
        active_voice_id,
        active_voice_name=None,
        api_key: str | None = None,
        provider=None,
        role: str = "direct",
        model: str = "sonic-3",
        volume: float = DEFAULT_CARTESIA_TTS_VOLUME,
        base_url: str | None = None,
        api_version: str | None = None,
    ) -> None:
        self._provider = provider or get_tts_provider(CARTESIA_PROVIDER_ID)
        default_tts = self._provider.create_livekit_tts(
            voice_id=default_voice_id,
            api_key=api_key,
            base_url=base_url,
            api_version=api_version,
            model=model,
            volume=volume,
        )
        super().__init__(
            capabilities=default_tts.capabilities,
            sample_rate=default_tts.sample_rate,
            num_channels=default_tts.num_channels,
        )
        self._default_voice_id = default_voice_id
        self._default_voice_name = default_voice_name
        self._active_voice_id = active_voice_id
        self._active_voice_name = active_voice_name or (lambda: None)
        self._api_key = api_key
        self._role = role
        self._model = model
        self._volume = volume
        self._base_url = base_url
        self._api_version = api_version
        self._tts_by_voice_id: dict[str, livekit_tts.TTS] = {
            default_voice_id: default_tts
        }
        logger.info(
            "dispatch_timing stage=tts_initialized role=%s provider=%s model=%s "
            "default_voice_id=%s default_voice_name=%s api_key_configured=%s "
            "volume=%s sample_rate=%s num_channels=%s",
            self._role,
            self._provider.provider_id,
            self._model,
            self._default_voice_id,
            self._default_voice_name or "",
            bool(self._api_key),
            self._volume,
            self.sample_rate,
            self.num_channels,
        )

    @property
    def model(self) -> str:
        return self._model

    @property
    def provider(self) -> str:
        return self._provider.display_name

    def synthesize(
        self,
        text: str,
        *,
        conn_options=DEFAULT_API_CONNECT_OPTIONS,
    ):
        return self.synthesize_with_voice(
            text,
            voice_id=self._active_voice_id(),
            conn_options=conn_options,
        )

    def synthesize_with_voice(
        self,
        text: str,
        *,
        voice_id: str | None,
        conn_options=DEFAULT_API_CONNECT_OPTIONS,
    ):
        spoken_text = format_for_speech(text)
        if not spoken_text:
            spoken_text = "Technical output omitted, shown on screen."
        self._log_tts(
            stage="tts_synthesize_start",
            voice_id=voice_id,
            spoken_text=spoken_text,
        )
        return self._tts_for_voice(voice_id).synthesize(
            spoken_text,
            conn_options=conn_options,
        )

    def stream(
        self,
        *,
        conn_options=DEFAULT_API_CONNECT_OPTIONS,
    ):
        voice_id = self._active_voice_id()
        resolved_voice_id = self.resolve_voice_id(voice_id)
        logger.info(
            "dispatch_timing stage=tts_stream_start role=%s requested_voice_id=%s "
            "resolved_voice_id=%s voice_name=%s conn_options=%s",
            self._role,
            voice_id or "",
            resolved_voice_id,
            self._voice_name_for_id(resolved_voice_id) or "",
            type(conn_options).__name__,
        )
        return SpeechFormattingSynthesizeStream(
            self._tts_for_voice(resolved_voice_id).stream(
                conn_options=conn_options,
            ),
            role=self._role,
            voice_id=resolved_voice_id,
            voice_name=self._voice_name_for_id(resolved_voice_id),
        )

    def prewarm(self) -> None:
        voice_id = self._active_voice_id()
        logger.info(
            "dispatch_timing stage=tts_prewarm role=%s requested_voice_id=%s "
            "resolved_voice_id=%s voice_name=%s",
            self._role,
            voice_id or "",
            self.resolve_voice_id(voice_id),
            self.resolve_voice_name(voice_id) or "",
        )
        self._tts_for_voice(self._active_voice_id()).prewarm()

    def resolve_voice_id(self, voice_id: str | None) -> str:
        return voice_id or self._default_voice_id

    def resolve_voice_name(self, voice_id: str | None) -> str | None:
        return self._voice_name_for_id(self.resolve_voice_id(voice_id))

    def _tts_for_voice(self, voice_id: str | None) -> livekit_tts.TTS:
        resolved_voice_id = self.resolve_voice_id(voice_id)
        tts = self._tts_by_voice_id.get(resolved_voice_id)
        if tts is None:
            logger.info(
                "dispatch_timing stage=tts_voice_client_create role=%s "
                "provider=%s voice_id=%s voice_name=%s model=%s volume=%s",
                self._role,
                self._provider.provider_id,
                resolved_voice_id,
                self._voice_name_for_id(resolved_voice_id) or "",
                self._model,
                self._volume,
            )
            tts = self._provider.create_livekit_tts(
                voice_id=resolved_voice_id,
                api_key=self._api_key,
                base_url=self._base_url,
                api_version=self._api_version,
                model=self._model,
                volume=self._volume,
            )
            self._tts_by_voice_id[resolved_voice_id] = tts
        return tts

    def _voice_name_for_id(self, voice_id: str | None) -> str | None:
        resolved_voice_id = voice_id or self._default_voice_id
        if resolved_voice_id == self._default_voice_id:
            return self._default_voice_name
        active_voice_id = self._active_voice_id()
        if active_voice_id == resolved_voice_id:
            active_voice_name = self._active_voice_name()
            return active_voice_name if isinstance(active_voice_name, str) else None
        return None

    def _log_tts(
        self,
        *,
        stage: str,
        voice_id: str | None,
        spoken_text: str,
    ) -> None:
        resolved_voice_id = voice_id or self._default_voice_id
        logger.info(
            "dispatch_timing stage=%s role=%s voice_id=%s voice_name=%s "
            "text_len=%d text_hash=%s text_excerpt=%r",
            stage,
            self._role,
            resolved_voice_id,
            self._voice_name_for_id(resolved_voice_id) or "",
            len(spoken_text),
            hashlib.sha256(spoken_text.encode("utf-8")).hexdigest()[:12],
            spoken_text[:160],
        )

    async def aclose(self) -> None:
        logger.info(
            "dispatch_timing stage=tts_close_start role=%s voice_client_count=%d",
            self._role,
            len(self._tts_by_voice_id),
        )
        for tts in self._tts_by_voice_id.values():
            await tts.aclose()
        logger.info("dispatch_timing stage=tts_close_end role=%s", self._role)


VoiceSelectingCartesiaTTS = VoiceSelectingTTS


class SpeechFormattingSynthesizeStream:
    def __init__(
        self,
        stream,
        *,
        role: str,
        voice_id: str | None = None,
        voice_name: str | None = None,
    ) -> None:
        self._stream = stream
        self._buffer = ""
        self._role = role
        self._voice_id = voice_id
        self._voice_name = voice_name
        self._push_count = 0
        self._flush_count = 0
        self._audio_event_count = 0
        self._non_audio_event_count = 0

    def push_text(self, token: str) -> None:
        self._buffer += token
        self._push_count += 1
        if LIVEKIT_VERBOSE_LOGGING:
            logger.info(
                "dispatch_timing stage=tts_stream_push_text role=%s voice_id=%s "
                "voice_name=%s push_count=%d token_len=%d buffer_len=%d token_excerpt=%r",
                self._role,
                self._voice_id or "",
                self._voice_name or "",
                self._push_count,
                len(token),
                len(self._buffer),
                token[:120],
            )

    def flush(self) -> None:
        self._flush_count += 1
        if self._buffer:
            spoken_text = format_for_speech(self._buffer)
            final_text = spoken_text or "Technical output omitted, shown on screen."
            logger.info(
                "dispatch_timing stage=tts_stream_flush role=%s voice_id=%s "
                "voice_name=%s flush_count=%d original_len=%d text_len=%d "
                "text_hash=%s text_excerpt=%r",
                self._role,
                self._voice_id or "",
                self._voice_name or "",
                self._flush_count,
                len(self._buffer),
                len(final_text),
                hashlib.sha256(final_text.encode("utf-8")).hexdigest()[:12],
                final_text[:160],
            )
            self._stream.push_text(final_text)
            self._buffer = ""
        elif LIVEKIT_VERBOSE_LOGGING:
            logger.info(
                "dispatch_timing stage=tts_stream_flush_empty role=%s voice_id=%s "
                "voice_name=%s flush_count=%d",
                self._role,
                self._voice_id or "",
                self._voice_name or "",
                self._flush_count,
            )
        self._stream.flush()
        if LIVEKIT_VERBOSE_LOGGING:
            logger.info(
                "dispatch_timing stage=tts_stream_underlying_flush role=%s voice_id=%s "
                "voice_name=%s flush_count=%d",
                self._role,
                self._voice_id or "",
                self._voice_name or "",
                self._flush_count,
            )

    def end_input(self) -> None:
        if LIVEKIT_VERBOSE_LOGGING:
            logger.info(
                "dispatch_timing stage=tts_stream_end_input role=%s voice_id=%s "
                "voice_name=%s push_count=%d flush_count=%d",
                self._role,
                self._voice_id or "",
                self._voice_name or "",
                self._push_count,
                self._flush_count,
            )
        self.flush()
        self._stream.end_input()

    async def aclose(self) -> None:
        if LIVEKIT_VERBOSE_LOGGING:
            logger.info(
                "dispatch_timing stage=tts_stream_close role=%s voice_id=%s "
                "voice_name=%s audio_events=%d non_audio_events=%d",
                self._role,
                self._voice_id or "",
                self._voice_name or "",
                self._audio_event_count,
                self._non_audio_event_count,
            )
        await self._stream.aclose()

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            event = await self._stream.__anext__()
        except StopAsyncIteration:
            if LIVEKIT_VERBOSE_LOGGING:
                logger.info(
                    "dispatch_timing stage=tts_stream_iter_end role=%s voice_id=%s "
                    "voice_name=%s audio_events=%d non_audio_events=%d",
                    self._role,
                    self._voice_id or "",
                    self._voice_name or "",
                    self._audio_event_count,
                    self._non_audio_event_count,
                )
            raise
        frame = getattr(event, "frame", None)
        if frame is not None:
            self._audio_event_count += 1
            if LIVEKIT_VERBOSE_LOGGING:
                logger.info(
                    "dispatch_timing stage=tts_audio_frame role=%s voice_id=%s "
                    "voice_name=%s audio_event_count=%d sample_rate=%s "
                    "num_channels=%s samples_per_channel=%s",
                    self._role,
                    self._voice_id or "",
                    self._voice_name or "",
                    self._audio_event_count,
                    getattr(frame, "sample_rate", ""),
                    getattr(frame, "num_channels", ""),
                    getattr(frame, "samples_per_channel", ""),
                )
        else:
            self._non_audio_event_count += 1
            if LIVEKIT_VERBOSE_LOGGING:
                logger.info(
                    "dispatch_timing stage=tts_non_audio_event role=%s voice_id=%s "
                    "voice_name=%s non_audio_event_count=%d event_type=%s",
                    self._role,
                    self._voice_id or "",
                    self._voice_name or "",
                    self._non_audio_event_count,
                    type(event).__name__,
                )
        return event

    async def __aenter__(self):
        await self._stream.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc, exc_tb) -> None:
        await self._stream.__aexit__(exc_type, exc, exc_tb)


class LiveKitVoiceRouter:
    def __init__(self, dispatcher_client) -> None:
        self._dispatcher_client = dispatcher_client
        self._active_client = dispatcher_client
        self._target_clients: dict[str, SuperAgentsLiveKitClient] = {}
        self._active_target_voice_id: str | None = None
        self._active_target_voice_name: str | None = None
        self._proactive_steer_prompt_hashes: dict[str, float] = {}

    @property
    def active_client(self):
        return self._active_client

    @property
    def active_target_voice_id(self) -> str | None:
        return self._active_target_voice_id

    @property
    def active_target_voice_name(self) -> str | None:
        return self._active_target_voice_name

    def exit_to_dispatch(self) -> None:
        self._active_client = self._dispatcher_client
        self._active_target_voice_id = None
        self._active_target_voice_name = None
        self._dispatcher_client.reset_voice_route_to_dispatcher()

    async def transfer_to_thread(
        self,
        *,
        thread_id: str,
        cwd: str,
        label: str | None,
        voice_id: str | None = None,
        voice_name: str | None = None,
    ) -> None:
        target_voice = stable_super_agent_voice(thread_id, label)
        target_voice_id = voice_id or (target_voice.voice_id if target_voice else None)
        target_voice_name = voice_name or (target_voice.name if target_voice else None)
        target_client = self._target_clients.get(thread_id)
        if target_client is None:
            target_client = SuperAgentsLiveKitClient(
                cwd=cwd,
                state_path=None,
                approval_policy=LIVEKIT_CODEX_APPROVAL_POLICY,
                sandbox=LIVEKIT_CODEX_SANDBOX,
                service_tier=codex_service_tier(Path(LIVEKIT_DISPATCHER_CONFIG_PATH)),
                persist_thread=False,
                initial_thread_id=thread_id,
                super_agent_name=label,
                super_agent_agent_name=target_voice_name,
                use_super_agent_reasoning=True,
            )
            self._target_clients[thread_id] = target_client
        else:
            target_client.set_super_agent_name(label)
            target_client.set_super_agent_agent_name(target_voice_name)
        await target_client.prepare()
        self._active_client = target_client
        self._active_target_voice_id = target_voice_id
        self._active_target_voice_name = target_voice_name
        self._dispatcher_client.persist_voice_route(
            active_target_thread_id=thread_id,
            active_target_kind="codex_thread",
            active_target_label=label,
            active_target_voice_id=target_voice_id,
            active_target_voice_name=target_voice_name,
        )

    def claim_speech(self, client, turn_id: str) -> bool:
        return self._active_client is client and client.claim_speech(turn_id)

    def mark_proactive_steer(self, prompt: str) -> None:
        self._prune_proactive_steer_prompt_hashes()
        self._proactive_steer_prompt_hashes[_event_text_hash(prompt.strip())] = (
            time.monotonic()
        )

    def should_skip_proactively_steered_prompt(self, prompt: str) -> bool:
        prompt = prompt.strip()
        if not prompt:
            return False
        has_active_prompt = getattr(self._active_client, "has_active_prompt", None)
        if callable(has_active_prompt) and has_active_prompt(prompt):
            return False
        self._prune_proactive_steer_prompt_hashes()
        prompt_hash = _event_text_hash(prompt)
        return self._proactive_steer_prompt_hashes.pop(prompt_hash, None) is not None

    def _prune_proactive_steer_prompt_hashes(self) -> None:
        cutoff = time.monotonic() - PROACTIVE_STEER_PROMPT_CACHE_SECONDS
        stale_hashes = [
            prompt_hash
            for prompt_hash, created_at in self._proactive_steer_prompt_hashes.items()
            if created_at < cutoff
        ]
        for prompt_hash in stale_hashes:
            self._proactive_steer_prompt_hashes.pop(prompt_hash, None)

    async def close(self) -> None:
        for client in self._target_clients.values():
            await client.aclose()


class AnnouncerSpeechQueue:
    """Serializes non-Codex announcer speech behind normal agent speech."""

    def __init__(
        self,
        *,
        session: AgentSession,
        announcer_tts: VoiceSelectingTTS,
        max_queue_size: int = ANNOUNCER_MAX_QUEUE_SIZE,
        silence_grace_seconds: float = ANNOUNCER_SILENCE_GRACE_SECONDS,
    ) -> None:
        self._session = session
        self._announcer_tts = announcer_tts
        self._queue: asyncio.Queue[QueuedAnnouncerItem | None] = asyncio.Queue(
            maxsize=max_queue_size
        )
        self._silence_grace_seconds = max(0.0, silence_grace_seconds)
        self._state_changed = asyncio.Event()
        self._closed = False
        self._worker_task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._worker_task is None:
            self._worker_task = asyncio.create_task(
                self._run(),
                name="openbase-announcer-speech-queue",
            )

    def enqueue(self, message: AnnouncerQueueItem) -> bool:
        try:
            self._queue.put_nowait(
                QueuedAnnouncerItem(message=message, enqueued_at=time.monotonic())
            )
        except asyncio.QueueFull:
            logger.warning(
                "dispatch_timing stage=announcer_queue_full message_id=%s "
                "queue_size=%d max_queue_size=%d",
                message.message_id,
                self._queue.qsize(),
                self._queue.maxsize,
            )
            return False
        text_len = len(message.text) if isinstance(message, AnnouncerMessage) else 0
        logger.info(
            "dispatch_timing stage=announcer_enqueued message_id=%s kind=%s "
            "text_len=%d audio_path=%s voice_id=%s queue_size=%d",
            message.message_id,
            "text" if isinstance(message, AnnouncerMessage) else "audio_file",
            text_len,
            message.audio_path if isinstance(message, AnnouncerAudioMessage) else "",
            message.voice_id if isinstance(message, AnnouncerMessage) else "",
            self._queue.qsize(),
        )
        return True

    def notify_state_changed(self, *_args) -> None:
        self._state_changed.set()

    async def close(self) -> None:
        self._closed = True
        self.notify_state_changed()
        await self._queue.put(None)
        if self._worker_task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker_task
        await self._announcer_tts.aclose()

    async def _run(self) -> None:
        while True:
            queued_message = await self._queue.get()
            if queued_message is None:
                return
            try:
                await self._speak(
                    queued_message.message,
                    enqueued_at=queued_message.enqueued_at,
                )
            except Exception:
                logger.warning(
                    "Unable to play announcer message %s",
                    queued_message.message.message_id,
                    exc_info=True,
                )

    async def _speak(
        self,
        message: AnnouncerQueueItem,
        *,
        enqueued_at: float | None = None,
    ) -> None:
        if isinstance(message, AnnouncerAudioMessage):
            await self._play_audio(message, enqueued_at=enqueued_at)
            return

        started = time.monotonic()
        if enqueued_at is None:
            enqueued_at = started
        logger.info(
            "dispatch_timing stage=announcer_playout_wait_start message_id=%s",
            message.message_id,
        )
        if not await self._wait_until_both_silent(
            message_id=message.message_id,
            enqueued_at=enqueued_at,
        ):
            return

        spoken_text = format_for_speech(message.text)
        if not spoken_text:
            spoken_text = "Technical output omitted, shown on screen."
        logger.info(
            "dispatch_timing stage=announcer_speech_formatted message_id=%s "
            "original_len=%d spoken_len=%d",
            message.message_id,
            len(message.text),
            len(spoken_text),
        )

        if not self._both_silent() and not await self._wait_until_both_silent(
            message_id=message.message_id,
            enqueued_at=enqueued_at,
        ):
            return

        logger.info(
            "dispatch_timing stage=announcer_say_start message_id=%s wait_ms=%d "
            "queue_age_ms=%d voice_id=%s voice_name=%s text_len=%d",
            message.message_id,
            int((time.monotonic() - started) * 1000),
            int((time.monotonic() - enqueued_at) * 1000),
            self._announcer_tts.resolve_voice_id(message.voice_id),
            self._announcer_tts.resolve_voice_name(message.voice_id) or "",
            len(message.text),
        )

        handle = self._session.say(
            spoken_text,
            audio=self._announcer_audio(spoken_text, voice_id=message.voice_id),
            allow_interruptions=False,
            add_to_chat_ctx=False,
        )
        await handle.wait_for_playout()
        logger.info(
            "dispatch_timing stage=announcer_playout_end message_id=%s elapsed_ms=%d",
            message.message_id,
            int((time.monotonic() - started) * 1000),
        )

    async def _wait_until_both_silent(
        self,
        *,
        message_id: str,
        enqueued_at: float,
    ) -> bool:
        wait_logged = False
        wait_started = time.monotonic()
        while not self._closed:
            current_speech = self._session.current_speech
            has_current_speech = self._speech_active(current_speech)
            user_state = str(getattr(self._session, "user_state", "") or "")
            if not has_current_speech and user_state != "speaking":
                await self._wait_for_quiet_grace_period()
                current_speech = self._session.current_speech
                has_current_speech = self._speech_active(current_speech)
                user_state = str(getattr(self._session, "user_state", "") or "")
                if not has_current_speech and user_state != "speaking":
                    if wait_logged:
                        logger.info(
                            "dispatch_timing stage=announcer_silence_wait_end "
                            "message_id=%s wait_ms=%d queue_age_ms=%d",
                            message_id,
                            int((time.monotonic() - wait_started) * 1000),
                            int((time.monotonic() - enqueued_at) * 1000),
                        )
                    return True
                continue

            if not wait_logged:
                wait_logged = True
                logger.info(
                    "dispatch_timing stage=announcer_silence_wait_start "
                    "message_id=%s queue_size=%d user_state=%s agent_state=%s "
                    "has_current_speech=%s queue_age_ms=%d",
                    message_id,
                    self._queue.qsize(),
                    user_state,
                    getattr(self._session, "agent_state", "") or "",
                    has_current_speech,
                    int((time.monotonic() - enqueued_at) * 1000),
                )

            if has_current_speech:
                await current_speech.wait_for_playout()
                continue

            await self._wait_for_state_change_or_timeout(
                ANNOUNCER_STATE_WAIT_TIMEOUT_SECONDS
            )

        return False

    def _both_silent(self) -> bool:
        return not self._speech_active(
            self._session.current_speech
        ) and str(getattr(self._session, "user_state", "") or "") != "speaking"

    @staticmethod
    def _speech_active(speech_handle) -> bool:
        return speech_handle is not None and not speech_handle.done()

    async def _wait_for_quiet_grace_period(self) -> None:
        if self._silence_grace_seconds <= 0:
            return
        await self._wait_for_state_change_or_timeout(self._silence_grace_seconds)

    async def _wait_for_state_change_or_timeout(self, timeout_seconds: float) -> None:
        self._state_changed.clear()
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._state_changed.wait(), timeout_seconds)

    async def _announcer_audio(
        self,
        text: str,
        *,
        voice_id: str | None,
    ) -> AsyncIterator[rtc.AudioFrame]:
        # Use streaming synthesis (WebSocket) instead of non-streaming
        # synthesize() (HTTP POST to /tts/bytes) because the Openbase Cloud
        # audio proxy only supports the WebSocket path.
        resolved_voice_id = self._announcer_tts.resolve_voice_id(voice_id)
        tts_stream = self._announcer_tts._tts_for_voice(resolved_voice_id).stream()
        spoken_text = format_for_speech(text)
        if not spoken_text:
            spoken_text = "Technical output omitted, shown on screen."
        tts_stream.push_text(spoken_text)
        tts_stream.flush()
        tts_stream.end_input()
        try:
            async for event in tts_stream:
                yield event.frame
        finally:
            await tts_stream.aclose()

    async def _play_audio(
        self,
        message: AnnouncerAudioMessage,
        *,
        enqueued_at: float | None = None,
    ) -> None:
        started = time.monotonic()
        if enqueued_at is None:
            enqueued_at = started
        audio_path = Path(message.audio_path).expanduser()
        if not audio_path.is_file():
            logger.warning(
                "Unable to play announcer audio %s: file not found",
                message.message_id,
            )
            return
        if audio_path.suffix.lower() not in SUPPORTED_AUDIO_EXTENSIONS:
            logger.warning(
                "Unable to play announcer audio %s: unsupported extension %s",
                message.message_id,
                audio_path.suffix.lower(),
            )
            return

        logger.info(
            "dispatch_timing stage=announcer_audio_playout_wait_start message_id=%s",
            message.message_id,
        )
        if not await self._wait_until_both_silent(
            message_id=message.message_id,
            enqueued_at=enqueued_at,
        ):
            return
        if not self._both_silent() and not await self._wait_until_both_silent(
            message_id=message.message_id,
            enqueued_at=enqueued_at,
        ):
            return

        handle = self._session.say(
            "",
            audio=self._audio_file_frames(audio_path),
            allow_interruptions=False,
            add_to_chat_ctx=False,
        )
        await handle.wait_for_playout()
        logger.info(
            "dispatch_timing stage=announcer_audio_playout_end message_id=%s "
            "elapsed_ms=%d audio_basename=%s",
            message.message_id,
            int((time.monotonic() - started) * 1000),
            audio_path.name,
        )

    async def _audio_file_frames(self, path: Path) -> AsyncIterator[rtc.AudioFrame]:
        for frame in _decode_audio_file(path):
            yield frame


def _decode_audio_file(path: Path) -> list[rtc.AudioFrame]:
    frames: list[rtc.AudioFrame] = []
    with av.open(str(path)) as container:
        stream = next((candidate for candidate in container.streams.audio), None)
        if stream is None:
            raise ValueError(f"No audio stream found in {path.name}.")
        resampler = av.AudioResampler(format="s16", layout="mono", rate=48000)
        for packet in container.demux(stream):
            for decoded in packet.decode():
                for resampled in resampler.resample(decoded):
                    frames.append(_av_frame_to_livekit_frame(resampled))
        for resampled in resampler.resample(None):
            frames.append(_av_frame_to_livekit_frame(resampled))
    return frames


def _av_frame_to_livekit_frame(frame) -> rtc.AudioFrame:
    data = bytes(frame.planes[0])
    return rtc.AudioFrame(
        data=data,
        sample_rate=frame.sample_rate,
        num_channels=len(frame.layout.channels),
        samples_per_channel=frame.samples,
    )


def _packet_json_payload(
    data_packet: rtc.DataPacket,
    *,
    topic: str,
    label: str,
) -> dict | None:
    if data_packet.topic != topic:
        return None

    try:
        payload = json.loads(data_packet.data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        logger.warning(
            "dispatch_timing stage=data_packet_malformed label=%s topic=%s "
            "payload_bytes=%d payload_hash=%s",
            label,
            data_packet.topic,
            len(data_packet.data),
            _packet_hash(data_packet),
        )
        return None

    if not isinstance(payload, dict):
        logger.warning(
            "dispatch_timing stage=data_packet_unexpected_payload label=%s topic=%s "
            "payload_type=%s payload_bytes=%d payload_hash=%s",
            label,
            data_packet.topic,
            type(payload).__name__,
            len(data_packet.data),
            _packet_hash(data_packet),
        )
        return None

    return payload


def parse_announcer_packet(data_packet: rtc.DataPacket) -> AnnouncerMessage | None:
    payload = _packet_json_payload(
        data_packet,
        topic=ANNOUNCER_TOPIC,
        label="announcer",
    )
    if payload is None:
        return None
    if payload.get("kind") == ANNOUNCER_AUDIO_KIND:
        return None

    text = str(payload.get("text") or "").strip()
    if not text:
        logger.warning(
            "dispatch_timing stage=announcer_packet_missing_text topic=%s "
            "payload_bytes=%d payload_hash=%s",
            data_packet.topic,
            len(data_packet.data),
            _packet_hash(data_packet),
        )
        return None

    message_id = str(payload.get("message_id") or f"announcer-{uuid.uuid4().hex}")
    return AnnouncerMessage(
        message_id=message_id,
        text=text,
        voice_id=_optional_packet_str(payload.get("voice_id")),
    )


def parse_announcer_audio_packet(
    data_packet: rtc.DataPacket,
) -> AnnouncerAudioMessage | None:
    payload = _packet_json_payload(
        data_packet,
        topic=ANNOUNCER_TOPIC,
        label="announcer audio",
    )
    if payload is None or payload.get("kind") != ANNOUNCER_AUDIO_KIND:
        return None

    audio_path = str(payload.get("audio_path") or "").strip()
    if not audio_path:
        logger.warning(
            "dispatch_timing stage=announcer_audio_packet_missing_path topic=%s "
            "payload_bytes=%d payload_hash=%s",
            data_packet.topic,
            len(data_packet.data),
            _packet_hash(data_packet),
        )
        return None

    message_id = str(payload.get("message_id") or f"announcer-audio-{uuid.uuid4().hex}")
    return AnnouncerAudioMessage(
        message_id=message_id,
        audio_path=audio_path,
    )


def _packet_participant_identity(data_packet: rtc.DataPacket) -> str:
    participant = getattr(data_packet, "participant", None)
    return str(getattr(participant, "identity", "") or "")


def _packet_hash(data_packet: rtc.DataPacket) -> str:
    return hashlib.sha256(data_packet.data).hexdigest()[:12]


def parse_voice_route_packet(data_packet: rtc.DataPacket) -> VoiceRouteCommand | None:
    payload = _packet_json_payload(
        data_packet,
        topic=VOICE_ROUTE_TOPIC,
        label="voice route",
    )
    if payload is None:
        return None

    action = str(payload.get("action") or "").strip()
    if not action:
        return None
    state = payload.get("state") if isinstance(payload.get("state"), dict) else {}
    return VoiceRouteCommand(
        action=action,
        thread_id=_optional_packet_str(payload.get("thread_id")),
        cwd=_optional_packet_str(payload.get("cwd")),
        label=_optional_packet_str(payload.get("label")),
        active_target_voice_id=_optional_packet_str(
            state.get("active_target_voice_id")
        ),
        active_target_voice_name=_optional_packet_str(
            state.get("active_target_voice_name")
        )
        or _optional_packet_str(payload.get("agent_name")),
    )


def _optional_packet_str(value) -> str | None:
    return value if isinstance(value, str) and value else None


def _track_log_fields(track=None, publication=None) -> dict[str, str]:
    source = publication if publication is not None else track
    return {
        "track_sid": str(getattr(source, "sid", "") or ""),
        "track_name": str(getattr(source, "name", "") or ""),
        "track_kind": str(getattr(source, "kind", "") or ""),
        "track_source": str(getattr(source, "source", "") or ""),
        "mime_type": str(getattr(source, "mime_type", "") or ""),
        "muted": str(getattr(source, "muted", "")),
        "subscribed": str(getattr(publication, "subscribed", ""))
        if publication is not None
        else "",
    }


def _participant_log_fields(participant=None) -> dict[str, str]:
    return {
        "participant_identity": str(getattr(participant, "identity", "") or ""),
        "participant_sid": str(getattr(participant, "sid", "") or ""),
        "participant_name": str(getattr(participant, "name", "") or ""),
        "participant_kind": str(getattr(participant, "kind", "") or ""),
    }


def _register_room_diagnostics(room: rtc.Room):
    def on_participant_connected(participant) -> None:
        fields = _participant_log_fields(participant)
        logger.info(
            "dispatch_timing stage=room_participant_connected "
            "participant_identity=%s participant_sid=%s participant_name=%s "
            "participant_kind=%s publication_count=%d",
            fields["participant_identity"],
            fields["participant_sid"],
            fields["participant_name"],
            fields["participant_kind"],
            len(getattr(participant, "track_publications", {}) or {}),
        )

    def on_participant_disconnected(participant) -> None:
        fields = _participant_log_fields(participant)
        logger.info(
            "dispatch_timing stage=room_participant_disconnected "
            "participant_identity=%s participant_sid=%s participant_name=%s "
            "participant_kind=%s disconnect_reason=%s",
            fields["participant_identity"],
            fields["participant_sid"],
            fields["participant_name"],
            fields["participant_kind"],
            getattr(participant, "disconnect_reason", ""),
        )

    def on_track_published(publication, participant) -> None:
        participant_fields = _participant_log_fields(participant)
        track_fields = _track_log_fields(publication=publication)
        logger.info(
            "dispatch_timing stage=room_track_published participant_identity=%s "
            "participant_sid=%s track_sid=%s track_name=%s track_kind=%s "
            "track_source=%s mime_type=%s muted=%s subscribed=%s",
            participant_fields["participant_identity"],
            participant_fields["participant_sid"],
            track_fields["track_sid"],
            track_fields["track_name"],
            track_fields["track_kind"],
            track_fields["track_source"],
            track_fields["mime_type"],
            track_fields["muted"],
            track_fields["subscribed"],
        )

    def on_track_subscribed(track, publication, participant) -> None:
        participant_fields = _participant_log_fields(participant)
        track_fields = _track_log_fields(track=track, publication=publication)
        logger.info(
            "dispatch_timing stage=room_track_subscribed participant_identity=%s "
            "participant_sid=%s track_sid=%s track_name=%s track_kind=%s "
            "track_source=%s mime_type=%s muted=%s subscribed=%s track_class=%s",
            participant_fields["participant_identity"],
            participant_fields["participant_sid"],
            track_fields["track_sid"],
            track_fields["track_name"],
            track_fields["track_kind"],
            track_fields["track_source"],
            track_fields["mime_type"],
            track_fields["muted"],
            track_fields["subscribed"],
            type(track).__name__,
        )

    def on_track_unsubscribed(track, publication, participant) -> None:
        participant_fields = _participant_log_fields(participant)
        track_fields = _track_log_fields(track=track, publication=publication)
        logger.info(
            "dispatch_timing stage=room_track_unsubscribed participant_identity=%s "
            "participant_sid=%s track_sid=%s track_name=%s track_kind=%s "
            "track_source=%s mime_type=%s track_class=%s",
            participant_fields["participant_identity"],
            participant_fields["participant_sid"],
            track_fields["track_sid"],
            track_fields["track_name"],
            track_fields["track_kind"],
            track_fields["track_source"],
            track_fields["mime_type"],
            type(track).__name__,
        )

    def on_track_subscription_failed(participant, track_sid, error) -> None:
        participant_fields = _participant_log_fields(participant)
        logger.warning(
            "dispatch_timing stage=room_track_subscription_failed "
            "participant_identity=%s participant_sid=%s track_sid=%s error=%s",
            participant_fields["participant_identity"],
            participant_fields["participant_sid"],
            track_sid,
            error,
        )

    def on_track_muted(publication, participant) -> None:
        participant_fields = _participant_log_fields(participant)
        track_fields = _track_log_fields(publication=publication)
        logger.info(
            "dispatch_timing stage=room_track_muted participant_identity=%s "
            "participant_sid=%s track_sid=%s track_name=%s track_kind=%s "
            "track_source=%s",
            participant_fields["participant_identity"],
            participant_fields["participant_sid"],
            track_fields["track_sid"],
            track_fields["track_name"],
            track_fields["track_kind"],
            track_fields["track_source"],
        )

    def on_track_unmuted(publication, participant) -> None:
        participant_fields = _participant_log_fields(participant)
        track_fields = _track_log_fields(publication=publication)
        logger.info(
            "dispatch_timing stage=room_track_unmuted participant_identity=%s "
            "participant_sid=%s track_sid=%s track_name=%s track_kind=%s "
            "track_source=%s",
            participant_fields["participant_identity"],
            participant_fields["participant_sid"],
            track_fields["track_sid"],
            track_fields["track_name"],
            track_fields["track_kind"],
            track_fields["track_source"],
        )

    def on_active_speakers_changed(speakers) -> None:
        identities = [
            str(getattr(participant, "identity", "") or "") for participant in speakers
        ]
        logger.info(
            "dispatch_timing stage=room_active_speakers_changed count=%d identities=%s",
            len(identities),
            ",".join(identities),
        )

    def on_connection_state_changed(connection_state) -> None:
        logger.info(
            "dispatch_timing stage=room_connection_state_changed state=%s",
            connection_state,
        )

    def on_transcription_received(segments, participant, publication) -> None:
        participant_fields = _participant_log_fields(participant)
        track_fields = _track_log_fields(publication=publication)
        for segment in segments:
            text = str(getattr(segment, "text", "") or "")
            logger.info(
                "dispatch_timing stage=room_transcription_received "
                "participant_identity=%s participant_sid=%s track_sid=%s "
                "segment_id=%s final=%s text_len=%d text_hash=%s text_excerpt=%r",
                participant_fields["participant_identity"],
                participant_fields["participant_sid"],
                track_fields["track_sid"],
                getattr(segment, "id", ""),
                getattr(segment, "final", ""),
                len(text),
                _event_text_hash(text),
                text[:160],
            )

    handlers = (
        ("participant_connected", on_participant_connected),
        ("participant_disconnected", on_participant_disconnected),
        ("track_published", on_track_published),
        ("track_subscribed", on_track_subscribed),
        ("track_unsubscribed", on_track_unsubscribed),
        ("track_subscription_failed", on_track_subscription_failed),
        ("track_muted", on_track_muted),
        ("track_unmuted", on_track_unmuted),
        ("active_speakers_changed", on_active_speakers_changed),
        ("connection_state_changed", on_connection_state_changed),
        ("transcription_received", on_transcription_received),
    )
    for event_name, handler in handlers:
        room.on(event_name, handler)

    for participant in (room.remote_participants or {}).values():
        on_participant_connected(participant)
        for publication in (participant.track_publications or {}).values():
            on_track_published(publication, participant)
            if getattr(publication, "subscribed", False):
                track = getattr(publication, "track", None)
                if track is not None:
                    on_track_subscribed(track, publication, participant)
                else:
                    participant_fields = _participant_log_fields(participant)
                    track_fields = _track_log_fields(publication=publication)
                    logger.info(
                        "dispatch_timing stage=room_track_already_subscribed "
                        "participant_identity=%s participant_sid=%s track_sid=%s "
                        "track_name=%s track_kind=%s track_source=%s mime_type=%s",
                        participant_fields["participant_identity"],
                        participant_fields["participant_sid"],
                        track_fields["track_sid"],
                        track_fields["track_name"],
                        track_fields["track_kind"],
                        track_fields["track_source"],
                        track_fields["mime_type"],
                    )

    return handlers


def _register_session_diagnostics(
    session: AgentSession,
    voice_router: LiveKitVoiceRouter,
    *,
    enable_logging: bool,
):
    proactive_steer_tasks: set[asyncio.Task[None]] = set()

    async def proactively_steer_final_transcript(transcript: str) -> None:
        try:
            steer_active_turn = getattr(
                voice_router.active_client,
                "steer_active_turn",
                None,
            )
            if not callable(steer_active_turn):
                return
            turn_id = await steer_active_turn(transcript)
            if not turn_id:
                return
            voice_router.mark_proactive_steer(transcript)
            logger.info(
                "dispatch_timing stage=session_user_input_proactive_steer "
                "turn_id=%s transcript_len=%d transcript_hash=%s",
                turn_id,
                len(transcript),
                _event_text_hash(transcript),
            )
        except Exception:
            logger.warning(
                "dispatch_timing stage=session_user_input_proactive_steer_failed "
                "transcript_len=%d transcript_hash=%s",
                len(transcript),
                _event_text_hash(transcript),
                exc_info=True,
            )

    def schedule_proactive_steer(transcript: str) -> None:
        if _is_exit_to_dispatch_command(transcript):
            return
        task = asyncio.create_task(
            proactively_steer_final_transcript(transcript),
            name="openbase-proactive-super-agents-steer",
        )
        proactive_steer_tasks.add(task)
        task.add_done_callback(proactive_steer_tasks.discard)

    def on_user_state_changed(event) -> None:
        if not enable_logging:
            return
        logger.info(
            "dispatch_timing stage=session_user_state_changed old_state=%s new_state=%s",
            getattr(event, "old_state", ""),
            getattr(event, "new_state", ""),
        )

    def on_agent_state_changed(event) -> None:
        if not enable_logging:
            return
        logger.info(
            "dispatch_timing stage=session_agent_state_changed old_state=%s new_state=%s",
            getattr(event, "old_state", ""),
            getattr(event, "new_state", ""),
        )

    def on_user_input_transcribed(event) -> None:
        transcript = str(getattr(event, "transcript", "") or "")
        is_final = str(getattr(event, "is_final", "")).lower() == "true"
        if enable_logging:
            logger.info(
                "dispatch_timing stage=session_user_input_transcribed final=%s "
                "speaker_id=%s language=%s transcript_len=%d transcript_hash=%s "
                "transcript_excerpt=%r",
                getattr(event, "is_final", ""),
                getattr(event, "speaker_id", "") or "",
                getattr(event, "language", "") or "",
                len(transcript),
                _event_text_hash(transcript),
                transcript[:160],
            )
        if is_final and transcript.strip():
            schedule_proactive_steer(transcript.strip())

    def on_conversation_item_added(event) -> None:
        if not enable_logging:
            return
        item = getattr(event, "item", None)
        text_content = str(getattr(item, "text_content", "") or "")
        logger.info(
            "dispatch_timing stage=session_conversation_item_added item_type=%s "
            "role=%s text_len=%d text_hash=%s text_excerpt=%r",
            type(item).__name__,
            getattr(item, "role", "") or "",
            len(text_content),
            _event_text_hash(text_content),
            text_content[:160],
        )

    def on_speech_created(event) -> None:
        if not enable_logging:
            return
        speech_handle = getattr(event, "speech_handle", None)
        logger.info(
            "dispatch_timing stage=session_speech_created user_initiated=%s "
            "source=%s speech_handle_id=%s",
            getattr(event, "user_initiated", ""),
            getattr(event, "source", ""),
            getattr(speech_handle, "id", "") or getattr(speech_handle, "_id", ""),
        )

    def on_error(event) -> None:
        if not enable_logging:
            return
        error = getattr(event, "error", None)
        logger.warning(
            "dispatch_timing stage=session_error source=%s error_type=%s error=%s",
            type(getattr(event, "source", None)).__name__,
            type(error).__name__,
            error,
        )

    def on_close(event) -> None:
        if not enable_logging:
            return
        logger.info(
            "dispatch_timing stage=session_close reason=%s error_type=%s error=%s",
            getattr(event, "reason", ""),
            type(getattr(event, "error", None)).__name__,
            getattr(event, "error", None),
        )

    handlers = (
        ("user_state_changed", on_user_state_changed),
        ("agent_state_changed", on_agent_state_changed),
        ("user_input_transcribed", on_user_input_transcribed),
        ("conversation_item_added", on_conversation_item_added),
        ("speech_created", on_speech_created),
        ("error", on_error),
        ("close", on_close),
    )
    for event_name, handler in handlers:
        session.on(event_name, handler)
    return handlers


server = LiveKitAgentServer(
    host=LIVEKIT_AGENT_HOST,
    port=LIVEKIT_AGENT_PORT,
    **_livekit_agent_server_options(),
)


def prewarm(proc: JobProcess):
    vad_model = silero.VAD.load()
    proc.userdata["vad"] = (
        LoggingVAD(vad_model) if LIVEKIT_VERBOSE_LOGGING else vad_model
    )


server.setup_fnc = prewarm


def _build_voice_backend_client(*, persist_thread: bool) -> SuperAgentsLiveKitClient:
    return SuperAgentsLiveKitClient(
        cwd=LIVEKIT_CODEX_THREAD_CWD,
        state_path=LIVEKIT_CODEX_THREAD_STATE_PATH,
        developer_instructions=_load_dispatcher_developer_instructions(),
        approval_policy=LIVEKIT_CODEX_APPROVAL_POLICY,
        sandbox=LIVEKIT_CODEX_SANDBOX,
        service_tier=codex_service_tier(Path(LIVEKIT_DISPATCHER_CONFIG_PATH)),
        persist_thread=persist_thread,
    )


_shared_voice_backend_client = _build_voice_backend_client(persist_thread=True)


def _build_stt(vad_model=None):
    stt_provider = selected_stt_provider_id()
    if stt_provider == DEEPGRAM_STT_PROVIDER_ID:
        logger.info("Using Deepgram STT")
        stt = deepgram.STT(api_key=DEEPGRAM_API_KEY)
        stt = BrainScoreSTT(stt) if _brain_score_enabled() else stt
        return LoggingSTT(stt) if LIVEKIT_VERBOSE_LOGGING else stt
    if stt_provider == ASSEMBLYAI_STT_PROVIDER_ID:
        logger.info("Using AssemblyAI STT")
        stt = assemblyai.STT(api_key=ASSEMBLY_AI_API_KEY)
        stt = BrainScoreSTT(stt) if _brain_score_enabled() else stt
        return LoggingSTT(stt) if LIVEKIT_VERBOSE_LOGGING else stt
    if stt_provider == OPENBASE_CLOUD_STT_PROVIDER_ID:
        logger.info("Using Openbase Cloud STT")
        stt = assemblyai.STT(
            api_key=_openbase_cloud_audio_token(),
            base_url=_openbase_cloud_audio_ws_base_url("assemblyai"),
        )
        stt = BrainScoreSTT(stt) if _brain_score_enabled() else stt
        return LoggingSTT(stt) if LIVEKIT_VERBOSE_LOGGING else stt
    if stt_provider == LOCAL_MLX_WHISPER_STT_PROVIDER_ID:
        logger.info("Using local MLX Whisper STT")
        vad = vad_model or silero.VAD.load()
        stt = livekit_stt.StreamAdapter(stt=MLXWhisperSTT(), vad=vad)
        stt = BrainScoreSTT(stt) if _brain_score_enabled() else stt
        return LoggingSTT(stt) if LIVEKIT_VERBOSE_LOGGING else stt

    raise ValueError(f"Unsupported STT provider={stt_provider!r}")


def _openbase_cloud_audio_token() -> str:
    try:
        token = MachineTokenManager(WEB_BACKEND_URL).get_machine_token()
    except (AuthLoginRequiredError, AuthTransientError, MachineTokenError) as exc:
        raise OpenbaseCloudAudioAuthenticationError(
            "Openbase Cloud audio is selected, but Openbase Coder could not get "
            "a valid Openbase machine token. Run `openbase-coder login` and "
            "restart the Openbase services, or choose direct provider keys or "
            "local audio in voice settings."
        ) from exc
    if not token:
        raise OpenbaseCloudAudioAuthenticationError(
            "Openbase Cloud audio is selected, but Openbase Coder received an "
            "empty Openbase machine token. Run `openbase-coder login` and restart "
            "the Openbase services, or choose direct provider keys or local audio "
            "in voice settings."
        )
    return token


def _openbase_cloud_audio_http_base_url(provider: str) -> str:
    return f"{OPENBASE_CLOUD_AUDIO_BASE_URL}/{provider}"


def _openbase_cloud_audio_ws_base_url(provider: str) -> str:
    base_url = _openbase_cloud_audio_http_base_url(provider)
    if base_url.startswith("https://"):
        return f"wss://{base_url.removeprefix('https://')}"
    if base_url.startswith("http://"):
        return f"ws://{base_url.removeprefix('http://')}"
    return base_url


def _diagnostic_vad(vad_model):
    if not LIVEKIT_VERBOSE_LOGGING or isinstance(vad_model, LoggingVAD):
        return vad_model
    return LoggingVAD(vad_model)


async def _transfer_voice_route(
    voice_router: LiveKitVoiceRouter,
    route_command: VoiceRouteCommand,
    announcer_queue: AnnouncerSpeechQueue,
) -> None:
    assert route_command.thread_id is not None
    assert route_command.cwd is not None
    try:
        await voice_router.transfer_to_thread(
            thread_id=route_command.thread_id,
            cwd=route_command.cwd,
            label=route_command.label,
            voice_id=route_command.active_target_voice_id,
            voice_name=route_command.active_target_voice_name,
        )
    except Exception:
        logger.warning("Unable to transfer LiveKit voice route", exc_info=True)
        voice_router.exit_to_dispatch()
        announcer_queue.enqueue(
            AnnouncerMessage(
                message_id=f"voice-route-{uuid.uuid4().hex}",
                text="Unable to transfer voice route.",
            )
        )
        return

    announcer_queue.enqueue(
        AnnouncerMessage(
            message_id=f"voice-route-{uuid.uuid4().hex}",
            text="Voice route transferred.",
            voice_id=voice_router.active_target_voice_id,
        )
    )


@server.rtc_session(agent_name=LIVEKIT_DISPATCH_AGENT_NAME)
async def livekit_agent(ctx: JobContext):
    _refresh_audio_credentials()
    ctx.log_context_fields = {
        "room": ctx.room.name,
    }
    logger.info(
        "Connecting LiveKit voice session to Super Agents backend with cwd=%s",
        LIVEKIT_CODEX_THREAD_CWD,
    )
    voice_backend_client = (
        _build_voice_backend_client(persist_thread=False)
        if LIVEKIT_CODEX_FRESH_THREAD_PER_SESSION
        else _shared_voice_backend_client
    )
    prepare_task = asyncio.create_task(voice_backend_client.prepare())
    prepare_task.add_done_callback(_log_prepare_result)
    voice_router = LiveKitVoiceRouter(voice_backend_client)

    logger.info("Connecting to LiveKit room")
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    logger.info("Connected to LiveKit room")
    room_diagnostic_handlers = (
        _register_room_diagnostics(ctx.room) if LIVEKIT_VERBOSE_LOGGING else ()
    )

    dispatcher_voice = dispatcher_voice_config()
    tts_provider = get_tts_provider(dispatcher_voice.provider)
    announcer_voice = (
        tts_provider.voice_for_id(CARTESIA_ANNOUNCER_VOICE_ID)
        if tts_provider.provider_id == CARTESIA_PROVIDER_ID
        else None
    ) or tts_provider.default_announcer_voice()
    openbase_cloud_audio_token = (
        _openbase_cloud_audio_token()
        if tts_provider.provider_id == OPENBASE_CLOUD_TTS_PROVIDER_ID
        else ""
    )
    cartesia_api_key = openbase_cloud_audio_token or CARTESIA_API_KEY
    cartesia_base_url = (
        _openbase_cloud_audio_http_base_url("cartesia")
        if openbase_cloud_audio_token
        else None
    )
    cartesia_api_version = (
        OPENBASE_CLOUD_AUDIO_CARTESIA_VERSION if openbase_cloud_audio_token else None
    )
    direct_tts = VoiceSelectingTTS(
        default_voice_id=dispatcher_voice.voice_id,
        default_voice_name=dispatcher_voice.name,
        active_voice_id=lambda: voice_router.active_target_voice_id,
        active_voice_name=lambda: voice_router.active_target_voice_name,
        api_key=cartesia_api_key,
        provider=tts_provider,
        role="direct",
        base_url=cartesia_base_url,
        api_version=cartesia_api_version,
    )
    announcer_tts = VoiceSelectingTTS(
        default_voice_id=announcer_voice.id,
        default_voice_name=announcer_voice.name,
        active_voice_id=lambda: voice_router.active_target_voice_id,
        active_voice_name=lambda: voice_router.active_target_voice_name,
        api_key=cartesia_api_key,
        provider=tts_provider,
        role="announcer",
        base_url=cartesia_base_url,
        api_version=cartesia_api_version,
    )

    session_vad = _diagnostic_vad(ctx.proc.userdata["vad"])

    # Set up a voice AI pipeline
    session = AgentSession(
        stt=_build_stt(session_vad),
        llm=CodexLiveKitLLM(voice_router),
        tts=direct_tts,
        turn_handling={
            "turn_detection": MultilingualModel(),
            "interruption": {"mode": "vad"},
        },
        vad=session_vad,
        preemptive_generation=False,
    )
    session_diagnostic_handlers = _register_session_diagnostics(
        session,
        voice_router,
        enable_logging=LIVEKIT_VERBOSE_LOGGING,
    )

    # Start the session
    await session.start(
        agent=Assistant(),
        room=ctx.room,
    )
    logger.info(
        "dispatch_timing stage=agent_session_start_complete room_name=%s "
        "stt_provider=%s tts_role=direct",
        ctx.room.name,
        selected_stt_provider_id(),
    )

    announcer_queue = AnnouncerSpeechQueue(
        session=session,
        announcer_tts=announcer_tts,
    )

    announcer_queue_session_handlers = (
        ("user_state_changed", announcer_queue.notify_state_changed),
        ("agent_state_changed", announcer_queue.notify_state_changed),
        ("speech_created", announcer_queue.notify_state_changed),
    )
    for event_name, handler in announcer_queue_session_handlers:
        session.on(event_name, handler)

    announcer_queue.start()

    def on_data_received(data_packet: rtc.DataPacket) -> None:
        logger.info(
            "dispatch_timing stage=livekit_data_received topic=%s kind=%s "
            "payload_bytes=%d payload_hash=%s participant_identity=%s",
            data_packet.topic,
            data_packet.kind,
            len(data_packet.data),
            _packet_hash(data_packet),
            _packet_participant_identity(data_packet),
        )
        message = parse_announcer_packet(data_packet)
        if message is not None:
            logger.info(
                "dispatch_timing stage=announcer_packet_received message_id=%s "
                "voice_id=%s text_len=%d payload_hash=%s",
                message.message_id,
                message.voice_id or "",
                len(message.text),
                _packet_hash(data_packet),
            )
            announcer_queue.enqueue(message)
            return

        audio_message = parse_announcer_audio_packet(data_packet)
        if audio_message is not None:
            logger.info(
                "dispatch_timing stage=announcer_audio_packet_received "
                "message_id=%s audio_path=%s payload_hash=%s",
                audio_message.message_id,
                audio_message.audio_path,
                _packet_hash(data_packet),
            )
            announcer_queue.enqueue(audio_message)
            return

        route_command = parse_voice_route_packet(data_packet)
        if route_command is None:
            logger.info(
                "dispatch_timing stage=livekit_data_ignored topic=%s payload_hash=%s",
                data_packet.topic,
                _packet_hash(data_packet),
            )
            return
        logger.info(
            "dispatch_timing stage=voice_route_packet_received action=%s "
            "thread_id=%s cwd=%s label=%s active_target_voice_id=%s "
            "payload_hash=%s",
            route_command.action,
            route_command.thread_id or "",
            route_command.cwd or "",
            route_command.label or "",
            route_command.active_target_voice_id or "",
            _packet_hash(data_packet),
        )
        if route_command.action == "exit_to_dispatch":
            voice_router.exit_to_dispatch()
            announcer_queue.enqueue(
                AnnouncerMessage(
                    message_id=f"voice-route-{uuid.uuid4().hex}",
                    text="Back to dispatch.",
                )
            )
        elif route_command.action == "transfer_to_thread":
            if not route_command.thread_id or not route_command.cwd:
                logger.warning(
                    "Ignoring incomplete LiveKit voice route transfer command"
                )
                return
            asyncio.create_task(
                _transfer_voice_route(
                    voice_router,
                    route_command,
                    announcer_queue,
                )
            )
        else:
            logger.warning(
                "Ignoring unsupported LiveKit voice route action %s",
                route_command.action,
            )

    ctx.room.on("data_received", on_data_received)

    async def close_announcer_queue(*_args) -> None:
        ctx.room.off("data_received", on_data_received)
        for event_name, handler in room_diagnostic_handlers:
            ctx.room.off(event_name, handler)
        for event_name, handler in session_diagnostic_handlers:
            session.off(event_name, handler)
        for event_name, handler in announcer_queue_session_handlers:
            session.off(event_name, handler)
        await announcer_queue.close()
        await voice_router.close()

    ctx.add_shutdown_callback(close_announcer_queue)
    logger.info("LiveKit AgentSession started")


def main():
    cli.run_app(server)


def _log_prepare_result(task: asyncio.Task[str]) -> None:
    try:
        thread_id = task.result()
    except Exception:
        logger.warning("Failed to warm Codex LiveKit thread", exc_info=True)
    else:
        logger.info("Warmed Codex LiveKit thread %s", thread_id)


if __name__ == "__main__":
    main()
