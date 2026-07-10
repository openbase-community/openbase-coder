from __future__ import annotations

# ruff: noqa: E402, I001

import json
import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("OPENBASE_CODER_CLI_SECRET_KEY", "test-secret")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "openbase_coder_cli.config.settings")

import django
from rest_framework.test import APIRequestFactory, force_authenticate

django.setup()

from openbase_coder_cli import dispatcher_config
from openbase_coder_cli.openbase_coder_cli_app import voice_dispatch_settings
from openbase_coder_cli.vocalbridge import config as vocalbridge_config


def _authenticated_request(method: str, path: str, data: dict | None = None):
    factory = APIRequestFactory()
    request_factory = {
        "GET": factory.get,
        "PUT": factory.put,
    }[method]
    request = request_factory(path, data=data or {}, format="json")
    force_authenticate(request, user=SimpleNamespace(is_authenticated=True))
    return request


def _isolate_paths(monkeypatch, tmp_path: Path) -> tuple[Path, Path]:
    config_path = tmp_path / "dispatcher-config.json"
    env_file = tmp_path / ".env"
    monkeypatch.setattr(dispatcher_config, "CODEX_DISPATCHER_CONFIG_PATH", config_path)
    monkeypatch.setattr(voice_dispatch_settings, "DEFAULT_ENV_FILE_PATH", env_file)
    monkeypatch.setattr(vocalbridge_config, "DEFAULT_ENV_FILE_PATH", env_file)
    for env_key in (
        vocalbridge_config.VOCALBRIDGE_API_KEY_ENV,
        vocalbridge_config.VOCALBRIDGE_AGENT_ID_ENV,
        vocalbridge_config.VOCALBRIDGE_API_URL_ENV,
    ):
        monkeypatch.delenv(env_key, raising=False)
    return config_path, env_file


def test_voice_dispatch_settings_defaults_to_livekit(monkeypatch, tmp_path) -> None:
    _isolate_paths(monkeypatch, tmp_path)

    response = voice_dispatch_settings.voice_dispatch_settings(
        _authenticated_request("GET", "/api/settings/voice-dispatch/")
    )

    assert response.status_code == 200
    assert response.data["provider"] == "livekit"
    assert response.data["default_provider"] == "livekit"
    assert [option["id"] for option in response.data["providers"]] == [
        "livekit",
        "vocalbridge",
    ]
    assert response.data["vocalbridge"]["api_key_configured"] is False
    assert (
        response.data["vocalbridge"]["api_url"]
        == vocalbridge_config.DEFAULT_VOCALBRIDGE_API_URL
    )


def test_voice_dispatch_settings_requires_api_key_for_vocalbridge(
    monkeypatch, tmp_path
) -> None:
    _isolate_paths(monkeypatch, tmp_path)

    response = voice_dispatch_settings.voice_dispatch_settings(
        _authenticated_request(
            "PUT",
            "/api/settings/voice-dispatch/",
            {"provider": "vocalbridge"},
        )
    )

    assert response.status_code == 400
    assert "API key" in response.data["error"]
    assert dispatcher_config.voice_dispatch_provider() == "livekit"


def test_voice_dispatch_settings_saves_provider_and_credentials(
    monkeypatch, tmp_path
) -> None:
    config_path, env_file = _isolate_paths(monkeypatch, tmp_path)

    response = voice_dispatch_settings.voice_dispatch_settings(
        _authenticated_request(
            "PUT",
            "/api/settings/voice-dispatch/",
            {
                "provider": "vocalbridge",
                "vocalbridge_api_key": "vb_test_key",
                "vocalbridge_agent_id": "agent-123",
            },
        )
    )

    assert response.status_code == 200
    assert response.data["provider"] == "vocalbridge"
    assert response.data["changed"] is True
    assert response.data["vocalbridge"]["api_key_configured"] is True
    assert response.data["vocalbridge"]["agent_id"] == "agent-123"
    # The key itself is never echoed back.
    assert "vb_test_key" not in json.dumps(
        {key: value for key, value in response.data.items()}
    )

    payload = json.loads(config_path.read_text(encoding="utf-8"))
    assert payload["voice_dispatch_provider"] == "vocalbridge"
    env_text = env_file.read_text(encoding="utf-8")
    assert "VOCAL_BRIDGE_API_KEY=vb_test_key" in env_text
    assert "VOCAL_BRIDGE_AGENT_ID=agent-123" in env_text


def test_voice_dispatch_settings_switches_back_to_livekit(
    monkeypatch, tmp_path
) -> None:
    config_path, env_file = _isolate_paths(monkeypatch, tmp_path)
    env_file.write_text("VOCAL_BRIDGE_API_KEY=vb_test_key\n", encoding="utf-8")
    dispatcher_config.set_voice_dispatch_provider("vocalbridge", config_path)

    response = voice_dispatch_settings.voice_dispatch_settings(
        _authenticated_request(
            "PUT",
            "/api/settings/voice-dispatch/",
            {"provider": "livekit"},
        )
    )

    assert response.status_code == 200
    assert response.data["provider"] == "livekit"
    assert dispatcher_config.voice_dispatch_provider() == "livekit"
    # Credentials stay configured for the next switch back.
    assert response.data["vocalbridge"]["api_key_configured"] is True


def test_voice_dispatch_settings_rejects_unknown_provider(
    monkeypatch, tmp_path
) -> None:
    _isolate_paths(monkeypatch, tmp_path)

    response = voice_dispatch_settings.voice_dispatch_settings(
        _authenticated_request(
            "PUT",
            "/api/settings/voice-dispatch/",
            {"provider": "carrier-pigeon"},
        )
    )

    assert response.status_code == 400
