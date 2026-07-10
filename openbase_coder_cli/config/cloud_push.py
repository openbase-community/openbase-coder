"""Openbase Cloud push delivery client for agent → user notifications/calls.

Sends alert notifications and PushKit VoIP calls to the signed-in user's phone
via the cloud ``/api/openbase/push/send/`` endpoint. Mirrors the auth and error
handling of ``cloud_audio.py``.

CODER_DESTINATIONS mirrors the iOS ``CoderDestination`` enum
(ios/Openbase/CoderDestination.swift), which is the source of truth for the
deep-link vocabulary. Keep it in sync with the cloud ``PUSH_DESTINATIONS`` set
and the iOS enum.
"""

from __future__ import annotations

import httpx

from openbase_coder_cli.config.token_manager import (
    DEFAULT_WEB_BACKEND_URL,
    AuthLoginRequiredError,
    AuthTransientError,
    get_token_manager,
)

CODER_DESTINATIONS = (
    "call",
    "dispatch",
    "threads",
    "sync_conflicts",
    "approvals",
    "reports",
    "diff",
    "account",
    "voice_test",
)


class PushError(RuntimeError):
    """A push notification or call could not be delivered."""


def send_notification(
    *,
    body: str,
    title: str = "Openbase Coder",
    destination: str = "dispatch",
    params: dict[str, str] | None = None,
    thread_id: str = "",
    report_id: str = "",
    device_id: str = "",
    web_backend_url: str = DEFAULT_WEB_BACKEND_URL,
) -> dict:
    """Send a deep-linked alert notification to the user's iPhone."""
    payload: dict[str, object] = {
        "type": "notification",
        "body": body,
        "title": title,
        "openbase_destination": destination,
    }
    if params:
        payload["params"] = params
    if thread_id:
        payload["thread_id"] = thread_id
    if report_id:
        payload["report_id"] = report_id
    if device_id:
        payload["device_id"] = device_id
    return _push_send(payload, web_backend_url.rstrip("/"))


def place_call(
    *,
    room_name: str = "",
    caller_name: str = "Openbase Coder",
    caller_identity: str = "",
    livekit_dispatch_agent_name: str = "",
    params: dict[str, str] | None = None,
    web_backend_url: str = DEFAULT_WEB_BACKEND_URL,
) -> dict:
    """Ring the user's iPhone via a PushKit VoIP call into ``room_name``."""
    payload: dict[str, object] = {
        "type": "call",
        "caller_name": caller_name,
        "openbase_destination": "call",
    }
    if room_name:
        payload["room_name"] = room_name
    if caller_identity:
        payload["caller_identity"] = caller_identity
    if livekit_dispatch_agent_name:
        payload["livekit_dispatch_agent_name"] = livekit_dispatch_agent_name
    if params:
        payload["params"] = params
    return _push_send(payload, web_backend_url.rstrip("/"))


def _push_send(payload: dict[str, object], web_backend_url: str) -> dict:
    token_manager = get_token_manager(web_backend_url)
    token = token_manager.get_access_token()

    try:
        response = httpx.post(
            f"{web_backend_url}/api/openbase/push/send/",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
            json=payload,
            timeout=15,
        )
    except httpx.HTTPError as exc:
        raise AuthTransientError(f"Push send failed: {exc}") from exc

    if response.status_code == 401:
        raise AuthLoginRequiredError(
            "Openbase Cloud rejected the current login while sending a push."
        )
    if response.status_code == 404:
        raise PushError(
            "No registered iPhone to receive the push. Open the Openbase app on "
            "your phone at least once to register it."
        )
    if response.status_code == 503:
        raise PushError(_response_detail(response))
    if response.status_code >= 500:
        raise AuthTransientError(
            f"Push send failed with backend status {response.status_code}."
        )
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise PushError(
            f"Push send failed with backend status {response.status_code}: "
            f"{_response_detail(response)}"
        ) from exc

    payload_out = response.json()
    if not isinstance(payload_out, dict):
        raise AuthTransientError("Push send returned an invalid payload.")
    return payload_out


def _response_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:300].strip() or response.reason_phrase
    if isinstance(payload, dict):
        detail = payload.get("detail") or payload.get("error")
        if detail:
            return str(detail)
    return str(payload)[:300]
