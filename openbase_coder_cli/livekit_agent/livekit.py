"""LiveKit agent entrypoint: server wiring for the Openbase Coder voice session.

The per-concern implementations live in sibling modules (``config``,
``voices``, ``spoken_commands``, ``codex_llm``, ``audio_scoring``,
``audio_diagnostics``, ``tts_selection``, ``packets``, ``speech_queue``,
``voice_routing``, ``room_diagnostics``, ``session_diagnostics``). Their
public names are re-exported here for backward compatibility.
"""

import asyncio
import logging
import os
import uuid
from pathlib import Path

from livekit import rtc
from livekit.agents import (
    Agent,
    AgentSession,
    AutoSubscribe,
    JobContext,
    JobProcess,
    cli,
)
from livekit.agents import (
    AgentServer as LiveKitAgentServer,
)
from livekit.agents import (
    stt as livekit_stt,
)
from livekit.plugins import assemblyai, cartesia, deepgram, silero  # noqa: F401
from livekit.plugins.turn_detector.multilingual import MultilingualModel

from openbase_coder_cli.brain_score import (  # noqa: F401
    brain_score_token_configured,
    brain_score_token_file,
    load_brain_score_token,
)
from openbase_coder_cli.config.machine_token_manager import (
    MachineTokenError,
    MachineTokenManager,
)
from openbase_coder_cli.config.token_manager import (  # noqa: F401
    DEFAULT_WEB_BACKEND_URL,
    AuthLoginRequiredError,
    AuthTransientError,
)
from openbase_coder_cli.dispatcher_config import (
    codex_service_tier,
    selected_stt_provider_id,
    selected_tts_provider_id,
)
from openbase_coder_cli.livekit_agent.audio_diagnostics import (  # noqa: F401
    LoggingRecognizeStream,
    LoggingSTT,
    LoggingVAD,
    LoggingVADStream,
    _log_stt_event,
)
from openbase_coder_cli.livekit_agent.audio_scoring import (  # noqa: F401
    BrainScoreAudioScorer,
    BrainScoreRecognizeStream,
    BrainScoreSTT,
    _brain_score_enabled,
    _last_brain_score_update_at,
    _load_brain_score_token,
    _upload_brain_score_chunk,
    _write_brain_score_json,
)
from openbase_coder_cli.livekit_agent.codex_llm import (  # noqa: F401
    CodexLiveKitLLM,
    CodexLLMStream,
)
from openbase_coder_cli.livekit_agent.config import (  # noqa: F401
    ANNOUNCER_AUDIO_KIND,
    ANNOUNCER_MAX_QUEUE_SIZE,
    ANNOUNCER_SILENCE_GRACE_SECONDS,
    ANNOUNCER_STATE_WAIT_TIMEOUT_SECONDS,
    ANNOUNCER_TOPIC,
    BRAIN_SCORE_COOLDOWN_SECONDS,
    BRAIN_SCORE_ENABLED,
    BRAIN_SCORE_ENDPOINT,
    BRAIN_SCORE_INTERVAL_SECONDS,
    BRAIN_SCORE_LATITUDE,
    BRAIN_SCORE_LONGITUDE,
    BRAIN_SCORE_MIN_DURATION_SECONDS,
    BRAIN_SCORE_OUTPUT_PATH,
    BRAIN_SCORE_TOKEN_FILE,
    CARTESIA_ANNOUNCER_VOICE_ID,
    CARTESIA_VOICE_ID,
    CODEX_APP_SERVER_URL,
    DEFAULT_DIRECT_LIVEKIT_INSTRUCTIONS_PATH,
    DEFAULT_LIVEKIT_DISPATCHER_CONFIG_PATH,
    DIRECT_LIVEKIT_BUILTIN_DEVELOPER_INSTRUCTIONS,
    DIRECT_LIVEKIT_INSTRUCTIONS_PATH_ENV,
    DIRECT_LIVEKIT_INSTRUCTIONS_TEXT_ENV,
    DISPATCHER_BUILTIN_DEVELOPER_INSTRUCTIONS,
    LIVEKIT_AGENT_HOST,
    LIVEKIT_AGENT_LOAD_THRESHOLD_ENV,
    LIVEKIT_AGENT_NUM_IDLE_PROCESSES_ENV,
    LIVEKIT_AGENT_PORT,
    LIVEKIT_AUDIO_FRAME_LOG_EVERY,
    LIVEKIT_AUDIO_FRAME_LOG_FIRST,
    LIVEKIT_CODEX_ACK_DELAY_SECONDS,
    LIVEKIT_CODEX_ACK_MESSAGE,
    LIVEKIT_CODEX_APPROVAL_POLICY,
    LIVEKIT_CODEX_FRESH_THREAD_PER_SESSION,
    LIVEKIT_CODEX_SANDBOX,
    LIVEKIT_CODEX_THREAD_CWD,
    LIVEKIT_CODEX_THREAD_STATE_PATH,
    LIVEKIT_DISPATCH_AGENT_NAME,
    LIVEKIT_DISPATCHER_CONFIG_PATH,
    LIVEKIT_STT_PROVIDER,
    LIVEKIT_VERBOSE_LOGGING,
    OPENBASE_CLOUD_AUDIO_BASE_URL,
    OPENBASE_CLOUD_AUDIO_CARTESIA_VERSION,
    PROACTIVE_STEER_PROMPT_CACHE_SECONDS,
    SUPPORTED_AUDIO_EXTENSIONS,
    VOICE_ROUTE_TOPIC,
    WEB_BACKEND_URL,
    _canonical_env_path,
    _load_dispatcher_developer_instructions,
    _load_openbase_env,
    _optional_float_env,
    _optional_int_env,
    _read_instruction_file,
    load_direct_livekit_developer_instructions,
)
from openbase_coder_cli.livekit_agent.logging_utils import (  # noqa: F401
    _event_text_hash,
    _frame_duration_ms,
    _should_log_audio_frame,
)
from openbase_coder_cli.livekit_agent.packets import (  # noqa: F401
    AnnouncerAudioMessage,
    AnnouncerMessage,
    AnnouncerQueueItem,
    QueuedAnnouncerItem,
    VoiceRouteCommand,
    _optional_packet_str,
    _packet_hash,
    _packet_json_payload,
    _packet_participant_identity,
    parse_announcer_audio_packet,
    parse_announcer_packet,
    parse_voice_route_packet,
)
from openbase_coder_cli.livekit_agent.room_diagnostics import (  # noqa: F401
    _participant_log_fields,
    _register_room_diagnostics,
    _track_log_fields,
)
from openbase_coder_cli.livekit_agent.session_diagnostics import (
    _register_session_diagnostics,
)
from openbase_coder_cli.livekit_agent.speech_formatter import (  # noqa: F401
    format_for_speech,
)
from openbase_coder_cli.livekit_agent.speech_queue import (  # noqa: F401
    AnnouncerSpeechQueue,
    _av_frame_to_livekit_frame,
    _decode_audio_file,
)
from openbase_coder_cli.livekit_agent.spoken_commands import (  # noqa: F401
    EXIT_TO_DISPATCH_PHRASE,
    EXIT_TO_DISPATCH_PHRASES,
    _is_exit_to_dispatch_command,
    _normalize_spoken_command,
)
from openbase_coder_cli.livekit_agent.super_agents_client import (
    SuperAgentsLiveKitClient,
)
from openbase_coder_cli.livekit_agent.tts_selection import (  # noqa: F401
    SpeechFormattingSynthesizeStream,
    VoiceSelectingCartesiaTTS,
    VoiceSelectingTTS,
)
from openbase_coder_cli.livekit_agent.voice_routing import (
    LiveKitVoiceRouter,
    _transfer_voice_route,
)
from openbase_coder_cli.livekit_agent.voices import (  # noqa: F401
    SUPER_AGENT_VOICE_IDS,
    SUPER_AGENT_VOICES,
    CartesiaVoice,
    _current_super_agent_voices,
    _voices_from_ids,
    dispatcher_voice_config,
    stable_super_agent_voice,
    stable_super_agent_voice_id,
)
from openbase_coder_cli.stt_providers import (
    ASSEMBLYAI_STT_PROVIDER_ID,
    DEEPGRAM_STT_PROVIDER_ID,
    LOCAL_MLX_WHISPER_STT_PROVIDER_ID,
    OPENBASE_CLOUD_STT_PROVIDER_ID,
    MLXWhisperSTT,
)
from openbase_coder_cli.tts_providers import (  # noqa: F401
    CARTESIA_PROVIDER_ID,
    DEFAULT_CARTESIA_ANNOUNCER_VOICE_ID,
    DEFAULT_CARTESIA_TTS_VOLUME,
    DEFAULT_CARTESIA_VOICE_ID,
    KOKORO_PROVIDER_ID,
    OPENBASE_CLOUD_TTS_PROVIDER_ID,
    get_tts_provider,
)

logger = logging.getLogger(__name__)

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


class OpenbaseCloudAudioAuthenticationError(RuntimeError):
    """Openbase Cloud audio requires a valid Openbase machine token."""


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


class Assistant(Agent):
    """The LiveKit agent"""

    def __init__(self) -> None:
        super().__init__(
            instructions="",  # Instructions are not used due to LastMessageOnlyStream.
        )


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
