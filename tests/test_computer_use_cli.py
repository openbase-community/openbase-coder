from __future__ import annotations

import importlib

import httpx
import pytest
from click.testing import CliRunner

computer_use_cli = importlib.import_module("openbase_coder_cli.cli.computer_use")
local_server = importlib.import_module("openbase_coder_cli.cli.local_server")


class FakeTokenManager:
    def get_access_token(self) -> str:
        return "jwt.token.value"


class FakeCompanionClient:
    instances: list["FakeCompanionClient"] = []

    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        FakeCompanionClient.instances.append(self)

    def ensure_running(self) -> None:
        self.calls.append(("ensure_running", None))

    def status(self) -> dict:
        self.calls.append(("status", None))
        return {"ok": True, "state": "off"}

    def start_screen_share(self, session: dict) -> dict:
        self.calls.append(("start_screen_share", session))
        return {"ok": True, "state": "sharing"}

    def stop_screen_share(self) -> dict:
        self.calls.append(("stop_screen_share", None))
        return {"ok": True, "state": "off"}

    def start_computer_use(
        self, *, instructions: str, model: str | None, max_steps: int
    ) -> dict:
        self.calls.append(
            (
                "start_computer_use",
                {"instructions": instructions, "model": model, "max_steps": max_steps},
            )
        )
        return {"ok": True, "state": "controlling"}

    def steer_computer_use(self, instructions: str) -> dict:
        self.calls.append(("steer_computer_use", instructions))
        return {"ok": True, "state": "controlling"}

    def queue_computer_use(self, instructions: str) -> dict:
        self.calls.append(("queue_computer_use", instructions))
        return {"ok": True, "state": "controlling"}

    def interrupt_computer_use(self) -> dict:
        self.calls.append(("interrupt_computer_use", None))
        return {"ok": True, "state": "off"}


@pytest.fixture(autouse=True)
def linux_platform(monkeypatch):
    monkeypatch.setattr(computer_use_cli.platform, "system", lambda: "Linux")


def patch_local_server_request(monkeypatch, fake_request) -> None:
    monkeypatch.setattr(local_server, "get_token_manager", lambda: FakeTokenManager())
    monkeypatch.setattr(local_server.httpx, "request", fake_request)


def test_start_turns_on_screen_share_before_computer_use(monkeypatch):
    FakeCompanionClient.instances = []

    def fake_request(method, url, **kwargs):
        assert method == "GET"
        assert url == "http://127.0.0.1:7999/api/livekit-companion-session/"
        return httpx.Response(
            200,
            json={
                "roomUrl": "ws://localhost:7880",
                "companionToken": "token",
                "companionTokenExpiresAt": "2026-05-23T12:00:00Z",
            },
        )

    patch_local_server_request(monkeypatch, fake_request)
    monkeypatch.setattr(computer_use_cli, "CompanionClient", FakeCompanionClient)

    result = CliRunner().invoke(
        computer_use_cli.computer_use,
        ["start", "--model", "gpt-test", "--max-steps", "4", "click", "the", "button"],
    )

    assert result.exit_code == 0
    client = FakeCompanionClient.instances[0]
    assert [name for name, _ in client.calls] == [
        "ensure_running",
        "status",
        "start_screen_share",
        "start_computer_use",
    ]
    assert client.calls[2][1]["roomUrl"] == "ws://localhost:7880"
    assert client.calls[3][1] == {
        "instructions": "click the button",
        "model": "gpt-test",
        "max_steps": 4,
    }


def test_companion_client_requests_display_source_for_screen_share(monkeypatch):
    captured_payloads: list[dict] = []

    def fake_request(method, url, **kwargs):
        captured_payloads.append(kwargs["json"])
        return httpx.Response(200, json={"ok": True, "state": "sharing"})

    monkeypatch.setattr(computer_use_cli.httpx, "request", fake_request)
    monkeypatch.setenv("OPENBASE_LIVEKIT_COMPANION_IPC_PORT", "39281")
    monkeypatch.setenv("OPENBASE_LIVEKIT_COMPANION_IPC_SECRET", "secret")

    session = {"roomUrl": "ws://localhost:7880", "token": "token"}
    response = computer_use_cli.CompanionClient().start_screen_share(session)

    assert response["state"] == "sharing"
    assert captured_payloads == [
        {"roomUrl": "ws://localhost:7880", "token": "token", "sourceType": "display"}
    ]
    assert session == {"roomUrl": "ws://localhost:7880", "token": "token"}


def test_start_refuses_second_active_run(monkeypatch):
    class BusyCompanionClient(FakeCompanionClient):
        def status(self) -> dict:
            self.calls.append(("status", None))
            return {"ok": True, "state": "controlling"}

    monkeypatch.setattr(computer_use_cli, "CompanionClient", BusyCompanionClient)

    result = CliRunner().invoke(computer_use_cli.computer_use, ["start", "do", "thing"])

    assert result.exit_code != 0
    assert "already running" in result.output


def test_start_stops_screen_share_if_computer_use_start_fails(monkeypatch):
    FakeCompanionClient.instances = []

    class FailingCompanionClient(FakeCompanionClient):
        def start_computer_use(
            self, *, instructions: str, model: str | None, max_steps: int
        ) -> dict:
            self.calls.append(("start_computer_use", instructions))
            raise RuntimeError("boom")

    def fake_request(method, url, **kwargs):
        assert method == "GET"
        return httpx.Response(
            200, json={"roomUrl": "ws://localhost:7880", "companionToken": "token"}
        )

    patch_local_server_request(monkeypatch, fake_request)
    monkeypatch.setattr(computer_use_cli, "CompanionClient", FailingCompanionClient)

    result = CliRunner().invoke(computer_use_cli.computer_use, ["start", "do", "thing"])

    assert result.exit_code != 0
    assert "Unable to start computer use" in result.output
    assert [name for name, _ in FailingCompanionClient.instances[0].calls][
        -1
    ] == "stop_screen_share"


def test_steer_replaces_active_instructions(monkeypatch):
    FakeCompanionClient.instances = []
    monkeypatch.setattr(computer_use_cli, "CompanionClient", FakeCompanionClient)

    result = CliRunner().invoke(computer_use_cli.computer_use, ["steer", "new", "plan"])

    assert result.exit_code == 0
    assert FakeCompanionClient.instances[0].calls == [
        ("steer_computer_use", "new plan")
    ]


def test_queue_appends_follow_up_instructions(monkeypatch):
    FakeCompanionClient.instances = []
    monkeypatch.setattr(computer_use_cli, "CompanionClient", FakeCompanionClient)

    result = CliRunner().invoke(
        computer_use_cli.computer_use, ["queue", "then", "save"]
    )

    assert result.exit_code == 0
    assert FakeCompanionClient.instances[0].calls == [
        ("queue_computer_use", "then save")
    ]


def test_interrupt_calls_companion(monkeypatch):
    FakeCompanionClient.instances = []
    monkeypatch.setattr(computer_use_cli, "CompanionClient", FakeCompanionClient)

    result = CliRunner().invoke(computer_use_cli.computer_use, ["interrupt"])

    assert result.exit_code == 0
    assert FakeCompanionClient.instances[0].calls == [("interrupt_computer_use", None)]


def test_computer_use_refuses_macos(monkeypatch):
    monkeypatch.setattr(computer_use_cli.platform, "system", lambda: "Darwin")

    result = CliRunner().invoke(computer_use_cli.computer_use, ["status"])

    assert result.exit_code != 0
    assert "Linux-only" in result.output
    assert "native Computer Use" in result.output
