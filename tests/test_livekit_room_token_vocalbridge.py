from __future__ import annotations

# ruff: noqa: E402, I001

import os
from types import SimpleNamespace

os.environ.setdefault("OPENBASE_CODER_CLI_SECRET_KEY", "test-secret")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "openbase_coder_cli.config.settings")

import django
from rest_framework.test import APIRequestFactory, force_authenticate

django.setup()

from openbase_coder_cli.openbase_coder_cli_app import livekit as app_livekit
from openbase_coder_cli.vocalbridge.config import (
    VocalBridgeCredentials,
    VocalBridgeNotConfiguredError,
)
from openbase_coder_cli.vocalbridge.tokens import VocalBridgeTokenError


def _jwt_authenticated_request(data: dict | None = None):
    factory = APIRequestFactory()
    request = factory.post("/api/livekit-room-token/", data=data or {}, format="json")
    user = SimpleNamespace(
        is_authenticated=True,
        email="gabe@example.com",
        pk=1,
        get_full_name=lambda: "Gabe",
    )
    force_authenticate(request, user=user, token={"email": "gabe@example.com"})
    return request


def _use_vocalbridge(monkeypatch) -> None:
    monkeypatch.setattr(app_livekit, "voice_dispatch_provider", lambda: "vocalbridge")
    monkeypatch.setattr(
        app_livekit,
        "vocalbridge_credentials",
        lambda: VocalBridgeCredentials(
            api_key="vb_key", agent_id=None, api_url="https://vocalbridgeai.com"
        ),
    )


def test_room_token_uses_vocalbridge_and_starts_responder(monkeypatch) -> None:
    _use_vocalbridge(monkeypatch)
    minted: list[str] = []
    responders: list[dict] = []

    def fake_mint(*, participant_name, session_id=None, credentials=None):
        minted.append(participant_name)
        return {
            "livekit_url": "wss://agent.livekit.cloud",
            "token": f"jwt-{participant_name}",
            "room_name": f"vb-room-{session_id}",
        }

    monkeypatch.setattr(app_livekit, "mint_vocalbridge_token", fake_mint)
    monkeypatch.setattr(
        app_livekit,
        "ensure_vocalbridge_responder",
        lambda **kwargs: responders.append(kwargs) or True,
    )

    response = app_livekit.livekit_room_token(
        _jwt_authenticated_request({"livekit_dispatch_agent_name": "livekit-agent"})
    )

    assert response.status_code == 200
    assert response.data["provider"] == "vocalbridge"
    assert response.data["token"] == "jwt-Gabe"
    assert response.data["url"] == "wss://agent.livekit.cloud"
    assert response.data["room_name"].startswith("vb-room-openbase-")
    assert minted == ["Gabe", "Openbase Coder"]
    assert len(responders) == 1
    assert responders[0]["room_name"] == response.data["room_name"]
    assert responders[0]["token"] == "jwt-Openbase Coder"


def test_room_token_reports_missing_vocalbridge_configuration(monkeypatch) -> None:
    monkeypatch.setattr(app_livekit, "voice_dispatch_provider", lambda: "vocalbridge")

    def raise_not_configured():
        raise VocalBridgeNotConfiguredError("Add a VocalBridge API key first.")

    monkeypatch.setattr(app_livekit, "vocalbridge_credentials", raise_not_configured)

    response = app_livekit.livekit_room_token(
        _jwt_authenticated_request({"livekit_dispatch_agent_name": "livekit-agent"})
    )

    assert response.status_code == 400
    assert response.data["code"] == "vocalbridge_not_configured"


def test_room_token_reports_vocalbridge_token_failure(monkeypatch) -> None:
    _use_vocalbridge(monkeypatch)

    def fail_mint(**_kwargs):
        raise VocalBridgeTokenError("boom", status_code=500)

    monkeypatch.setattr(app_livekit, "mint_vocalbridge_token", fail_mint)

    response = app_livekit.livekit_room_token(
        _jwt_authenticated_request({"livekit_dispatch_agent_name": "livekit-agent"})
    )

    assert response.status_code == 502
    assert response.data["code"] == "vocalbridge_token_failed"


def test_room_token_local_path_reports_livekit_provider(monkeypatch) -> None:
    monkeypatch.setattr(app_livekit, "voice_dispatch_provider", lambda: "livekit")
    monkeypatch.setattr(
        app_livekit,
        "_livekit_client_token_credentials",
        lambda: ("livekit-client-key", "livekit-client-secret"),
    )
    monkeypatch.setattr(
        app_livekit,
        "ensure_openbase_cloud_audio_subscription",
        lambda **_kwargs: None,
    )

    response = app_livekit.livekit_room_token(
        _jwt_authenticated_request({"livekit_dispatch_agent_name": "livekit-agent"})
    )

    assert response.status_code == 200
    assert response.data["provider"] == "livekit"
    assert "url" not in response.data
    assert response.data["token"]
