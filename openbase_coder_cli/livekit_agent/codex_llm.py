"""LiveKit LLM bridge that runs user turns against the Codex app-server."""

import asyncio
import contextlib
import hashlib
import logging
import uuid
from typing import TYPE_CHECKING

from livekit.agents import llm
from livekit.agents.llm.chat_context import ChatMessage
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS

from openbase_coder_cli.livekit_agent.config import (
    LIVEKIT_CODEX_ACK_DELAY_SECONDS,
    LIVEKIT_CODEX_ACK_MESSAGE,
    load_direct_livekit_developer_instructions,
)
from openbase_coder_cli.livekit_agent.spoken_commands import (
    _is_exit_to_dispatch_command,
)
from openbase_coder_cli.onboarding_reminder import append_onboarding_reminder

if TYPE_CHECKING:
    from openbase_coder_cli.livekit_agent.voice_routing import LiveKitVoiceRouter

logger = logging.getLogger(__name__)


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

        # When the dispatcher is already active, "exit to dispatch" is a no-op;
        # treat the utterance as a normal prompt instead of swallowing it.
        if (
            _is_exit_to_dispatch_command(prompt)
            and not self._voice_router.is_dispatcher_active
        ):
            self._voice_router.exit_to_dispatch()
            self._emit_delta("Back to dispatch.")
            return

        if self._voice_router.is_dispatcher_active:
            prompt = append_onboarding_reminder(prompt)

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
        elif speech_text and turn_id:
            # The generation's event channel closed before the answer could
            # be emitted; hand it to the orphaned-result handler so it is
            # still spoken instead of silently dropped.
            orphan_handler = getattr(voice_client, "orphaned_result_handler", None)
            if callable(orphan_handler):
                logger.info(
                    "dispatch_timing stage=livekit_llm_channel_closed_redelivery "
                    "message_id=%s turn_id=%s speech_len=%d",
                    self._message_id,
                    turn_id,
                    len(speech_text),
                )
                orphan_handler(voice_client, turn_id, speech_text)

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
