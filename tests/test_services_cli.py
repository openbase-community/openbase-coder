from __future__ import annotations

import importlib
from types import SimpleNamespace

from click.testing import CliRunner

services_cli = importlib.import_module("openbase_coder_cli.cli.services")


def test_services_status_fails_when_tailscale_serve_health_fails(monkeypatch):
    monkeypatch.setattr(services_cli, "require_installation", lambda: None)
    monkeypatch.setattr(
        services_cli,
        "SERVICES",
        [SimpleNamespace(name="django-cli")],
    )
    monkeypatch.setattr(
        services_cli,
        "launchctl_status",
        lambda _svc: {"installed": True, "pid": 1234},
    )
    monkeypatch.setattr(
        services_cli,
        "tailscale_serve_health",
        lambda: SimpleNamespace(
            healthy=False,
            tailscale_available=True,
            tailscale_running=True,
            host="mac.tailnet.ts.net",
            openbase_url="http://mac.tailnet.ts.net:18080",
            openbase_configured=True,
            livekit_configured=True,
            openbase_reachable=False,
            error="connection refused",
        ),
    )

    result = CliRunner().invoke(services_cli.services, ["status"])

    assert result.exit_code != 0
    assert "external-health     failed (connection refused)" in result.output
    assert "One or more Openbase services are unhealthy." in result.output
