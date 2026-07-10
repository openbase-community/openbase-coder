"""Room-side responder for VocalBridge voice dispatch.

VocalBridge's hosted voice agent delegates domain questions over the LiveKit
data channel as ``query_agent`` actions and expects ``agent_response``
answers on the same channel (see the VocalBridge developer guide, "AI
Agents"). This responder joins the room as a silent participant next to the
user, runs each delegated query through the restricted VocalBridge
dispatcher agent, and publishes the answer back.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from typing import Any, Callable

from livekit import rtc

from openbase_coder_cli.vocalbridge.dispatcher_agent import (
    build_vocalbridge_dispatcher_client,
)

logger = logging.getLogger(__name__)

CLIENT_ACTIONS_TOPIC = "client_actions"
QUERY_AGENT_ACTION = "query_agent"
AGENT_RESPONSE_ACTION = "agent_response"
HEARTBEAT_ACTION = "heartbeat"
HEARTBEAT_ACK_ACTION = "heartbeat_ack"

# VocalBridge stops waiting for an agent_response after ~60 seconds; answer
# with a holding message just before that instead of silently missing the
# window. The turn keeps running so a follow-up query can pick up the result.
QUERY_ANSWER_TIMEOUT_SECONDS = 50.0
QUERY_TIMEOUT_RESPONSE = (
    "I'm still working on that. Ask me again in a moment for the result."
)
QUERY_EMPTY_RESPONSE = "I looked into that but don't have a useful answer yet."
# Hosted room tokens expire after an hour; stop the responder then even if
# LiveKit never delivers a clean disconnect event.
MAX_SESSION_SECONDS = 3600.0


def parse_client_action(data: bytes) -> tuple[str, dict[str, Any]] | None:
    """Decode a ``client_actions`` packet into (action, payload)."""
    try:
        message = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(message, dict) or message.get("type") != "client_action":
        return None
    action = message.get("action")
    if not isinstance(action, str) or not action:
        return None
    payload = message.get("payload")
    return action, payload if isinstance(payload, dict) else {}


def client_action_packet(action: str, payload: dict[str, Any]) -> bytes:
    return json.dumps(
        {"type": "client_action", "action": action, "payload": payload}
    ).encode("utf-8")


class VocalBridgeResponder:
    """Answers ``query_agent`` delegations in one VocalBridge room."""

    def __init__(
        self,
        *,
        room_name: str,
        livekit_url: str,
        token: str,
        dispatcher_client_factory: Callable[[], Any] = (
            build_vocalbridge_dispatcher_client
        ),
    ) -> None:
        self._room_name = room_name
        self._livekit_url = livekit_url
        self._token = token
        self._dispatcher_client_factory = dispatcher_client_factory
        self._dispatcher_client: Any | None = None
        self._closed = asyncio.Event()
        self._pending_queries: set[asyncio.Task] = set()

    async def run(self) -> None:
        room = rtc.Room()

        @room.on("data_received")
        def on_data_received(packet: rtc.DataPacket) -> None:
            if packet.topic != CLIENT_ACTIONS_TOPIC:
                return
            parsed = parse_client_action(packet.data)
            if parsed is None:
                return
            action, payload = parsed
            self._handle_action(room, action, payload)

        @room.on("disconnected")
        def on_disconnected(*_args) -> None:
            self._closed.set()

        logger.info("Connecting VocalBridge responder to room %s", self._room_name)
        await room.connect(self._livekit_url, self._token)
        self._dispatcher_client = self._dispatcher_client_factory()
        prepare = getattr(self._dispatcher_client, "prepare", None)
        if prepare is not None:
            try:
                await prepare()
            except Exception:
                logger.warning(
                    "Could not warm the VocalBridge dispatcher thread",
                    exc_info=True,
                )
        logger.info(
            "VocalBridge responder connected to room %s as %s",
            room.name,
            room.local_participant.identity,
        )
        try:
            await asyncio.wait_for(self._closed.wait(), timeout=MAX_SESSION_SECONDS)
        except asyncio.TimeoutError:
            logger.info(
                "VocalBridge responder session for room %s reached its lifetime limit",
                self._room_name,
            )
        finally:
            for task in tuple(self._pending_queries):
                task.cancel()
            client = self._dispatcher_client
            if client is not None:
                try:
                    await client.aclose()
                except Exception:
                    logger.debug(
                        "Error closing VocalBridge dispatcher client",
                        exc_info=True,
                    )
            await room.disconnect()

    def _handle_action(
        self, room: rtc.Room, action: str, payload: dict[str, Any]
    ) -> None:
        if action == HEARTBEAT_ACTION:
            self._spawn(
                self._publish(room, HEARTBEAT_ACK_ACTION, dict(payload)),
            )
            return
        if action != QUERY_AGENT_ACTION:
            return
        query = str(payload.get("query") or "").strip()
        turn_id = str(payload.get("turn_id") or "").strip()
        if not query or not turn_id:
            logger.warning(
                "Ignoring incomplete VocalBridge query_agent payload in room %s",
                self._room_name,
            )
            return
        logger.info(
            "VocalBridge query received room=%s turn_id=%s query_len=%d",
            self._room_name,
            turn_id,
            len(query),
        )
        self._spawn(self._answer_query(room, query=query, turn_id=turn_id))

    def _spawn(self, coroutine) -> None:
        task = asyncio.create_task(coroutine)
        self._pending_queries.add(task)
        task.add_done_callback(self._pending_queries.discard)

    async def _answer_query(self, room: rtc.Room, *, query: str, turn_id: str) -> None:
        started = time.monotonic()
        try:
            result = await asyncio.wait_for(
                asyncio.shield(self._run_dispatcher_turn(query)),
                timeout=QUERY_ANSWER_TIMEOUT_SECONDS,
            )
            response_text = (
                str(result.get("_livekit_speech_text") or "").strip()
                or QUERY_EMPTY_RESPONSE
            )
        except asyncio.TimeoutError:
            response_text = QUERY_TIMEOUT_RESPONSE
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "VocalBridge dispatcher turn failed room=%s turn_id=%s",
                self._room_name,
                turn_id,
            )
            response_text = (
                "Something went wrong while I was looking into that. Please try again."
            )
        logger.info(
            "VocalBridge query answered room=%s turn_id=%s elapsed_ms=%d "
            "response_chars=%d",
            self._room_name,
            turn_id,
            int((time.monotonic() - started) * 1000),
            len(response_text),
        )
        await self._publish(
            room,
            AGENT_RESPONSE_ACTION,
            {"response": response_text, "turn_id": turn_id},
        )

    async def _run_dispatcher_turn(self, query: str) -> dict[str, Any]:
        assert self._dispatcher_client is not None
        return await self._dispatcher_client.run_turn(query)

    async def _publish(
        self, room: rtc.Room, action: str, payload: dict[str, Any]
    ) -> None:
        try:
            await room.local_participant.publish_data(
                client_action_packet(action, payload),
                reliable=True,
                topic=CLIENT_ACTIONS_TOPIC,
            )
        except Exception:
            logger.exception(
                "Unable to publish VocalBridge %s packet in room %s",
                action,
                self._room_name,
            )


_responders_lock = threading.Lock()
_responder_threads: dict[str, threading.Thread] = {}


def ensure_vocalbridge_responder(
    *,
    room_name: str,
    livekit_url: str,
    token: str,
) -> bool:
    """Start a responder for ``room_name`` unless one is already running.

    Runs in a daemon thread with its own event loop so the long-lived room
    session does not block the Django request cycle. Returns True when a new
    responder was started.
    """
    with _responders_lock:
        existing = _responder_threads.get(room_name)
        if existing is not None and existing.is_alive():
            return False

        def _run() -> None:
            try:
                responder = VocalBridgeResponder(
                    room_name=room_name,
                    livekit_url=livekit_url,
                    token=token,
                )
                asyncio.run(responder.run())
            except Exception:
                logger.exception(
                    "VocalBridge responder for room %s exited with an error",
                    room_name,
                )
            finally:
                with _responders_lock:
                    if _responder_threads.get(room_name) is thread:
                        del _responder_threads[room_name]

        thread = threading.Thread(
            target=_run,
            name=f"vocalbridge-responder-{room_name}",
            daemon=True,
        )
        _responder_threads[room_name] = thread
        thread.start()
        return True
