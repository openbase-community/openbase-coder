"""
Doctor command — verify service health and security configuration.
"""

from __future__ import annotations

import subprocess

import click

from openbase_coder_cli.paths import DEFAULT_ENV_FILE_PATH
from openbase_coder_cli.services.definitions import SERVICES
from openbase_coder_cli.services.installation import InstallationConfig
from openbase_coder_cli.services.launchd import launchctl_status
from openbase_coder_cli.services.tailscale_serve import tailscale_serve_health

# Services that have authentication and may safely bind to 0.0.0.0
_AUTHENTICATED_PORTS: dict[int, str] = {
    7999: "django-cli (JWT auth)",
    7880: "livekit-server (API key auth)",
}

# Required env vars and known-insecure default values
_REQUIRED_ENV: list[tuple[str, list[str]]] = [
    ("OPENBASE_CODER_CLI_SECRET_KEY", []),
    ("LIVEKIT_API_KEY", ["devkey"]),
    ("LIVEKIT_API_SECRET", ["secret"]),
]

_LIVEKIT_CLIENT_ENV = ("LIVEKIT_CLIENT_API_KEY", "LIVEKIT_CLIENT_API_SECRET")


def _parse_env_file() -> dict[str, str]:
    """Read the .env file and return key-value pairs."""
    env: dict[str, str] = {}
    if not DEFAULT_ENV_FILE_PATH.is_file():
        return env
    for line in DEFAULT_ENV_FILE_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip().strip("\"'")
    return env


def _get_listening_sockets() -> list[tuple[str, int]]:
    """Return (bind_address, port) for all TCP LISTEN sockets.

    Uses lsof to query the system, falling back to ss when lsof is missing.
    """
    try:
        result = subprocess.run(
            ["lsof", "-iTCP", "-sTCP:LISTEN", "-P", "-n"],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return _get_listening_sockets_ss()
    seen: set[tuple[str, int]] = set()
    sockets: list[tuple[str, int]] = []
    for line in result.stdout.splitlines()[1:]:  # skip header
        parts = line.split()
        if len(parts) < 9:
            continue
        # NAME column is like "*:7880" or "127.0.0.1:2024"
        name = parts[8]
        if ":" not in name:
            continue
        host, _, port_str = name.rpartition(":")
        try:
            port = int(port_str)
        except ValueError:
            continue
        key = (host, port)
        if key not in seen:
            seen.add(key)
            sockets.append(key)
    return sockets


def _get_listening_sockets_ss() -> list[tuple[str, int]]:
    try:
        result = subprocess.run(
            ["ss", "-ltnH"],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return []
    seen: set[tuple[str, int]] = set()
    sockets: list[tuple[str, int]] = []
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        # Local Address:Port column is like "0.0.0.0:7880" or "[::]:7880"
        name = parts[3]
        host, _, port_str = name.rpartition(":")
        try:
            port = int(port_str)
        except ValueError:
            continue
        key = (host, port)
        if key not in seen:
            seen.add(key)
            sockets.append(key)
    return sockets


def _check_livekit_client_credentials(env: dict[str, str], warn, ok) -> None:
    missing = [name for name in _LIVEKIT_CLIENT_ENV if not env.get(name)]
    if missing:
        warn(
            "LiveKit client token credentials missing "
            f"({', '.join(missing)}): run 'openbase-coder setup' and restart services"
        )
        return

    reused = []
    if env.get("LIVEKIT_CLIENT_API_KEY") == env.get("LIVEKIT_API_KEY"):
        reused.append("LIVEKIT_CLIENT_API_KEY")
    if env.get("LIVEKIT_CLIENT_API_SECRET") == env.get("LIVEKIT_API_SECRET"):
        reused.append("LIVEKIT_CLIENT_API_SECRET")
    if reused:
        warn(
            "LiveKit client token credentials reuse local server credentials "
            f"({', '.join(reused)}): run 'openbase-coder setup' and restart services"
        )
        return

    ok("LiveKit client token credentials: set and separate from server credentials")


@click.command()
def doctor() -> None:
    """Check service health and security configuration."""
    ok_count = 0
    warn_count = 0
    fail_count = 0

    def ok(msg: str) -> None:
        nonlocal ok_count
        ok_count += 1
        click.echo(click.style("  OK  ", fg="green") + msg)

    def warn(msg: str) -> None:
        nonlocal warn_count
        warn_count += 1
        click.echo(click.style("  WARN ", fg="yellow") + msg)

    def fail(msg: str) -> None:
        nonlocal fail_count
        fail_count += 1
        click.echo(click.style("  FAIL ", fg="red") + msg)

    # --- Installation ---
    click.echo()
    click.echo(click.style("Installation", bold=True))
    if InstallationConfig.exists():
        ok("installation.json found")
    else:
        fail("installation.json missing — run 'openbase-coder setup'")

    # --- Service health ---
    click.echo()
    click.echo(click.style("Service Health", bold=True))
    for svc in SERVICES:
        info = launchctl_status(svc)
        if not info["installed"]:
            fail(f"{svc.name}: not installed")
        elif info["pid"]:
            ok(f"{svc.name}: running (pid {info['pid']})")
        else:
            exit_code = info.get("last_exit_code", "unknown")
            fail(f"{svc.name}: not running (last exit: {exit_code})")

    # --- Bind address security ---
    click.echo()
    click.echo(click.style("Network Security", bold=True))
    sockets = _get_listening_sockets()

    for port, label in _AUTHENTICATED_PORTS.items():
        listeners = [(h, p) for h, p in sockets if p == port]
        if not listeners:
            warn(f"port {port} ({label}): not listening")
        else:
            for host, _ in listeners:
                if host in ("*", "0.0.0.0", "[::]"):
                    ok(f"port {port} ({label}): bound to {host} (auth enabled)")
                else:
                    ok(f"port {port} ({label}): bound to {host}")

    # --- Tailscale Serve ---
    click.echo()
    click.echo(click.style("Tailscale Serve", bold=True))
    serve_health = tailscale_serve_health()
    if not serve_health.tailscale_available:
        fail("tailscale: not found on PATH")
    elif not serve_health.tailscale_running:
        fail(f"tailscale: not running ({serve_health.error or 'unknown error'})")
    else:
        ok(f"tailscale: running for {serve_health.host or 'unknown host'}")

    if serve_health.openbase_configured:
        ok("Openbase API Serve route: :18080 -> http://127.0.0.1:7999")
    else:
        fail(
            "Openbase API Serve route missing: run "
            "tailscale serve --bg --http=18080 http://127.0.0.1:7999"
        )

    if serve_health.livekit_configured:
        ok("LiveKit Serve route: :7880 -> tcp://127.0.0.1:7880")
    else:
        fail(
            "LiveKit Serve route missing: run "
            "tailscale serve --bg --tcp=7880 tcp://127.0.0.1:7880"
        )

    if serve_health.openbase_reachable:
        ok(f"external Openbase health check passed at {serve_health.openbase_url}")
    else:
        detail = f": {serve_health.error}" if serve_health.error else ""
        fail(f"external Openbase health check failed{detail}")

    # --- Credentials ---
    click.echo()
    click.echo(click.style("Credentials", bold=True))
    env = _parse_env_file()

    if not DEFAULT_ENV_FILE_PATH.is_file():
        fail(f".env file not found at {DEFAULT_ENV_FILE_PATH}")
    else:
        ok(f".env file exists at {DEFAULT_ENV_FILE_PATH}")

    for var_name, insecure_values in _REQUIRED_ENV:
        value = env.get(var_name, "")
        if not value:
            fail(f"{var_name}: not set")
        elif value in insecure_values:
            fail(f"{var_name}: using insecure default value '{value}'")
        else:
            ok(f"{var_name}: set")

    _check_livekit_client_credentials(env, warn, ok)

    # --- Summary ---
    click.echo()
    total = ok_count + warn_count + fail_count
    summary = f"{ok_count}/{total} checks passed"
    if fail_count:
        summary += f", {fail_count} failed"
    if warn_count:
        summary += f", {warn_count} warnings"

    if fail_count:
        click.echo(click.style(summary, fg="red", bold=True))
    elif warn_count:
        click.echo(click.style(summary, fg="yellow", bold=True))
    else:
        click.echo(click.style(summary, fg="green", bold=True))
    click.echo()
