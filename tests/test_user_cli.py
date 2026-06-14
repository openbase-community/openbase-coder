from __future__ import annotations

import importlib
import json

import httpx
import pytest
from click.testing import CliRunner

dispatcher_config = importlib.import_module("openbase_coder_cli.dispatcher_config")
local_server = importlib.import_module("openbase_coder_cli.cli.local_server")
main_cli = importlib.import_module("openbase_coder_cli.cli")
user_cli = importlib.import_module("openbase_coder_cli.cli.user")


@pytest.fixture(autouse=True)
def clear_super_agent_context(monkeypatch):
    monkeypatch.delenv("OPENBASE_SUPER_AGENT_THREAD_ID", raising=False)
    monkeypatch.delenv("OPENBASE_SUPER_AGENT_LABEL", raising=False)
    monkeypatch.delenv("OPENBASE_SUPER_AGENT_AGENT_NAME", raising=False)
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    monkeypatch.delenv("OPENBASE_CODER_ANNOUNCER_VOICE_ID", raising=False)


class FakeTokenManager:
    def get_access_token(self) -> str:
        return "jwt.token.value"


def patch_local_server_request(monkeypatch, fake_request) -> None:
    monkeypatch.setattr(local_server, "get_token_manager", lambda: FakeTokenManager())
    monkeypatch.setattr(local_server.httpx, "request", fake_request)


def test_user_say_posts_message(monkeypatch):
    calls = []

    def fake_request(method, url, **kwargs):
        assert method == "POST"
        calls.append((url, kwargs))
        return httpx.Response(
            202,
            json={"message_id": "announcer-1", "room_name": "room-1"},
        )

    monkeypatch.setenv("OPENBASE_CODER_CLI_SERVER_URL", "http://localhost:7999/")
    patch_local_server_request(monkeypatch, fake_request)

    result = CliRunner().invoke(user_cli.user, ["say", "Dottie", "hello", "there"])

    assert result.exit_code == 0
    assert "room-1" in result.output
    assert calls[0][0] == "http://localhost:7999/api/user/say/"
    assert calls[0][1]["json"] == {"agent_name": "Dottie", "text": "hello there"}


def test_user_say_posts_explicit_room(monkeypatch):
    calls = []

    def fake_request(method, url, **kwargs):
        assert method == "POST"
        calls.append(kwargs["json"])
        return httpx.Response(
            202,
            json={"message_id": "announcer-1", "room_name": "room-explicit"},
        )

    patch_local_server_request(monkeypatch, fake_request)

    result = CliRunner().invoke(
        user_cli.user,
        ["say", "--room", "room-explicit", "Dottie", "hello"],
    )

    assert result.exit_code == 0
    assert calls == [
        {"agent_name": "Dottie", "text": "hello", "room_name": "room-explicit"}
    ]


def test_user_say_accepts_explicit_dispatcher(monkeypatch):
    calls = []

    def fake_request(method, url, **kwargs):
        assert method == "POST"
        calls.append(kwargs["json"])
        return httpx.Response(
            202,
            json={"message_id": "announcer-1", "room_name": "room-1"},
        )

    patch_local_server_request(monkeypatch, fake_request)

    result = CliRunner().invoke(user_cli.user, ["say", "dispatcher", "hello"])

    assert result.exit_code == 0
    assert calls == [{"agent_name": "dispatcher", "text": "hello"}]


def test_user_say_ignores_legacy_identity_environment(monkeypatch):
    calls = []

    def fake_request(method, url, **kwargs):
        assert method == "POST"
        calls.append(kwargs["json"])
        return httpx.Response(
            202,
            json={"message_id": "announcer-1", "room_name": "room-1"},
        )

    monkeypatch.setenv("OPENBASE_SUPER_AGENT_THREAD_ID", "thread-1")
    monkeypatch.setenv("OPENBASE_SUPER_AGENT_LABEL", "Build")
    monkeypatch.setenv("OPENBASE_SUPER_AGENT_AGENT_NAME", "Carl")
    monkeypatch.setenv("CODEX_THREAD_ID", "thread-1")
    monkeypatch.setenv("OPENBASE_CODER_ANNOUNCER_VOICE_ID", "stale-voice")
    patch_local_server_request(monkeypatch, fake_request)

    result = CliRunner().invoke(user_cli.user, ["say", "Dottie", "hello"])

    assert result.exit_code == 0
    assert calls == [{"agent_name": "Dottie", "text": "hello"}]


def test_user_say_requires_message_after_agent_name():
    result = CliRunner().invoke(user_cli.user, ["say", "Dottie"])

    assert result.exit_code != 0
    assert "Agent name is required" in result.output
    assert "openbase-coder user say AGENT_NAME MESSAGE" in result.output


def test_user_say_rejects_blank_agent_name():
    result = CliRunner().invoke(user_cli.user, ["say", "", "hello"])

    assert result.exit_code != 0
    assert "Agent name is required and cannot be blank" in result.output


def test_user_super_agent_name_derives_from_thread_name(monkeypatch):
    voice_route = importlib.import_module("openbase_coder_cli.livekit_voice_route")
    monkeypatch.setattr(
        voice_route,
        "SUPER_AGENT_VOICES",
        (
            voice_route.CartesiaVoice("voice-carl", "Carl"),
            voice_route.CartesiaVoice("voice-dottie", "Dottie"),
        ),
    )
    monkeypatch.setattr(
        voice_route, "SUPER_AGENT_VOICE_IDS", ("voice-carl", "voice-dottie")
    )

    result = CliRunner().invoke(main_cli.main, ["super-agent-name", "Build Thing"])

    assert result.exit_code == 0
    assert result.output.strip() in {"Carl", "Dottie"}
    assert (
        result.output.strip()
        == voice_route.super_agent_voice_for_context(
            "Build Thing",
            "Build Thing",
        ).name
    )


def test_user_super_agent_name_command_is_not_nested_under_user():
    result = CliRunner().invoke(user_cli.user, ["super-agent-name", "Build Thing"])

    assert result.exit_code != 0
    assert "No such command 'super-agent-name'" in result.output


def test_user_super_agent_name_json(monkeypatch):
    voice_route = importlib.import_module("openbase_coder_cli.livekit_voice_route")
    monkeypatch.setattr(
        voice_route,
        "SUPER_AGENT_VOICES",
        (voice_route.CartesiaVoice("voice-dottie", "Dottie"),),
    )
    monkeypatch.setattr(voice_route, "SUPER_AGENT_VOICE_IDS", ("voice-dottie",))

    result = CliRunner().invoke(
        main_cli.main,
        ["super-agent-name", "  Build   Thing  ", "--json"],
    )

    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "thread_name": "Build Thing",
        "agent_name": "Dottie",
        "voice_id": "voice-dottie",
        "voice_name": "Dottie",
    }


def test_user_say_reports_server_error(monkeypatch):
    def fake_request(method, url, **kwargs):
        assert method == "POST"
        return httpx.Response(
            404, json={"detail": "No active LiveKit voice room was found."}
        )

    patch_local_server_request(monkeypatch, fake_request)

    result = CliRunner().invoke(user_cli.user, ["say", "Dottie", "hello"])

    assert result.exit_code != 0
    assert "No active LiveKit voice room" in result.output


def test_resolve_sound_path_accepts_existing_path(tmp_path):
    audio_path = tmp_path / "done.wav"
    audio_path.write_bytes(b"audio")

    assert user_cli.resolve_sound_path(str(audio_path)) == audio_path


def test_resolve_sound_path_finds_named_sound_without_suffix(monkeypatch, tmp_path):
    sounds_dir = tmp_path / "sounds"
    sounds_dir.mkdir()
    audio_path = sounds_dir / "done.mp3"
    audio_path.write_bytes(b"audio")
    monkeypatch.setattr(user_cli, "OPENBASE_SOUNDS_DIR", sounds_dir)

    assert user_cli.resolve_sound_path("done") == audio_path


def test_resolve_sound_path_rejects_missing_named_sound(monkeypatch, tmp_path):
    sounds_dir = tmp_path / "sounds"
    sounds_dir.mkdir()
    monkeypatch.setattr(user_cli, "OPENBASE_SOUNDS_DIR", sounds_dir)

    result = CliRunner().invoke(user_cli.user, ["play", "missing"])

    assert result.exit_code != 0
    assert "Named sound not found" in result.output


def test_resolve_sound_path_rejects_named_path_traversal(monkeypatch, tmp_path):
    sounds_dir = tmp_path / "sounds"
    sounds_dir.mkdir()
    monkeypatch.setattr(user_cli, "OPENBASE_SOUNDS_DIR", sounds_dir)

    result = CliRunner().invoke(user_cli.user, ["play", "../done"])

    assert result.exit_code != 0
    assert "Audio file not found" in result.output


def test_user_play_posts_resolved_path_and_room(monkeypatch, tmp_path):
    calls = []
    audio_path = tmp_path / "done.wav"
    audio_path.write_bytes(b"audio")

    def fake_request(method, url, **kwargs):
        assert method == "POST"
        calls.append((url, kwargs["json"]))
        return httpx.Response(
            202,
            json={"message_id": "announcer-audio-1", "room_name": "room-explicit"},
        )

    patch_local_server_request(monkeypatch, fake_request)

    result = CliRunner().invoke(
        user_cli.user,
        ["play", "--room", "room-explicit", str(audio_path)],
    )

    assert result.exit_code == 0
    assert calls == [
        (
            "http://127.0.0.1:7999/api/user/play/",
            {"audio_path": str(audio_path), "room_name": "room-explicit"},
        )
    ]


def test_voice_route_reports_blocker(monkeypatch):
    def fake_request(method, url, **kwargs):
        assert method == "GET"
        return httpx.Response(
            200,
            json={
                "active_route": "dispatcher",
                "dispatcher_thread_id": "dispatcher-1",
                "instruction_override_supported": False,
                "blocked_reason": "blocked",
            },
        )

    patch_local_server_request(monkeypatch, fake_request)

    result = CliRunner().invoke(user_cli.user, ["voice-route"])

    assert result.exit_code == 0
    assert "Active route: dispatcher" in result.output
    assert "Target transfer blocked: blocked" in result.output


def test_transfer_to_thread_reports_blocker(monkeypatch):
    def fake_request(method, url, **kwargs):
        assert method == "POST"
        assert kwargs["json"] == {"thread_id": "thread-1"}
        return httpx.Response(409, json={"detail": "transfer blocked"})

    patch_local_server_request(monkeypatch, fake_request)

    result = CliRunner().invoke(user_cli.user, ["transfer-to-thread", "thread-1"])

    assert result.exit_code != 0
    assert "transfer blocked" in result.output


def test_transfer_to_agent_posts_agent_name(monkeypatch):
    calls = []

    def fake_request(method, url, **kwargs):
        assert method == "POST"
        calls.append((url, kwargs["json"]))
        return httpx.Response(
            202,
            json={
                "command_id": "route-1",
                "room_name": "room-1",
                "state": {"active_target_thread_id": "thread-1"},
            },
        )

    patch_local_server_request(monkeypatch, fake_request)

    result = CliRunner().invoke(user_cli.user, ["transfer-to-agent", "Build Agent"])

    assert result.exit_code == 0
    assert "thread-1" in result.output
    assert calls == [
        (
            "http://127.0.0.1:7999/api/livekit-voice-route/transfer/",
            {"agent_name": "Build Agent"},
        )
    ]


def test_exit_to_dispatch_posts_route_command(monkeypatch):
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs["json"]))
        return httpx.Response(
            202,
            json={"command_id": "route-1", "room_name": "room-1"},
        )

    patch_local_server_request(monkeypatch, fake_request)

    result = CliRunner().invoke(user_cli.user, ["exit-to-dispatch"])

    assert result.exit_code == 0
    assert "dispatcher" in result.output
    assert calls[0][0] == "POST"
    assert calls[0][2] == {}


def test_top_level_exit_to_dispatch_posts_route_command(monkeypatch):
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs["json"]))
        return httpx.Response(
            202,
            json={"command_id": "route-1", "room_name": "room-explicit"},
        )

    patch_local_server_request(monkeypatch, fake_request)

    result = CliRunner().invoke(
        main_cli.main,
        ["exit-to-dispatch", "--room", "room-explicit"],
    )

    assert result.exit_code == 0
    assert "room-explicit" in result.output
    assert calls == [
        (
            "POST",
            "http://127.0.0.1:7999/api/livekit-voice-route/exit/",
            {"room_name": "room-explicit"},
        )
    ]


def test_dispatcher_reasoning_sets_config_file(monkeypatch, tmp_path):
    config_path = tmp_path / "dispatcher-config.json"
    monkeypatch.setattr(dispatcher_config, "CODEX_DISPATCHER_CONFIG_PATH", config_path)

    result = CliRunner().invoke(user_cli.user, ["dispatcher-reasoning", "low"])

    assert result.exit_code == 0
    assert "set to low" in result.output
    assert (
        json.loads(config_path.read_text(encoding="utf-8"))[
            "dispatcher_reasoning_effort"
        ]
        == "low"
    )


def test_super_agents_reasoning_sets_config_file(monkeypatch, tmp_path):
    config_path = tmp_path / "dispatcher-config.json"
    monkeypatch.setattr(dispatcher_config, "CODEX_DISPATCHER_CONFIG_PATH", config_path)

    result = CliRunner().invoke(user_cli.user, ["super-agents-reasoning", "medium"])

    assert result.exit_code == 0
    assert "set to medium" in result.output
    assert (
        json.loads(config_path.read_text(encoding="utf-8"))[
            "super_agents_reasoning_effort"
        ]
        == "medium"
    )


def test_super_agents_model_sets_config_file(monkeypatch, tmp_path):
    config_path = tmp_path / "dispatcher-config.json"
    monkeypatch.setattr(dispatcher_config, "CODEX_DISPATCHER_CONFIG_PATH", config_path)

    result = CliRunner().invoke(user_cli.user, ["super-agents-model", "opus"])

    assert result.exit_code == 0
    assert "set to opus" in result.output
    assert (
        json.loads(config_path.read_text(encoding="utf-8"))["super_agents_model"]
        == "opus"
    )


def test_reasoning_config_ignores_legacy_shared_key(tmp_path):
    config_path = tmp_path / "dispatcher-config.json"
    config_path.write_text(json.dumps({"reasoning_effort": "low"}), encoding="utf-8")

    assert dispatcher_config.dispatcher_reasoning_effort(config_path) is None
    assert dispatcher_config.super_agents_reasoning_effort(config_path) is None


def test_dispatcher_reasoning_rejects_invalid_level():
    result = CliRunner().invoke(user_cli.user, ["operator-reasoning", "extreme"])

    assert result.exit_code != 0
    assert "Reasoning effort must be one of" in result.output
