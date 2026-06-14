from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("OPENBASE_CODER_CLI_SECRET_KEY", "test-secret")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "openbase_coder_cli.config.settings")

import django  # noqa: E402
from rest_framework.test import APIRequestFactory, force_authenticate  # noqa: E402

django.setup()

from openbase_coder_cli import dispatcher_config  # noqa: E402
from openbase_coder_cli.openbase_coder_cli_app import views  # noqa: E402
from openbase_coder_cli.tts_providers import (  # noqa: E402
    KOKORO_PROVIDER_ID,
    TTSDownloadStatus,
    get_tts_provider,
)


def _authenticated_request(method: str, path: str, data: dict | None = None):
    factory = APIRequestFactory()
    request_factory = {
        "GET": factory.get,
        "PUT": factory.put,
        "POST": factory.post,
    }[method]
    request = request_factory(path, data=data or {}, format="json")
    force_authenticate(request, user=SimpleNamespace(is_authenticated=True))
    return request


def test_cartesia_voice_settings_returns_catalog_and_dispatcher_default(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "dispatcher-config.json"
    monkeypatch.setattr(dispatcher_config, "CODEX_DISPATCHER_CONFIG_PATH", config_path)
    monkeypatch.setattr(views, "dispatcher_voice", dispatcher_config.dispatcher_voice)

    response = views.cartesia_voice_settings(
        _authenticated_request("GET", "/api/settings/cartesia-voices/")
    )

    assert response.status_code == 200
    assert response.data["dispatcher_voice"] == {
        "id": "9626c31c-bec5-4cca-baa8-f8ba9e84c8bc",
        "name": "Jacqueline",
        "provider": "cartesia",
    }
    assert response.data["provider"] == "cartesia"
    assert {provider["id"] for provider in response.data["providers"]} == {
        "cartesia",
        "openbase_cloud",
        "kokoro",
    }
    assert response.data["voices"][0]["name"] == "Jacqueline"
    assert "kokoro" in response.data["voices_by_provider"]
    assert "openbase_cloud" in response.data["voices_by_provider"]
    assert len(response.data["voices_by_provider"]["kokoro"]) == 28
    assert all(
        voice["language"] == "en"
        for voice in response.data["voices_by_provider"]["kokoro"]
    )
    assert any(voice["name"] == "Thandi" for voice in response.data["voices"])


def test_dispatcher_voice_settings_persists_verified_name(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "dispatcher-config.json"
    monkeypatch.setattr(dispatcher_config, "CODEX_DISPATCHER_CONFIG_PATH", config_path)
    monkeypatch.setattr(
        views, "set_dispatcher_voice", dispatcher_config.set_dispatcher_voice
    )

    response = views.dispatcher_voice_settings(
        _authenticated_request(
            "PUT",
            "/api/settings/dispatcher-voice/",
            {"voice_id": "692846ad-1a6b-49b8-bfc5-86421fd41a19"},
        )
    )

    assert response.status_code == 200
    assert response.data["dispatcher_voice"] == {
        "id": "692846ad-1a6b-49b8-bfc5-86421fd41a19",
        "name": "Thandi",
        "provider": "cartesia",
    }
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    assert payload["tts_provider"] == "cartesia"
    assert payload["dispatcher_voice_id"] == "692846ad-1a6b-49b8-bfc5-86421fd41a19"
    assert payload["dispatcher_voice_name"] == "Thandi"


def test_dispatcher_voice_settings_rejects_unknown_voice() -> None:
    response = views.dispatcher_voice_settings(
        _authenticated_request(
            "PUT",
            "/api/settings/dispatcher-voice/",
            {"voice_id": "unknown-voice"},
        )
    )

    assert response.status_code == 400
    assert "catalog" in response.data["detail"]


def test_tts_settings_rejects_kokoro_before_download(
    monkeypatch, tmp_path: Path
) -> None:
    config_path = tmp_path / "dispatcher-config.json"
    monkeypatch.setattr(dispatcher_config, "CODEX_DISPATCHER_CONFIG_PATH", config_path)
    monkeypatch.setattr(
        views,
        "set_tts_provider_and_dispatcher_voice",
        dispatcher_config.set_tts_provider_and_dispatcher_voice,
    )
    monkeypatch.setattr(
        get_tts_provider(KOKORO_PROVIDER_ID),
        "readiness",
        lambda: SimpleNamespace(ready=False),
    )

    response = views.tts_settings(
        _authenticated_request(
            "PUT",
            "/api/settings/tts/",
            {"provider": "kokoro", "voice_id": "af_heart"},
        )
    )

    assert response.status_code == 400
    assert "Download Kokoro" in response.data["detail"]


def test_tts_settings_persists_kokoro_when_ready(monkeypatch, tmp_path: Path) -> None:
    config_path = tmp_path / "dispatcher-config.json"
    monkeypatch.setattr(dispatcher_config, "CODEX_DISPATCHER_CONFIG_PATH", config_path)
    monkeypatch.setattr(
        views,
        "set_tts_provider_and_dispatcher_voice",
        dispatcher_config.set_tts_provider_and_dispatcher_voice,
    )
    monkeypatch.setattr(
        get_tts_provider(KOKORO_PROVIDER_ID),
        "readiness",
        lambda: TTSDownloadStatus(
            provider=KOKORO_PROVIDER_ID,
            ready=True,
            required_files=30,
            cached_files=30,
        ),
    )

    response = views.tts_settings(
        _authenticated_request(
            "PUT",
            "/api/settings/tts/",
            {"provider": "kokoro", "voice_id": "af_heart"},
        )
    )

    assert response.status_code == 200
    assert response.data["provider"] == "kokoro"
    assert response.data["dispatcher_voice"] == {
        "id": "af_heart",
        "name": "Heart",
        "provider": "kokoro",
    }
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    assert payload["tts_provider"] == "kokoro"
    assert payload["dispatcher_voice_id"] == "af_heart"


def test_tts_settings_persists_openbase_cloud(monkeypatch, tmp_path: Path) -> None:
    config_path = tmp_path / "dispatcher-config.json"
    monkeypatch.setattr(dispatcher_config, "CODEX_DISPATCHER_CONFIG_PATH", config_path)
    monkeypatch.setattr(
        views,
        "set_tts_provider_and_dispatcher_voice",
        dispatcher_config.set_tts_provider_and_dispatcher_voice,
    )

    response = views.tts_settings(
        _authenticated_request(
            "PUT",
            "/api/settings/tts/",
            {
                "provider": "openbase_cloud",
                "voice_id": "9626c31c-bec5-4cca-baa8-f8ba9e84c8bc",
            },
        )
    )

    assert response.status_code == 200
    assert response.data["provider"] == "openbase_cloud"
    assert response.data["dispatcher_voice"] == {
        "id": "9626c31c-bec5-4cca-baa8-f8ba9e84c8bc",
        "name": "Jacqueline",
        "provider": "openbase_cloud",
    }
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    assert payload["tts_provider"] == "openbase_cloud"


def test_tts_settings_rejects_non_english_kokoro_voice(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "dispatcher-config.json"
    monkeypatch.setattr(dispatcher_config, "CODEX_DISPATCHER_CONFIG_PATH", config_path)
    monkeypatch.setattr(
        views,
        "set_tts_provider_and_dispatcher_voice",
        dispatcher_config.set_tts_provider_and_dispatcher_voice,
    )
    monkeypatch.setattr(
        get_tts_provider(KOKORO_PROVIDER_ID),
        "readiness",
        lambda: TTSDownloadStatus(
            provider=KOKORO_PROVIDER_ID,
            ready=True,
            required_files=30,
            cached_files=30,
        ),
    )

    response = views.tts_settings(
        _authenticated_request(
            "PUT",
            "/api/settings/tts/",
            {"provider": "kokoro", "voice_id": "jf_tebukuro"},
        )
    )

    assert response.status_code == 400
    assert "catalog" in response.data["detail"]


def test_stt_settings_returns_default_provider(monkeypatch, tmp_path: Path) -> None:
    config_path = tmp_path / "dispatcher-config.json"
    monkeypatch.delenv("LIVEKIT_STT_PROVIDER", raising=False)
    monkeypatch.setattr(dispatcher_config, "CODEX_DISPATCHER_CONFIG_PATH", config_path)
    monkeypatch.setattr(
        views._livekit,
        "local_mlx_whisper_readiness",
        lambda: SimpleNamespace(
            payload=lambda: {
                "provider": "local_mlx_whisper",
                "ready": False,
                "model": "mlx-community/whisper-small.en-mlx",
                "detail": "missing",
            }
        ),
    )

    response = views.stt_settings(_authenticated_request("GET", "/api/settings/stt/"))

    assert response.status_code == 200
    assert response.data["provider"] == "assemblyai"
    assert {provider["id"] for provider in response.data["providers"]} == {
        "assemblyai",
        "openbase_cloud",
        "deepgram",
        "local_mlx_whisper",
    }
    assert response.data["local_download"]["ready"] is False


def test_stt_settings_rejects_local_before_download(
    monkeypatch, tmp_path: Path
) -> None:
    config_path = tmp_path / "dispatcher-config.json"
    monkeypatch.setattr(dispatcher_config, "CODEX_DISPATCHER_CONFIG_PATH", config_path)
    monkeypatch.setattr(views, "set_stt_provider", dispatcher_config.set_stt_provider)
    monkeypatch.setattr(
        dispatcher_config,
        "local_mlx_whisper_readiness",
        lambda: SimpleNamespace(ready=False),
    )

    response = views.stt_settings(
        _authenticated_request(
            "PUT",
            "/api/settings/stt/",
            {"provider": "local_mlx_whisper"},
        )
    )

    assert response.status_code == 400
    assert "Download local MLX Whisper" in response.data["detail"]


def test_stt_settings_persists_local_when_ready(monkeypatch, tmp_path: Path) -> None:
    config_path = tmp_path / "dispatcher-config.json"
    monkeypatch.setattr(dispatcher_config, "CODEX_DISPATCHER_CONFIG_PATH", config_path)
    monkeypatch.setattr(views, "set_stt_provider", dispatcher_config.set_stt_provider)
    monkeypatch.setattr(
        dispatcher_config,
        "local_mlx_whisper_readiness",
        lambda: SimpleNamespace(ready=True),
    )
    monkeypatch.setattr(
        views._livekit,
        "local_mlx_whisper_readiness",
        lambda: SimpleNamespace(
            payload=lambda: {
                "provider": "local_mlx_whisper",
                "ready": True,
                "model": "mlx-community/whisper-small.en-mlx",
                "detail": None,
            }
        ),
    )

    response = views.stt_settings(
        _authenticated_request(
            "PUT",
            "/api/settings/stt/",
            {"provider": "local_mlx_whisper"},
        )
    )

    assert response.status_code == 200
    assert response.data["provider"] == "local_mlx_whisper"
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    assert payload["stt_provider"] == "local_mlx_whisper"


def test_stt_settings_persists_openbase_cloud(monkeypatch, tmp_path: Path) -> None:
    config_path = tmp_path / "dispatcher-config.json"
    monkeypatch.setattr(dispatcher_config, "CODEX_DISPATCHER_CONFIG_PATH", config_path)
    monkeypatch.setattr(views, "set_stt_provider", dispatcher_config.set_stt_provider)

    response = views.stt_settings(
        _authenticated_request(
            "PUT",
            "/api/settings/stt/",
            {"provider": "openbase_cloud"},
        )
    )

    assert response.status_code == 200
    assert response.data["provider"] == "openbase_cloud"
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    assert payload["stt_provider"] == "openbase_cloud"
