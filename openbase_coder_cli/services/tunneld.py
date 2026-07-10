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
from typing import Any

import httpx

TUNNELD_LOCAL_API = os.environ.get("OPENBASE_TUNNELD_URL", "http://127.0.0.1:7998")
TUNNELD_TIMEOUT_SECONDS = 5
TUNNELD_PROBE_TIMEOUT_SECONDS = 8
TUNNELD_START_WAIT_SECONDS = 15


def tsnet_enabled() -> bool:
    return os.environ.get("OPENBASE_TSNET", "").strip().lower() in {"1", "true", "yes"}


def tunneld_status() -> tuple[bool, dict[str, Any] | None, str | None]:
    """Fetch node status from tunneld.

    Returns ``(tunneld_available, status_payload, error)`` with the same
    contract as ``_tailscale_status_payload`` in ``tailnet_devices``;
    ``status_payload`` matches the ``tailscale status --json`` schema.
    """
    try:
        response = httpx.get(f"{TUNNELD_LOCAL_API}/status", timeout=TUNNELD_TIMEOUT_SECONDS)
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
        response = httpx.get(f"{TUNNELD_LOCAL_API}/health", timeout=TUNNELD_TIMEOUT_SECONDS)
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
            timeout=TUNNELD_PROBE_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        return {"ok": False, "error": f"tunneld probe failed: {exc}"}


def ensure_tunneld_running() -> None:
    """Start openbase-tunneld if needed and wait until it forwards traffic."""
    health = tunneld_health()
    if not health.get("reachable"):
        binary = os.environ.get("OPENBASE_TUNNELD_BIN") or shutil.which("openbase-tunneld")
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

    deadline = time.monotonic() + TUNNELD_START_WAIT_SECONDS
    while True:
        health = tunneld_health()
        if health.get("backend_state") == "Running" and health.get("forwards_up"):
            return
        if health.get("backend_state") == "NeedsLogin" and health.get("auth_url"):
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
