from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("OPENBASE_CODER_CLI_SECRET_KEY", "test-secret")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "openbase_coder_cli.config.settings")

import django  # noqa: E402
from rest_framework.test import APIRequestFactory, force_authenticate  # noqa: E402

django.setup()

from openbase_coder_cli.openbase_coder_cli_app import (  # noqa: E402
    ios_app_control as views,
)


class FakeChannelLayer:
    def __init__(self) -> None:
        self.sent: list[tuple[str, dict]] = []

    async def group_send(self, group: str, event: dict) -> None:
        self.sent.append((group, event))


def _request(payload: dict):
    request = APIRequestFactory().post(
        "/api/user/ios-app-control/",
        payload,
        format="json",
    )
    force_authenticate(request, user=SimpleNamespace(is_authenticated=True))
    return request


def test_ios_app_control_open_url_broadcasts(monkeypatch):
    channel_layer = FakeChannelLayer()
    monkeypatch.setattr(views, "get_channel_layer", lambda: channel_layer)

    response = views.ios_app_control(
        _request({"action": "open_url", "url": "openbase://threads/123"})
    )

    assert response.status_code == 202
    assert response.data["status"] == "published"
    assert channel_layer.sent[0][0] == "ios_app_control"
    assert channel_layer.sent[0][1]["type"] == "ios_app_control"
    assert channel_layer.sent[0][1]["data"]["action"] == "open_url"
    assert channel_layer.sent[0][1]["data"]["url"] == "openbase://threads/123"
    assert channel_layer.sent[0][1]["data"]["command_id"].startswith(
        "ios-app-control-"
    )


def test_ios_app_control_mute_broadcasts(monkeypatch):
    channel_layer = FakeChannelLayer()
    monkeypatch.setattr(views, "get_channel_layer", lambda: channel_layer)

    response = views.ios_app_control(
        _request({"action": "set_call_muted", "muted": True})
    )

    assert response.status_code == 202
    assert channel_layer.sent[0][1]["data"]["muted"] is True


def test_ios_app_control_start_livekit_voice_test_call_broadcasts(monkeypatch):
    channel_layer = FakeChannelLayer()
    monkeypatch.setattr(views, "get_channel_layer", lambda: channel_layer)

    response = views.ios_app_control(
        _request({"action": "start_livekit_voice_test_call"})
    )

    assert response.status_code == 202
    assert channel_layer.sent[0][1]["data"]["action"] == (
        "start_livekit_voice_test_call"
    )


def test_ios_app_control_start_developer_call_broadcasts(monkeypatch):
    channel_layer = FakeChannelLayer()
    monkeypatch.setattr(views, "get_channel_layer", lambda: channel_layer)

    response = views.ios_app_control(_request({"action": "start_developer_call"}))

    assert response.status_code == 202
    assert channel_layer.sent[0][1]["data"]["action"] == "start_developer_call"


def test_ios_app_control_upload_diagnostics_broadcasts(monkeypatch):
    channel_layer = FakeChannelLayer()
    monkeypatch.setattr(views, "get_channel_layer", lambda: channel_layer)

    response = views.ios_app_control(
        _request({"action": "upload_diagnostics", "limit": 500})
    )

    assert response.status_code == 202
    assert channel_layer.sent[0][1]["data"]["action"] == "upload_diagnostics"
    assert channel_layer.sent[0][1]["data"]["limit"] == 500


@pytest.mark.parametrize("url", ["example.com", "javascript:alert(1)", "file:///tmp/a"])
def test_ios_app_control_rejects_invalid_urls(url):
    response = views.ios_app_control(_request({"action": "open_url", "url": url}))

    assert response.status_code == 400


@pytest.mark.parametrize("limit", [0, 2001])
def test_ios_app_control_rejects_invalid_upload_diagnostics_limit(limit):
    response = views.ios_app_control(
        _request({"action": "upload_diagnostics", "limit": limit})
    )

    assert response.status_code == 400
