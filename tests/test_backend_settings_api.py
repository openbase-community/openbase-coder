from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("OPENBASE_CODER_CLI_SECRET_KEY", "test-secret")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "openbase_coder_cli.config.settings")

import django  # noqa: E402
from rest_framework.test import APIRequestFactory, force_authenticate  # noqa: E402

django.setup()

from openbase_coder_cli.openbase_coder_cli_app import backend_settings  # noqa: E402


def _authenticated_request(method: str, path: str, data: dict | None = None):
    factory = APIRequestFactory()
    request_factory = {
        "GET": factory.get,
        "PUT": factory.put,
    }[method]
    request = request_factory(path, data=data or {}, format="json")
    force_authenticate(request, user=SimpleNamespace(is_authenticated=True))
    return request


def test_coding_backend_settings_defaults_when_env_file_missing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    env_file = tmp_path / ".env"
    monkeypatch.setattr(backend_settings, "DEFAULT_ENV_FILE_PATH", env_file)

    response = backend_settings.coding_backend_settings(
        _authenticated_request("GET", "/api/settings/coding-backend/")
    )

    assert response.status_code == 200
    assert response.data["backend"] == "codex"
    assert response.data["default_backend"] == "codex"
    assert response.data["env_file_exists"] is False
    assert response.data["restart_required"] is False
    assert [option["id"] for option in response.data["supported_backends"]] == [
        "codex",
        "claude-agent-sdk",
        "claude-tui",
    ]


def test_coding_backend_settings_persists_backend(
    monkeypatch,
    tmp_path: Path,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("KEEP_ME=1\nOPENBASE_CODEX_BACKEND=codex\n", encoding="utf-8")
    monkeypatch.setattr(backend_settings, "DEFAULT_ENV_FILE_PATH", env_file)

    response = backend_settings.coding_backend_settings(
        _authenticated_request(
            "PUT",
            "/api/settings/coding-backend/",
            {"backend": "claude-tui"},
        )
    )

    assert response.status_code == 200
    assert response.data["backend"] == "claude-tui"
    assert response.data["changed"] is True
    assert response.data["restart_required"] is True
    assert "dispatcher/MCP host" in response.data["restart_hint"]
    content = env_file.read_text(encoding="utf-8")
    assert "KEEP_ME=1" in content
    assert "OPENBASE_CODEX_BACKEND=codex" in content
    assert "OPENBASE_CODING_BACKEND=claude-tui" in content


def test_coding_backend_settings_reads_legacy_backend(
    monkeypatch,
    tmp_path: Path,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("OPENBASE_CODEX_BACKEND=claude-agent-sdk\n", encoding="utf-8")
    monkeypatch.setattr(backend_settings, "DEFAULT_ENV_FILE_PATH", env_file)

    response = backend_settings.coding_backend_settings(
        _authenticated_request("GET", "/api/settings/coding-backend/")
    )

    assert response.status_code == 200
    assert response.data["backend"] == "claude-agent-sdk"


def test_coding_backend_settings_rejects_unsupported_backend(
    monkeypatch,
    tmp_path: Path,
) -> None:
    env_file = tmp_path / ".env"
    monkeypatch.setattr(backend_settings, "DEFAULT_ENV_FILE_PATH", env_file)

    response = backend_settings.coding_backend_settings(
        _authenticated_request(
            "PUT",
            "/api/settings/coding-backend/",
            {"backend": "surprise"},
        )
    )

    assert response.status_code == 400
    assert "backend" in response.data
    assert not env_file.exists()
