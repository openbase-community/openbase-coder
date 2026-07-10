"""VocalBridge credentials and dispatcher-agent configuration."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from openbase_coder_cli.paths import (
    DEFAULT_ENV_FILE_PATH,
    OPENBASE_VOCALBRIDGE_INSTRUCTIONS_PATH,
)

logger = logging.getLogger(__name__)

VOCALBRIDGE_API_KEY_ENV = "VOCAL_BRIDGE_API_KEY"
VOCALBRIDGE_AGENT_ID_ENV = "VOCAL_BRIDGE_AGENT_ID"
VOCALBRIDGE_API_URL_ENV = "VOCAL_BRIDGE_API_URL"
DEFAULT_VOCALBRIDGE_API_URL = "https://vocalbridgeai.com"

# The VocalBridge dispatcher is intentionally narrow: it coordinates Super
# Agents over MCP and looks around the file system, and nothing else. All
# speech (STT/TTS, greetings, filler) is handled by the hosted VocalBridge
# voice agent; this agent only answers delegated queries.
VOCALBRIDGE_BUILTIN_DEVELOPER_INSTRUCTIONS = """
You are the Openbase Coder dispatcher answering queries delegated from a
VocalBridge voice agent. Your replies are spoken aloud to the user, so keep
them short, plain prose that reads well as speech. Never include code, logs,
JSON, diffs, or long file paths in a reply; summarize their practical meaning
instead.
You are strictly a dispatcher. You may only:
- use the Super Agents MCP tools to start, steer, check on, and read coding
  threads
- explore the file system read-only (list directories, read files, search)
  to identify projects and repositories to dispatch work into
Do not edit files, write files, run state-changing commands, install
software, or do coding work yourself. Delegate all coding work to Super
Agents threads and report their status.
Answer quickly: the voice agent gives up waiting after about a minute, so
prefer a short useful answer now over a thorough one later.
""".strip()


class VocalBridgeNotConfiguredError(RuntimeError):
    """VocalBridge dispatch is selected but no API key is configured."""


@dataclass(frozen=True)
class VocalBridgeCredentials:
    api_key: str
    agent_id: str | None
    api_url: str


def _env_file_values(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _configured_value(name: str, env_file: Path) -> str | None:
    value = (os.getenv(name) or "").strip()
    if value:
        return value
    value = (_env_file_values(env_file).get(name) or "").strip()
    return value or None


def vocalbridge_api_key(env_file: Path | None = None) -> str | None:
    return _configured_value(VOCALBRIDGE_API_KEY_ENV, env_file or DEFAULT_ENV_FILE_PATH)


def vocalbridge_agent_id(env_file: Path | None = None) -> str | None:
    return _configured_value(
        VOCALBRIDGE_AGENT_ID_ENV, env_file or DEFAULT_ENV_FILE_PATH
    )


def vocalbridge_api_url(env_file: Path | None = None) -> str:
    return (
        _configured_value(VOCALBRIDGE_API_URL_ENV, env_file or DEFAULT_ENV_FILE_PATH)
        or DEFAULT_VOCALBRIDGE_API_URL
    ).rstrip("/")


def vocalbridge_credentials(env_file: Path | None = None) -> VocalBridgeCredentials:
    api_key = vocalbridge_api_key(env_file)
    if not api_key:
        raise VocalBridgeNotConfiguredError(
            "VocalBridge voice dispatch is selected, but no VocalBridge API key "
            "is configured. Add one in voice dispatch settings, or switch back "
            "to the local LiveKit dispatcher."
        )
    return VocalBridgeCredentials(
        api_key=api_key,
        agent_id=vocalbridge_agent_id(env_file),
        api_url=vocalbridge_api_url(env_file),
    )


def load_vocalbridge_dispatcher_instructions() -> str:
    try:
        loaded = OPENBASE_VOCALBRIDGE_INSTRUCTIONS_PATH.read_text(
            encoding="utf-8"
        ).strip()
    except OSError:
        loaded = ""
    return loaded or VOCALBRIDGE_BUILTIN_DEVELOPER_INSTRUCTIONS
