"""Agent session event handlers: diagnostics and proactive turn steering."""

import asyncio
import logging

from livekit.agents import AgentSession

from openbase_coder_cli.livekit_agent.logging_utils import _event_text_hash
from openbase_coder_cli.livekit_agent.spoken_commands import (
    _is_exit_to_dispatch_command,
)
from openbase_coder_cli.livekit_agent.voice_routing import LiveKitVoiceRouter

logger = logging.getLogger(__name__)


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
