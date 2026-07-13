from __future__ import annotations

CODEX_BACKEND = "codex"
OPENBASE_CLOUD_BACKEND = "openbase_cloud"
CLAUDE_CODE_BACKEND = "claude_code"
SUPPORTED_BACKENDS = (CODEX_BACKEND, OPENBASE_CLOUD_BACKEND, CLAUDE_CODE_BACKEND)
DEFAULT_CODING_BACKEND = "codex"
CODING_BACKEND_ENV_KEY = "OPENBASE_CODING_BACKEND"
# Per-process launch-default override read by super-agents-mcp: set in each
# MCP server registration so spawned Super Agents default to the spawning
# session's own backend type. Explicit per-spawn backend params still win.
SUPER_AGENTS_DEFAULT_BACKEND_ENV_KEY = "SUPER_AGENTS_DEFAULT_BACKEND"
BACKEND_ALIASES = {
    "codex": CODEX_BACKEND,
    "openbase cloud": OPENBASE_CLOUD_BACKEND,
    "claude code": CLAUDE_CODE_BACKEND,
}


def normalize_backend(value: str | None) -> str:
    raw = _normalize_backend_alias(value)
    if not raw:
        return DEFAULT_CODING_BACKEND
    aliases = {
        _normalize_backend_alias(alias): backend
        for alias, backend in BACKEND_ALIASES.items()
    }
    try:
        return aliases[raw]
    except KeyError as exc:
        supported = ", ".join(SUPPORTED_BACKENDS)
        raise ValueError(
            f"Unsupported backend: {value}. Supported backends: {supported}."
        ) from exc


def _normalize_backend_alias(value: str | None) -> str:
    raw = (value or "").strip().lower()
    return " ".join(raw.replace("_", " ").replace("-", " ").split())
