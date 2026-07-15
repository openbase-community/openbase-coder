# backend

View or switch the selected coding backend.

In the apps: **Settings → Coding Backend** in the
[desktop app](../desktop-app.md) and [console](../console.md) switches the
same setting; the desktop onboarding flow chooses it during first-time setup.

## Usage

```bash
openbase-coder backend status
openbase-coder backend list
openbase-coder backend use codex
```

## Supported Backends

- `codex`: default native Codex app-server backend.
- `openbase_cloud`: Codex-compatible backend through the Openbase Cloud model proxy.
- `claude_code`: Claude Code backend for Super Agents UI-driver sessions using local Claude auth/billing, not `ANTHROPIC_API_KEY`.

The command persists the selection in `~/.openbase/.env` as
`OPENBASE_CODING_BACKEND=<backend>`, the same setting written by
`openbase-coder setup --backend ...` and read by the local console.


The backend setting controls `super-agents-mcp` coding sessions. Codex and
Openbase Cloud use the local `codex-app-server` service; Claude Code bypasses
that service for Super Agents UI-driver sessions. In the apps, saving a changed
backend first asks for confirmation, then automatically restarts Openbase
services and recreates the dispatcher thread. The restart interrupts active
voice calls, may interrupt coding turns, and clears the current dispatcher
conversation context; it does not delete Super Agent threads or project files.
Separately running Codex or Claude clients may still need to be reopened so
their MCP process reloads the backend.

When switching with the CLI, restart Openbase services and recreate the
dispatcher explicitly so the new environment is loaded:

```bash
openbase-coder restart --recreate-dispatcher
```

For Claude Code, Openbase uses its managed `CLAUDE_CONFIG_DIR` at
`~/.openbase/claude_config`. Check and configure that scoped login with:

```bash
openbase-coder claude status
openbase-coder claude login
```
