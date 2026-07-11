"""Client for openbase-tunneld, the embedded-tsnet daemon (tunneld/ in this repo).

When ``OPENBASE_TSNET=1``, the CLI talks to the daemon's loopback control API
instead of shelling out to the user-installed ``tailscale`` binary. The daemon
serves ``/status`` in the same JSON schema as ``tailscale status --json``, so
existing parsers work on its payload unchanged.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx

TUNNELD_LOCAL_API = os.environ.get("OPENBASE_TUNNELD_URL", "http://127.0.0.1:7998")
TUNNELD_TIMEOUT_SECONDS = 5
TUNNELD_PROBE_TIMEOUT_SECONDS = 8
TUNNELD_START_WAIT_SECONDS = 15


def _state_dir() -> Path:
    configured = os.environ.get("OPENBASE_TSNET_STATE_DIR")
    if configured:
        return Path(configured)
    return Path.home() / ".openbase" / "tsnet"


def _control_headers() -> dict[str, str]:
    """Bearer token minted by the daemon into <statedir>/control.token."""
    token = os.environ.get("OPENBASE_TUNNELD_TOKEN")
    if not token:
        try:
            token = (_state_dir() / "control.token").read_text().strip()
        except OSError:
            return {}
    return {"Authorization": f"Bearer {token}"}


def _packaged_binary() -> str | None:
    """The bundled daemon inside a standalone package, when running from one."""
    package_dir = os.environ.get("OPENBASE_CODER_PACKAGE_DIR")
    if not package_dir:
        return None
    candidate = Path(package_dir) / "bin" / "openbase-tunneld"
    return str(candidate) if os.access(candidate, os.X_OK) else None


def tsnet_enabled() -> bool:
    """Whether this install uses embedded Tailscale instead of the app.

    ``OPENBASE_TSNET`` is an explicit local override in either direction;
    otherwise the cloud's rollout decision (cached from device-registration
    responses) applies.
    """
    override = os.environ.get("OPENBASE_TSNET", "").strip().lower()
    if override in {"1", "true", "yes"}:
        return True
    if override in {"0", "false", "no"}:
        return False
    # Imported lazily: onboarding imports tailscale_serve, which imports us.
    from openbase_coder_cli.services.onboarding import read_onboarding_cache

    cloud_policy = read_onboarding_cache().get("cloud_policy")
    if isinstance(cloud_policy, dict):
        return bool(cloud_policy.get("embedded_tailscale"))
    return False


def voice_turn_info() -> dict[str, Any] | None:
    """TURN relay credentials for embedded-mode WebRTC media.

    The daemon mints them into ``<statedir>/turn.json`` and runs the relay on
    the tailnet; the phone forces its LiveKit media through it because an
    in-app tsnet node has no OS route for WebRTC's UDP sockets. Served only
    over loopback and the user's own tailnet.
    """
    import json

    try:
        raw = json.loads((_state_dir() / "turn.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict) or not raw.get("username") or not raw.get("password"):
        return None
    return {
        "username": raw["username"],
        "password": raw["password"],
        "port": raw.get("port", 3478),
        "realm": raw.get("realm", "openbase"),
    }


def tunneld_status() -> tuple[bool, dict[str, Any] | None, str | None]:
    """Fetch node status from tunneld.

    Returns ``(tunneld_available, status_payload, error)`` with the same
    contract as ``_tailscale_status_payload`` in ``tailnet_devices``;
    ``status_payload`` matches the ``tailscale status --json`` schema.
    """
    try:
        response = httpx.get(
            f"{TUNNELD_LOCAL_API}/status",
            headers=_control_headers(),
            timeout=TUNNELD_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        return False, None, f"openbase-tunneld is not reachable at {TUNNELD_LOCAL_API}: {exc}"

    try:
        payload = response.json()
    except ValueError as exc:
        return True, None, f"Unable to parse tunneld status JSON: {exc}"

    if response.status_code != 200:
        return True, None, str(payload.get("error") or f"HTTP {response.status_code} from tunneld")
    return True, payload, None


def tunneld_health() -> dict[str, Any]:
    try:
        response = httpx.get(
            f"{TUNNELD_LOCAL_API}/health",
            headers=_control_headers(),
            timeout=TUNNELD_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        return {"reachable": False, "error": str(exc)}
    if response.status_code == 401:
        # The daemon is up but our token is stale/missing; do not treat this
        # as unreachable or a caller may spawn a duplicate daemon.
        return {
            "reachable": True,
            "error": "control token rejected (check <statedir>/control.token)",
        }
    try:
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        return {"reachable": False, "error": str(exc)}
    payload["reachable"] = True
    return payload


def tunneld_probe(host: str, port: int = 18080, path: str = "/api/health/") -> dict[str, Any]:
    """Dial a tailnet peer through the embedded node (host network can't)."""
    try:
        response = httpx.get(
            f"{TUNNELD_LOCAL_API}/probe",
            params={"host": host, "port": str(port), "path": path},
            headers=_control_headers(),
            timeout=TUNNELD_PROBE_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        return {"ok": False, "error": f"tunneld probe failed: {exc}"}


REAUTH_MIN_INTERVAL_SECONDS = 600
_last_reauth_attempt = 0.0


def try_tunneld_reauth() -> bool:
    """Mint a fresh cloud key and log the daemon back in (throttled).

    Tailnet node keys eventually expire; health polls call this so an
    expired daemon self-heals instead of requiring a re-setup.
    """
    global _last_reauth_attempt
    now = time.monotonic()
    if now - _last_reauth_attempt < REAUTH_MIN_INTERVAL_SECONDS:
        return False
    _last_reauth_attempt = now
    # Imported lazily: cloud_registration imports tailscale_serve -> us.
    from openbase_coder_cli.services.cloud_registration import (
        mint_tailscale_auth_key,
    )

    auth_key = mint_tailscale_auth_key()
    if not auth_key:
        return False
    return tunneld_login(auth_key)


def tunneld_login(auth_key: str) -> bool:
    """Log the running daemon into the tailnet with an auth key."""
    try:
        response = httpx.post(
            f"{TUNNELD_LOCAL_API}/login",
            json={"auth_key": auth_key},
            headers=_control_headers(),
            timeout=TUNNELD_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError:
        return False
    return response.status_code == 200


def ensure_tunneld_running(auth_key: str | None = None) -> None:
    """Start openbase-tunneld if needed and wait until it forwards traffic.

    ``auth_key`` (typically minted by openbase-cloud at login) is submitted to
    the daemon when it needs a tailnet login; without one, the daemon's
    interactive login URL is surfaced in the raised error.
    """
    health = tunneld_health()
    if not health.get("reachable"):
        binary = os.environ.get("OPENBASE_TUNNELD_BIN") or _packaged_binary() or shutil.which(
            "openbase-tunneld"
        )
        if not binary:
            raise RuntimeError(
                "openbase-tunneld is not running and no binary was found "
                "(set OPENBASE_TUNNELD_BIN or add openbase-tunneld to PATH)."
            )
        subprocess.Popen(
            [binary, "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    login_submitted = False
    deadline = time.monotonic() + TUNNELD_START_WAIT_SECONDS
    while True:
        health = tunneld_health()
        if health.get("backend_state") == "Running" and health.get("forwards_up"):
            return
        if health.get("backend_state") == "NeedsLogin":
            if auth_key and not login_submitted:
                login_submitted = tunneld_login(auth_key)
                if login_submitted:
                    # Key redemption takes a few seconds beyond normal startup.
                    deadline = max(
                        deadline,
                        time.monotonic() + TUNNELD_START_WAIT_SECONDS,
                    )
            elif not auth_key and health.get("auth_url"):
                raise RuntimeError(
                    "openbase-tunneld needs a Tailscale login: open "
                    f"{health['auth_url']} or restart it with an auth key (TS_AUTHKEY)."
                )
        if time.monotonic() >= deadline:
            raise RuntimeError(
                "openbase-tunneld did not reach Running state "
                f"(state: {health.get('backend_state') or health.get('error')})."
            )
        time.sleep(0.5)
