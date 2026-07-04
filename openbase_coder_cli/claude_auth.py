from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openbase_coder_cli.paths import (
    NORMAL_CLAUDE_STATE_PATH,
    OPENBASE_CLAUDE_CONFIG_DIR,
    OPENBASE_CLAUDE_JSON_PATH,
)

NORMAL_CLAUDE_KEYCHAIN_SERVICE = "Claude Code-credentials"


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
