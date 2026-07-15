from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("OPENBASE_CODER_CLI_SECRET_KEY", "test-secret")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "openbase_coder_cli.config.settings")

import django  # noqa: E402
from rest_framework.test import APIRequestFactory, force_authenticate  # noqa: E402

django.setup()

from openbase_coder_cli.openbase_coder_cli_app import views  # noqa: E402
from openbase_coder_cli.services import onboarding  # noqa: E402


def _fake_status_payload() -> dict:
    return {
        "cli_configured": True,
        "checks": {
            "installation_config": True,
            "env_file": True,
            "services_installed": True,
        },
        "authenticated": True,
        "backend_auth": {"backend": "claude_code", "ready": True},
        "tailscale_self": {"available": True},
        "tailscale_serve": {"healthy": True},
        "cloud": {},
    }


def test_onboarding_status_returns_payload(monkeypatch) -> None:
    from openbase_coder_cli.openbase_coder_cli_app import (
        onboarding as onboarding_views,
    )

    monkeypatch.setattr(
        onboarding_views, "onboarding_status_payload", _fake_status_payload
    )

    request = APIRequestFactory().get("/api/onboarding/status/")
    force_authenticate(request, user=SimpleNamespace(is_authenticated=True))
    response = views.onboarding_status(request)

    assert response.status_code == 200
    assert response.data == _fake_status_payload()


def test_onboarding_status_payload_composes_checks(monkeypatch, tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("KEY=value\n", encoding="utf-8")

    monkeypatch.setattr(onboarding.InstallationConfig, "exists", classmethod(lambda cls: True))
    monkeypatch.setattr(
        onboarding.InstallationConfig,
        "load",
        classmethod(lambda cls: SimpleNamespace(env_file=str(env_file))),
    )
    monkeypatch.setattr(
        onboarding, "configured_default_services", lambda: [SimpleNamespace(name="svc")]
    )
    monkeypatch.setattr(onboarding, "launchctl_status", lambda svc: {"installed": True})
    monkeypatch.setattr(
        onboarding,
        "tailscale_self_identity",
        lambda: {"available": True, "dns_name": "mac.tailnet.ts.net"},
    )
    monkeypatch.setattr(
        onboarding,
        "tailscale_serve_health",
        lambda: SimpleNamespace(to_dict=lambda: {"healthy": True}),
    )
    monkeypatch.setattr(
        onboarding.TokenManager,
        "has_refresh_token",
        property(lambda self: True),
    )
    monkeypatch.setattr(
        onboarding, "read_onboarding_cache", lambda: {"last_register": {"ok": True}}
    )
    monkeypatch.setattr(
        onboarding,
        "backend_auth_status",
        lambda *, authenticated: {"backend": "codex", "ready": authenticated},
    )

    payload = onboarding.onboarding_status_payload()

    assert payload["cli_configured"] is True
    assert payload["checks"] == {
        "installation_config": True,
        "env_file": True,
        "services_installed": True,
    }
    assert payload["authenticated"] is True
    assert payload["backend_auth"] == {"backend": "codex", "ready": True}
    assert payload["tailscale_self"]["dns_name"] == "mac.tailnet.ts.net"
    assert payload["tailscale_serve"] == {"healthy": True}
    assert payload["cloud"] == {"last_register": {"ok": True}}


def test_cli_configured_false_when_installation_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        onboarding.InstallationConfig, "exists", classmethod(lambda cls: False)
    )

    checks = onboarding.cli_configured_checks()

    assert checks == {
        "installation_config": False,
        "env_file": False,
        "services_installed": False,
    }
    assert onboarding.compute_cli_configured() is False


def test_cli_configured_false_when_service_not_installed(
    monkeypatch, tmp_path
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("KEY=value\n", encoding="utf-8")

    monkeypatch.setattr(
        onboarding.InstallationConfig, "exists", classmethod(lambda cls: True)
    )
    monkeypatch.setattr(
        onboarding.InstallationConfig,
        "load",
        classmethod(lambda cls: SimpleNamespace(env_file=str(env_file))),
    )
    monkeypatch.setattr(
        onboarding, "configured_default_services", lambda: [SimpleNamespace(name="svc")]
    )
    monkeypatch.setattr(
        onboarding, "launchctl_status", lambda svc: {"installed": False}
    )

    checks = onboarding.cli_configured_checks()

    assert checks["installation_config"] is True
    assert checks["env_file"] is True
    assert checks["services_installed"] is False


def test_backend_auth_claude_code_uses_claude_auth_status(monkeypatch) -> None:
    monkeypatch.setattr(onboarding, "selected_coding_backend", lambda: "claude_code")
    monkeypatch.setattr(
        onboarding,
        "claude_auth_status",
        lambda: SimpleNamespace(logged_in=True),
    )

    assert onboarding.backend_auth_status() == {
        "backend": "claude_code",
        "ready": True,
    }


def test_backend_auth_codex_requires_service_auth_json(
    monkeypatch, tmp_path
) -> None:
    codex_home = tmp_path / "codex_home"
    monkeypatch.setattr(onboarding, "CODEX_HOME_DIR", codex_home)
    monkeypatch.setattr(onboarding, "selected_coding_backend", lambda: "codex")

    assert onboarding.backend_auth_status()["ready"] is False

    codex_home.mkdir(parents=True)
    (codex_home / "auth.json").write_text('{"tokens": {}}', encoding="utf-8")
    assert onboarding.backend_auth_status()["ready"] is True


def test_backend_auth_codex_ignores_empty_or_dangling_auth(
    monkeypatch, tmp_path
) -> None:
    codex_home = tmp_path / "codex_home"
    codex_home.mkdir(parents=True)
    monkeypatch.setattr(onboarding, "CODEX_HOME_DIR", codex_home)
    monkeypatch.setattr(onboarding, "selected_coding_backend", lambda: "codex")

    (codex_home / "auth.json").symlink_to(tmp_path / "missing-auth.json")
    assert onboarding.backend_auth_status()["ready"] is False

    (codex_home / "auth.json").unlink()
    (codex_home / "auth.json").write_text("{}", encoding="utf-8")
    assert onboarding.backend_auth_status()["ready"] is False


def test_backend_auth_openbase_cloud_follows_cli_login(monkeypatch) -> None:
    monkeypatch.setattr(
        onboarding, "selected_coding_backend", lambda: "openbase_cloud"
    )

    assert onboarding.backend_auth_status(authenticated=True) == {
        "backend": "openbase_cloud",
        "ready": True,
    }
    assert onboarding.backend_auth_status(authenticated=False)["ready"] is False


def test_selected_coding_backend_reads_installation_env_file(
    monkeypatch, tmp_path
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("OPENBASE_CODING_BACKEND=claude_code\n", encoding="utf-8")
    monkeypatch.setattr(
        onboarding.InstallationConfig, "exists", classmethod(lambda cls: True)
    )
    monkeypatch.setattr(
        onboarding.InstallationConfig,
        "load",
        classmethod(lambda cls: SimpleNamespace(env_file=str(env_file))),
    )

    assert onboarding.selected_coding_backend() == "claude_code"
