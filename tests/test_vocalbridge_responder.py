from __future__ import annotations

import asyncio
import json

from openbase_coder_cli.vocalbridge import responder as vocalbridge_responder
from openbase_coder_cli.vocalbridge.responder import (
    AGENT_RESPONSE_ACTION,
    CLIENT_ACTIONS_TOPIC,
    HEARTBEAT_ACK_ACTION,
    VocalBridgeResponder,
    client_action_packet,
    parse_client_action,
)


class FakeLocalParticipant:
    def __init__(self) -> None:
        self.published: list[tuple[bytes, str]] = []

    async def publish_data(self, data: bytes, *, reliable: bool, topic: str) -> None:
        assert reliable is True
        self.published.append((data, topic))


class FakeRoom:
    def __init__(self) -> None:
        self.local_participant = FakeLocalParticipant()


class FakeDispatcherClient:
    def __init__(self, speech_text: str = "Charlotte is on it.") -> None:
        self.prompts: list[str] = []
        self._speech_text = speech_text

    async def run_turn(self, prompt: str, **_kwargs) -> dict:
        self.prompts.append(prompt)
        return {"_livekit_speech_text": self._speech_text}

    async def aclose(self) -> None:
        pass


def _build_responder(client: FakeDispatcherClient) -> VocalBridgeResponder:
    responder = VocalBridgeResponder(
        room_name="room-1",
        livekit_url="wss://example.livekit.cloud",
        token="jwt",
        dispatcher_client_factory=lambda: client,
    )
    responder._dispatcher_client = client
    return responder


def _published_actions(room: FakeRoom) -> list[dict]:
    return [
        json.loads(data.decode("utf-8"))
        for data, topic in room.local_participant.published
        if topic == CLIENT_ACTIONS_TOPIC
    ]


def test_parse_client_action_roundtrip() -> None:
    packet = client_action_packet("query_agent", {"query": "hi", "turn_id": "t1"})
    parsed = parse_client_action(packet)
    assert parsed == ("query_agent", {"query": "hi", "turn_id": "t1"})


def test_parse_client_action_rejects_other_payloads() -> None:
    assert parse_client_action(b"not json") is None
    assert parse_client_action(json.dumps({"type": "other"}).encode()) is None
    assert parse_client_action(json.dumps({"type": "client_action"}).encode()) is None


def test_query_agent_runs_dispatcher_and_publishes_response() -> None:
    client = FakeDispatcherClient()
    responder = _build_responder(client)
    room = FakeRoom()

    async def scenario() -> None:
        responder._handle_action(
            room,
            "query_agent",
            {"query": "Start an agent on the console repo", "turn_id": "turn-9"},
        )
        await asyncio.gather(*responder._pending_queries)

    asyncio.run(scenario())

    assert client.prompts == ["Start an agent on the console repo"]
    actions = _published_actions(room)
    assert actions == [
        {
            "type": "client_action",
            "action": AGENT_RESPONSE_ACTION,
            "payload": {"response": "Charlotte is on it.", "turn_id": "turn-9"},
        }
    ]


def test_query_agent_times_out_with_holding_response(monkeypatch) -> None:
    monkeypatch.setattr(vocalbridge_responder, "QUERY_ANSWER_TIMEOUT_SECONDS", 0.01)

    class SlowClient(FakeDispatcherClient):
        async def run_turn(self, prompt: str, **_kwargs) -> dict:
            await asyncio.sleep(1)
            return {}

    responder = _build_responder(SlowClient())
    room = FakeRoom()

    async def scenario() -> None:
        responder._handle_action(
            room, "query_agent", {"query": "slow one", "turn_id": "turn-1"}
        )
        await asyncio.gather(*responder._pending_queries)

    asyncio.run(scenario())

    actions = _published_actions(room)
    assert len(actions) == 1
    assert actions[0]["payload"]["turn_id"] == "turn-1"
    assert (
        actions[0]["payload"]["response"]
        == vocalbridge_responder.QUERY_TIMEOUT_RESPONSE
    )


def test_heartbeat_is_acked() -> None:
    responder = _build_responder(FakeDispatcherClient())
    room = FakeRoom()

    async def scenario() -> None:
        responder._handle_action(room, "heartbeat", {"timestamp": 123})
        await asyncio.gather(*responder._pending_queries)

    asyncio.run(scenario())

    actions = _published_actions(room)
    assert actions == [
        {
            "type": "client_action",
            "action": HEARTBEAT_ACK_ACTION,
            "payload": {"timestamp": 123},
        }
    ]


def test_incomplete_query_is_ignored() -> None:
    client = FakeDispatcherClient()
    responder = _build_responder(client)
    room = FakeRoom()

    async def scenario() -> None:
        responder._handle_action(room, "query_agent", {"query": ""})
        responder._handle_action(room, "unrelated_action", {"query": "hi"})
        await asyncio.gather(*responder._pending_queries)

    asyncio.run(scenario())

    assert client.prompts == []
    assert _published_actions(room) == []


def test_ensure_vocalbridge_responder_deduplicates(monkeypatch) -> None:
    started: list[str] = []

    class FakeThread:
        def __init__(self, *, target, name, daemon) -> None:
            self._name = name

        def start(self) -> None:
            started.append(self._name)

        def is_alive(self) -> bool:
            return True

    monkeypatch.setattr(vocalbridge_responder.threading, "Thread", FakeThread)
    monkeypatch.setattr(vocalbridge_responder, "_responder_threads", {})

    first = vocalbridge_responder.ensure_vocalbridge_responder(
        room_name="room-x", livekit_url="wss://x", token="t"
    )
    second = vocalbridge_responder.ensure_vocalbridge_responder(
        room_name="room-x", livekit_url="wss://x", token="t"
    )

    assert first is True
    assert second is False
    assert started == ["vocalbridge-responder-room-x"]

