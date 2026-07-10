"""WebSocket consumers for real-time thread updates."""

from __future__ import annotations

import asyncio
import json
import logging

from channels.generic.websocket import AsyncJsonWebsocketConsumer
from open_approvals import resolve_requests_file

from openbase_coder_cli.mcp.session_manager import get_session_manager
from openbase_coder_cli.openbase_coder_cli_app.approvals import (
    pending_approval_requests,
)
from openbase_coder_cli.openbase_coder_cli_app.thread_metadata import (
    annotate_thread_payload,
)

logger = logging.getLogger(__name__)


def _friendly_error(exc: Exception) -> str:
    """Extract a human-readable message from manager errors.

    The session manager bubbles up codex app-server JSON-RPC errors as
    RuntimeError("{json}"), which is unhelpful when surfaced to the UI.
    """
    raw = str(exc)
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return raw
    if isinstance(payload, dict) and isinstance(payload.get("message"), str):
        return payload["message"]
    return raw


class ThreadConsumer(AsyncJsonWebsocketConsumer):
    """WebSocket consumer for a single thread's real-time updates."""

    async def connect(self):
        if self.scope.get("user") != "authenticated":
            await self.close(code=4001)
            return

        self.thread_id = self.scope["url_route"]["kwargs"]["thread_id"]
        self.group_name = f"thread_{self.thread_id}"

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        manager = get_session_manager()
        try:
            thread = await manager.get_thread_state(self.thread_id)
        except (ValueError, RuntimeError) as exc:
            logger.error(
                "Unable to load initial state for thread %s: %s", self.thread_id, exc
            )
            await self.send_json(
                {
                    "type": "error",
                    "data": {
                        "message": _friendly_error(exc),
                        "code": "thread_state_unavailable",
                    },
                }
            )
            return
        if thread:
            await self.send_json(
                {
                    "type": "thread_state",
                    "data": annotate_thread_payload(
                        thread.model_dump(mode="json"),
                        thread_id=self.thread_id,
                    ),
                }
            )

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive_json(self, content, **kwargs):
        action = content.get("action")
        manager = get_session_manager()

        if action == "start_turn":
            prompt = content.get("prompt", "")
            if not prompt:
                await self.send_json(
                    {"type": "error", "data": {"message": "prompt is required"}}
                )
                return
            try:
                await manager.start_turn(self.thread_id, prompt)
            except (ValueError, RuntimeError) as exc:
                logger.warning(
                    "start_turn failed for thread %s: %s", self.thread_id, exc
                )
                await self.send_json(
                    {"type": "error", "data": {"message": _friendly_error(exc)}}
                )

        elif action == "interrupt_turn":
            try:
                success = await manager.interrupt_turn(self.thread_id)
            except (ValueError, RuntimeError) as exc:
                logger.warning(
                    "interrupt_turn failed for thread %s: %s", self.thread_id, exc
                )
                await self.send_json(
                    {"type": "error", "data": {"message": _friendly_error(exc)}}
                )
                return
            if not success:
                await self.send_json(
                    {
                        "type": "error",
                        "data": {"message": "No active turn to interrupt"},
                    }
                )

    async def turn_started(self, event):
        await self.send_json({"type": "turn_started", "data": event["data"]})

    async def output_update(self, event):
        await self.send_json({"type": "output_update", "data": event["data"]})

    async def turn_completed(self, event):
        await self.send_json(
            {
                "type": "turn_completed",
                "data": annotate_thread_payload(
                    event["data"],
                    thread_id=self.thread_id,
                ),
            }
        )

    async def thread_state(self, event):
        await self.send_json(
            {
                "type": "thread_state",
                "data": annotate_thread_payload(
                    event["data"],
                    thread_id=self.thread_id,
                ),
            }
        )

    async def error(self, event):
        await self.send_json({"type": "error", "data": event["data"]})


class AllThreadsConsumer(AsyncJsonWebsocketConsumer):
    """Global WebSocket consumer that broadcasts turn lifecycle updates for all threads."""

    async def connect(self):
        if self.scope.get("user") != "authenticated":
            await self.close(code=4001)
            return

        await self.channel_layer.group_add("all_threads", self.channel_name)
        await self.accept()

        manager = get_session_manager()
        try:
            threads = await manager.list_threads()
        except (ValueError, RuntimeError) as exc:
            logger.error("Unable to list threads for all-threads socket: %s", exc)
            await self.send_json(
                {
                    "type": "error",
                    "data": {
                        "message": _friendly_error(exc),
                        "code": "thread_list_unavailable",
                    },
                }
            )
            return
        running = [thread for thread in threads if thread.status == "running"]
        for thread in running:
            await self.send_json(
                {
                    "type": "turn_started",
                    "thread_id": thread.session_id,
                    "data": (
                        thread.current_run.model_dump(mode="json")
                        if thread.current_run
                        else {}
                    ),
                }
            )

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard("all_threads", self.channel_name)

    async def receive_json(self, content, **kwargs):
        return

    async def turn_started(self, event):
        await self.send_json(
            {
                "type": "turn_started",
                "thread_id": event["thread_id"],
                "data": event["data"],
            }
        )

    async def turn_completed(self, event):
        await self.send_json(
            {
                "type": "turn_completed",
                "thread_id": event["thread_id"],
                "data": event["data"],
            }
        )

    async def error(self, event):
        await self.send_json(
            {
                "type": "error",
                "thread_id": event["thread_id"],
                "data": event["data"],
            }
        )


class _ApprovalStoreWatcher:
    """Broadcasts to the approvals group whenever the shared store file changes.

    Every approval producer (Codex app-server callbacks, Claude Code
    permission gating, skills) writes the shared open-approvals store, so one
    local file stat per tick replaces per-client HTTP polling.
    """

    group_name = "approval_requests"
    poll_seconds = 0.5

    def __init__(self) -> None:
        self._connections = 0
        self._task: asyncio.Task[None] | None = None

    def acquire(self) -> None:
        self._connections += 1
        if self._task is None or self._task.done():
            # Capture the baseline before yielding control so store writes
            # racing with the first connect are still detected.
            self._task = asyncio.create_task(self._watch(self._store_signature()))

    def release(self) -> None:
        self._connections = max(0, self._connections - 1)

    async def _watch(self, last_signature: tuple[float, int] | None) -> None:
        from channels.layers import get_channel_layer

        while self._connections > 0:
            await asyncio.sleep(self.poll_seconds)
            signature = self._store_signature()
            if signature == last_signature:
                continue
            last_signature = signature
            channel_layer = get_channel_layer()
            if channel_layer is not None:
                await channel_layer.group_send(
                    self.group_name,
                    {"type": "approval_requests_changed"},
                )

    @staticmethod
    def _store_signature() -> tuple[float, int] | None:
        try:
            stat = resolve_requests_file().stat()
        except OSError:
            return None
        return (stat.st_mtime, stat.st_size)


_approval_store_watcher = _ApprovalStoreWatcher()


class ApprovalRequestsConsumer(AsyncJsonWebsocketConsumer):
    """Pushes the pending approval-request list when the shared store changes."""

    group_name = _ApprovalStoreWatcher.group_name

    async def connect(self):
        self._watching = False
        if self.scope.get("user") != "authenticated":
            await self.close(code=4001)
            return

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        _approval_store_watcher.acquire()
        self._watching = True
        await self._send_snapshot()

    async def disconnect(self, close_code):
        if getattr(self, "_watching", False):
            _approval_store_watcher.release()
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive_json(self, content, **kwargs):
        if content.get("action") == "refresh":
            await self._send_snapshot()

    async def approval_requests_changed(self, event):
        await self._send_snapshot()

    async def _send_snapshot(self):
        try:
            requests = await pending_approval_requests()
        except Exception:
            logger.warning(
                "Unable to load approval requests for the approvals socket",
                exc_info=True,
            )
            return
        await self.send_json(
            {"type": "approval_requests", "data": {"requests": requests}}
        )


class IOSAppControlConsumer(AsyncJsonWebsocketConsumer):
    """Foreground iOS app command channel."""

    group_name = "ios_app_control"

    async def connect(self):
        if self.scope.get("user") != "authenticated":
            await self.close(code=4001)
            return

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive_json(self, content, **kwargs):
        return

    async def ios_app_control(self, event):
        await self.send_json({"type": "ios_app_control", "data": event["data"]})
