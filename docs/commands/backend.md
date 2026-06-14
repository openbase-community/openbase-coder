# backend

View or switch the selected coding backend.

## Usage

```bash
openbase-coder backend status
openbase-coder backend list
openbase-coder backend use codex
```

## Supported Backends

- `codex`: default native Codex app-server backend.
- `claude-agent-sdk`: Claude Agent SDK backend for Super Agents UI-driver sessions using local Claude auth/billing, not `ANTHROPIC_API_KEY`.
- `claude-tui`: local Claude Code CLI/TUI backend.

The command persists the selection in `~/.openbase/.env` as
`OPENBASE_CODING_BACKEND=<backend>`, the same setting written by
`openbase-coder setup --backend ...` and read by the local console.
Older installs that still set `OPENBASE_CODEX_BACKEND` are supported as a
fallback.

The backend setting controls `super-agents-mcp` coding sessions. The voice
dispatcher still needs the local `codex-app-server` service, so keep Openbase
services running for any backend. After switching backend, restart or recreate
the dispatcher/MCP host so `super-agents-mcp` reloads its environment.
