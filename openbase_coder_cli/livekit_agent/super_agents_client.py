from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any

from openbase_coder_cli.dispatcher_config import (
    dispatcher_reasoning_effort,
    dispatcher_voice,
    super_agents_model,
    super_agents_reasoning_effort,
)
from openbase_coder_cli.livekit_agent.codex_thread_state import (
    load_thread_id,
    persist_thread_id,
    persist_voice_route_state,
    thread_state_file_lock,
)
from openbase_coder_cli.livekit_agent.codex_turns import (
    _active_turn_id_mismatch,
    _is_no_active_turn_error,
    _is_turn_cannot_accept_steering_error,
    _prompt_debug_fields,
    _speech_excerpt,
    _super_agent_name,
    _with_super_agent_identity_instructions,
)
from openbase_coder_cli.paths import CODEX_DISPATCHER_CONFIG_PATH

logger = logging.getLogger(__name__)
DISPATCH_TIMING_LOG = "dispatch_timing"
DEFAULT_CODEX_MODEL = "gpt-5.5"
SUPER_AGENTS_MODEL_ENV = "SUPER_AGENTS_MODEL"
DEFAULT_DISPATCHER_LABEL = "dispatcher"
TURN_POLL_INTERVAL_SECONDS = 0.5


def _default_model_name() -> str:
    return os.getenv("CODEX_MODEL", DEFAULT_CODEX_MODEL).strip() or DEFAULT_CODEX_MODEL


def _super_agents_model_name(path: Path | None = None) -> str | None:
    return (
        super_agents_model(path)
        or os.getenv(SUPER_AGENTS_MODEL_ENV, "").strip()
        or None
    )


class SuperAgentsLiveKitClient:
    """LiveKit voice client backed by the Super Agents Python interface."""

    def __init__(
        self,
        *,
        cwd: str,
        state_path: str | None = None,
        developer_instructions: str | None = None,
        approval_policy: str = "never",
        sandbox: str = "danger-full-access",
        model_name: str | None = None,
        service_tier: str = "fast",
        dispatcher_config_path: str | Path | None = None,
        persist_thread: bool = True,
        initial_thread_id: str | None = None,
        super_agent_name: str | None = None,
        super_agent_agent_name: str | None = None,
        use_super_agent_reasoning: bool = False,
        backend_client: Any | None = None,
    ) -> None:
        self._cwd = cwd
        self._state_path = (
            Path(state_path or Path.home() / ".openbase" / "livekit-voice-route.json")
            if persist_thread
            else None
        )
        self._developer_instructions = developer_instructions or None
        self._approval_policy = approval_policy
        self._sandbox = sandbox
        self._model_name = model_name or _default_model_name()
        self._service_tier = service_tier
        self._super_agent_name = _super_agent_name(
            super_agent_name
            if super_agent_name is not None
            else DEFAULT_DISPATCHER_LABEL
            if persist_thread
            else None
        )
        self._super_agent_agent_name = _super_agent_name(super_agent_agent_name)
        self._use_super_agent_reasoning = use_super_agent_reasoning
        self._dispatcher_config_path = Path(
            dispatcher_config_path
            or os.getenv("LIVEKIT_DISPATCHER_CONFIG_PATH")
            or CODEX_DISPATCHER_CONFIG_PATH
        )
        self._super_agents_model_name = _super_agents_model_name(
            self._dispatcher_config_path
        )
        self._backend_client = backend_client or self._client_from_environment()
        self._thread_id = initial_thread_id or (
            self._load_thread_id() if persist_thread else None
        )
        self._thread_loaded = False
        self._active_turn_id: str | None = None
        self._active_turn_started_at: float | None = None
        self._active_turn_dispatch_id: str | None = None
        self._claimed_speech_turns: set[str] = set()
        self._state_lock = asyncio.Lock()
        self._turn_start_lock = asyncio.Lock()

    @property
    def model_name(self) -> str:
        backend = getattr(self._backend_client, "backend", None)
        if isinstance(backend, str) and backend != "codex":
            return backend
        return self._model_name

    def set_super_agent_name(self, name: str | None) -> None:
        self._super_agent_name = _super_agent_name(name)

    def set_super_agent_agent_name(self, name: str | None) -> None:
        self._super_agent_agent_name = _super_agent_name(name)

    async def aclose(self) -> None:
        close = getattr(self._backend_client, "close", None)
        if close is not None:
            await close()

    async def prepare(self) -> str:
        return await self._ensure_thread()

    async def run_turn(
        self,
        prompt: str,
        *,
        developer_instructions: str | None = None,
    ) -> dict[str, Any]:
        dispatch_id = f"voice-{uuid.uuid4().hex[:12]}"
        dispatch_started = time.monotonic()
        prompt_debug = _prompt_debug_fields(prompt)

        async with self._turn_start_lock:
            thread_id = await self._ensure_thread()
            logger.info(
                "%s stage=voice_request_received dispatch_id=%s thread_id=%s "
                "cwd_basename=%s elapsed_ms=%d",
                DISPATCH_TIMING_LOG,
                dispatch_id,
                thread_id,
                Path(self._cwd).name,
                int((time.monotonic() - dispatch_started) * 1000),
            )

            if self._active_turn_id:
                turn_id = await self._steer_turn(thread_id, prompt)
            else:
                turn_id = await self._start_turn(
                    thread_id,
                    prompt,
                    developer_instructions=developer_instructions,
                    dispatch_id=dispatch_id,
                )
            self._active_turn_id = turn_id
            self._active_turn_started_at = time.monotonic()
            self._active_turn_dispatch_id = dispatch_id

        logger.info(
            "%s stage=turn_wait_start dispatch_id=%s thread_id=%s turn_id=%s "
            "prompt_hash=%s prompt_len=%s",
            DISPATCH_TIMING_LOG,
            dispatch_id,
            thread_id,
            turn_id,
            prompt_debug["hash"],
            prompt_debug["length"],
        )
        result = await self._wait_for_turn(thread_id, turn_id)
        speech_text = _speech_text_from_progress(result)
        completed_turn = {
            "id": turn_id,
            "status": result.get("status") or result.get("summary", {}).get("status"),
            "_livekit_speech_text": speech_text,
            "_livekit_turn_id": turn_id,
            "progress": result,
        }
        if self._active_turn_id == turn_id:
            self._active_turn_id = None
            self._active_turn_started_at = None
            self._active_turn_dispatch_id = None
        logger.info(
            "%s stage=voice_turn_result dispatch_id=%s turn_id=%s status=%s "
            "elapsed_ms=%d speech_chars=%d",
            DISPATCH_TIMING_LOG,
            dispatch_id,
            turn_id,
            completed_turn.get("status"),
            int((time.monotonic() - dispatch_started) * 1000),
            len(speech_text),
        )
        return completed_turn

    async def _start_turn(
        self,
        thread_id: str,
        prompt: str,
        *,
        developer_instructions: str | None,
        dispatch_id: str,
    ) -> str:
        reasoning_effort = self._configured_reasoning_effort()
        turn_input: dict[str, Any] = {
            "prompt": prompt,
            "cwd": self._cwd,
            "label": self._super_agent_name,
            "agentName": self._super_agent_agent_name,
            "approvalPolicy": self._approval_policy,
            "sandbox": self._sandbox,
            "serviceTier": self._service_tier,
            "_mcpCallId": dispatch_id,
        }
        if self._backend_is_codex():
            turn_input["model"] = self._model_name
        elif self._super_agents_model_name:
            turn_input["model"] = self._super_agents_model_name
        if reasoning_effort:
            turn_input["reasoningEffort"] = reasoning_effort
        if effective_developer_instructions := self._turn_developer_instructions(
            developer_instructions
        ):
            turn_input["developerInstructions"] = effective_developer_instructions

        result = await self._backend_client.start_turn_by_label(
            self._query(thread_id=thread_id),
            turn_input,
        )
        turn_id = _extract_turn_id(result)
        if not turn_id:
            raise RuntimeError("Super Agents did not return a turn id.")
        logger.info(
            "%s stage=turn_start_response dispatch_id=%s thread_id=%s turn_id=%s",
            DISPATCH_TIMING_LOG,
            dispatch_id,
            thread_id,
            turn_id,
        )
        return turn_id

    async def _steer_turn(self, thread_id: str, prompt: str) -> str:
        assert self._active_turn_id is not None
        prompt_debug = _prompt_debug_fields(prompt)
        try:
            result = await self._backend_client.steer_by_label(
                self._query(thread_id=thread_id, turn_id=self._active_turn_id),
                prompt,
            )
        except RuntimeError as exc:
            actual_turn_id = _active_turn_id_mismatch(exc)
            if actual_turn_id:
                logger.warning(
                    "Super Agents active turn id drifted during steering; "
                    "expected_turn_id=%s actual_turn_id=%s prompt_hash=%s",
                    self._active_turn_id,
                    actual_turn_id,
                    prompt_debug["hash"],
                )
                self._active_turn_id = actual_turn_id
                result = await self._backend_client.steer_by_label(
                    self._query(thread_id=thread_id, turn_id=actual_turn_id),
                    prompt,
                )
            elif _is_turn_cannot_accept_steering_error(exc):
                logger.warning(
                    "Super Agents turn %s could not accept steering; leaving active turn running "
                    "prompt_hash=%s",
                    self._active_turn_id,
                    prompt_debug["hash"],
                )
                return self._active_turn_id
            elif _is_no_active_turn_error(exc):
                logger.info(
                    "Super Agents turn %s was already inactive during steering prompt_hash=%s",
                    self._active_turn_id,
                    prompt_debug["hash"],
                )
                self._active_turn_id = None
                return await self._start_turn(
                    thread_id,
                    prompt,
                    developer_instructions=None,
                    dispatch_id=f"voice-{uuid.uuid4().hex[:12]}",
                )
            else:
                raise
        turn_id = _extract_turn_id(result) or self._active_turn_id
        logger.info(
            "Submitted Super Agents turn steering turn_id=%s prompt_hash=%s prompt_len=%s",
            turn_id,
            prompt_debug["hash"],
            prompt_debug["length"],
        )
        return turn_id

    async def _wait_for_turn(self, thread_id: str, turn_id: str) -> dict[str, Any]:
        while True:
            progress = await self._backend_client.progress_by_label(
                self._query(
                    thread_id=thread_id,
                    turn_id=turn_id,
                    include_items=True,
                    final_only=True,
                    max_items=5,
                    max_output_chars=4000,
                    include_turn=True,
                )
            )
            status = str(
                progress.get("status")
                or progress.get("summary", {}).get("status")
                or ""
            ).lower()
            if status == "waiting" and not _progress_has_pending_requests(progress):
                return progress
            if status and status not in {
                "running",
                "waiting",
                "queued",
                "inprogress",
                "in_progress",
            }:
                return progress
            await asyncio.sleep(TURN_POLL_INTERVAL_SECONDS)

    async def _ensure_thread(self) -> str:
        async with self._state_lock:
            if self._state_path is not None:
                with self._thread_state_file_lock():
                    canonical_thread_id = self._load_thread_id()
                    if canonical_thread_id and canonical_thread_id != self._thread_id:
                        logger.info(
                            "Adopting canonical LiveKit Super Agents thread from disk "
                            "previous_thread_id=%s canonical_thread_id=%s",
                            self._thread_id,
                            canonical_thread_id,
                        )
                        self._thread_id = canonical_thread_id
                        self._thread_loaded = False

                    if self._thread_loaded and self._thread_id:
                        return self._thread_id

                    if self._thread_id:
                        try:
                            return await self._resume_thread(self._thread_id)
                        except Exception:
                            logger.warning(
                                "Failed to resume persisted LiveKit Super Agents thread %s",
                                self._thread_id,
                                exc_info=True,
                            )
                            self._thread_id = None
                            self._thread_loaded = False

                    return await self._start_thread()

            if self._thread_loaded and self._thread_id:
                return self._thread_id
            if self._thread_id:
                try:
                    return await self._resume_thread(self._thread_id)
                except Exception:
                    logger.warning(
                        "Failed to resume LiveKit Super Agents thread %s; creating a new one",
                        self._thread_id,
                        exc_info=True,
                    )
                    self._thread_id = None
                    self._thread_loaded = False
            return await self._start_thread()

    async def _start_thread(self) -> str:
        params: dict[str, Any] = {
            "name": self._super_agent_name or DEFAULT_DISPATCHER_LABEL,
            "label": self._super_agent_name or DEFAULT_DISPATCHER_LABEL,
            "agentName": self._super_agent_agent_name,
            "cwd": self._cwd,
            "approvalPolicy": self._approval_policy,
            "sandbox": self._sandbox,
        }
        if self._backend_is_codex():
            params["model"] = self._model_name
        elif self._super_agents_model_name:
            params["model"] = self._super_agents_model_name
        if developer_instructions := self._thread_developer_instructions():
            params["developerInstructions"] = developer_instructions
        started = await self._backend_client.start_thread(params)
        thread_id = _extract_thread_id(started)
        if not thread_id:
            raise RuntimeError("Super Agents did not return a thread id.")
        self._thread_id = thread_id
        self._thread_loaded = True
        self._persist_thread_id(thread_id)
        logger.info("Started LiveKit Super Agents thread %s", thread_id)
        return thread_id

    async def _resume_thread(self, thread_id: str) -> str:
        resumed = await self._backend_client.resume_by_label(
            self._query(thread_id=thread_id, prefer="latest_any")
        )
        self._thread_id = _extract_thread_id(resumed) or thread_id
        self._thread_loaded = True
        self._persist_thread_id(self._thread_id)
        return self._thread_id

    def _query(self, **overrides: Any) -> Any:
        from super_agents.app_models import LabelQueryInput

        values: dict[str, Any] = {
            "label": self._super_agent_name or DEFAULT_DISPATCHER_LABEL,
            "cwd": self._cwd,
            "prefer": "latest_any",
        }
        values.update(overrides)
        return LabelQueryInput(**values)

    def _client_from_environment(self) -> Any:
        from super_agents.backend_clients import client_from_environment

        return client_from_environment()

    def _backend_is_codex(self) -> bool:
        return getattr(self._backend_client, "backend", "codex") == "codex"

    def _turn_developer_instructions(
        self,
        developer_instructions: str | None,
    ) -> str | None:
        parts = [
            part.strip()
            for part in (self._developer_instructions, developer_instructions)
            if part and part.strip()
        ]
        return _with_super_agent_identity_instructions(
            "\n\n".join(parts) if parts else None,
            self._super_agent_name,
            self._super_agent_agent_name,
        )

    def _thread_developer_instructions(self) -> str | None:
        return _with_super_agent_identity_instructions(
            self._developer_instructions,
            self._super_agent_name,
            self._super_agent_agent_name,
        )

    def _thread_state_file_lock(self):
        assert self._state_path is not None
        return thread_state_file_lock(self._state_path)

    def _dispatcher_reasoning_effort(self) -> str | None:
        return dispatcher_reasoning_effort(self._dispatcher_config_path)

    def _super_agents_reasoning_effort(self) -> str | None:
        return super_agents_reasoning_effort(self._dispatcher_config_path)

    def _configured_reasoning_effort(self) -> str | None:
        if self._use_super_agent_reasoning:
            return self._super_agents_reasoning_effort() or "high"
        return self._dispatcher_reasoning_effort()

    def _dispatcher_voice(self) -> dict[str, str]:
        return dispatcher_voice(self._dispatcher_config_path)

    def _load_thread_id(self) -> str | None:
        return load_thread_id(self._state_path)

    def _persist_thread_id(self, thread_id: str) -> None:
        persist_thread_id(self._state_path, thread_id)
        self._persist_voice_route_state(
            active_target_thread_id=None,
            active_target_kind=None,
            active_target_label=None,
            active_target_voice_id=None,
            active_target_voice_name=None,
        )

    def _persist_voice_route_state(
        self,
        *,
        active_target_thread_id: str | None,
        active_target_kind: str | None,
        active_target_label: str | None,
        active_target_voice_id: str | None,
        active_target_voice_name: str | None,
    ) -> None:
        persist_voice_route_state(
            self._state_path,
            dispatcher_thread_id=self._thread_id,
            dispatcher_voice=self._dispatcher_voice(),
            active_target_thread_id=active_target_thread_id,
            active_target_kind=active_target_kind,
            active_target_label=active_target_label,
            active_target_voice_id=active_target_voice_id,
            active_target_voice_name=active_target_voice_name,
        )

    def claim_speech(self, turn_id: str) -> bool:
        if turn_id in self._claimed_speech_turns:
            return False
        self._claimed_speech_turns.add(turn_id)
        return True

    def release_speech_claim(self, turn_id: str) -> None:
        self._claimed_speech_turns.discard(turn_id)

    def reset_voice_route_to_dispatcher(self) -> None:
        self.persist_voice_route(
            active_target_thread_id=None,
            active_target_kind=None,
            active_target_label=None,
            active_target_voice_id=None,
            active_target_voice_name=None,
        )

    def persist_voice_route(
        self,
        *,
        active_target_thread_id: str | None,
        active_target_kind: str | None,
        active_target_label: str | None,
        active_target_voice_id: str | None,
        active_target_voice_name: str | None,
    ) -> None:
        self._persist_voice_route_state(
            active_target_thread_id=active_target_thread_id,
            active_target_kind=active_target_kind,
            active_target_label=active_target_label,
            active_target_voice_id=active_target_voice_id,
            active_target_voice_name=active_target_voice_name,
        )


def _extract_thread_id(payload: dict[str, Any]) -> str | None:
    for key in ("threadId", "thread_id"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    thread = payload.get("thread")
    if isinstance(thread, dict):
        value = thread.get("id") or thread.get("threadId")
        if isinstance(value, str) and value:
            return value
    session = payload.get("session")
    if isinstance(session, dict):
        value = session.get("id") or session.get("threadId")
        if isinstance(value, str) and value:
            return value
    return None


def _extract_turn_id(payload: dict[str, Any]) -> str | None:
    for key in ("turnId", "turn_id"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    turn = payload.get("turn") or payload.get("item")
    if isinstance(turn, dict):
        value = turn.get("id") or turn.get("turnId")
        if isinstance(value, str) and value:
            return value
    return None


def _speech_text_from_progress(progress: dict[str, Any]) -> str:
    from super_agents.app_formatting import find_useful_text

    candidates: list[Any] = [
        progress.get("lastUsefulMessage"),
        progress.get("lastObservedState"),
        progress.get("summary", {}).get("lastUsefulMessage")
        if isinstance(progress.get("summary"), dict)
        else None,
    ]
    summary = progress.get("summary")
    if isinstance(summary, dict):
        candidates.append(summary.get("items"))
    candidates.extend(
        [
            progress.get("turn"),
            progress.get("turns"),
            progress.get("recentTurns"),
            progress.get("logTail"),
        ]
    )
    for candidate in candidates:
        text = find_useful_text(candidate)
        if text:
            return _speech_excerpt(text)
    return ""


def _progress_has_pending_requests(progress: dict[str, Any]) -> bool:
    if progress.get("pendingRequests"):
        return True
    summary = progress.get("summary")
    if isinstance(summary, dict) and summary.get("pendingRequestCount"):
        return True
    tracked = progress.get("trackedTurn")
    if isinstance(tracked, dict):
        if tracked.get("pendingRequestCount"):
            return True
        pending = tracked.get("pendingRequests")
        if isinstance(pending, list) and pending:
            return True
    return False
