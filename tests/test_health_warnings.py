from __future__ import annotations

# ruff: noqa: E402, I001

import os
from dataclasses import dataclass

os.environ.setdefault("OPENBASE_CODER_CLI_SECRET_KEY", "test-secret")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "openbase_coder_cli.config.settings")

import django

django.setup()

from openbase_coder_cli.openbase_coder_cli_app import health_warnings as hw


@dataclass
class FakeService:
    name: str
    install_by_default: bool = True


def test_expected_service_not_running_warns(monkeypatch) -> None:
    services = [FakeService("django-cli"), FakeService("livekit-server")]
    statuses = {
        "django-cli": {"installed": True, "pid": 123},
        "livekit-server": {"installed": True, "pid": None, "last_exit_code": 1},
    }
    monkeypatch.setattr("openbase_coder_cli.services.definitions.SERVICES", services)
    monkeypatch.setattr(
        "openbase_coder_cli.services.launchd.launchctl_status",
        lambda svc: statuses[svc.name],
    )

    warnings = hw._service_warnings()

    ids = [w["id"] for w in warnings]
    assert ids == ["service-stopped:livekit-server"]
    assert warnings[0]["severity"] == "critical"


def test_conditional_service_expected_only_when_enabled(monkeypatch) -> None:
    services = [FakeService("code-sync", install_by_default=False)]
    monkeypatch.setattr("openbase_coder_cli.services.definitions.SERVICES", services)
    status = {"installed": False, "pid": None}
    monkeypatch.setattr(
        "openbase_coder_cli.services.launchd.launchctl_status", lambda svc: status
    )

    monkeypatch.setattr(hw, "_code_sync_expected", lambda: True)
    hw._CONDITIONAL_SERVICES["code-sync"] = lambda: True
    try:
        warnings = hw._service_warnings()
        assert [w["id"] for w in warnings] == ["service-missing:code-sync"]

        # Feature off + service installed -> unexpected-service warning.
        hw._CONDITIONAL_SERVICES["code-sync"] = lambda: False
        status.update({"installed": True, "pid": 5})
        warnings = hw._service_warnings()
        assert [w["id"] for w in warnings] == ["service-unexpected:code-sync"]

        # Feature off + not installed -> silence.
        status.update({"installed": False, "pid": None})
        assert hw._service_warnings() == []
    finally:
        hw._CONDITIONAL_SERVICES["code-sync"] = hw._code_sync_expected


def test_collect_skips_sync_checks_when_disabled(monkeypatch) -> None:
    monkeypatch.setattr(hw, "_service_warnings", lambda: [])
    monkeypatch.setattr(hw, "_code_sync_expected", lambda: False)
    called = []
    monkeypatch.setattr(hw, "_sync_warnings", lambda: called.append(1) or [])

    assert hw.collect_warnings() == []
    assert called == []
