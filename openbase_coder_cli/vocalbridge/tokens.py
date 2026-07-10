"""Mint VocalBridge room tokens through the VocalBridge REST API."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from openbase_coder_cli.vocalbridge.config import (
    VocalBridgeCredentials,
    vocalbridge_credentials,
)

logger = logging.getLogger(__name__)

TOKEN_REQUEST_TIMEOUT_SECONDS = 15.0


class VocalBridgeTokenError(RuntimeError):
    """The VocalBridge token endpoint rejected or failed the request."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def mint_vocalbridge_token(
    *,
    participant_name: str,
    session_id: str | None = None,
    credentials: VocalBridgeCredentials | None = None,
) -> dict[str, Any]:
    """Request a LiveKit access token for the configured VocalBridge agent.

    Returns the VocalBridge response payload: ``livekit_url``, ``token``,
    ``room_name``, ``participant_identity``, ``expires_in``, ``agent_mode``.
    Passing the same ``session_id`` for multiple participants places them in
    the same room.
    """
    creds = credentials or vocalbridge_credentials()
    headers = {
        "X-API-Key": creds.api_key,
        "Content-Type": "application/json",
    }
    if creds.agent_id:
        headers["X-Agent-Id"] = creds.agent_id
    body: dict[str, Any] = {"participant_name": participant_name}
    if session_id:
        body["session_id"] = session_id

    try:
        response = httpx.post(
            f"{creds.api_url}/api/v1/token",
            headers=headers,
            json=body,
            timeout=TOKEN_REQUEST_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        raise VocalBridgeTokenError(
            f"Could not reach the VocalBridge token endpoint: {exc}"
        ) from exc

    if response.status_code >= 400:
        raise VocalBridgeTokenError(
            "The VocalBridge token endpoint returned "
            f"{response.status_code}: {response.text[:500]}",
            status_code=response.status_code,
        )

    payload = response.json()
    if not isinstance(payload, dict) or not payload.get("token"):
        raise VocalBridgeTokenError(
            "The VocalBridge token endpoint returned an unexpected payload."
        )
    return payload
