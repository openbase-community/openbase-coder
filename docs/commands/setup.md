# setup

Run the full Openbase local installation flow.

## Usage

```bash
openbase-coder setup [OPTIONS]
```

For first-time setup without installing the CLI first, prefer `uvx`:

```bash
uvx --python 3.13 openbase-coder setup
```

## Options

| Option | Default | Description |
|---|---|---|
| `--workspace-dir PATH` | `~/.openbase/workspace` | Workspace clone location |
| `--env-file PATH` | `~/.openbase/.env` | Shared environment file path |
| `--assembly-ai-api-key TEXT` | env `ASSEMBLY_AI_API_KEY` | Optional STT key |
| `--cartesia-api-key TEXT` | env `CARTESIA_API_KEY` | Optional TTS key |
| `--skip-clone` | `false` | Skip workspace clone/pull |
| `--skip-services` | `false` | Skip launchd install |

## Behavior Details

`setup` is macOS-only and performs these phases:

1. Ensures `~/.openbase` exists.
2. Clones/pulls `openbase-coder-workspace`.
3. Runs `multi sync` if `multi` is available.
4. Writes `installation.json` with `workspace_path` and `env_file`.
5. Creates `.env` with generated secrets if missing.
6. Symlinks `~/.openbase/codex_home/auth.json` to `~/.codex/auth.json` so launchd Codex services use the normal Codex login.
7. Creates missing default instruction files in `~/.openbase/codex_home` from the workspace `instructions/` directory: `AGENTS.md`, `VOICE_INSTRUCTIONS.md`, `DISPATCHER_INSTRUCTIONS.md`, and `SUPER_AGENT_INSTRUCTIONS.md`.
8. Creates missing `~/.openbase/codex_home/dispatcher-config.json` with dispatcher reasoning effort `low` and Super Agents reasoning effort `high`.
9. Symlinks workspace skills from `skills/skills/` into `~/.openbase/codex_home/skills`.
10. Initializes `cli` with `uv sync` and LiveKit model downloads.
11. Configures `~/.openbase/codex_home/config.toml` with full Codex local access (`sandbox_mode = "danger-full-access"`), disabled permission prompts, and the Super Agents MCP server. The MCP command prefers the workspace venv executable and falls back to the resolved local `uv` path.
12. Writes Codex app-server defaults like `CODEX_MODEL=gpt-5.5`, `CODEX_MODEL_REASONING_EFFORT=high`, `CODEX_SERVICE_TIER=fast`, `CODEX_APP_SERVER_URL`, and `LIVEKIT_CODEX_THREAD_CWD` into the shared `.env`.
13. Builds `console`.
14. Installs launchd services unless skipped.

## Example

```bash
uvx --python 3.13 openbase-coder setup \
  --workspace-dir ~/.openbase/workspace \
  --env-file ~/.openbase/.env
```

## Notes

- If `.env` already exists, setup leaves it unchanged.
- If instruction files already exist in `~/.openbase/codex_home`, setup leaves them unchanged.
- If `dispatcher-config.json` already exists in `~/.openbase/codex_home`, setup leaves it unchanged.
- Existing skill symlinks in `~/.openbase/codex_home/skills` are updated to the workspace source. Real skill directories or files are left unchanged.
- Existing `~/.openbase/codex_home/config.toml` content is preserved, except setup enforces the root permission keys and creates or replaces the `[mcp_servers.super-agents]` table.
- If `npm`, `uv`, or `multi` are missing, related steps are skipped with messages.
