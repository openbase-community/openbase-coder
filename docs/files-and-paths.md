# Files and Paths

This page lists the key files Openbase CLI creates or consumes.

## Base Directories

- Openbase data root: `~/.openbase`
- Workspace clone (default): `~/.openbase/workspace`
- Launchd plists: `~/Library/LaunchAgents`

## Setup-Time Artifacts

| Path | Created By | Purpose |
|---|---|---|
| `~/.openbase/installation.json` | `openbase-coder setup` | Stores `workspace_path` + `env_file` |
| `~/.openbase/.env` | `openbase-coder setup` | Shared env config and generated secrets |
| `~/.openbase/codex_home/auth.json` | `openbase-coder setup` | Symlink to `~/.codex/auth.json` for launchd Codex services |
| `~/.openbase/codex_home/AGENTS.md` | `openbase-coder setup` | Default instructions for the Openbase voice Codex home |
| `~/.openbase/codex_home/VOICE_INSTRUCTIONS.md` | `openbase-coder setup` | Default direct voice-session instructions |
| `~/.openbase/codex_home/DISPATCHER_INSTRUCTIONS.md` | `openbase-coder setup` | Default dispatcher-only instructions |
| `~/.openbase/codex_home/SUPER_AGENT_INSTRUCTIONS.md` | `openbase-coder setup` | Default Super Agent thread instructions |
| `~/.openbase/codex_home/dispatcher-config.json` | `openbase-coder setup`, user/MCP commands | Dispatcher runtime settings, including dispatcher and Super Agents reasoning effort |
| `~/.openbase/codex_home/config.toml` | `openbase-coder setup` | Openbase service Codex config, including broad local access and the Super Agents MCP server |
| `~/.openbase/codex_home/skills/<skill>/` | `openbase-coder setup` | Symlink to a workspace-owned skill source under `skills/skills/<skill>/` |
| `~/.openbase/workspace/` | `openbase-coder setup` | Openbase workspace repo clone |
| `~/.openbase/workspace/cli/.venv/` | `openbase-coder setup` | CLI and bundled LiveKit worker environment |

The four instruction files above are seeded from the workspace `instructions/`
directory and are only created when missing.
The dispatcher config is created when missing with dispatcher reasoning effort
`low` and Super Agents reasoning effort `high`; setup does not overwrite an
existing dispatcher config.
Workspace skills are symlink-installed, not copied, so edits to source skills
are visible to the Openbase Codex home immediately.
The Codex home config grants full local sandbox access, disables permission
prompts, and uses the workspace venv Super Agents MCP executable when available;
otherwise setup records the resolved absolute `uv` path for the current machine.

## Service Artifacts

| Path Pattern | Created By | Purpose |
|---|---|---|
| `~/.openbase/launchd/<service>.sh` | `services install/regenerate` | Launch wrappers |
| `~/Library/LaunchAgents/com.openbase.coder.<service>.plist` | `services install/regenerate` | launchd job definitions |
| `~/.openbase/logs/<service>.stdout.log` | launchd services | Service stdout logs |
| `~/.openbase/logs/<service>.stderr.log` | launchd services | Service stderr logs |

Wrappers for `codex-app-server`, `livekit-agent`, and `django-cli` prefer binaries from
`<workspace>/.venv/bin/`, then `<workspace>/cli/.venv/bin/`, then
`<workspace>/agent/.venv/bin/`
so launchd follows the configured workspace checkout.

Managed services:

- `livekit-server`
- `codex-app-server`
- `livekit-agent`
- `django-cli`

## Runtime Data

| Path | Written By | Purpose |
|---|---|---|
| `~/.openbase/db.sqlite3` | Django migrations/runtime | App DB for local CLI state |
| `~/.openbase/staticfiles/` | `collectstatic` | Served static assets |
| `~/.openbase/coder-projects.json` | Session/project APIs | Recent project tracking |
| `~/.openbase/auth.json` | `openbase-coder login` | Access/refresh tokens |

## Plugin Data

| Path | Written By | Purpose |
|---|---|---|
| `~/.openbase/plugins/plugins.json` | `openbase-coder plugins add/update/remove` | Installed plugin registry |
| `~/.openbase/plugins/plugin_requirements.txt` | plugin lifecycle commands | Untracked plugin pip requirements ledger |
| `~/.openbase/plugins/sources/` | `plugins add/update` (GitHub sources) | Local clones used for pinned installs |
| `~/.openbase/plugins/console/registry.json` | plugin lifecycle commands | Generated console registry metadata |
| `~/.openbase/plugins/skills_ownership.json` | plugin lifecycle commands | Ownership map for globally synced skills |
| `~/.claude/skills/<plugin_id>__<skill_name>/SKILL.md` | plugin lifecycle commands | Plugin-declared global agent skills |

## Console and API Routes (Used by iOS)

| Route | Used By |
|---|---|
| `/api/threads/` | Threads tab |
| `/api/projects/recent/` | Threads tab |
| `/api/git/diff/` and `/dashboard/diff` | Diff tab |
| `/ws/threads/` | Threads tab global turn updates |
| `/ws/threads/<thread_id>/` | Thread detail realtime updates |

## Plugin API Routes

| Route | Purpose |
|---|---|
| `/api/plugins/` | List installed plugins and capabilities |
| `/api/plugins/<plugin_id>/` | Show one plugin |
| `/api/plugins/console-registry/` | Return generated console registry metadata |
| `/api/bootstrap/<bootstrapper_name>/` | Run bootstrapper by name |
| `/api/plugins/<plugin_id>/...` | Plugin-declared Django URL modules (if provided) |
