"""Tests for the team activity reporter and local proxy."""

from __future__ import annotations

import importlib
import json
import subprocess

import httpx
import pytest
from click.testing import CliRunner

from openbase_coder_cli.services import team_activity as svc

cmd_module = importlib.import_module("openbase_coder_cli.cli.team_activity")
team_activity = cmd_module.team_activity


@pytest.fixture(autouse=True)
def _no_disable(monkeypatch):
    monkeypatch.delenv(svc.DISABLED_ENV, raising=False)


def test_changed_file_paths_parses_porcelain(monkeypatch):
    output = " M cli/auth.py\n?? tests/new_test.py\nR  old.py -> pkg/new.py\n"

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args, 0, stdout=output, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    paths = svc.changed_file_paths("/tmp/repo")
    assert paths == ["cli/auth.py", "tests/new_test.py", "pkg/new.py"]


def test_snapshot_is_paths_only(monkeypatch, tmp_path):
    monkeypatch.setattr(
        svc, "get_recent_projects", lambda: [{"path": "/work/openbase-cli"}]
    )
    monkeypatch.setattr(
        svc, "changed_file_paths", lambda directory: ["a.py", "sub/b.py"]
    )
    monkeypatch.setattr(
        svc,
        "_active_threads",
        lambda: [
            {
                "thread_id": "t1",
                "name": "fix-login",
                "agent_name": "coding",
                "status": "running",
                "directory": "/work/openbase-cli/sub",
            }
        ],
    )
    monkeypatch.setattr(svc, "_device_id", lambda: "desktop-test")

    payload = svc.collect_activity_snapshot()

    assert payload["repos"] == [
        {"name": "openbase-cli", "changed_files": ["a.py", "sub/b.py"]}
    ]
    assert payload["threads"] == [
        {
            "thread_id": "t1",
            "name": "fix-login",
            "agent_name": "coding",
            "status": "running",
            "repo": "openbase-cli",
        }
    ]
    serialized = json.dumps(payload)
    assert "/work/openbase-cli" not in serialized  # no absolute paths
    assert "diff" not in serialized


def test_report_disabled_skips_post(monkeypatch):
    monkeypatch.setenv(svc.DISABLED_ENV, "1")

    def boom(*args, **kwargs):  # pragma: no cover - must not be called
        raise AssertionError("should not collect when disabled")

    monkeypatch.setattr(svc, "collect_activity_snapshot", boom)
    result = svc.report_team_activity_once()
    assert result.ok is True
    assert "disabled" in result.detail


def test_report_unsupported_backend(monkeypatch):
    monkeypatch.setattr(
        svc,
        "collect_activity_snapshot",
        lambda: {"device_id": "d", "threads": [], "repos": []},
    )

    class FakeManager:
        def get_access_token(self):
            return "token"

    monkeypatch.setattr(svc, "get_token_manager", lambda: FakeManager())
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *a, **k: httpx.Response(404, request=httpx.Request("POST", "http://x")),
    )
    result = svc.report_team_activity_once()
    assert result.ok is False
    assert result.supported is False


def test_report_tolerates_local_server_down(monkeypatch):
    monkeypatch.setattr(svc, "get_recent_projects", lambda: [])

    def raise_click(*args, **kwargs):
        import click

        raise click.ClickException("server down")

    monkeypatch.setattr(
        "openbase_coder_cli.cli.local_server.local_server_request", raise_click
    )

    class FakeManager:
        def get_access_token(self):
            return "token"

    monkeypatch.setattr(svc, "get_token_manager", lambda: FakeManager())
    captured = {}

    def fake_post(url, json=None, **kwargs):
        captured["payload"] = json
        return httpx.Response(200, request=httpx.Request("POST", url), json={})

    monkeypatch.setattr(httpx, "post", fake_post)
    result = svc.report_team_activity_once()
    assert result.ok is True
    assert captured["payload"]["threads"] == []


def test_once_command_exits_zero_on_failure(monkeypatch):
    monkeypatch.setattr(
        cmd_module,
        "report_team_activity_once",
        lambda: svc.TeamActivityResult(ok=False, supported=False, detail="nope"),
    )
    result = CliRunner().invoke(team_activity, ["once"])
    assert result.exit_code == 0
    assert "WARN" in result.output


def test_fetch_team_activity_degrades(monkeypatch):
    class FakeManager:
        def get_access_token(self):
            return "token"

    monkeypatch.setattr(svc, "get_token_manager", lambda: FakeManager())
    monkeypatch.setattr(
        httpx,
        "get",
        lambda *a, **k: httpx.Response(404, request=httpx.Request("GET", "http://x")),
    )
    data = svc.fetch_team_activity()
    assert data["supported"] is False
