from __future__ import annotations

SUPPORTED_BACKENDS = ("codex", "claude-agent-sdk", "claude-tui")
DEFAULT_CODING_BACKEND = "codex"
CODING_BACKEND_ENV_KEY = "OPENBASE_CODING_BACKEND"
LEGACY_CODEX_BACKEND_ENV_KEY = "OPENBASE_CODEX_BACKEND"
BACKEND_ALIASES = {
    "codex": "codex",
    "openai": "codex",
    "claude": "claude-agent-sdk",
    "claude-code": "claude-agent-sdk",
    "claude-agent": "claude-agent-sdk",
    "claude-agent-sdk": "claude-agent-sdk",
    "claude-sdk": "claude-agent-sdk",
    "claude-tui": "claude-tui",
    "claude-code-tui": "claude-tui",
}


def normalize_backend(value: str | None) -> str:
    raw = (value or "").strip().lower()
    if not raw:
        return DEFAULT_CODING_BACKEND
    try:
        return BACKEND_ALIASES[raw]
    except KeyError as exc:
        supported = ", ".join(SUPPORTED_BACKENDS)
        raise ValueError(
            f"Unsupported backend: {value}. Supported backends: {supported}."
        ) from exc
