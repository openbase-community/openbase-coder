from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openbase_coder_cli.paths import (
    NORMAL_CLAUDE_STATE_PATH,
    OPENBASE_CLAUDE_CONFIG_DIR,
    OPENBASE_CLAUDE_JSON_PATH,
    OPENBASE_CLAUDE_STATE_PATH,
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
    openbase_state_path: Path = OPENBASE_CLAUDE_STATE_PATH,
    mcp_config_path: Path = OPENBASE_CLAUDE_JSON_PATH,
) -> ClaudeAuthBridgeResult:
    state_updated = _merge_claude_state(
        normal_state_path=normal_state_path,
        openbase_state_path=openbase_state_path,
        mcp_config_path=mcp_config_path,
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
    args = [command, "auth", "login"]
    if sso:
        args.append("--sso")
    if email:
        args.extend(["--email", email])
    return subprocess.call(args, env=claude_env(config_dir))


def _merge_claude_state(
    *,
    normal_state_path: Path,
    openbase_state_path: Path,
    mcp_config_path: Path,
) -> bool:
    normal_state = _read_json_object(normal_state_path)
    if not normal_state:
        return False

    existing_state = _read_json_object(openbase_state_path)
    mcp_config = _read_json_object(mcp_config_path)
    merged: dict[str, Any] = {**normal_state, **existing_state}
    mcp_servers: dict[str, Any] = {}
    for payload in (normal_state, existing_state, mcp_config):
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
