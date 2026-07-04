"""
Doctor command — verify service health and security configuration.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import click

from openbase_coder_cli.backend_config import (
    CLAUDE_CODE_BACKEND,
    CODEX_BACKEND,
    CODING_BACKEND_ENV_KEY,
    DEFAULT_CODING_BACKEND,
    OPENBASE_CLOUD_BACKEND,
    normalize_backend,
)
from openbase_coder_cli.claude_auth import claude_auth_status
from openbase_coder_cli.dispatcher_config import (
    selected_stt_provider_id,
    selected_tts_provider_id,
)
from openbase_coder_cli.paths import (
    AUTH_JSON_PATH,
    CODEX_HOME_DIR,
    DEFAULT_ENV_FILE_PATH,
)
from openbase_coder_cli.services.definitions import SERVICES
from openbase_coder_cli.services.installation import InstallationConfig
from openbase_coder_cli.services.launchd import launchctl_status
from openbase_coder_cli.services.tailscale_serve import tailscale_serve_health
from openbase_coder_cli.stt_providers import (
    LOCAL_MLX_WHISPER_STT_PROVIDER_ID,
    local_mlx_whisper_readiness,
)
from openbase_coder_cli.tts_providers import KOKORO_PROVIDER_ID, get_tts_provider

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


def _selected_backend(env: dict[str, str]) -> str:
    raw_value = (
        env.get(CODING_BACKEND_ENV_KEY)
        or DEFAULT_CODING_BACKEND
    )
    try:
        return normalize_backend(raw_value)
    except ValueError:
        return DEFAULT_CODING_BACKEND


def _check_installation_config(ok, warn, fail) -> None:
    if not InstallationConfig.exists():
        fail("installation.json missing — run 'openbase-coder setup'")
        return

    ok("installation.json found")
    try:
        config = InstallationConfig.load()
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        fail(f"installation.json could not be read: {exc}")
        return

    if config.standalone:
        ok("standalone runtime mode enabled")
        _check_path(config.package_path, "standalone package", ok, fail, directory=True)
        _check_path(config.python_path, "bundled Python", ok, fail)
        _check_path(config.livekit_server_path, "bundled LiveKit server", ok, fail)
        _check_path(
            config.console_build_dir,
            "bundled console build",
            ok,
            fail,
            directory=True,
            child="index.html",
        )
        if config.workspace_path:
            warn(
                "dev workspace is still configured in standalone mode; "
                "rerun setup from the standalone CLI to clear it"
            )
        else:
            ok("no workspace checkout required at runtime")
        return

    if config.workspace_path:
        ok("development workspace runtime mode enabled")
    else:
        warn("non-standalone install has no workspace_path configured")


def _check_path(
    value: str,
    label: str,
    ok,
    fail,
    *,
    directory: bool = False,
    child: str | None = None,
) -> None:
    if not value:
        fail(f"{label}: not configured")
        return

    path = Path(value).expanduser()
    exists = path.is_dir() if directory else path.is_file()
    if child and exists:
        exists = (path / child).is_file()
    if exists:
        ok(f"{label}: {path}")
    else:
        fail(f"{label}: missing at {path}")


def _check_agent_auth(env: dict[str, str], ok, warn, fail, action=None) -> None:
    action = action or fail
    backend = _selected_backend(env)
    ok(f"coding backend selected: {backend}")

    codex_auth = Path.home() / ".codex" / "auth.json"
    service_codex_auth = CODEX_HOME_DIR / "auth.json"
    if backend == CODEX_BACKEND:
        if codex_auth.is_file():
            ok("Codex auth: logged in")
        else:
            action("Codex auth missing: run 'codex login'")

        if service_codex_auth.exists():
            ok("Openbase Codex service auth bridge: configured")
        else:
            warn(
                "Openbase Codex service auth bridge missing: "
                "run 'openbase-coder setup' after 'codex login'"
            )

    if backend == OPENBASE_CLOUD_BACKEND:
        if AUTH_JSON_PATH.is_file():
            ok("Openbase Cloud auth: logged in")
        else:
            action("Openbase Cloud auth missing: run 'openbase-coder login'")

    if backend == CLAUDE_CODE_BACKEND:
        status = claude_auth_status()
        if status.logged_in:
            ok("Claude Code auth: logged in")
        else:
            detail = f" ({status.raw_output})" if status.raw_output else ""
            action(f"Claude Code auth missing: run 'claude auth login'{detail}")


def _check_audio_readiness(ok, warn) -> None:
    tts_provider = selected_tts_provider_id()
    stt_provider = selected_stt_provider_id()
    ok(f"TTS provider selected: {tts_provider}")
    ok(f"STT provider selected: {stt_provider}")

    if tts_provider == KOKORO_PROVIDER_ID:
        status = get_tts_provider(KOKORO_PROVIDER_ID).readiness()
        if status.ready:
            ok(
                "Kokoro local audio: ready "
                f"({status.cached_files}/{status.required_files} files cached)"
            )
        else:
            detail = f": {status.detail}" if status.detail else ""
            warn(
                "Kokoro local audio not ready "
                f"({status.cached_files}/{status.required_files} files cached)"
                f"{detail}; run 'openbase-coder setup --audio-provider local'"
            )

    if stt_provider == LOCAL_MLX_WHISPER_STT_PROVIDER_ID:
        status = local_mlx_whisper_readiness()
        if status.ready:
            ok(f"Local MLX Whisper: ready ({status.model})")
        else:
            detail = f": {status.detail}" if status.detail else ""
            warn(
                "Local MLX Whisper not ready "
                f"({status.model}){detail}; "
                "run 'openbase-coder setup --audio-provider local'"
            )


@click.command()
def doctor() -> None:
    """Check service health and security configuration."""
    ok_count = 0
    warn_count = 0
    fail_count = 0
    action_count = 0

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

    def action(msg: str) -> None:
        nonlocal action_count
        action_count += 1
        click.echo(click.style("  SETUP", fg="cyan") + " " + msg)

    # --- Installation ---
    click.echo()
    click.echo(click.style("Installation", bold=True))
    _check_installation_config(ok, warn, fail)

    # --- Service health ---
    click.echo()
    click.echo(click.style("Service Health", bold=True))
    for svc in SERVICES:
        info = launchctl_status(svc)
        required = getattr(svc, "install_by_default", True)
        if not info["installed"]:
            if required:
                fail(f"{svc.name}: not installed")
            else:
                ok(f"{svc.name}: optional (not installed)")
        elif info["pid"]:
            ok(f"{svc.name}: running (pid {info['pid']})")
        else:
            exit_code = info.get("last_exit_code", "unknown")
            if required:
                fail(f"{svc.name}: not running (last exit: {exit_code})")
            else:
                ok(f"{svc.name}: optional (not running, last exit: {exit_code})")

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
        action("tailscale: not found on PATH")
    elif not serve_health.tailscale_running:
        action(f"tailscale: not running ({serve_health.error or 'unknown error'})")
    else:
        ok(f"tailscale: running for {serve_health.host or 'unknown host'}")

    if serve_health.openbase_configured:
        ok("Openbase API Serve route: :18080 -> http://127.0.0.1:7999")
    else:
        action(
            "Openbase API Serve route missing: run "
            "tailscale serve --bg --http=18080 http://127.0.0.1:7999"
        )

    if serve_health.livekit_configured:
        ok("LiveKit Serve route: :7880 -> tcp://127.0.0.1:7880")
    else:
        action(
            "LiveKit Serve route missing: run "
            "tailscale serve --bg --tcp=7880 tcp://127.0.0.1:7880"
        )

    if serve_health.openbase_reachable:
        ok(f"external Openbase health check passed at {serve_health.openbase_url}")
    else:
        detail = f": {serve_health.error}" if serve_health.error else ""
        action(f"external Openbase health check failed{detail}")

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

    # --- Agent auth ---
    click.echo()
    click.echo(click.style("Agent Auth", bold=True))
    _check_agent_auth(env, ok, warn, fail, action)

    # --- Audio ---
    click.echo()
    click.echo(click.style("Audio", bold=True))
    _check_audio_readiness(ok, warn)

    # --- Summary ---
    click.echo()
    total = ok_count + warn_count + fail_count + action_count
    summary = f"{ok_count}/{total} checks passed"
    if fail_count:
        summary += f", {fail_count} failed"
    if warn_count:
        summary += f", {warn_count} warnings"
    if action_count:
        summary += f", {action_count} setup actions"

    if fail_count:
        click.echo(click.style(summary, fg="red", bold=True))
    elif warn_count or action_count:
        click.echo(click.style(summary, fg="yellow", bold=True))
    else:
        click.echo(click.style(summary, fg="green", bold=True))
    click.echo()
