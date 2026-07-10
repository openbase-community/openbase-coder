from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace


def _setup_django():
    os.environ.setdefault("OPENBASE_CODER_CLI_SECRET_KEY", "test-secret")
    os.environ.setdefault(
        "DJANGO_SETTINGS_MODULE", "openbase_coder_cli.config.settings"
    )

    import django

    django.setup()


def _authenticated_request(method: str, path: str, payload: dict | None = None):
    from rest_framework.test import APIRequestFactory, force_authenticate

    factory = APIRequestFactory()
    request = getattr(factory, method.lower())(path, payload or {}, format="json")
    force_authenticate(request, user=SimpleNamespace(is_authenticated=True))
    return request


def _isolate(monkeypatch, tmp_path: Path) -> None:
    from openbase_coder_cli.services import console_settings

    monkeypatch.setattr(
        console_settings,
        "CONSOLE_SETTINGS_JSON_PATH",
        tmp_path / "console-settings.json",
    )
    monkeypatch.setenv(
        "SUPER_AGENTS_PERMISSION_GUARD_FILE",
        str(tmp_path / "permission-guard.json"),
    )


def test_lockdown_disabled_by_default(tmp_path: Path, monkeypatch) -> None:
    _isolate(monkeypatch, tmp_path)
    from openbase_coder_cli.services import lockdown
    from openbase_coder_cli.services.console_settings import get_locked_down_mode

    assert get_locked_down_mode() is False
    assert lockdown.lockdown_restricted() is False
    assert lockdown.sync_lockdown_guard(relock=True) is False


def test_enabled_lockdown_restricts_launches(tmp_path: Path, monkeypatch) -> None:
    _isolate(monkeypatch, tmp_path)
    from super_agents.permission_guard import apply_permission_guard

    from openbase_coder_cli.services import lockdown
    from openbase_coder_cli.services.console_settings import (
        set_lockdown_safe_phrase,
        set_locked_down_mode,
    )

    set_lockdown_safe_phrase("rumpelstiltskin dances")
    set_locked_down_mode(True)
    assert lockdown.sync_lockdown_guard(relock=True) is True
    assert lockdown.lockdown_restricted() is True

    guarded = apply_permission_guard(
        {"approvalPolicy": "never", "sandbox": "danger-full-access"}
    )
    assert guarded["approvalPolicy"] == "on-request"
    assert guarded["sandboxPolicy"] == "workspace-write"
    assert guarded["permissionMode"] == "default"


def test_safe_phrase_in_direct_transcript_unlocks(tmp_path: Path, monkeypatch) -> None:
    _isolate(monkeypatch, tmp_path)
    from super_agents.permission_guard import apply_permission_guard

    from openbase_coder_cli.services import lockdown
    from openbase_coder_cli.services.console_settings import (
        set_lockdown_safe_phrase,
        set_locked_down_mode,
    )

    set_lockdown_safe_phrase("rumpelstiltskin dances")
    set_locked_down_mode(True)
    lockdown.sync_lockdown_guard(relock=True)

    assert lockdown.record_direct_transcript("please just fix the bug") is False
    assert lockdown.lockdown_restricted() is True

    # Punctuation and casing from STT do not matter.
    assert (
        lockdown.record_direct_transcript("Okay — Rumpelstiltskin, dances! Go wild.")
        is True
    )
    assert lockdown.lockdown_restricted() is False
    passthrough = {"approvalPolicy": "never"}
    assert apply_permission_guard(passthrough) == passthrough

    # A new voice session re-arms the restriction.
    assert lockdown.sync_lockdown_guard(relock=True) is True
    assert lockdown.lockdown_restricted() is True


def test_unlock_needs_the_phrase_and_lock_enabled(tmp_path: Path, monkeypatch) -> None:
    _isolate(monkeypatch, tmp_path)
    from openbase_coder_cli.services import lockdown
    from openbase_coder_cli.services.console_settings import (
        set_lockdown_safe_phrase,
        set_locked_down_mode,
    )

    # Mode off: hearing the phrase does nothing.
    set_lockdown_safe_phrase("open sesame now")
    assert lockdown.record_direct_transcript("open sesame now") is False

    # Mode on but no phrase configured: never unlocks.
    set_locked_down_mode(True)
    lockdown.sync_lockdown_guard(relock=True)
    monkeypatch.setattr(lockdown, "get_lockdown_safe_phrase", lambda: "")
    assert lockdown.record_direct_transcript("open sesame now") is False
    assert lockdown.lockdown_restricted() is True


def test_disabling_lockdown_lifts_restriction(tmp_path: Path, monkeypatch) -> None:
    _isolate(monkeypatch, tmp_path)
    from openbase_coder_cli.services import lockdown
    from openbase_coder_cli.services.console_settings import (
        set_lockdown_safe_phrase,
        set_locked_down_mode,
    )

    set_lockdown_safe_phrase("open sesame now")
    set_locked_down_mode(True)
    lockdown.sync_lockdown_guard(relock=True)
    set_locked_down_mode(False)

    assert lockdown.sync_lockdown_guard() is False
    assert lockdown.lockdown_restricted() is False


def test_lockdown_settings_api_roundtrip(tmp_path: Path, monkeypatch) -> None:
    _setup_django()
    _isolate(monkeypatch, tmp_path)

    from openbase_coder_cli.openbase_coder_cli_app import services_views

    response = services_views.lockdown_settings(
        _authenticated_request("GET", "/api/settings/lockdown/")
    )
    assert response.status_code == 200
    assert response.data["locked_down_mode"] is False
    assert response.data["restricted"] is False

    # Enabling without a phrase is rejected.
    response = services_views.lockdown_settings(
        _authenticated_request(
            "PATCH", "/api/settings/lockdown/", {"locked_down_mode": True}
        )
    )
    assert response.status_code == 400

    response = services_views.lockdown_settings(
        _authenticated_request(
            "PATCH",
            "/api/settings/lockdown/",
            {"locked_down_mode": True, "lockdown_safe_phrase": "open sesame now"},
        )
    )
    assert response.status_code == 200
    assert response.data["locked_down_mode"] is True
    assert response.data["lockdown_safe_phrase"] == "open sesame now"
    assert response.data["restricted"] is True

    response = services_views.lockdown_settings(
        _authenticated_request(
            "PATCH", "/api/settings/lockdown/", {"locked_down_mode": False}
        )
    )
    assert response.status_code == 200
    assert response.data["locked_down_mode"] is False
    assert response.data["restricted"] is False


def test_lockdown_cli_enable_requires_phrase(tmp_path: Path, monkeypatch) -> None:
    _isolate(monkeypatch, tmp_path)
    from click.testing import CliRunner

    from openbase_coder_cli.cli.lockdown import lockdown as lockdown_cli
    from openbase_coder_cli.services import lockdown

    runner = CliRunner()
    result = runner.invoke(lockdown_cli, ["enable"])
    assert result.exit_code != 0
    assert "safe phrase" in result.output.lower()

    result = runner.invoke(lockdown_cli, ["enable", "--safe-phrase", "open sesame now"])
    assert result.exit_code == 0
    assert lockdown.lockdown_restricted() is True

    result = runner.invoke(lockdown_cli, ["status", "--json"])
    assert result.exit_code == 0
    assert '"locked_down_mode": true' in result.output

    result = runner.invoke(lockdown_cli, ["disable"])
    assert result.exit_code == 0
    assert lockdown.lockdown_restricted() is False


def test_voice_target_client_applies_guard(tmp_path: Path, monkeypatch) -> None:
    _isolate(monkeypatch, tmp_path)
    import asyncio

    from openbase_coder_cli.livekit_agent.super_agents_client import (
        SuperAgentsLiveKitClient,
    )
    from openbase_coder_cli.services.console_settings import (
        set_lockdown_safe_phrase,
        set_locked_down_mode,
    )
    from openbase_coder_cli.services.lockdown import sync_lockdown_guard

    set_lockdown_safe_phrase("open sesame now")
    set_locked_down_mode(True)
    sync_lockdown_guard(relock=True)

    class FakeBackend:
        def __init__(self) -> None:
            self.thread_inputs: list[dict] = []
            self.backend = "codex"

        async def start_thread(self, params: dict) -> dict:
            self.thread_inputs.append(params)
            return {"threadId": "thread-1"}

    backend = FakeBackend()
    client = SuperAgentsLiveKitClient(
        cwd=str(tmp_path),
        state_path=None,
        persist_thread=False,
        super_agent_name="worker",
        backend_client=backend,
        enforce_lockdown=True,
    )
    asyncio.run(client._start_thread())

    params = backend.thread_inputs[0]
    assert params["approvalPolicy"] == "on-request"
    assert params["sandboxPolicy"] == "workspace-write"
    assert params["permissionMode"] == "default"
    assert "sandbox" not in params

    # The dispatcher client (no enforcement) keeps its bypass defaults.
    dispatcher_backend = FakeBackend()
    dispatcher = SuperAgentsLiveKitClient(
        cwd=str(tmp_path),
        state_path=None,
        persist_thread=False,
        backend_client=dispatcher_backend,
    )
    asyncio.run(dispatcher._start_thread())
    dispatcher_params = dispatcher_backend.thread_inputs[0]
    assert dispatcher_params["approvalPolicy"] == "never"
    assert dispatcher_params["sandbox"] == "danger-full-access"
