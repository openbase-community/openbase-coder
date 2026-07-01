"""Openbase thread manager backed by the Super Agents Codex client."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from super_agents.app_models import LabelQueryInput
from super_agents.app_server_client import (
    CodexAppServerClient,
    extract_notification_thread_id,
    extract_notification_turn_id,
    extract_thread_cwd,
    extract_thread_id,
    extract_thread_name,
    extract_threads,
    extract_turn_id,
    find_latest_turn,
    is_permission_request,
    login_shell_config_override,
    shared_permission_requests,
    write_shared_permission_decision,
)
from super_agents.backend_clients import (
    CLAUDE_CODE_BACKEND,
    backend_from_environment,
    client_from_environment,
)

from openbase_coder_cli.livekit_voice_history import record_voice_assignment
from openbase_coder_cli.livekit_voice_route import (
    get_livekit_voice_route_state,
    super_agent_voice_for_context,
)
from openbase_coder_cli.paths import CODEX_SUPER_AGENT_INSTRUCTIONS_PATH

from .models import ThreadInfo as SessionInfo
from .models import ThreadStatus as SessionStatus
from .models import TurnInfo as RunInfo

logger = logging.getLogger(__name__)

SUPER_AGENT_INSTRUCTIONS_PATH_ENV = "CODEX_SUPER_AGENT_INSTRUCTIONS_PATH"
SUPER_AGENT_INSTRUCTIONS_TEXT_ENV = "CODEX_SUPER_AGENT_INSTRUCTIONS"
_USE_SUPER_AGENT_INSTRUCTIONS = object()
THREAD_HISTORY_LIMIT_ENV = "OPENBASE_CODER_THREAD_HISTORY_LIMIT"
DEFAULT_THREAD_HISTORY_LIMIT = 25


@dataclass(frozen=True)
class ThreadListPage:
    threads: list[SessionInfo]
    next_cursor: str | None


class _SuperAgentsClient(Protocol):
    async def ensure_connected(self) -> None: ...
    async def list_threads(
        self,
        use_state_db_only: bool = True,
        search_term: str | None = None,
        cwd: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> dict[str, Any]: ...
    async def read_thread(
        self,
        thread_id: str,
        include_turns: bool = True,
    ) -> dict[str, Any]: ...
    async def start_thread(self, input_data: dict[str, Any]) -> dict[str, Any]: ...
    async def start_turn(self, input_data: dict[str, Any]) -> dict[str, Any]: ...
    async def cancel_turn(self, thread_id: str, turn_id: str) -> dict[str, Any]: ...
    def pending_permission_requests(self) -> list[Any]: ...
    async def answer_request(
        self,
        request_id: str | int,
        result: dict[str, Any],
    ) -> dict[str, Any]: ...
    async def save_routine(self, input_data: dict[str, Any]) -> dict[str, Any]: ...
    async def list_routines(self) -> dict[str, Any]: ...
    async def read_routine(self, name: str) -> dict[str, Any]: ...
    async def delete_routine(self, name: str) -> dict[str, Any]: ...
    async def run_due_routines(
        self,
        name: str | None = None,
        force: bool = False,
    ) -> dict[str, Any]: ...
    async def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        timeout_seconds: float = 30,
    ) -> dict[str, Any]: ...
    async def merge_session(
        self,
        thread_id: str,
        patch: dict[str, Any],
        *,
        clear_fields: list[str] | None = None,
    ) -> None: ...
    async def get_session(self, thread_id: str) -> Any: ...


async def _broadcast(session_id: str, event: dict[str, Any]) -> None:
    """Broadcast an event to the WebSocket group for a thread."""
    try:
        from channels.layers import get_channel_layer

        channel_layer = get_channel_layer()
        if channel_layer is None:
            return
        group_name = f"thread_{session_id}"
        await channel_layer.group_send(group_name, event)

        if event.get("type") in ("turn_started", "turn_completed"):
            global_event = {**event, "thread_id": session_id}
            await channel_layer.group_send("all_threads", global_event)
    except Exception:
        logger.debug(
            "Failed to broadcast event for thread %s", session_id, exc_info=True
        )


def _read_instruction_file(path: Path) -> str | None:
    try:
        loaded = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    except OSError:
        logger.warning(
            "Unable to read Super Agent instruction file %s",
            path,
            exc_info=True,
        )
        return None
    return loaded or None


def resolve_super_agent_instructions_path(
    *,
    env: dict[str, str] | None = None,
    default_path: Path | None = None,
) -> Path:
    values = env if env is not None else os.environ
    explicit_path = values.get(SUPER_AGENT_INSTRUCTIONS_PATH_ENV, "").strip()
    if explicit_path:
        return Path(explicit_path).expanduser()
    return default_path or CODEX_SUPER_AGENT_INSTRUCTIONS_PATH


def load_super_agent_developer_instructions(
    *,
    env: dict[str, str] | None = None,
    default_path: Path | None = None,
) -> str | None:
    values = env if env is not None else os.environ
    loaded = _read_instruction_file(
        resolve_super_agent_instructions_path(env=values, default_path=default_path)
    )
    if loaded:
        return loaded

    text = values.get(SUPER_AGENT_INSTRUCTIONS_TEXT_ENV, "").strip()
    return text or None


def _timestamp_to_datetime(value: int | float | str | None) -> datetime:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=UTC)
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(UTC)


def _datetime_to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return (
        value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    )


def _thread_history_limit(env: dict[str, str] | None = None) -> int:
    raw = (env or os.environ).get(THREAD_HISTORY_LIMIT_ENV)
    if raw is None or raw.strip() == "":
        return DEFAULT_THREAD_HISTORY_LIMIT
    try:
        return max(0, int(raw))
    except ValueError:
        logger.warning(
            "Ignoring invalid %s=%r; using default limit %s",
            THREAD_HISTORY_LIMIT_ENV,
            raw,
            DEFAULT_THREAD_HISTORY_LIMIT,
        )
        return DEFAULT_THREAD_HISTORY_LIMIT


def _is_payload_too_large_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return (
        "message too big" in message
        or "exceeds limit" in message
        or "sent 1009" in message
        or "received 1009" in message
    )


def _runtime_error_message(exc: RuntimeError) -> str:
    raw = str(exc)
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return raw
    if isinstance(payload, dict) and isinstance(payload.get("message"), str):
        return payload["message"]
    return raw


def _is_thread_unavailable_error(exc: RuntimeError) -> bool:
    message = _runtime_error_message(exc).lower()
    return "not found" in message or "invalid thread id" in message


RUNNING_STATUSES = {"active", "inProgress", "in_progress", "running", "pending"}
COMPLETED_STATUSES = {"completed", "success"}
ERROR_STATUSES = {"failed", "error", "cancelled", "canceled", "interrupted"}
THREAD_IDLE_STATUSES = {"notLoaded", "not_loaded", "idle", "unknown"}
WAITING_FLAGS = {"waitingOnUserInput", "waiting_on_user_input"}
WAITING_STATUSES = {"waiting", "waitingOnUserInput", "waiting_on_user_input"}


def _status_type(value: Any) -> str:
    if isinstance(value, dict):
        candidate = value.get("type") or value.get("status")
        return candidate if isinstance(candidate, str) else ""
    return value if isinstance(value, str) else ""


def _is_waiting_status(status: Any) -> bool:
    if _status_type(status) in WAITING_STATUSES:
        return True
    if not isinstance(status, dict):
        return False
    flags = status.get("activeFlags")
    if not isinstance(flags, list):
        return False
    return any(flag in WAITING_FLAGS for flag in flags if isinstance(flag, str))


def _is_running_status(status: Any) -> bool:
    return _status_type(status) in RUNNING_STATUSES and not _is_waiting_status(status)


def _thread_status(status: Any) -> SessionStatus:
    if _is_waiting_status(status):
        return SessionStatus.waiting
    status_type = _status_type(status)
    if status_type in ERROR_STATUSES:
        return SessionStatus.error
    if status_type in RUNNING_STATUSES:
        return SessionStatus.running
    if status_type in COMPLETED_STATUSES:
        return SessionStatus.completed
    if status_type in THREAD_IDLE_STATUSES:
        return SessionStatus.idle
    return SessionStatus.idle


def _turn_status(status: Any, error: Any) -> SessionStatus:
    if error not in (None, ""):
        return SessionStatus.error
    if _is_waiting_status(status):
        return SessionStatus.waiting
    status_type = _status_type(status)
    if status_type in COMPLETED_STATUSES:
        return SessionStatus.completed
    if status_type in RUNNING_STATUSES:
        return SessionStatus.running
    if status_type in ERROR_STATUSES:
        return SessionStatus.error
    return SessionStatus.error


def _turn_sort_key(turn: dict[str, Any]) -> int:
    for key in ("completedAt", "finishedAt", "updatedAt", "startedAt", "createdAt"):
        value = turn.get(key)
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str) and value:
            try:
                return int(
                    datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
                    * 1000
                )
            except ValueError:
                pass
    return 0


def _extract_user_message(turn: dict[str, Any]) -> str:
    text_parts: list[str] = []
    for item in turn.get("items", []):
        if item.get("type") != "userMessage":
            continue
        for content in item.get("content", []):
            if content.get("type") == "text":
                text = content.get("text", "").strip()
                if text:
                    text_parts.append(text)
    return "\n\n".join(text_parts) or _optional_turn_string(
        turn,
        "prompt",
        "promptPreview",
    ) or ""


def _extract_agent_output(turn: dict[str, Any]) -> str:
    final_parts: list[str] = []
    fallback_parts: list[str] = []
    for item in turn.get("items", []):
        if item.get("type") != "agentMessage":
            continue
        text = item.get("text", "").strip()
        if not text:
            continue
        fallback_parts.append(text)
        phase = item.get("phase")
        if isinstance(phase, str) and phase.startswith("final"):
            final_parts.append(text)
    return "\n\n".join(final_parts or fallback_parts) or _optional_turn_string(
        turn,
        "lastUsefulMessage",
        "lastObservedState",
    ) or ""


def _undelivered_suffix(delivered_text: str, current_text: str) -> str:
    if not current_text:
        return ""
    if not delivered_text:
        return current_text
    if current_text.startswith(delivered_text):
        return current_text[len(delivered_text) :]
    return current_text


def _optional_thread_string(thread: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = thread.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _optional_turn_string(turn: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = turn.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _request_json(request: Any) -> dict[str, Any]:
    to_json = getattr(request, "to_json", None)
    if callable(to_json):
        value = to_json()
        if isinstance(value, dict):
            return value
    if isinstance(request, dict):
        return request
    return {}


def _approval_request_payload(request: Any) -> dict[str, Any]:
    raw = _request_json(request)
    params = raw.get("params") if isinstance(raw.get("params"), dict) else {}
    method = raw.get("method")
    if isinstance(method, str) and not is_permission_request(method):
        raise ValueError(f"Request {raw.get('id')} is not an approval request.")
    return {
        "id": raw.get("id"),
        "method": method,
        "params": params,
        "received_at": raw.get("receivedAt") or raw.get("received_at"),
        "thread_id": params.get("threadId") or params.get("thread_id"),
        "turn_id": params.get("turnId") or params.get("turn_id"),
    }


def _thread_payload(result: dict[str, Any]) -> dict[str, Any] | None:
    thread = result.get("thread") if isinstance(result.get("thread"), dict) else result
    return thread if isinstance(thread, dict) else None


def _normalize_backend_thread_payload(payload: dict[str, Any]) -> dict[str, Any]:
    session = payload.get("session") if isinstance(payload.get("session"), dict) else {}
    normalized = {**session, **payload}
    if "threadId" not in normalized and isinstance(normalized.get("id"), str):
        normalized["threadId"] = normalized["id"]
    return normalized


def _next_cursor(result: dict[str, Any]) -> str | None:
    value = result.get("nextCursor") or result.get("next_cursor")
    return value if isinstance(value, str) and value else None


def _is_backend_thread_payload(thread: dict[str, Any]) -> bool:
    return _optional_thread_string(thread, "backend") is not None


def _run_from_turn(
    turn: dict[str, Any], *, raw_status: SessionStatus | None = None
) -> RunInfo:
    turn_id = extract_turn_id(turn)
    if not turn_id:
        raise ValueError("Turn payload is missing an id")
    started_at = _timestamp_to_datetime(
        turn.get("startedAt") or turn.get("createdAt") or turn.get("updatedAt")
    )
    completed_at_value = turn.get("completedAt") or turn.get("finishedAt")
    completed_at = (
        _timestamp_to_datetime(completed_at_value) if completed_at_value else None
    )
    error = turn.get("error")
    stderr = json.dumps(error) if error else ""
    status = _turn_status(turn.get("status"), error)
    if raw_status == SessionStatus.waiting and status == SessionStatus.running:
        status = SessionStatus.waiting

    return RunInfo(
        run_id=turn_id,
        started_at=started_at,
        completed_at=completed_at,
        status=status,
        accumulated_output=_extract_agent_output(turn),
        accumulated_stderr=stderr,
        return_code=0 if status == SessionStatus.completed else -1,
        message=_extract_user_message(turn),
        reasoning_effort=_optional_turn_string(
            turn,
            "reasoningEffort",
            "reasoning_effort",
        ),
    )


class _OpenbaseSuperAgentsClient(CodexAppServerClient):
    def __init__(
        self, manager: "CodexAppServerSessionManager", ws_url: str | None
    ) -> None:
        super().__init__(ws_url=ws_url)
        self._manager = manager

    async def start_managed_server(self) -> None:
        """Openbase owns the Codex app-server lifecycle through launchd services."""
        raise RuntimeError(
            f"Codex app-server is not ready at {self.ws_url}; "
            "start the Openbase codex-app-server service instead."
        )

    def handle_server_request(
        self,
        request_id: str | int,
        method: str,
        params: dict[str, Any],
    ) -> None:
        super().handle_server_request(request_id, method, params)
        self._manager.handle_client_event("server_request", params)

    def handle_notification(self, method: str, params: dict[str, Any]) -> None:
        super().handle_notification(method, params)
        self._manager.handle_client_event(method, params)


class CodexAppServerSessionManager:
    """Openbase-compatible thread facade backed by Super Agents."""

    def __init__(
        self,
        ws_url: str | None = None,
        client: _SuperAgentsClient | None = None,
    ) -> None:
        self._ws_url = ws_url or os.environ.get(
            "CODEX_APP_SERVER_URL", "ws://127.0.0.1:4500"
        )
        self._uses_external_client = client is not None
        self._client: _SuperAgentsClient = client or self._default_client()
        self._turn_to_session: dict[str, str] = {}
        self._delivered_text: dict[str, str] = {}
        self._state_lock = asyncio.Lock()

    def _default_client(self) -> _SuperAgentsClient:
        if backend_from_environment() == CLAUDE_CODE_BACKEND:
            return client_from_environment()
        return _OpenbaseSuperAgentsClient(self, self._ws_url)

    def _uses_backend_session_api(self) -> bool:
        return not callable(getattr(self._client, "read_thread", None))

    async def create_thread(
        self,
        directory: str,
        thread_id: str | None = None,
    ) -> SessionInfo:
        """Create or reuse a Codex app-server thread for the directory."""
        return await self.create_session(directory, session_id=thread_id)

    async def archive_thread(self, thread_id: str) -> bool:
        """Archive a Codex app-server thread."""
        return await self.close_session(thread_id)

    async def start_turn(self, thread_id: str, prompt: str) -> str:
        """Start a new Codex turn on an existing thread."""
        return await self.send_message(thread_id, prompt)

    async def get_thread_state(self, thread_id: str) -> SessionInfo | None:
        """Get the current thread snapshot."""
        return await self.get_session_state(thread_id)

    async def interrupt_turn(self, thread_id: str) -> bool:
        """Interrupt the current turn on a thread."""
        return await self.interrupt_run(thread_id)

    async def list_approval_requests(self) -> list[dict[str, Any]]:
        """List currently pending app-server approval requests across threads."""
        requests_by_id = {
            str(request.get("id")): request
            for request in shared_permission_requests()
            if request.get("id") is not None
        }
        try:
            await self._client.ensure_connected()
            for request in self._client.pending_permission_requests():
                payload = _approval_request_payload(request)
                if payload.get("id") is not None:
                    requests_by_id[str(payload["id"])] = payload
        except Exception:
            logger.debug("Unable to merge in-process approval requests", exc_info=True)
        return [
            _approval_request_payload(request) for request in requests_by_id.values()
        ]

    async def answer_approval_request(
        self,
        request_id: str | int,
        decision: Literal["accept", "decline", "cancel"],
    ) -> dict[str, Any]:
        """Answer one pending app-server approval request."""
        await self._client.ensure_connected()
        request = self._find_pending_approval_request(request_id)
        if request is None:
            if write_shared_permission_decision(request_id, decision):
                return {
                    "answered": False,
                    "queued": True,
                    "requestId": request_id,
                    "result": {"decision": decision},
                }
            raise ValueError(f"No pending approval request found for id {request_id}.")
        return await self._client.answer_request(request.id, {"decision": decision})

    def _find_pending_approval_request(self, request_id: str | int) -> Any | None:
        candidates: list[str | int] = [request_id]
        if isinstance(request_id, str) and request_id.isdigit():
            candidates.append(int(request_id))
        candidate_strings = {str(item) for item in candidates}
        for request in self._client.pending_permission_requests():
            if request.id in candidates or str(request.id) in candidate_strings:
                return request
        return None

    async def list_routines(self) -> dict[str, Any]:
        """List persisted Super Agents routines."""
        return await self._client.list_routines()

    async def read_routine(self, name: str) -> dict[str, Any]:
        """Read one persisted Super Agents routine."""
        return await self._client.read_routine(name)

    async def save_routine(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Create or update a persisted Super Agents routine."""
        return await self._client.save_routine(input_data)

    async def delete_routine(self, name: str) -> dict[str, Any]:
        """Delete one persisted Super Agents routine."""
        return await self._client.delete_routine(name)

    async def run_due_routines(
        self,
        name: str | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        """Run due routines through the Super Agents client library."""
        return await self._client.run_due_routines(name=name, force=force)

    async def resume_thread_with_developer_instructions(
        self,
        thread_id: str,
        directory: str,
        developer_instructions: str,
    ) -> None:
        """Resume a thread with explicit developer instructions."""
        await self._resume_thread(
            thread_id,
            directory,
            developer_instructions=developer_instructions,
        )

    async def resume_thread_without_developer_instructions(
        self,
        thread_id: str,
        directory: str,
    ) -> None:
        """Resume a thread without changing its developer instructions."""
        await self._resume_thread(
            thread_id,
            directory,
            developer_instructions=None,
        )

    async def _resume_thread(
        self,
        thread_id: str,
        directory: str,
        *,
        developer_instructions: str | None | object = _USE_SUPER_AGENT_INSTRUCTIONS,
    ) -> None:
        if developer_instructions is _USE_SUPER_AGENT_INSTRUCTIONS:
            effective_developer_instructions = load_super_agent_developer_instructions()
        elif isinstance(developer_instructions, str):
            effective_developer_instructions = developer_instructions
        else:
            effective_developer_instructions = None

        if self._uses_backend_session_api():
            if effective_developer_instructions is not None:
                resume_by_label = getattr(self._client, "resume_by_label", None)
                if callable(resume_by_label):
                    await resume_by_label(
                        LabelQueryInput(thread_id=thread_id, cwd=directory),
                        developer_instructions=effective_developer_instructions,
                    )
                    return
            read_by_label = getattr(self._client, "read_by_label", None)
            if callable(read_by_label):
                await read_by_label(
                    LabelQueryInput(thread_id=thread_id, cwd=directory),
                    include_turns=False,
                )
            return

        await self._client.ensure_connected()
        params: dict[str, Any] = {
            "threadId": thread_id,
            "cwd": directory,
            "approvalPolicy": "never",
            "sandbox": "danger-full-access",
            "config": await login_shell_config_override(),
        }
        if effective_developer_instructions is not None:
            params["developerInstructions"] = effective_developer_instructions
        await self._client.request("thread/resume", params)
        await self._client.merge_session(
            thread_id,
            {
                "threadId": thread_id,
                "cwd": directory,
                "lastStatus": "unknown",
                "updatedAt": _datetime_to_iso(datetime.now(UTC)),
            },
        )

    async def list_threads(self) -> list[SessionInfo]:
        """List stored Codex threads through Super Agents."""
        return await self.list_sessions()

    async def list_thread_page(
        self,
        *,
        limit: int,
        cursor: str | None = None,
    ) -> ThreadListPage:
        """List one stored Codex thread page through Super Agents."""
        if self._uses_backend_session_api():
            return await self._backend_thread_page(limit=limit, cursor=cursor)

        result = await self._list_thread_page_result(limit=limit, cursor=cursor)
        raw_threads = extract_threads(result)
        sessions = [
            self._session_from_thread(thread, include_turns=False)
            for thread in raw_threads
        ]
        return ThreadListPage(
            threads=sorted(sessions, key=self._sort_key, reverse=True),
            next_cursor=_next_cursor(result),
        )

    async def _backend_thread_page(
        self,
        *,
        limit: int,
        cursor: str | None,
    ) -> ThreadListPage:
        sessions = await self._backend_sessions()
        sorted_sessions = sorted(sessions, key=self._sort_key, reverse=True)
        try:
            start = int(cursor or 0)
        except ValueError:
            start = 0
        end = start + limit
        return ThreadListPage(
            threads=sorted_sessions[start:end],
            next_cursor=str(end) if end < len(sorted_sessions) else None,
        )

    async def _backend_sessions(self) -> list[SessionInfo]:
        sessions_method = getattr(self._client, "sessions", None)
        if not callable(sessions_method):
            return []
        raw_sessions = await sessions_method()
        return [
            self._session_from_thread(
                _normalize_backend_thread_payload(session),
                include_turns=False,
            )
            for session in raw_sessions
            if isinstance(session, dict)
        ]

    async def _list_thread_page_result(
        self,
        *,
        limit: int,
        cursor: str | None,
    ) -> dict[str, Any]:
        if self._uses_external_client:
            if cursor:
                await self._client.ensure_connected()
                return await self._client.request(
                    "thread/list",
                    {
                        "useStateDbOnly": True,
                        "limit": limit,
                        "cursor": cursor,
                    },
                )
            return await self._client.list_threads(
                True,
                limit=limit,
            )

        client = _OpenbaseSuperAgentsClient(self, self._ws_url)
        try:
            await client.ensure_connected()
            params: dict[str, Any] = {
                "useStateDbOnly": True,
                "limit": limit,
            }
            if cursor:
                params["cursor"] = cursor
            return await client.request("thread/list", params)
        finally:
            await client.close()

    async def create_session(
        self,
        directory: str,
        session_id: str | None = None,
        session_type: Literal["codex"] = "codex",
    ) -> SessionInfo:
        """Create or reuse a Codex app-server thread for the directory."""
        if session_type != "codex":
            raise ValueError("session_type must be 'codex'")

        expanded_dir = str(Path(directory).expanduser().resolve())
        if not os.path.isdir(expanded_dir):
            raise ValueError(f"Directory does not exist: {expanded_dir}")

        if session_id is not None:
            session = await self.get_session_state(session_id)
            if session is None:
                raise ValueError(f"Thread {session_id} not found")
            return session

        if self._uses_backend_session_api():
            existing_sessions = await self._backend_sessions()
            for session in existing_sessions:
                if session.directory == expanded_dir:
                    return session
            name = Path(expanded_dir).name or f"thread-{uuid.uuid4().hex[:8]}"
            if any(session.name == name for session in existing_sessions):
                name = f"{name}-{uuid.uuid4().hex[:8]}"
            thread_input = {
                "name": name,
                "cwd": expanded_dir,
            }
            developer_instructions = load_super_agent_developer_instructions()
            if developer_instructions is not None:
                thread_input["developerInstructions"] = developer_instructions
            started = await self._client.start_thread(thread_input)
            return self._session_from_thread(
                _normalize_backend_thread_payload(started),
                include_turns=False,
            )

        result = await self._client.list_threads(
            True,
            cwd=expanded_dir,
            limit=1,
        )
        existing = extract_threads(result)
        if existing:
            return self._session_from_thread(existing[0], include_turns=False)

        thread_input = {"cwd": expanded_dir}
        developer_instructions = load_super_agent_developer_instructions()
        if developer_instructions is not None:
            thread_input["developerInstructions"] = developer_instructions

        started = await self._client.start_thread(thread_input)
        thread = _thread_payload(started)
        if thread is None:
            raise RuntimeError("Super Agents did not return a thread")
        return self._session_from_thread(thread, include_turns=False)

    async def close_session(self, session_id: str) -> bool:
        """Archive a persisted thread."""
        await self.interrupt_run(session_id)
        if self._uses_backend_session_api():
            return await self.get_session_state(session_id) is not None
        try:
            await self._client.ensure_connected()
            await self._client.request("thread/archive", {"threadId": session_id})
        except RuntimeError as exc:
            if _is_thread_unavailable_error(exc):
                return False
            raise
        async with self._state_lock:
            turn_ids = [
                turn_id
                for turn_id, candidate_session_id in self._turn_to_session.items()
                if candidate_session_id == session_id
            ]
            for turn_id in turn_ids:
                self._turn_to_session.pop(turn_id, None)
                self._delivered_text.pop(turn_id, None)
        return True

    async def send_message(self, session_id: str, message: str) -> str:
        """Start a turn on a Codex app-server thread."""
        thread = await self.get_session_state(session_id)
        if thread is None:
            raise ValueError(f"Thread {session_id} not found")
        if thread.current_run is not None and thread.current_run.status in {
            SessionStatus.running,
            SessionStatus.waiting,
        }:
            raise ValueError(
                f"Thread {session_id} already has an active turn. Interrupt it first."
            )
        if not thread.directory:
            raise ValueError(f"Thread {session_id} is missing its cwd")

        if self._uses_backend_session_api():
            started = await self._client.start_turn_by_label(
                LabelQueryInput(thread_id=session_id, cwd=thread.directory),
                {"prompt": message, "cwd": thread.directory},
            )
            turn_id = extract_turn_id(started)
            if not turn_id:
                raise RuntimeError("Super Agents did not return a turn id")
            return turn_id

        turn_input = {
            "threadId": session_id,
            "cwd": thread.directory,
            "prompt": message,
        }
        try:
            started = await self._client.start_turn(turn_input)
        except RuntimeError as exc:
            if not _is_thread_unavailable_error(exc):
                raise
            await self._resume_thread(session_id, thread.directory)
            started = await self._client.start_turn(turn_input)
        turn_id = extract_turn_id(started)
        if not turn_id:
            raise RuntimeError("Super Agents did not return a turn id")
        agent_name = thread.agent_name
        voice = super_agent_voice_for_context(session_id, thread.name, agent_name)
        logger.info(
            "livekit_voice_assignment_super_agent_turn thread_id=%s thread_name=%s "
            "agent_name=%s voice_id=%s voice_name=%s route_active=%s",
            session_id,
            thread.name or "",
            agent_name or "",
            voice.voice_id if voice else "",
            voice.name if voice else "",
            _has_livekit_voice_route(),
        )
        if agent_name and voice is not None and _has_livekit_voice_route():
            record_voice_assignment(
                thread_id=session_id,
                agent_name=agent_name,
                cwd=thread.directory,
                voice_id=voice.voice_id,
                voice_name=voice.name,
                kind="codex_thread",
                source="super_agent_start",
            )
        run = RunInfo(
            run_id=turn_id,
            started_at=datetime.now(UTC),
            status=SessionStatus.running,
            message=message,
            reasoning_effort=_optional_turn_string(
                started,
                "reasoningEffort",
                "reasoning_effort",
            ),
        )
        async with self._state_lock:
            self._turn_to_session[turn_id] = session_id
            self._delivered_text[turn_id] = ""

        await _broadcast(
            session_id,
            {"type": "turn_started", "data": run.model_dump(mode="json")},
        )
        return turn_id

    async def get_session_state(self, session_id: str) -> SessionInfo | None:
        """Get the current thread snapshot."""
        result = await self._read_thread(session_id, include_turns=True)
        if result is None:
            return None
        return self._session_from_thread(result, include_turns=True)

    async def interrupt_run(self, session_id: str) -> bool:
        """Interrupt the current turn in a thread."""
        if self._uses_backend_session_api():
            try:
                result = await self._client.cancel_by_label(
                    LabelQueryInput(thread_id=session_id)
                )
            except RuntimeError as exc:
                message = _runtime_error_message(exc).lower()
                if _is_thread_unavailable_error(exc) or "no active" in message:
                    return False
                raise
            return bool(result.get("cancelled", True))

        turn_id = await self._active_turn_id(session_id)
        if turn_id is None:
            return False
        try:
            await self._client.cancel_turn(session_id, turn_id)
        except RuntimeError as exc:
            message = _runtime_error_message(exc).lower()
            if _is_thread_unavailable_error(exc) or "no active" in message:
                return False
            raise
        return True

    async def list_sessions(self) -> list[SessionInfo]:
        """List stored Codex threads through Super Agents."""
        if self._uses_backend_session_api():
            return sorted(await self._backend_sessions(), key=self._sort_key, reverse=True)

        result = await self._client.list_threads(
            True,
            limit=100,
        )
        raw_threads = extract_threads(result)
        cursor = _next_cursor(result)
        while cursor:
            await self._client.ensure_connected()
            result = await self._client.request(
                "thread/list",
                {
                    "useStateDbOnly": True,
                    "limit": 100,
                    "cursor": cursor,
                },
            )
            raw_threads.extend(extract_threads(result))
            cursor = _next_cursor(result)
        sessions = [
            self._session_from_thread(thread, include_turns=False)
            for thread in raw_threads
        ]
        return sorted(sessions, key=self._sort_key, reverse=True)

    def _sort_key(self, session: SessionInfo) -> datetime:
        if session.current_run is not None:
            return session.current_run.started_at
        if session.run_history:
            last_run = session.run_history[-1]
            return last_run.completed_at or last_run.started_at
        return session.updated_at

    async def _active_turn_id(self, session_id: str) -> str | None:
        local_turn_id: str | None = None
        async with self._state_lock:
            for turn_id, candidate_session_id in self._turn_to_session.items():
                if candidate_session_id == session_id:
                    local_turn_id = turn_id
                    break

        thread = await self._read_thread(session_id, include_turns=True)
        if thread is not None:
            turn = find_latest_turn(thread, active_only=True)
            if turn and isinstance(turn.get("id"), str):
                return turn["id"]
            if local_turn_id is not None:
                async with self._state_lock:
                    self._turn_to_session.pop(local_turn_id, None)
                    self._delivered_text.pop(local_turn_id, None)
            return None
        return local_turn_id

    async def _read_thread(
        self,
        session_id: str,
        *,
        include_turns: bool,
    ) -> dict[str, Any] | None:
        if self._uses_backend_session_api():
            read_by_label = getattr(self._client, "read_by_label", None)
            if not callable(read_by_label):
                return None
            try:
                result = await read_by_label(
                    LabelQueryInput(
                        thread_id=session_id,
                        max_items=_thread_history_limit() if include_turns else 5,
                    ),
                    include_turns=include_turns,
                )
            except RuntimeError as exc:
                if _is_thread_unavailable_error(exc):
                    return None
                raise
            thread = _thread_payload(_normalize_backend_thread_payload(result))
            return thread

        fetched_turns = include_turns
        try:
            result = await self._client.read_thread(session_id, include_turns)
        except RuntimeError as exc:
            message = _runtime_error_message(exc).lower()
            if _is_thread_unavailable_error(exc):
                return None
            if include_turns and "includeturns is unavailable" in message:
                result = await self._client.read_thread(session_id, False)
                fetched_turns = False
            elif include_turns and _is_payload_too_large_error(exc):
                logger.warning(
                    "Thread %s full payload is too large; reading compact state",
                    session_id,
                )
                result = await self._client.read_thread(session_id, False)
                fetched_turns = False
            else:
                raise
        except Exception as exc:
            if not include_turns or not _is_payload_too_large_error(exc):
                raise
            logger.warning(
                "Thread %s full payload is too large; reading compact state",
                session_id,
            )
            result = await self._client.read_thread(session_id, False)
            fetched_turns = False
        thread = _thread_payload(result)
        if thread is not None and fetched_turns:
            await self._merge_tracked_turn_reasoning(thread)
        elif thread is not None and include_turns:
            await self._merge_tracked_turn_summaries(thread)
        return thread

    async def _merge_tracked_turn_summaries(self, thread: dict[str, Any]) -> None:
        thread_id = extract_thread_id(thread)
        if not thread_id:
            return
        get_session = getattr(self._client, "get_session", None)
        if not callable(get_session):
            return
        try:
            tracked_session = await get_session(thread_id)
        except Exception:
            logger.debug(
                "Unable to read Super Agents tracked session for thread %s",
                thread_id,
                exc_info=True,
            )
            return
        tracked_turns = getattr(tracked_session, "turns", None) or {}
        if not isinstance(tracked_turns, dict):
            return

        summaries: list[dict[str, Any]] = []
        for turn_id, summary in tracked_turns.items():
            status = getattr(summary, "status", None)
            started_at = getattr(summary, "started_at", None)
            finished_at = getattr(summary, "finished_at", None)
            if not isinstance(status, str) or not isinstance(started_at, str):
                continue
            prompt_preview = getattr(summary, "prompt_preview", None)
            last_useful_message = getattr(summary, "last_useful_message", None)
            items: list[dict[str, Any]] = []
            if isinstance(prompt_preview, str) and prompt_preview:
                items.append(
                    {
                        "type": "userMessage",
                        "content": [{"type": "text", "text": prompt_preview}],
                    }
                )
            if isinstance(last_useful_message, str) and last_useful_message:
                items.append(
                    {
                        "type": "agentMessage",
                        "phase": "final",
                        "text": last_useful_message,
                    }
                )
            summaries.append(
                {
                    "id": str(getattr(summary, "turn_id", None) or turn_id),
                    "status": status,
                    "startedAt": started_at,
                    "completedAt": (
                        finished_at
                        if status in {"completed", "failed", "cancelled"}
                        else None
                    ),
                    "items": items,
                    "reasoningEffort": getattr(summary, "reasoning_effort", None),
                    "error": None,
                }
            )
        if summaries:
            thread["turns"] = summaries

    async def _merge_tracked_turn_reasoning(self, thread: dict[str, Any]) -> None:
        thread_id = extract_thread_id(thread)
        if not thread_id:
            return
        get_session = getattr(self._client, "get_session", None)
        if not callable(get_session):
            return
        try:
            tracked_session = await get_session(thread_id)
        except Exception:
            logger.debug(
                "Unable to read Super Agents tracked session for thread %s",
                thread_id,
                exc_info=True,
            )
            return
        tracked_turns = getattr(tracked_session, "turns", None) or {}
        if not isinstance(tracked_turns, dict):
            return
        for turn in thread.get("turns", []):
            if not isinstance(turn, dict):
                continue
            turn_id = turn.get("id")
            if not isinstance(turn_id, str):
                continue
            summary = tracked_turns.get(turn_id)
            reasoning_effort = getattr(summary, "reasoning_effort", None)
            if isinstance(reasoning_effort, str) and reasoning_effort:
                turn["reasoningEffort"] = reasoning_effort

    def _session_from_thread(
        self,
        thread: dict[str, Any],
        *,
        include_turns: bool,
    ) -> SessionInfo:
        thread_id = extract_thread_id(thread)
        if not thread_id:
            raise ValueError("Thread payload is missing an id")
        raw_status = _thread_status(thread.get("status"))
        uses_backend_active_turn_id = _is_backend_thread_payload(thread)
        name = extract_thread_name(thread)
        status_warning = _optional_thread_string(
            thread,
            "statusWarning",
            "status_warning",
        )
        session = SessionInfo(
            session_id=thread_id,
            directory=extract_thread_cwd(thread) or "",
            name=name,
            agent_name=_optional_thread_string(thread, "agentName", "agent_name"),
            title=_optional_thread_string(thread, "title", "summary"),
            preview=_optional_thread_string(thread, "preview", "description"),
            is_likely_stale=bool(
                thread.get("isLikelyStale") or thread.get("is_likely_stale")
            ),
            status_warning=status_warning,
            session_type="codex",
            created_at=_timestamp_to_datetime(thread.get("createdAt")),
            updated_at=_timestamp_to_datetime(
                thread.get("updatedAt") or thread.get("createdAt")
            ),
            raw_status=raw_status,
            status_override=raw_status if uses_backend_active_turn_id else None,
        )
        if not include_turns:
            return session

        run_history: list[RunInfo] = []
        current_run: RunInfo | None = None
        active_turn_id = _optional_thread_string(thread, "activeTurnId", "active_turn_id")
        turns = sorted(thread.get("turns", []), key=_turn_sort_key)
        for turn in turns:
            turn_id = extract_turn_id(turn)
            if not isinstance(turn, dict) or not turn_id:
                continue
            run = _run_from_turn(
                {
                    **turn,
                    "id": turn_id,
                },
                raw_status=raw_status,
            )
            is_active_run = run.status in {SessionStatus.running, SessionStatus.waiting}
            if uses_backend_active_turn_id and is_active_run and turn_id != active_turn_id:
                continue
            if status_warning == "stale_active_turn" and is_active_run:
                run_history.append(run)
                continue
            if is_active_run:
                current_run = run
            else:
                run_history.append(run)

        history_limit = _thread_history_limit()
        if len(run_history) > history_limit:
            run_history = run_history[-history_limit:]

        session.current_run = current_run
        session.run_history = run_history
        if (
            current_run is None
            and run_history
            and raw_status
            in {
                SessionStatus.running,
                SessionStatus.waiting,
            }
        ):
            session.raw_status = run_history[-1].status
        return session

    def handle_client_event(self, method: str, params: dict[str, Any]) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self._handle_client_event(method, params))

    async def _handle_client_event(self, method: str, params: dict[str, Any]) -> None:
        thread_id = extract_notification_thread_id(params)
        turn_id = extract_notification_turn_id(params)
        if turn_id and not thread_id:
            async with self._state_lock:
                thread_id = self._turn_to_session.get(turn_id)
        if not thread_id:
            return

        if method == "server_request":
            session_state = await self.get_session_state(thread_id)
            if session_state is not None:
                await _broadcast(
                    thread_id,
                    {
                        "type": "thread_state",
                        "data": session_state.model_dump(mode="json"),
                    },
                )
            return

        if method == "item/agentMessage/delta":
            delta = params.get("delta", "")
            if turn_id and isinstance(delta, str) and delta:
                await self._append_output(thread_id, turn_id, delta)
            return

        if method == "item/completed":
            item = params.get("item", {})
            if isinstance(item, dict) and item.get("type") == "agentMessage":
                text = item.get("text", "")
                if turn_id and isinstance(text, str) and text:
                    delivered = self._delivered_text.get(turn_id, "")
                    suffix = _undelivered_suffix(delivered, text)
                    if suffix:
                        await self._append_output(thread_id, turn_id, suffix)
            return

        if method in {"turn/completed", "turn/failed"}:
            if turn_id:
                async with self._state_lock:
                    self._turn_to_session.pop(turn_id, None)
                    self._delivered_text.pop(turn_id, None)
            session_state = await self.get_session_state(thread_id)
            if session_state is not None:
                await _broadcast(
                    thread_id,
                    {
                        "type": "turn_completed",
                        "data": session_state.model_dump(mode="json"),
                    },
                )

    async def _append_output(self, thread_id: str, turn_id: str, text: str) -> None:
        async with self._state_lock:
            self._delivered_text[turn_id] = self._delivered_text.get(turn_id, "") + text
        await _broadcast(
            thread_id,
            {
                "type": "output_update",
                "data": {"stream": "stdout", "line": text, "chunk": True},
            },
        )


_session_manager: CodexAppServerSessionManager | None = None


def get_session_manager() -> CodexAppServerSessionManager:
    """Get the singleton thread manager instance."""
    global _session_manager
    if _session_manager is None:
        _session_manager = CodexAppServerSessionManager()
    return _session_manager


def _has_livekit_voice_route() -> bool:
    try:
        state = get_livekit_voice_route_state()
    except Exception:
        return False
    return bool(state.dispatcher_thread_id or state.active_target_thread_id)
