"""Tests for TokenManager locking, atomic persistence, and refresh handling."""

import json
import threading
from unittest import mock

import httpx
import pytest

from openbase_coder_cli.config import token_manager as tm_module
from openbase_coder_cli.config.token_manager import (
    AuthLoginRequiredError,
    AuthTransientError,
    TokenManager,
)


@pytest.fixture
def auth_path(tmp_path, monkeypatch):
    path = tmp_path / "auth.json"
    monkeypatch.setattr(tm_module, "AUTH_JSON_PATH", path)
    return path


@pytest.fixture
def manager(auth_path):
    return TokenManager("https://backend.example.com")


def write_auth(auth_path, access="at", refresh="rt", expires_at=0.0):
    auth_path.write_text(
        json.dumps(
            {
                "access_token": access,
                "refresh_token": refresh,
                "access_expires_at": expires_at,
            }
        )
    )


def refresh_response(status_code=200, access="at-new", refresh="rt-new"):
    payload = {"data": {"access_token": access, "refresh_token": refresh}}
    return httpx.Response(
        status_code,
        json=payload,
        request=httpx.Request("POST", "https://backend.example.com"),
    )


def test_valid_access_token_used_without_refresh(manager, auth_path, monkeypatch):
    write_auth(auth_path, access="cached", expires_at=9e12)
    with mock.patch.object(httpx, "post") as post:
        assert manager.get_access_token() == "cached"
        post.assert_not_called()


def test_refresh_rotates_and_persists(manager, auth_path):
    write_auth(auth_path, access="stale", expires_at=0)
    with mock.patch.object(httpx, "post", return_value=refresh_response()):
        assert manager.get_access_token() == "at-new"
    saved = json.loads(auth_path.read_text())
    assert saved["refresh_token"] == "rt-new"
    assert saved["access_token"] == "at-new"


def test_rejected_refresh_raises_login_required(manager, auth_path):
    write_auth(auth_path, access="stale", expires_at=0)
    with mock.patch.object(httpx, "post", return_value=refresh_response(400)):
        with pytest.raises(AuthLoginRequiredError):
            manager.get_access_token()
    # Tokens are not deleted; another process may have saved fresh ones.
    assert auth_path.is_file()


def test_network_error_raises_transient(manager, auth_path):
    write_auth(auth_path, access="stale", expires_at=0)
    with mock.patch.object(
        httpx, "post", side_effect=httpx.ConnectError("boom")
    ):
        with pytest.raises(AuthTransientError):
            manager.get_access_token()


def test_backend_5xx_raises_transient(manager, auth_path):
    write_auth(auth_path, access="stale", expires_at=0)
    with mock.patch.object(httpx, "post", return_value=refresh_response(503)):
        with pytest.raises(AuthTransientError):
            manager.get_access_token()


def test_missing_refresh_token_raises_login_required(manager, auth_path):
    write_auth(auth_path, access="", refresh="", expires_at=0)
    with pytest.raises(AuthLoginRequiredError):
        manager.get_access_token()


def test_torn_read_keeps_in_memory_tokens(manager, auth_path):
    write_auth(auth_path, access="good", refresh="rt", expires_at=9e12)
    manager.load()
    auth_path.write_text('{"access_token": "trunc')  # simulated torn write
    assert manager.get_access_token() == "good"


def test_concurrent_refresh_only_hits_backend_once(manager, auth_path):
    write_auth(auth_path, access="stale", expires_at=0)
    calls = []

    def fake_post(url, **kwargs):
        calls.append(kwargs["json"]["refresh_token"])
        return refresh_response(
            access=f"at-{len(calls)}", refresh=f"rt-{len(calls)}"
        )

    results = []
    with mock.patch.object(httpx, "post", side_effect=fake_post):
        threads = [
            threading.Thread(
                target=lambda: results.append(manager.get_access_token())
            )
            for _ in range(8)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

    # One thread refreshes; the rest reuse the freshly persisted token.
    assert len(calls) == 1
    assert set(results) == {"at-1"}
    assert json.loads(auth_path.read_text())["refresh_token"] == "rt-1"
