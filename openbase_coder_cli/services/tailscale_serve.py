from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any

import httpx

OPENBASE_CODER_TAILNET_PORT = 18080
OPENBASE_CODER_LOCAL_PORT = 7999
LIVEKIT_TAILNET_PORT = 7880
LIVEKIT_LOCAL_PORT = 7880
OPENBASE_HEALTH_PATH = "/api/health/"
TAILSCALE_TIMEOUT_SECONDS = 5
TAILSCALE_HEALTH_TIMEOUT_SECONDS = 2


@dataclass(frozen=True)
class TailscaleServeHealth:
    tailscale_available: bool
    tailscale_running: bool
    host: str | None
    openbase_url: str | None
    openbase_configured: bool
    livekit_configured: bool
    openbase_reachable: bool
    error: str | None = None

    @property
    def healthy(self) -> bool:
        return (
            self.tailscale_available
            and self.tailscale_running
            and self.openbase_configured
            and self.livekit_configured
            and self.openbase_reachable
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "tailscale_available": self.tailscale_available,
            "tailscale_running": self.tailscale_running,
            "host": self.host,
            "openbase_url": self.openbase_url,
            "openbase_configured": self.openbase_configured,
            "livekit_configured": self.livekit_configured,
            "openbase_reachable": self.openbase_reachable,
            "healthy": self.healthy,
            "error": self.error,
        }


def configure_tailscale_serve() -> None:
    tailscale_bin = _tailscale_bin()
    if not tailscale_bin:
        raise RuntimeError("tailscale was not found (checked PATH and /Applications/Tailscale.app).")

    _run_tailscale(
        tailscale_bin,
        "serve",
        "--bg",
        f"--http={OPENBASE_CODER_TAILNET_PORT}",
        f"http://127.0.0.1:{OPENBASE_CODER_LOCAL_PORT}",
    )
    _run_tailscale(
        tailscale_bin,
        "serve",
        "--bg",
        f"--tcp={LIVEKIT_TAILNET_PORT}",
        f"tcp://127.0.0.1:{LIVEKIT_LOCAL_PORT}",
    )


def tailscale_serve_health() -> TailscaleServeHealth:
    tailscale_bin = _tailscale_bin()
    if not tailscale_bin:
        return TailscaleServeHealth(
            tailscale_available=False,
            tailscale_running=False,
            host=None,
            openbase_url=None,
            openbase_configured=False,
            livekit_configured=False,
            openbase_reachable=False,
            error="tailscale was not found (checked PATH and /Applications/Tailscale.app).",
        )

    status = _tailscale_status(tailscale_bin)
    if status.get("error"):
        return TailscaleServeHealth(
            tailscale_available=True,
            tailscale_running=False,
            host=None,
            openbase_url=None,
            openbase_configured=False,
            livekit_configured=False,
            openbase_reachable=False,
            error=str(status["error"]),
        )

    host = _self_dns_name(status)
    serve_status = _tailscale_serve_status(tailscale_bin)
    if serve_status.get("error"):
        return TailscaleServeHealth(
            tailscale_available=True,
            tailscale_running=True,
            host=host,
            openbase_url=_openbase_url(host),
            openbase_configured=False,
            livekit_configured=False,
            openbase_reachable=False,
            error=str(serve_status["error"]),
        )

    openbase_configured = _openbase_serve_configured(serve_status, host)
    livekit_configured = _livekit_serve_configured(serve_status)
    openbase_url = _openbase_url(host)
    openbase_reachable, reachability_error = _openbase_reachable(openbase_url)

    return TailscaleServeHealth(
        tailscale_available=True,
        tailscale_running=True,
        host=host,
        openbase_url=openbase_url,
        openbase_configured=openbase_configured,
        livekit_configured=livekit_configured,
        openbase_reachable=openbase_reachable,
        error=reachability_error,
    )


TAILSCALE_APP_BUNDLE_CLI = "/Applications/Tailscale.app/Contents/MacOS/Tailscale"


def _tailscale_bin() -> str | None:
    found = shutil.which("tailscale")
    if found:
        return found
    # Direct-download and App Store installs don't put the CLI on PATH; the
    # binary inside the app bundle speaks the same CLI.
    if os.access(TAILSCALE_APP_BUNDLE_CLI, os.X_OK):
        return TAILSCALE_APP_BUNDLE_CLI
    return None


def _run_tailscale(tailscale_bin: str, *args: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [tailscale_bin, *args],
        capture_output=True,
        text=True,
        timeout=TAILSCALE_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "tailscale failed."
        raise RuntimeError(detail)
    return result


def _tailscale_status(tailscale_bin: str) -> dict[str, Any]:
    try:
        result = _run_tailscale(tailscale_bin, "status", "--json")
    except (OSError, subprocess.TimeoutExpired, RuntimeError) as exc:
        return {"error": f"Unable to run tailscale status: {exc}"}

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        return {"error": f"Unable to parse tailscale status JSON: {exc}"}


def _tailscale_serve_status(tailscale_bin: str) -> dict[str, Any]:
    try:
        result = _run_tailscale(tailscale_bin, "serve", "status", "--json")
    except (OSError, subprocess.TimeoutExpired, RuntimeError) as exc:
        return {"error": f"Unable to run tailscale serve status: {exc}"}

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        return {"error": f"Unable to parse tailscale serve status JSON: {exc}"}
    return payload if isinstance(payload, dict) else {}


def _self_dns_name(status: dict[str, Any]) -> str | None:
    self_payload = status.get("Self")
    if not isinstance(self_payload, dict):
        return None
    dns_name = self_payload.get("DNSName")
    if not isinstance(dns_name, str):
        return None
    return dns_name.strip().rstrip(".") or None


def _openbase_url(host: str | None) -> str | None:
    if not host:
        return None
    return f"http://{_url_host_literal(host)}:{OPENBASE_CODER_TAILNET_PORT}"


def _openbase_serve_configured(payload: dict[str, Any], host: str | None) -> bool:
    tcp = payload.get("TCP")
    web = payload.get("Web")
    tcp_port = str(OPENBASE_CODER_TAILNET_PORT)
    if not isinstance(tcp, dict) or not isinstance(tcp.get(tcp_port), dict):
        return False
    if not tcp[tcp_port].get("HTTP"):
        return False
    if not host or not isinstance(web, dict):
        return True

    expected_host = f"{host}:{OPENBASE_CODER_TAILNET_PORT}"
    entry = web.get(expected_host)
    if not isinstance(entry, dict):
        return False
    handlers = entry.get("Handlers")
    if not isinstance(handlers, dict):
        return False
    root = handlers.get("/")
    return (
        isinstance(root, dict)
        and root.get("Proxy") == f"http://127.0.0.1:{OPENBASE_CODER_LOCAL_PORT}"
    )


def _livekit_serve_configured(payload: dict[str, Any]) -> bool:
    tcp = payload.get("TCP")
    if not isinstance(tcp, dict):
        return False
    entry = tcp.get(str(LIVEKIT_TAILNET_PORT))
    return (
        isinstance(entry, dict)
        and entry.get("TCPForward") == f"127.0.0.1:{LIVEKIT_LOCAL_PORT}"
    )


def _openbase_reachable(openbase_url: str | None) -> tuple[bool, str | None]:
    if not openbase_url:
        return False, "Tailscale DNS name is unavailable."
    url = f"{openbase_url}{OPENBASE_HEALTH_PATH}"
    try:
        response = httpx.get(url, timeout=TAILSCALE_HEALTH_TIMEOUT_SECONDS)
    except httpx.HTTPError as exc:
        return False, str(exc)

    if response.status_code != 200:
        return False, f"HTTP {response.status_code} from {url}"

    try:
        payload = response.json()
    except ValueError:
        return False, f"Invalid JSON response from {url}"

    if payload.get("status") != "ok":
        return False, f"Unexpected health response from {url}"
    return True, None


def _url_host_literal(host: str) -> str:
    if ":" in host and not host.startswith("[") and not host.endswith("]"):
        return f"[{host}]"
    return host
