from __future__ import annotations

import importlib

import httpx
from click.testing import CliRunner

cloud_cli = importlib.import_module("openbase_coder_cli.cli.cloud")


class FakeTokenManager:
    def __init__(self, web_backend_url: str | None = None):
        self.web_backend_url = web_backend_url

    def load(self) -> None:
        pass

    def get_access_token(self) -> str:
        return "jwt.token.value"


def _patch_activity_response(monkeypatch, handler) -> None:
    def fake_get(url, **kwargs):
        return handler(url, **kwargs)

    monkeypatch.setattr(cloud_cli.httpx, "get", fake_get)


def test_agent_runs_active_true_when_runs_reported(monkeypatch):
    _patch_activity_response(
        monkeypatch,
        lambda url, **kwargs: httpx.Response(
            200, json={"active_run_count": 2, "thread_count": 5}
        ),
    )

    assert cloud_cli._agent_runs_active("http://127.0.0.1:7999", FakeTokenManager())


def test_agent_runs_active_false_when_no_runs(monkeypatch):
    _patch_activity_response(
        monkeypatch,
        lambda url, **kwargs: httpx.Response(
            200, json={"active_run_count": 0, "thread_count": 5}
        ),
    )

    assert not cloud_cli._agent_runs_active("http://127.0.0.1:7999", FakeTokenManager())


def test_agent_runs_active_false_when_server_unreachable(monkeypatch):
    def raise_connect_error(url, **kwargs):
        raise httpx.ConnectError("connection refused")

    _patch_activity_response(monkeypatch, raise_connect_error)

    assert not cloud_cli._agent_runs_active("http://127.0.0.1:7999", FakeTokenManager())


def test_agent_runs_active_false_on_error_status(monkeypatch):
    _patch_activity_response(
        monkeypatch,
        lambda url, **kwargs: httpx.Response(401, json={"detail": "unauthorized"}),
    )

    assert not cloud_cli._agent_runs_active("http://127.0.0.1:7999", FakeTokenManager())


def test_single_heartbeat_posts_run_activity(monkeypatch):
    posts = []

    def fake_post(url, **kwargs):
        posts.append((url, kwargs["json"]))
        return httpx.Response(200, json={"message": "Heartbeat recorded."})

    monkeypatch.setattr(cloud_cli, "TokenManager", FakeTokenManager)
    monkeypatch.setattr(cloud_cli, "_web_backend_url", lambda: "https://cloud.test")
    monkeypatch.setattr(
        cloud_cli, "_agent_runs_active", lambda local_url, manager: True
    )
    monkeypatch.setattr(cloud_cli.httpx, "post", fake_post)

    result = CliRunner().invoke(cloud_cli.cloud, ["heartbeat", "--interval", "0"])

    assert result.exit_code == 0
    assert posts == [
        ("https://cloud.test/api/openbase/devspaces/heartbeat/", {"active": True})
    ]


def test_single_heartbeat_reports_inactive_without_runs(monkeypatch):
    posts = []

    def fake_post(url, **kwargs):
        posts.append(kwargs["json"])
        return httpx.Response(200, json={"message": "Heartbeat recorded."})

    monkeypatch.setattr(cloud_cli, "TokenManager", FakeTokenManager)
    monkeypatch.setattr(cloud_cli, "_web_backend_url", lambda: "https://cloud.test")
    monkeypatch.setattr(
        cloud_cli, "_agent_runs_active", lambda local_url, manager: False
    )
    monkeypatch.setattr(cloud_cli.httpx, "post", fake_post)

    result = CliRunner().invoke(cloud_cli.cloud, ["heartbeat", "--interval", "0"])

    assert result.exit_code == 0
    assert posts == [{"active": False}]
