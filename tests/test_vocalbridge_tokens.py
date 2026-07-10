from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from openbase_coder_cli.vocalbridge import config as vocalbridge_config
from openbase_coder_cli.vocalbridge import tokens as vocalbridge_tokens
from openbase_coder_cli.vocalbridge.config import (
    VocalBridgeCredentials,
    VocalBridgeNotConfiguredError,
    vocalbridge_credentials,
)


def test_vocalbridge_credentials_require_api_key(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(vocalbridge_config, "DEFAULT_ENV_FILE_PATH", tmp_path / ".env")
    monkeypatch.delenv(vocalbridge_config.VOCALBRIDGE_API_KEY_ENV, raising=False)

    with pytest.raises(VocalBridgeNotConfiguredError):
        vocalbridge_credentials()


def test_vocalbridge_credentials_read_env_file(monkeypatch, tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "VOCAL_BRIDGE_API_KEY=vb_from_file\n"
        "VOCAL_BRIDGE_AGENT_ID=agent-9\n"
        "VOCAL_BRIDGE_API_URL=https://example.test/\n",
        encoding="utf-8",
    )
    for env_key in (
        vocalbridge_config.VOCALBRIDGE_API_KEY_ENV,
        vocalbridge_config.VOCALBRIDGE_AGENT_ID_ENV,
        vocalbridge_config.VOCALBRIDGE_API_URL_ENV,
    ):
        monkeypatch.delenv(env_key, raising=False)

    credentials = vocalbridge_credentials(env_file)

    assert credentials.api_key == "vb_from_file"
    assert credentials.agent_id == "agent-9"
    assert credentials.api_url == "https://example.test"


def test_mint_vocalbridge_token_sends_headers_and_session(monkeypatch) -> None:
    captured: dict = {}

    def fake_post(url, *, headers, json, timeout):
        captured.update({"url": url, "headers": headers, "json": json})
        request = httpx.Request("POST", url)
        return httpx.Response(
            200,
            request=request,
            json={
                "livekit_url": "wss://agent.livekit.cloud",
                "token": "jwt-token",
                "room_name": "room-1",
            },
        )

    monkeypatch.setattr(vocalbridge_tokens.httpx, "post", fake_post)

    payload = vocalbridge_tokens.mint_vocalbridge_token(
        participant_name="Gabe",
        session_id="session-1",
        credentials=VocalBridgeCredentials(
            api_key="vb_key",
            agent_id="agent-1",
            api_url="https://vocalbridgeai.com",
        ),
    )

    assert payload["token"] == "jwt-token"
    assert captured["url"] == "https://vocalbridgeai.com/api/v1/token"
    assert captured["headers"]["X-API-Key"] == "vb_key"
    assert captured["headers"]["X-Agent-Id"] == "agent-1"
    assert captured["json"] == {
        "participant_name": "Gabe",
        "session_id": "session-1",
    }


def test_mint_vocalbridge_token_wraps_http_errors(monkeypatch) -> None:
    def fake_post(url, **_kwargs):
        request = httpx.Request("POST", url)
        return httpx.Response(403, request=request, text="revoked")

    monkeypatch.setattr(vocalbridge_tokens.httpx, "post", fake_post)

    with pytest.raises(vocalbridge_tokens.VocalBridgeTokenError) as excinfo:
        vocalbridge_tokens.mint_vocalbridge_token(
            participant_name="Gabe",
            credentials=VocalBridgeCredentials(
                api_key="vb_key", agent_id=None, api_url="https://vocalbridgeai.com"
            ),
        )

    assert excinfo.value.status_code == 403
