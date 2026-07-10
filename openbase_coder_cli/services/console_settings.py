from __future__ import annotations

import json
from pathlib import Path

from openbase_coder_cli.paths import CONSOLE_SETTINGS_JSON_PATH

DEFAULT_DANGEROUS_CONFIRMATION_PHRASE = "yes, proceed"
DEFAULT_INCLUDE_NORMAL_CODEX_AGENTS = True
DEFAULT_LOCKED_DOWN_MODE = False


def get_ignored_launchctl_labels() -> list[str]:
    data = _read_settings()
    labels = data.get("ignored_launchctl_labels")
    if not isinstance(labels, list):
        return []
    return sorted(
        {label for label in labels if isinstance(label, str) and label.strip()}
    )


def set_ignored_launchctl_labels(labels: list[str]) -> list[str]:
    normalized = sorted(
        {label.strip() for label in labels if isinstance(label, str) and label.strip()}
    )
    data = _read_settings()
    data["ignored_launchctl_labels"] = normalized
    _write_settings(data)
    return normalized


def get_dangerous_confirmation_phrase() -> str:
    data = _read_settings()
    phrase = data.get("dangerous_confirmation_phrase")
    if not isinstance(phrase, str) or not phrase.strip():
        return DEFAULT_DANGEROUS_CONFIRMATION_PHRASE
    return phrase.strip()


def set_dangerous_confirmation_phrase(phrase: str) -> str:
    normalized = phrase.strip()
    if not normalized:
        raise ValueError("Dangerous confirmation phrase cannot be blank.")
    data = _read_settings()
    data["dangerous_confirmation_phrase"] = normalized
    _write_settings(data)
    return normalized


def include_normal_codex_agents_in_openbase_agents() -> bool:
    data = _read_settings()
    value = data.get("include_normal_codex_agents_in_openbase_agents")
    if isinstance(value, bool):
        return value
    return DEFAULT_INCLUDE_NORMAL_CODEX_AGENTS


def set_include_normal_codex_agents_in_openbase_agents(value: bool) -> bool:
    data = _read_settings()
    data["include_normal_codex_agents_in_openbase_agents"] = bool(value)
    _write_settings(data)
    return bool(value)


def get_locked_down_mode() -> bool:
    data = _read_settings()
    value = data.get("locked_down_mode")
    if isinstance(value, bool):
        return value
    return DEFAULT_LOCKED_DOWN_MODE


def set_locked_down_mode(value: bool) -> bool:
    data = _read_settings()
    data["locked_down_mode"] = bool(value)
    _write_settings(data)
    return bool(value)


def get_lockdown_safe_phrase() -> str:
    data = _read_settings()
    phrase = data.get("lockdown_safe_phrase")
    if not isinstance(phrase, str):
        return ""
    return phrase.strip()


def set_lockdown_safe_phrase(phrase: str) -> str:
    normalized = phrase.strip()
    if not normalized:
        raise ValueError("Lockdown safe phrase cannot be blank.")
    data = _read_settings()
    data["lockdown_safe_phrase"] = normalized
    _write_settings(data)
    return normalized


def _read_settings() -> dict:
    try:
        data = json.loads(CONSOLE_SETTINGS_JSON_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def _write_settings(data: dict) -> None:
    CONSOLE_SETTINGS_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = Path(f"{CONSOLE_SETTINGS_JSON_PATH}.tmp")
    tmp_path.write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(CONSOLE_SETTINGS_JSON_PATH)
