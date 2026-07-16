from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from openbase_coder_cli.livekit_agent.super_agents_client import (
    SuperAgentsLiveKitClient,
    _extract_turn_id,
    _response_is_queued,
    _speech_text_from_progress,
)


class FakeSuperAgentsBackend:
    backend = "claude-agent-sdk"

    def __init__(self) -> None:
        self.started_threads: list[dict[str, Any]] = []
        self.started_turns: list[tuple[Any, dict[str, Any]]] = []
        self.progress_calls = 0
        self.permission_callback: Any | None = None

    def register_permission_callback(self, callback: Any) -> None:
        self.permission_callback = callback

    async def start_thread(self, input_data: dict[str, Any]) -> dict[str, Any]:
        self.started_threads.append(input_data)
        return {"threadId": "dispatcher-thread"}

    async def resume_by_label(self, input_data) -> dict[str, Any]:
        return {"threadId": input_data.thread_id}

    async def start_turn_by_label(
        self,
        input_data,
        turn_input: dict[str, Any],
    ) -> dict[str, Any]:
        self.started_turns.append((input_data, turn_input))
        return {"turnId": "turn-1"}

    async def steer_by_label(
        self,
        input_data,
        prompt: str,
        turn_input: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {"turnId": input_data.turn_id, "prompt": prompt}

    async def progress_by_label(self, input_data) -> dict[str, Any]:
        self.progress_calls += 1
        return {
            "status": "waiting",
            "threadId": input_data.thread_id,
            "turnId": input_data.turn_id,
            "lastUsefulMessage": "The dispatcher answer is ready.",
        }


class FakeCodexSuperAgentsBackend(FakeSuperAgentsBackend):
    backend = "codex"

    def __init__(self) -> None:
        super().__init__()
        self.started_direct_turns: list[dict[str, Any]] = []
        self.resumed_threads: list[dict[str, Any]] = []

    async def resume_thread(
        self,
        thread_id: str,
        *,
        label: str | None = None,
        agent_name: str | None = None,
        developer_instructions: str | None = None,
    ) -> dict[str, Any]:
        self.resumed_threads.append(
            {
                "thread_id": thread_id,
                "label": label,
                "agent_name": agent_name,
                "developer_instructions": developer_instructions,
            }
        )
        return {"threadId": thread_id}

    async def start_turn(self, turn_input: dict[str, Any]) -> dict[str, Any]:
        self.started_direct_turns.append(turn_input)
        return {"turnId": "direct-turn-1"}

    async def progress_by_label(self, input_data) -> dict[str, Any]:
        self.progress_calls += 1
        return {
            "status": "waiting",
            "threadId": input_data.thread_id,
            "turnId": input_data.turn_id,
            "summary": {
                "items": [
                    {
                        "type": "agentMessage",
                        "text": "The direct dispatcher answer is ready.",
                    }
                ]
            },
        }


class FakeQueuedSuperAgentsBackend(FakeSuperAgentsBackend):
    def __init__(self) -> None:
        super().__init__()
        self.progress_inputs: list[Any] = []
        self.latest_progress_calls = 0

    async def start_turn_by_label(
        self,
        input_data,
        turn_input: dict[str, Any],
    ) -> dict[str, Any]:
        self.started_turns.append((input_data, turn_input))
        return {
            "queued": True,
            "threadId": "dispatcher-thread",
            "queueDepth": 1,
            "item": {
                "id": "q_queued-follow-up",
                "threadId": "dispatcher-thread",
                "status": "queued",
            },
        }

    async def progress_by_label(self, input_data) -> dict[str, Any]:
        self.progress_calls += 1
        self.progress_inputs.append(input_data)
        if input_data.turn_id == "q_queued-follow-up":
            raise AssertionError("LiveKit must not poll queued item ids as turn ids")
        if input_data.turn_id == "turn-2":
            return {
                "status": "waiting",
                "threadId": input_data.thread_id,
                "turnId": "turn-2",
                "summary": {
                    "items": [
                        {
                            "type": "agentMessage",
                            "text": "The queued dispatcher answer is ready.",
                        }
                    ]
                },
            }
        self.latest_progress_calls += 1
        return {
            "status": "running",
            "threadId": input_data.thread_id,
            "turnId": "turn-1" if self.latest_progress_calls == 1 else "turn-2",
        }


class FakeExternallyActiveSuperAgentsBackend(FakeSuperAgentsBackend):
    def __init__(self) -> None:
        super().__init__()
        self.resolved_labels: list[Any] = []
        self.steered: list[tuple[Any, str]] = []
        self.steer_turn_inputs: list[dict[str, Any] | None] = []

    async def resolve_label(self, input_data) -> dict[str, Any]:
        self.resolved_labels.append(input_data)
        return {
            "status": "running",
            "threadId": input_data.thread_id,
            "turnId": "active-turn-1",
        }

    async def steer_by_label(
        self,
        input_data,
        prompt: str,
        turn_input: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.steered.append((input_data, prompt))
        self.steer_turn_inputs.append(turn_input)
        return {"turnId": input_data.turn_id, "prompt": prompt}

    async def progress_by_label(self, input_data) -> dict[str, Any]:
        self.progress_calls += 1
        return {
            "status": "waiting",
            "threadId": input_data.thread_id,
            "turnId": input_data.turn_id,
            "summary": {
                "items": [
                    {
                        "type": "agentMessage",
                        "text": "The steered dispatcher answer is ready.",
                    }
                ]
            },
        }


class FakeSlowStartSuperAgentsBackend(FakeSuperAgentsBackend):
    def __init__(self) -> None:
        super().__init__()
        self.start_called = asyncio.Event()
        self.release_start = asyncio.Event()
        self.steered: list[tuple[Any, str]] = []
        self.steer_turn_inputs: list[dict[str, Any] | None] = []

    async def start_turn_by_label(
        self,
        input_data,
        turn_input: dict[str, Any],
    ) -> dict[str, Any]:
        self.started_turns.append((input_data, turn_input))
        self.start_called.set()
        await self.release_start.wait()
        return {"turnId": "turn-1"}

    async def steer_by_label(
        self,
        input_data,
        prompt: str,
        turn_input: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.steered.append((input_data, prompt))
        self.steer_turn_inputs.append(turn_input)
        return {"turnId": input_data.turn_id, "prompt": prompt}

    async def progress_by_label(self, input_data) -> dict[str, Any]:
        self.progress_calls += 1
        return {
            "status": "waiting",
            "threadId": input_data.thread_id,
            "turnId": input_data.turn_id,
            "summary": {
                "items": [
                    {
                        "type": "agentMessage",
                        "text": "The interrupted turn accepted steering.",
                    }
                ]
            },
        }


class FakeLongRunningSuperAgentsBackend(FakeSuperAgentsBackend):
    def __init__(self) -> None:
        super().__init__()
        self.progress_called = asyncio.Event()
        self.release_progress = asyncio.Event()
        self.steered: list[tuple[Any, str]] = []
        self.steer_turn_inputs: list[dict[str, Any] | None] = []

    async def start_turn_by_label(
        self,
        input_data,
        turn_input: dict[str, Any],
    ) -> dict[str, Any]:
        self.started_turns.append((input_data, turn_input))
        return {"turnId": "turn-1"}

    async def steer_by_label(
        self,
        input_data,
        prompt: str,
        turn_input: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.steered.append((input_data, prompt))
        self.steer_turn_inputs.append(turn_input)
        return {"turnId": input_data.turn_id, "prompt": prompt}

    async def progress_by_label(self, input_data) -> dict[str, Any]:
        self.progress_calls += 1
        if not self.started_turns:
            return {
                "status": "completed",
                "threadId": input_data.thread_id,
            }
        self.progress_called.set()
        await self.release_progress.wait()
        return {
            "status": "waiting",
            "threadId": input_data.thread_id,
            "turnId": input_data.turn_id,
            "summary": {
                "items": [
                    {
                        "type": "agentMessage",
                        "text": "The proactively steered turn is ready.",
                    }
                ]
            },
        }


class FakeStaleActiveSuperAgentsBackend(FakeSuperAgentsBackend):
    def __init__(self) -> None:
        super().__init__()
        self.steered: list[tuple[Any, str]] = []
        self.steer_turn_inputs: list[dict[str, Any] | None] = []

    async def resolve_label(self, input_data) -> dict[str, Any]:
        return {
            "status": "running",
            "threadId": input_data.thread_id,
            "turnId": "stale-turn",
        }

    async def steer_by_label(
        self,
        input_data,
        prompt: str,
        turn_input: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.steered.append((input_data, prompt))
        self.steer_turn_inputs.append(turn_input)
        return {"turnId": input_data.turn_id, "prompt": prompt}

    async def progress_by_label(self, input_data) -> dict[str, Any]:
        self.progress_calls += 1
        if input_data.turn_id == "stale-turn":
            return {
                "status": "completed",
                "threadId": input_data.thread_id,
                "turnId": "stale-turn",
            }
        return {
            "status": "waiting",
            "threadId": input_data.thread_id,
            "turnId": input_data.turn_id,
            "summary": {
                "items": [
                    {
                        "type": "agentMessage",
                        "text": "The replacement turn is ready.",
                    }
                ]
            },
        }


@pytest.mark.asyncio
async def test_super_agents_livekit_client_creates_thread_and_turn_through_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = FakeSuperAgentsBackend()
    state_path = tmp_path / "livekit-voice-route.json"
    config_path = tmp_path / "dispatcher-config.json"
    monkeypatch.setenv("OPENBASE_CODING_BACKEND", "claude_code")
    config_path.write_text(
        json.dumps(
            {
                "backend_models": {
                    "claude_code": {
                        "dispatcher": "haiku",
                        "super_agents": "opus",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    client = SuperAgentsLiveKitClient(
        cwd="/tmp/project",
        state_path=str(state_path),
        developer_instructions="dispatcher instructions",
        dispatcher_config_path=config_path,
        backend_client=backend,
    )

    thread_id = await client.prepare()
    result = await client.run_turn(
        "hello",
        developer_instructions="voice instructions",
    )

    assert thread_id == "dispatcher-thread"
    assert (
        json.loads(state_path.read_text(encoding="utf-8"))["dispatcher_thread_id"]
        == "dispatcher-thread"
    )
    assert backend.started_threads[0]["label"] == "dispatcher"
    assert backend.started_threads[0]["cwd"] == "/tmp/project"
    assert backend.started_threads[0]["model"] == "haiku"
    assert backend.started_turns[0][0].thread_id == "dispatcher-thread"
    assert backend.started_turns[0][1]["prompt"] == "hello"
    assert backend.started_turns[0][1]["model"] == "haiku"
    assert (
        "dispatcher instructions"
        in backend.started_turns[0][1]["developerInstructions"]
    )
    assert "voice instructions" in backend.started_turns[0][1]["developerInstructions"]
    assert result["_livekit_turn_id"] == "turn-1"
    assert result["_livekit_speech_text"] == "The dispatcher answer is ready."


@pytest.mark.asyncio
async def test_super_agents_livekit_client_starts_codex_turn_by_thread_id(
    tmp_path: Path,
) -> None:
    backend = FakeCodexSuperAgentsBackend()
    state_path = tmp_path / "livekit-voice-route.json"
    client = SuperAgentsLiveKitClient(
        cwd="/tmp/project",
        state_path=str(state_path),
        backend_client=backend,
    )

    result = await client.run_turn("hello")

    assert backend.started_turns == []
    assert backend.started_direct_turns[0]["threadId"] == "dispatcher-thread"
    assert backend.started_direct_turns[0]["prompt"] == "hello"
    assert result["_livekit_turn_id"] == "direct-turn-1"
    assert result["_livekit_speech_text"] == "The direct dispatcher answer is ready."


@pytest.mark.asyncio
async def test_super_agents_livekit_client_waits_for_queued_turn_to_start(
    tmp_path: Path,
) -> None:
    backend = FakeQueuedSuperAgentsBackend()
    state_path = tmp_path / "livekit-voice-route.json"
    client = SuperAgentsLiveKitClient(
        cwd="/tmp/project",
        state_path=str(state_path),
        backend_client=backend,
    )

    result = await client.run_turn("hello")

    assert result["_livekit_turn_id"] == "turn-2"
    assert result["_livekit_speech_text"] == "The queued dispatcher answer is ready."
    assert [input_data.turn_id for input_data in backend.progress_inputs] == [
        None,
        None,
        "turn-2",
    ]


@pytest.mark.asyncio
async def test_super_agents_livekit_client_steers_backend_active_turn(
    tmp_path: Path,
) -> None:
    backend = FakeExternallyActiveSuperAgentsBackend()
    state_path = tmp_path / "livekit-voice-route.json"
    client = SuperAgentsLiveKitClient(
        cwd="/tmp/project",
        state_path=str(state_path),
        backend_client=backend,
    )

    result = await client.run_turn("please adjust that")

    assert backend.started_turns == []
    assert len(backend.steered) == 1
    steer_input, prompt = backend.steered[0]
    assert steer_input.turn_id == "active-turn-1"
    assert prompt == "please adjust that"
    assert result["_livekit_turn_id"] == "active-turn-1"
    assert result["_livekit_speech_text"] == "The steered dispatcher answer is ready."


@pytest.mark.asyncio
async def test_super_agents_livekit_client_preserves_started_turn_after_cancellation(
    tmp_path: Path,
) -> None:
    backend = FakeSlowStartSuperAgentsBackend()
    state_path = tmp_path / "livekit-voice-route.json"
    client = SuperAgentsLiveKitClient(
        cwd="/tmp/project",
        state_path=str(state_path),
        backend_client=backend,
    )

    first = asyncio.create_task(client.run_turn("write about strawberries"))
    await backend.start_called.wait()
    first.cancel()
    backend.release_start.set()

    with pytest.raises(asyncio.CancelledError):
        await first

    result = await client.run_turn("change it to blueberries")

    assert len(backend.started_turns) == 1
    assert len(backend.steered) == 1
    steer_input, prompt = backend.steered[0]
    assert steer_input.turn_id == "turn-1"
    assert prompt == "change it to blueberries"
    assert result["_livekit_turn_id"] == "turn-1"
    assert result["_livekit_speech_text"] == "The interrupted turn accepted steering."


@pytest.mark.asyncio
async def test_super_agents_livekit_client_proactively_steers_active_turn(
    tmp_path: Path,
) -> None:
    backend = FakeLongRunningSuperAgentsBackend()
    state_path = tmp_path / "livekit-voice-route.json"
    client = SuperAgentsLiveKitClient(
        cwd="/tmp/project",
        state_path=str(state_path),
        backend_client=backend,
    )

    first = asyncio.create_task(client.run_turn("write about strawberries"))
    await backend.progress_called.wait()

    turn_id = await client.steer_active_turn("stop and write about blueberries")
    follow_up = asyncio.create_task(
        client.run_turn("stop and write about blueberries")
    )
    await asyncio.sleep(0)

    assert turn_id == "turn-1"
    assert len(backend.started_turns) == 1
    assert len(backend.steered) == 1
    steer_input, prompt = backend.steered[0]
    assert steer_input.turn_id == "turn-1"
    assert prompt == "stop and write about blueberries"

    backend.release_progress.set()
    first_result = await first
    follow_up_result = await follow_up

    assert len(backend.started_turns) == 1
    assert len(backend.steered) == 1
    assert first_result["_livekit_turn_id"] == "turn-1"
    assert follow_up_result["_livekit_turn_id"] == "turn-1"


@pytest.mark.asyncio
async def test_super_agents_livekit_client_passes_dispatcher_reasoning_to_steer(
    tmp_path: Path,
) -> None:
    backend = FakeLongRunningSuperAgentsBackend()
    state_path = tmp_path / "livekit-voice-route.json"
    dispatcher_config_path = tmp_path / "dispatcher-config.json"
    dispatcher_config_path.write_text(
        json.dumps({"dispatcher_reasoning_effort": "low"}),
        encoding="utf-8",
    )
    client = SuperAgentsLiveKitClient(
        cwd="/tmp/project",
        state_path=str(state_path),
        dispatcher_config_path=dispatcher_config_path,
        backend_client=backend,
    )

    first = asyncio.create_task(client.run_turn("write about strawberries"))
    await backend.progress_called.wait()

    turn_id = await client.steer_active_turn("stop and write about blueberries")

    backend.release_progress.set()
    await first

    assert turn_id == "turn-1"
    assert backend.steer_turn_inputs[0]["reasoningEffort"] == "low"


@pytest.mark.asyncio
async def test_super_agents_livekit_client_proactive_steer_does_not_start_turn(
    tmp_path: Path,
) -> None:
    backend = FakeSuperAgentsBackend()
    state_path = tmp_path / "livekit-voice-route.json"
    client = SuperAgentsLiveKitClient(
        cwd="/tmp/project",
        state_path=str(state_path),
        backend_client=backend,
    )

    turn_id = await client.steer_active_turn("hello")

    assert turn_id is None
    assert backend.started_turns == []


@pytest.mark.asyncio
async def test_super_agents_livekit_client_does_not_steer_stale_active_turn(
    tmp_path: Path,
) -> None:
    backend = FakeStaleActiveSuperAgentsBackend()
    state_path = tmp_path / "livekit-voice-route.json"
    client = SuperAgentsLiveKitClient(
        cwd="/tmp/project",
        state_path=str(state_path),
        backend_client=backend,
    )

    result = await client.run_turn("start fresh")

    assert backend.steered == []
    assert len(backend.started_turns) == 1
    assert result["_livekit_turn_id"] == "turn-1"
    assert result["_livekit_speech_text"] == "The replacement turn is ready."


@pytest.mark.asyncio
async def test_super_agents_livekit_client_resumes_codex_thread_by_id(
    tmp_path: Path,
) -> None:
    backend = FakeCodexSuperAgentsBackend()
    state_path = tmp_path / "livekit-voice-route.json"
    state_path.write_text(
        json.dumps({"dispatcher_thread_id": "canonical-dispatcher-thread"}),
        encoding="utf-8",
    )
    client = SuperAgentsLiveKitClient(
        cwd="/tmp/project",
        state_path=str(state_path),
        initial_thread_id="stale-dispatcher-thread",
        backend_client=backend,
    )

    thread_id = await client.prepare()

    assert thread_id == "canonical-dispatcher-thread"
    assert backend.resumed_threads == [
        {
            "thread_id": "canonical-dispatcher-thread",
            "label": "dispatcher",
            "agent_name": None,
            "developer_instructions": "Super Agent thread name: dispatcher",
        }
    ]
    assert backend.started_threads == []
    assert (
        json.loads(state_path.read_text(encoding="utf-8"))["dispatcher_thread_id"]
        == "canonical-dispatcher-thread"
    )


def test_super_agents_livekit_client_answers_mcp_elicitations(tmp_path: Path) -> None:
    backend = FakeCodexSuperAgentsBackend()
    SuperAgentsLiveKitClient(
        cwd=str(tmp_path),
        state_path=str(tmp_path / "livekit-voice-route.json"),
        backend_client=backend,
    )

    assert backend.permission_callback is not None
    accepted = backend.permission_callback(
        SimpleNamespace(
            method="mcpServer/elicitation/request",
            params={"serverName": "super_agents"},
        )
    )
    declined = backend.permission_callback(
        SimpleNamespace(
            method="mcpServer/elicitation/request",
            params={"serverName": "chrome"},
        )
    )

    assert accepted == {"action": "accept", "content": None, "_meta": None}
    assert declined == {"action": "decline", "content": None, "_meta": None}


def test_speech_text_from_progress_uses_agent_message_text() -> None:
    progress = {
        "summary": {
            "items": [
                {
                    "type": "agentMessage",
                    "text": "Here is the useful answer.",
                }
            ]
        }
    }

    assert _speech_text_from_progress(progress) == "Here is the useful answer."


def test_speech_text_from_progress_ignores_turn_ids() -> None:
    progress = {
        "summary": {
            "lastUsefulMessage": "019edae2 e304 77a3 9ddb 470ed17e64f7.",
        },
        "turn": {
            "id": "019edae2-e304-77a3-9ddb-470ed17e64f7",
            "status": "completed",
        },
    }

    assert _speech_text_from_progress(progress) == ""


def test_extract_turn_id_ignores_queued_item_id() -> None:
    payload = {
        "queued": True,
        "item": {
            "id": "q_queued-follow-up",
            "status": "queued",
        },
    }

    assert _extract_turn_id(payload) is None


def test_top_level_queue_item_id_is_queued_response() -> None:
    payload = {"turnId": "q_queued-follow-up", "status": "queued"}

    assert _response_is_queued(payload) is True
    assert _extract_turn_id(payload) is None


def test_speech_text_from_progress_ignores_user_message_text() -> None:
    progress = {
        "summary": {
            "items": [
                {
                    "type": "userMessage",
                    "content": [
                        {
                            "type": "text",
                            "text": "hey are you there",
                        }
                    ],
                }
            ],
            "lastUsefulMessage": "hey are you there",
        },
        "turn": {
            "items": [
                {
                    "type": "userMessage",
                    "content": [
                        {
                            "type": "text",
                            "text": "can you hear me",
                        }
                    ],
                }
            ]
        },
    }

    assert _speech_text_from_progress(progress) == ""
