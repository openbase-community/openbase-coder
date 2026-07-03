from __future__ import annotations

import importlib
import json
import os

from click.testing import CliRunner

from openbase_coder_cli.cli import main
from openbase_coder_cli.services.cloud_registration import CloudReportResult

onboarding_cli = importlib.import_module("openbase_coder_cli.cli.onboarding")
setup_cli = importlib.import_module("openbase_coder_cli.cli.setup")


def _fake_status_payload() -> dict:
    return {
        "cli_configured": True,
        "checks": {
            "installation_config": True,
            "env_file": True,
            "services_installed": False,
        },
        "authenticated": True,
        "tailscale_self": {
            "available": True,
            "tailscale_available": True,
            "dns_name": "mac.tailnet.ts.net",
            "node_hostname": "mac",
            "tailnet": "tailnet.ts.net",
            "ips": ["100.64.0.1"],
            "error": None,
        },
        "tailscale_serve": {
            "healthy": False,
            "openbase_url": "http://mac.tailnet.ts.net:18080",
            "error": "not reachable",
        },
        "cloud": {},
    }


def test_onboarding_status_json(monkeypatch) -> None:
    monkeypatch.setattr(
        onboarding_cli, "onboarding_status_payload", _fake_status_payload
    )

    result = CliRunner().invoke(main, ["onboarding", "status", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload == _fake_status_payload()


def test_onboarding_status_human_readable(monkeypatch) -> None:
    monkeypatch.setattr(
        onboarding_cli, "onboarding_status_payload", _fake_status_payload
    )

    result = CliRunner().invoke(main, ["onboarding", "status"])

    assert result.exit_code == 0
    assert "cli_configured" in result.output
    assert "services_installed" in result.output
    assert "mac.tailnet.ts.net" in result.output
    assert "not reachable" in result.output


def test_onboarding_report_success(monkeypatch) -> None:
    monkeypatch.setattr(
        onboarding_cli,
        "register_and_report",
        lambda: CloudReportResult(ok=True, supported=True, status_code=200),
    )

    result = CliRunner().invoke(main, ["onboarding", "report"])

    assert result.exit_code == 0
    assert "Registered device" in result.output


def test_onboarding_report_skips_when_unsupported(monkeypatch) -> None:
    monkeypatch.setattr(
        onboarding_cli,
        "register_and_report",
        lambda: CloudReportResult(
            ok=False, supported=False, error="not supported yet"
        ),
    )

    result = CliRunner().invoke(main, ["onboarding", "report"])

    assert result.exit_code == 0
    assert "Skipped" in result.output


def test_onboarding_report_fails_on_supported_error(monkeypatch) -> None:
    monkeypatch.setattr(
        onboarding_cli,
        "register_and_report",
        lambda: CloudReportResult(ok=False, supported=True, error="HTTP 500"),
    )

    result = CliRunner().invoke(main, ["onboarding", "report"])

    assert result.exit_code != 0
    assert "HTTP 500" in result.output


def test_setup_has_json_progress_option() -> None:
    result = CliRunner().invoke(main, ["setup", "--help"])

    assert result.exit_code == 0
    assert "--json-progress" in result.output


def test_setup_progress_emits_ndjson_events() -> None:
    read_fd, write_fd = os.pipe()
    progress = setup_cli._SetupProgress(False)
    progress.enabled = True
    progress._fd = write_fd

    progress.step("workspace", "start")
    progress.step("workspace", "ok")
    progress.step("tailscale_serve", "warn", "tailscale missing")
    progress.result(cli_configured=True, tailscale_serve_healthy=False)
    os.close(write_fd)

    with os.fdopen(read_fd, "r", encoding="utf-8") as reader:
        events = [json.loads(line) for line in reader.read().splitlines()]

    assert events[0] == {
        "event": "step",
        "id": "workspace",
        "status": "start",
        "detail": None,
    }
    assert events[1]["status"] == "ok"
    assert events[2] == {
        "event": "step",
        "id": "tailscale_serve",
        "status": "warn",
        "detail": "tailscale missing",
    }
    assert events[3] == {
        "event": "result",
        "ok": True,
        "cli_configured": True,
        "tailscale_serve_healthy": False,
    }


def test_setup_progress_abort_reports_current_step() -> None:
    read_fd, write_fd = os.pipe()
    progress = setup_cli._SetupProgress(False)
    progress.enabled = True
    progress._fd = write_fd

    progress.step("services", "start")
    progress.abort("boom")
    os.close(write_fd)

    with os.fdopen(read_fd, "r", encoding="utf-8") as reader:
        events = [json.loads(line) for line in reader.read().splitlines()]

    assert events[1] == {
        "event": "step",
        "id": "services",
        "status": "error",
        "detail": "boom",
    }
    assert events[2]["event"] == "result"
    assert events[2]["ok"] is False


def test_setup_progress_disabled_is_noop() -> None:
    progress = setup_cli._SetupProgress(False)
    progress.step("workspace", "start")
    progress.result(cli_configured=True, tailscale_serve_healthy=True)
    progress.abort("boom")


def test_setup_result_uses_computed_cli_state(monkeypatch, capfd) -> None:
    monkeypatch.setattr(setup_cli.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(setup_cli, "_run_setup_phases", lambda *args, **kwargs: True)
    monkeypatch.setattr(setup_cli, "compute_cli_configured", lambda: False)

    result = CliRunner().invoke(
        main,
        ["setup", "--json-progress", "--skip-clone", "--skip-services"],
    )

    assert result.exit_code == 0
    events = [
        json.loads(line)
        for line in capfd.readouterr().out.splitlines()
        if line.strip()
    ]
    assert events[-1] == {
        "event": "result",
        "ok": True,
        "cli_configured": False,
        "tailscale_serve_healthy": True,
    }
