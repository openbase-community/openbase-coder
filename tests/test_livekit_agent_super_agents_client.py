from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from openbase_coder_cli.livekit_agent.super_agents_client import (
    SuperAgentsLiveKitClient,
)


class FakeSuperAgentsBackend:
    backend = "claude-agent-sdk"

    def __init__(self) -> None:
        self.started_threads: list[dict[str, Any]] = []
        self.started_turns: list[tuple[Any, dict[str, Any]]] = []
        self.progress_calls = 0

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

    async def steer_by_label(self, input_data, prompt: str) -> dict[str, Any]:
        return {"turnId": input_data.turn_id, "prompt": prompt}

    async def progress_by_label(self, input_data) -> dict[str, Any]:
        self.progress_calls += 1
        return {
            "status": "waiting",
            "threadId": input_data.thread_id,
            "turnId": input_data.turn_id,
            "lastUsefulMessage": "The dispatcher answer is ready.",
        }


@pytest.mark.asyncio
async def test_super_agents_livekit_client_creates_thread_and_turn_through_backend(
    tmp_path: Path,
) -> None:
    backend = FakeSuperAgentsBackend()
    state_path = tmp_path / "livekit-voice-route.json"
    config_path = tmp_path / "dispatcher-config.json"
    config_path.write_text(
        json.dumps({"super_agents_model": "opus"}),
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
    assert backend.started_threads[0]["model"] == "opus"
    assert backend.started_turns[0][0].thread_id == "dispatcher-thread"
    assert backend.started_turns[0][1]["prompt"] == "hello"
    assert backend.started_turns[0][1]["model"] == "opus"
    assert (
        "dispatcher instructions"
        in backend.started_turns[0][1]["developerInstructions"]
    )
    assert "voice instructions" in backend.started_turns[0][1]["developerInstructions"]
    assert result["_livekit_turn_id"] == "turn-1"
    assert result["_livekit_speech_text"] == "The dispatcher answer is ready."
