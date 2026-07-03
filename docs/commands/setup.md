# setup

Run the full Openbase local installation flow.

## Usage

```bash
openbase-coder setup [OPTIONS]
```

## Backend Selection

Setup can choose the default coding backend:

```bash
openbase-coder setup --backend codex
openbase-coder setup --backend openbase_cloud
openbase-coder setup --backend claude-code
```

New env files default to `codex` when `--backend` is omitted.
Existing env files are left unchanged unless `--backend` is passed.

- `codex`: default native Codex app-server with OpenAI models.
- `openbase_cloud`: Codex-compatible sessions through the Openbase Cloud model
  proxy with Openbase login.
- `claude-code`: Claude Code backend using local Claude auth/billing for Super
  Agents UI-driver sessions.

For first-time setup without installing the CLI first, prefer `uvx`:

```bash
uvx --python 3.13 openbase-coder setup
```

For normal macOS installs, prefer the standalone package installer instead:

```bash
curl -fsSL https://raw.githubusercontent.com/openbase-community/openbase-coder/main/cli/scripts/install.sh | sh
openbase-coder setup
```

Standalone setup uses the bundled Python runtime, built console, shared
instructions, shared skills, and LiveKit server. It does not clone
`openbase-coder-workspace` unless `--dev-workspace` is passed.

With `--audio-provider local`, setup installs the optional Kokoro/MLX local
audio dependencies into the bundled Python runtime and downloads the required
models. Standalone packages should be built with Python 3.12 for this path
because Kokoro currently declares Python `<3.13`.

## Options

| Option | Default | Description |
|---|---|---|
| `--workspace-dir PATH` | `~/.openbase/workspace` | Workspace clone location |
| `--env-file PATH` | `~/.openbase/.env` | Shared environment file path |
| `--assembly-ai-api-key TEXT` | env `ASSEMBLY_AI_API_KEY` | Optional STT key |
| `--cartesia-api-key TEXT` | env `CARTESIA_API_KEY` | Optional TTS key |
| `--skip-clone` | `false` | Skip workspace clone/pull |
| `--dev-workspace` | `false` | Clone/sync the Openbase Coder workspace for development-mode runtime assets |
| `--skip-services` | `false` | Skip service install |
| `--link-codex-config` | `false` | Symlink Openbase's service Codex config to `~/.codex/config.toml` |
| `--json-progress` | `false` | Emit NDJSON step events on stdout for UI-driven setup; human-readable output moves to stderr |

## Behavior Details

`setup` runs on macOS (launchd) and Linux (systemd user services) and performs these phases:

1. Ensures `~/.openbase` exists.
2. Uses bundled runtime assets, or clones/pulls `openbase-coder-workspace` in dev-workspace mode.
3. Runs `multi sync` in dev-workspace mode.
4. Writes `installation.json` with the active runtime paths and `env_file`.
5. Creates `.env` with generated secrets if missing.
6. Symlinks `~/.openbase/codex_home/auth.json` to `~/.codex/auth.json` so launchd Codex services use the normal Codex login.
7. Links normal `~/.claude/CLAUDE.md` to `~/.codex/AGENTS.md`, preserving an existing real Claude instructions file by copying it into Codex AGENTS when Codex AGENTS is missing or backing it up when both files differ.
8. Regenerates `~/.openbase/codex_home/AGENTS.md` from the bundled package or workspace `instructions/AGENTS.md`. The generated file records its source template path and, by default, includes normal `~/.codex/AGENTS.md` content above the Openbase section.
9. Links `~/.openbase/claude_config/CLAUDE.md` to Openbase's generated `~/.openbase/codex_home/AGENTS.md`.
10. Renders shared default instruction files from the bundled package or workspace `instructions/` into `~/.openbase/instructions/`, and writes legacy Codex-home instruction copies as generated regular files.
11. Creates missing `~/.openbase/dispatcher-config.json` with default dispatcher reasoning effort `low`, default Super Agents reasoning effort `high`, and backend-specific default model settings, and keeps `~/.openbase/codex_home/dispatcher-config.json` as a legacy symlink.
12. Symlinks bundled or workspace skills into `~/.openbase/codex_home/skills` and `~/.openbase/claude_config/skills`.
13. Initializes `cli` with `uv sync` and LiveKit model downloads in dev-workspace mode.
14. Configures `~/.openbase/codex_home/config.toml` with full Codex local access (`sandbox_mode = "danger-full-access"`), disabled permission prompts, and the Super Agents MCP server. With `--link-codex-config`, this path is first linked to `~/.codex/config.toml`. The MCP command prefers the selected workspace's venv executable and falls back to the resolved local `uv` path.
15. Configures `~/.openbase/claude_config/.claude.json` with the Super Agents MCP server and writes `CLAUDE_CONFIG_DIR=~/.openbase/claude_config` into the shared `.env`.
16. Syncs normal Claude Code state into `~/.openbase/claude_config.json` when available. Claude Code OAuth still uses config-dir-scoped credentials; when `--backend claude-code` is selected, setup runs `openbase-coder claude login` if the managed Claude config is not already signed in.
17. Writes Codex app-server defaults like `CODEX_MODEL=gpt-5.5`, `CODEX_MODEL_REASONING_EFFORT=high`, `CODEX_SERVICE_TIER=standard`, `CODEX_APP_SERVER_URL`, and `LIVEKIT_CODEX_THREAD_CWD` into the shared `.env`. When `OPENBASE_CODING_BACKEND=openbase_cloud`, the app-server service switches to the Openbase Cloud model proxy at startup.
18. Uses the bundled console build, or builds `console` in dev-workspace mode.
19. Installs background services (launchd on macOS, systemd user units on Linux) unless skipped.
20. Configures Tailscale Serve routes for the iOS app:
    - `tailscale serve --bg --http=18080 http://127.0.0.1:7999`
    - `tailscale serve --bg --tcp=7880 tcp://127.0.0.1:7880`
21. Registers this device with Openbase cloud and reports `cli_configured`
    for the onboarding flow (warns and continues on failure; requires a prior
    `openbase-coder login`). See [`onboarding`](onboarding.md).

## JSON Progress

With `--json-progress`, setup emits one NDJSON event per line on stdout so a
UI (e.g. the Mac app's one-click setup) can render a live checklist; all
human-readable output — including subprocess output — is redirected to
stderr. Step ids, in order: `workspace`, `installation_config`, `env`,
`agent_config`, `services`, `tailscale_serve`, `cloud_report`.

```jsonc
{"event": "step", "id": "services", "status": "start", "detail": null}
{"event": "step", "id": "services", "status": "ok", "detail": null}
{"event": "step", "id": "tailscale_serve", "status": "warn", "detail": "tailscale was not found on PATH."}
{"event": "result", "ok": true, "cli_configured": true, "tailscale_serve_healthy": false}
```

`warn` steps are non-fatal. A hard failure emits a final `error` step event
and `{"event": "result", "ok": false, ...}`, and exits nonzero. The full
protocol is specified in the workspace `specs/onboarding/README.md`.

The generated env file records the selected backend as `OPENBASE_CODING_BACKEND`.
Older env files that still set `OPENBASE_CODEX_BACKEND` are supported as a
fallback.

## Example

```bash
uvx --python 3.13 openbase-coder setup \
  --workspace-dir ~/.openbase/workspace \
  --env-file ~/.openbase/.env
```

## Notes

- If `.env` already exists, setup leaves it unchanged.
- `~/.openbase/codex_home/AGENTS.md` is a generated regular file from `instructions/AGENTS.md`; setup rewrites it and records the source template path. A console setting controls whether normal `~/.codex/AGENTS.md` content is included above the Openbase section; the default is enabled.
- `~/.openbase/claude_config/CLAUDE.md` is a symlink to `~/.openbase/codex_home/AGENTS.md`. Normal `~/.claude/CLAUDE.md` is kept symlinked to `~/.codex/AGENTS.md`.
- Shared default instruction files under `~/.openbase/instructions` are generated regular files with source-template comments. Legacy files under `~/.openbase/codex_home/*_INSTRUCTIONS.md` are generated regular copies, not symlinks.
- If `dispatcher-config.json` already exists, setup preserves it. Legacy configs from `~/.openbase/codex_home/dispatcher-config.json` are migrated to `~/.openbase/dispatcher-config.json`.
- Existing skill symlinks in `~/.openbase/codex_home/skills` and `~/.openbase/claude_config/skills` are updated to the bundled or workspace source. Real skill directories or files are left unchanged.
- Existing `~/.openbase/codex_home/config.toml` content is preserved, except setup enforces the root permission keys and creates or replaces the `[mcp_servers.super-agents]` table. Passing `--link-codex-config` makes `~/.openbase/codex_home/config.toml` a symlink to `~/.codex/config.toml`; if the normal Codex config is missing, setup seeds it from the existing Openbase config before linking.
- If `npm`, `uv`, or `multi` are missing, related steps are skipped with messages.
- If Tailscale is missing or disconnected, setup prints the manual Serve
  commands and continues. `openbase-coder doctor` and `openbase-coder services
  status` fail until the Tailscale Serve routes and external Openbase health
  check pass.
