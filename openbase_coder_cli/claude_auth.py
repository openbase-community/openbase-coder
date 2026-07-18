from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openbase_coder_cli.paths import (
    NORMAL_CLAUDE_STATE_PATH,
    OPENBASE_CLAUDE_CONFIG_DIR,
    OPENBASE_CLAUDE_JSON_PATH,
)

NORMAL_CLAUDE_KEYCHAIN_SERVICE = "Claude Code-credentials"
# Claude Code prints turn-level auth failures as result text (exit code 0),
# e.g. "Failed to authenticate. API Error: 401 Invalid bearer token" or
# "Failed to authenticate: OAuth session expired and could not be refreshed".
CLAUDE_AUTH_FAILURE_PREFIX = "Failed to authenticate"
CLAUDE_AUTH_PROBE_PROMPT = "Reply with the single word ok."
CLAUDE_AUTH_PROBE_TIMEOUT_SECONDS = 90


@dataclass(frozen=True)
class ClaudeAuthBridgeResult:
    state_updated: bool
    message: str


@dataclass(frozen=True)
class ClaudeAuthStatus:
    logged_in: bool
    raw_output: str
    returncode: int


def openbase_claude_keychain_service(
    config_dir: Path = OPENBASE_CLAUDE_CONFIG_DIR,
) -> str:
    suffix = hashlib.sha256(str(config_dir).encode("utf-8")).hexdigest()[:8]
    return f"{NORMAL_CLAUDE_KEYCHAIN_SERVICE}-{suffix}"


def claude_env(config_dir: Path = OPENBASE_CLAUDE_CONFIG_DIR) -> dict[str, str]:
    env = os.environ.copy()
    env["CLAUDE_CONFIG_DIR"] = str(config_dir)
    return env


def sync_normal_claude_state(
    *,
    normal_state_path: Path = NORMAL_CLAUDE_STATE_PATH,
    openbase_state_path: Path = OPENBASE_CLAUDE_JSON_PATH,
) -> ClaudeAuthBridgeResult:
    """Merge normal Claude Code state into Openbase's managed state file.

    The target is ``$CLAUDE_CONFIG_DIR/.claude.json`` — the file Claude Code
    actually reads and writes when ``CLAUDE_CONFIG_DIR`` is set. Existing
    Openbase values win; ``mcpServers`` entries are unioned.
    """
    state_updated = _merge_claude_state(
        normal_state_path=normal_state_path,
        openbase_state_path=openbase_state_path,
    )
    message = (
        "Synced normal Claude Code state into Openbase."
        if state_updated
        else "Normal Claude Code state was not found or was already synced."
    )
    return ClaudeAuthBridgeResult(
        state_updated=state_updated,
        message=message,
    )


def copy_normal_claude_keychain(
    *, config_dir: Path = OPENBASE_CLAUDE_CONFIG_DIR
) -> bool:
    """Copy the normal Claude Code OAuth keychain item to Openbase's service.

    Claude Code stores tokens under a per-``CLAUDE_CONFIG_DIR`` keychain
    service, so the JSON state merge alone never transfers a login. Copying
    the keychain item lets non-interactive installs inherit the user's normal
    Claude login instead of requiring a second browser OAuth flow.
    """
    if platform.system() != "Darwin":
        return False
    secret = _read_keychain_secret(NORMAL_CLAUDE_KEYCHAIN_SERVICE)
    if not secret:
        return False
    account = _keychain_account(NORMAL_CLAUDE_KEYCHAIN_SERVICE) or os.environ.get(
        "USER", ""
    )
    target_service = openbase_claude_keychain_service(config_dir)
    result = subprocess.run(
        [
            "security",
            "add-generic-password",
            "-U",
            "-s",
            target_service,
            "-a",
            account,
            "-w",
            secret,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _read_keychain_secret(service: str) -> str | None:
    result = subprocess.run(
        ["security", "find-generic-password", "-s", service, "-w"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    secret = result.stdout.strip()
    return secret or None


def _keychain_account(service: str) -> str | None:
    result = subprocess.run(
        ["security", "find-generic-password", "-s", service],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith('"acct"'):
            _key, _sep, value = stripped.partition("=")
            value = value.strip()
            if value.startswith('"') and value.endswith('"'):
                return value[1:-1]
    return None


def claude_auth_status(
    *,
    config_dir: Path = OPENBASE_CLAUDE_CONFIG_DIR,
    claude_command: str | None = None,
) -> ClaudeAuthStatus:
    command = claude_command or shutil.which("claude") or "claude"
    try:
        completed = subprocess.run(
            [command, "auth", "status"],
            check=False,
            capture_output=True,
            text=True,
            env=claude_env(config_dir),
        )
    except FileNotFoundError:
        return ClaudeAuthStatus(
            logged_in=False,
            raw_output="Claude Code CLI not found on PATH.",
            returncode=127,
        )

    output = (completed.stdout or completed.stderr).strip()
    logged_in = False
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        logged_in = "loggedIn" in output and "true" in output
    else:
        logged_in = bool(payload.get("loggedIn"))
    return ClaudeAuthStatus(
        logged_in=logged_in,
        raw_output=output,
        returncode=completed.returncode,
    )


def is_claude_auth_failure_text(text: str | None) -> bool:
    """Whether turn output is Claude Code's spoken-back auth failure."""
    return bool(text) and text.strip().startswith(CLAUDE_AUTH_FAILURE_PREFIX)


def read_openbase_claude_credential_expiry(
    config_dir: Path = OPENBASE_CLAUDE_CONFIG_DIR,
) -> float | None:
    """Epoch-ms expiry of the Openbase-scoped Claude OAuth access token."""
    payload: dict[str, Any] = {}
    if platform.system() == "Darwin":
        secret = _read_keychain_secret(openbase_claude_keychain_service(config_dir))
        if secret:
            try:
                parsed = json.loads(secret)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict):
                payload = parsed
    else:
        payload = _read_json_object(config_dir / ".credentials.json")
    oauth = payload.get("claudeAiOauth")
    if not isinstance(oauth, dict):
        return None
    expires = oauth.get("expiresAt")
    return float(expires) if isinstance(expires, int | float) else None


def probe_claude_auth(
    *,
    config_dir: Path = OPENBASE_CLAUDE_CONFIG_DIR,
    claude_command: str | None = None,
) -> ClaudeAuthStatus:
    """Run a minimal real turn to see whether the scoped login actually works.

    ``claude auth status`` reports cached account state and keeps saying
    ``loggedIn: true`` after the OAuth tokens die, so only a real API call can
    tell. A successful probe also makes the CLI refresh and persist fresh
    tokens as a side effect. Inconclusive outcomes (timeout) count as logged
    in so transient stalls never report a false logout.
    """
    command = claude_command or shutil.which("claude") or "claude"
    try:
        completed = subprocess.run(
            [command, "-p", CLAUDE_AUTH_PROBE_PROMPT, "--model", "haiku"],
            check=False,
            capture_output=True,
            text=True,
            env=claude_env(config_dir),
            timeout=CLAUDE_AUTH_PROBE_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        return ClaudeAuthStatus(
            logged_in=False,
            raw_output="Claude Code CLI not found on PATH.",
            returncode=127,
        )
    except subprocess.TimeoutExpired:
        return ClaudeAuthStatus(
            logged_in=True,
            raw_output="Claude auth probe timed out; assuming the login is intact.",
            returncode=124,
        )
    output = (completed.stdout or completed.stderr).strip()
    return ClaudeAuthStatus(
        logged_in=not is_claude_auth_failure_text(output),
        raw_output=output,
        returncode=completed.returncode,
    )


def verified_claude_auth_status(
    *,
    config_dir: Path = OPENBASE_CLAUDE_CONFIG_DIR,
    claude_command: str | None = None,
) -> ClaudeAuthStatus:
    """Auth status that catches expired-but-cached logins.

    When ``claude auth status`` claims a login but the stored access token is
    past its expiry, verify with a probe turn: the probe either refreshes the
    tokens (still logged in) or surfaces the real auth failure.
    """
    status = claude_auth_status(config_dir=config_dir, claude_command=claude_command)
    if not status.logged_in:
        return status
    expiry_ms = read_openbase_claude_credential_expiry(config_dir)
    if expiry_ms is None or expiry_ms > time.time() * 1000:
        return status
    probe = probe_claude_auth(config_dir=config_dir, claude_command=claude_command)
    if probe.logged_in:
        return status
    return probe


def heal_claude_auth(
    *,
    config_dir: Path = OPENBASE_CLAUDE_CONFIG_DIR,
    claude_command: str | None = None,
) -> ClaudeAuthBridgeResult:
    """Re-bridge the normal Claude Code login after a scoped auth failure.

    The Openbase credential is a copy of the normal login, so whichever config
    dir refreshes first strands the other copy's refresh token. Copying the
    (healthy) normal credential back in is the recovery; ``state_updated``
    reports whether a probe confirmed the bridged login works.
    """
    sync_normal_claude_state()
    if not copy_normal_claude_keychain(config_dir=config_dir):
        return ClaudeAuthBridgeResult(
            state_updated=False,
            message="No normal Claude Code login was available to copy.",
        )
    probe = probe_claude_auth(config_dir=config_dir, claude_command=claude_command)
    if probe.logged_in:
        return ClaudeAuthBridgeResult(
            state_updated=True,
            message="Re-bridged the normal Claude Code login into Openbase.",
        )
    return ClaudeAuthBridgeResult(
        state_updated=False,
        message=f"Re-bridged login still failing: {probe.raw_output}",
    )


def run_claude_login(
    *,
    config_dir: Path = OPENBASE_CLAUDE_CONFIG_DIR,
    claude_command: str | None = None,
    sso: bool = False,
    email: str | None = None,
) -> int:
    command = claude_command or shutil.which("claude") or "claude"
    args = [command, "auth", "login", "--claudeai"]
    if sso:
        args.append("--sso")
    if email:
        args.extend(["--email", email])
    return subprocess.call(args, env=claude_env(config_dir))


def _merge_claude_state(
    *,
    normal_state_path: Path,
    openbase_state_path: Path,
) -> bool:
    normal_state = _read_json_object(normal_state_path)
    if not normal_state:
        return False

    existing_state = _read_json_object(openbase_state_path)
    merged: dict[str, Any] = {**normal_state, **existing_state}
    mcp_servers: dict[str, Any] = {}
    for payload in (normal_state, existing_state):
        value = payload.get("mcpServers")
        if isinstance(value, dict):
            mcp_servers.update(value)
    if mcp_servers:
        merged["mcpServers"] = mcp_servers

    if merged == existing_state:
        return False

    openbase_state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = openbase_state_path.with_name(
        f"{openbase_state_path.name}.tmp.{os.getpid()}"
    )
    tmp_path.write_text(
        json.dumps(merged, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp_path.chmod(0o600)
    tmp_path.replace(openbase_state_path)
    return True


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}
