"""Openbase git provenance hooks (inject-session-id).

A SessionStart hook for each coding backend Openbase manages. The hook
reads the ``session_id`` from the hook's stdin JSON and injects it back into
the conversation as additional context, so agents know their own
thread/session ID and can stamp commits with an ``Agent-Thread-Id`` trailer
tying each commit to the exact agent session that produced it.

Claude Code and Codex share the same hook wire format
(``hookSpecificOutput.additionalContext``), so one script serves both:

- Claude Code: registered under ``hooks.SessionStart`` in the Openbase-managed
  settings (``~/.openbase/claude_config/settings.json``).
- Codex: registered as ``hooks.json`` in the Openbase-managed ``CODEX_HOME``
  plus a ``[hooks.state]`` trust entry in its ``config.toml``. The
  ``trusted_hash`` replicates Codex's normalized hook trust identity
  (``sha256:`` of the canonical compact JSON of the event name plus the
  matcher group with the normalized command handler — see
  ``codex-rs/hooks/src/engine/discovery.rs``), so the hook is trusted without
  an interactive review.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from openbase_coder_cli.paths import (
    CODEX_HOME_DIR,
    OPENBASE_CLAUDE_CONFIG_DIR,
    OPENBASE_CLAUDE_SETTINGS_PATH,
)
from openbase_coder_cli.toml_text import replace_toml_table

HOOK_SCRIPT_NAME = "inject-session-id.sh"
CODEX_CONFIG_PATH = CODEX_HOME_DIR / "config.toml"
CODEX_HOOKS_JSON_PATH = CODEX_HOME_DIR / "hooks.json"
CODEX_HOOK_SCRIPT_PATH = CODEX_HOME_DIR / "hooks" / HOOK_SCRIPT_NAME
CLAUDE_HOOK_SCRIPT_PATH = OPENBASE_CLAUDE_CONFIG_DIR / "hooks" / HOOK_SCRIPT_NAME

# Codex normalizes a command hook that omits `timeout` to this default before
# hashing its trust identity.
_CODEX_DEFAULT_TIMEOUT_SEC = 600

# Dependency-free (no jq/python3): extract session_id with sed, keep only
# characters that are safe inside the JSON emitted below, and stay silent when
# no session_id is present.
HOOK_SCRIPT = """#!/bin/sh
# Openbase git provenance hook (SessionStart). Reads the session_id from the
# hook's stdin JSON and injects it into the conversation as additionalContext,
# so the agent knows its own thread/session ID and can stamp commits with an
# Agent-Thread-Id trailer. Claude Code and Codex share this hook wire format.
# Managed by Openbase; edits are overwritten on reinstall.

set -eu

INPUT=$(cat)
SESSION_ID=$(printf '%s' "$INPUT" \\
    | sed -n 's/.*"session_id"[[:space:]]*:[[:space:]]*"\\([^"]*\\)".*/\\1/p' \\
    | head -n 1)
SESSION_ID=$(printf '%s' "$SESSION_ID" | tr -cd 'A-Za-z0-9._-')

if [ -z "$SESSION_ID" ]; then
    exit 0
fi

printf '{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"Current agent thread/session ID: %s. Use this as the Agent-Thread-Id git commit trailer value when committing."}}\\n' "$SESSION_ID"
"""


def install_provenance_hooks() -> dict[str, Any]:
    """Install the provenance hooks for both managed backends; idempotent."""
    _install_hook_script(CLAUDE_HOOK_SCRIPT_PATH)
    _install_hook_script(CODEX_HOOK_SCRIPT_PATH)
    _register_claude_hook()
    _register_codex_hook()
    return provenance_hooks_status()


def provenance_hooks_status() -> dict[str, Any]:
    claude = _claude_hook_installed()
    codex = _codex_hook_installed()
    return {
        "installed": claude and codex,
        "backends": {
            "claude": {
                "installed": claude,
                "script_path": str(CLAUDE_HOOK_SCRIPT_PATH),
                "settings_path": str(OPENBASE_CLAUDE_SETTINGS_PATH),
            },
            "codex": {
                "installed": codex,
                "script_path": str(CODEX_HOOK_SCRIPT_PATH),
                "hooks_json_path": str(CODEX_HOOKS_JSON_PATH),
                "config_path": str(CODEX_CONFIG_PATH),
            },
        },
    }


def _install_hook_script(script_path: Path) -> None:
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(HOOK_SCRIPT, encoding="utf-8")
    script_path.chmod(0o755)


def _hook_script_current(script_path: Path) -> bool:
    try:
        current = script_path.read_text(encoding="utf-8")
    except OSError:
        return False
    return current == HOOK_SCRIPT and script_path.stat().st_mode & 0o111 != 0


# --- Claude Code ------------------------------------------------------------


def _claude_session_start_groups(settings: dict[str, Any]) -> list[Any]:
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return []
    groups = hooks.get("SessionStart")
    return groups if isinstance(groups, list) else []


def _claude_hook_registered(settings: dict[str, Any]) -> bool:
    return any(
        handler.get("command") == str(CLAUDE_HOOK_SCRIPT_PATH)
        for group in _claude_session_start_groups(settings)
        if isinstance(group, dict)
        for handler in group.get("hooks", [])
        if isinstance(handler, dict)
    )


def _claude_hook_installed() -> bool:
    return _hook_script_current(CLAUDE_HOOK_SCRIPT_PATH) and _claude_hook_registered(
        _read_json_object(OPENBASE_CLAUDE_SETTINGS_PATH)
    )


def _register_claude_hook() -> None:
    settings = _read_json_object(OPENBASE_CLAUDE_SETTINGS_PATH)
    if _claude_hook_registered(settings):
        return
    hooks = settings.setdefault("hooks", {})
    groups = hooks.setdefault("SessionStart", [])
    groups.append(
        {
            "matcher": "",
            "hooks": [
                {"type": "command", "command": str(CLAUDE_HOOK_SCRIPT_PATH)},
            ],
        }
    )
    OPENBASE_CLAUDE_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    OPENBASE_CLAUDE_SETTINGS_PATH.write_text(
        json.dumps(settings, indent=2) + "\n", encoding="utf-8"
    )


# --- Codex ------------------------------------------------------------------


def _codex_hook_entry() -> dict[str, Any]:
    return {"type": "command", "command": str(CODEX_HOOK_SCRIPT_PATH)}


def _codex_session_start_groups(hooks_file: dict[str, Any]) -> list[Any]:
    hooks = hooks_file.get("hooks")
    if not isinstance(hooks, dict):
        return []
    groups = hooks.get("SessionStart")
    return groups if isinstance(groups, list) else []


def _codex_hook_group_index(hooks_file: dict[str, Any]) -> int | None:
    """Index of the matcher group holding our handler (always handler 0)."""
    for index, group in enumerate(_codex_session_start_groups(hooks_file)):
        if not isinstance(group, dict):
            continue
        handlers = group.get("hooks")
        if (
            isinstance(handlers, list)
            and handlers
            and isinstance(handlers[0], dict)
            and handlers[0].get("command") == str(CODEX_HOOK_SCRIPT_PATH)
        ):
            return index
    return None


def codex_trusted_hash(command: str) -> str:
    """Replicate Codex's normalized command-hook trust hash."""
    identity = {
        "event_name": "session_start",
        "hooks": [
            {
                "type": "command",
                "command": command,
                "timeout": _CODEX_DEFAULT_TIMEOUT_SEC,
                "async": False,
            }
        ],
    }
    serialized = json.dumps(_canonical_json(identity), separators=(",", ":"))
    return f"sha256:{hashlib.sha256(serialized.encode('utf-8')).hexdigest()}"


def _canonical_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _canonical_json(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_canonical_json(item) for item in value]
    return value


def _codex_state_key(group_index: int) -> str:
    return f"{CODEX_HOOKS_JSON_PATH}:session_start:{group_index}:0"


def _codex_state_block(group_index: int) -> str:
    key = _codex_state_key(group_index)
    trusted = codex_trusted_hash(str(CODEX_HOOK_SCRIPT_PATH))
    return f'[hooks.state."{key}"]\ntrusted_hash = "{trusted}"\nenabled = true\n'


def _codex_hook_installed() -> bool:
    if not _hook_script_current(CODEX_HOOK_SCRIPT_PATH):
        return False
    group_index = _codex_hook_group_index(_read_json_object(CODEX_HOOKS_JSON_PATH))
    if group_index is None:
        return False
    try:
        config = CODEX_CONFIG_PATH.read_text(encoding="utf-8")
    except OSError:
        return False
    return _codex_state_block(group_index) in _normalize_blank_runs(config)


def _register_codex_hook() -> None:
    hooks_file = _read_json_object(CODEX_HOOKS_JSON_PATH)
    group_index = _codex_hook_group_index(hooks_file)
    if group_index is None:
        hooks = hooks_file.setdefault("hooks", {})
        groups = hooks.setdefault("SessionStart", [])
        groups.append({"hooks": [_codex_hook_entry()]})
        group_index = len(groups) - 1
        CODEX_HOOKS_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
        CODEX_HOOKS_JSON_PATH.write_text(
            json.dumps(hooks_file, indent=2) + "\n", encoding="utf-8"
        )

    existing = ""
    if CODEX_CONFIG_PATH.is_file():
        existing = CODEX_CONFIG_PATH.read_text(encoding="utf-8")
    key = _codex_state_key(group_index)
    updated = replace_toml_table(
        existing, f'hooks.state."{key}"', _codex_state_block(group_index)
    )
    CODEX_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CODEX_CONFIG_PATH.write_text(updated, encoding="utf-8")


def _normalize_blank_runs(text: str) -> str:
    lines = [line.rstrip() for line in text.splitlines()]
    return "\n".join(lines) + "\n"


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}
