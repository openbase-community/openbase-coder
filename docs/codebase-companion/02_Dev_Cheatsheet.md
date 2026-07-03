# Dev Cheatsheet

**Quick reference for local development.**  
**Index:** [INDEX.md](./INDEX.md)

---

## Prerequisites

| Tool | Version | Notes |
|------|---------|-------|
| Python | 3.13+ (3.13 recommended) | Required by `pyproject.toml` |
| uv | latest | Package manager |
| **super-agents** | `../super-agents/` | **Required sibling repo** — clone before `uv sync` (see below) |

Optional for full runtime: Git, npm, `livekit-server`, Tailscale.

### Clone `super-agents` + sync dependencies (required)

`pyproject.toml` pins `super-agents` as a **local editable** dependency at `../super-agents`. The project also requires **Python 3.13** (not 3.14) — dependencies like `spacy` (via `kokoro`) only ship `cp313` wheels.

**Canonical one-shot setup:**

```bash
cd openbase-coder
./scripts/dev-sync.sh
```

This script clones `../super-agents` if missing and runs `uv sync --extra dev --python 3.13`.

**Manual equivalent:**

```bash
cd /path/to/parent/of/openbase-coder
git clone https://github.com/montaguegabe/super-agents.git   # if missing
cd openbase-coder
uv sync --extra dev --python 3.13
```

Expected layout:

```text
parent/
├── openbase-coder/    ← this repo (.python-version → 3.13)
└── super-agents/      ← sibling repo
```

### Common errors

| Error | Cause | Fix |
|-------|-------|-----|
| `Distribution not found at: .../super-agents` | Sibling repo not cloned | Run `./scripts/dev-sync.sh` |
| `spacy ... only has wheels ... cp313` (you're on `cp314`) | Python 3.14 selected | Use 3.13: `./scripts/dev-sync.sh` or `uv sync --python 3.13` |

**Why Python 3.13 is pinned:** `requires-python = ">=3.13,<3.14"` in `pyproject.toml` and `.python-version` in the repo root tell `uv` and `pyenv` to use 3.13.

**Alternative (PyPI super-agents, no local edits):** Comment out `[tool.uv.sources]` for `super-agents` in `pyproject.toml`, then run `uv sync --extra dev --python 3.13`.

---

## UV & Python Primer

For developers new to **uv** or Python project tooling. See also [00_Learning_Path](./00_Learning_Path.md) Level 1 exercises.

### What is `uv`?

**uv** is a fast Python package and project manager — a modern combo of `pip` + virtualenv + lockfile tooling. In this repo it:

- Reads dependencies from `pyproject.toml` and `uv.lock`
- Creates and uses a project virtual environment (`.venv/`)
- Installs packages into that environment
- Runs commands inside it via `uv run`

You do **not** need to run `source .venv/bin/activate` when using `uv run`.

### First 30 minutes — command breakdown

**Before step 1:** Run `./scripts/dev-sync.sh` once ([Prerequisites](#clone-super-agents--sync-dependencies-required)).

```bash
cd openbase-coder
./scripts/dev-sync.sh          # or: uv sync --extra dev --python 3.13
uv run pytest -q
uv run openbase-coder server --reload --skip-collectstatic
# separate terminal:
curl -s http://127.0.0.1:7999/api/health/
```

| Command | What it does |
|---------|--------------|
| `uv sync --extra dev` | Install/sync all project dependencies into `.venv`. `--extra dev` also installs the optional **dev** group from `pyproject.toml` (pytest, ruff, etc.). Run after clone and when dependencies change. |
| `uv run pytest -q` | Run the test suite inside `.venv`. `pytest` discovers tests in `tests/`. `-q` = **quiet** (less output; failures still shown). |
| `uv run openbase-coder server` | Run the `openbase-coder` CLI from **this repo's code** (not a global install). `server` starts the local Django/ASGI API. |
| `--reload` | Auto-restart the server when you edit Python files (development mode). |
| `--skip-collectstatic` | Skip gathering static files on startup — faster for API-only dev. |
| `curl -s http://127.0.0.1:7999/api/health/` | `curl` makes an HTTP request from the terminal. `-s` = silent (no progress meter). Confirms the server is up. |

### How they fit together

```text
uv sync --extra dev     →  install deps + dev tools into .venv
uv run pytest -q        →  verify tests pass
uv run openbase-coder server ...  →  start API on port 7999
curl .../api/health/    →  confirm server responds
```

### `uv run` vs global `openbase-coder`

| Approach | When to use |
|----------|-------------|
| `uv run openbase-coder ...` | Developing **this repo** — always runs local source |
| `openbase-coder ...` after `uv tool install` | Daily use after setup — runs the installed tool |

For ramp-up in this repository, prefer `uv run`.

### Other `uv` commands you may see

| Command | Meaning |
|---------|---------|
| `uv run <command>` | Run any command inside the project `.venv` |
| `uv run ruff check ...` | Run the linter (dev dependency) |
| `uv tool install openbase-coder` | Install CLI globally as a persistent tool |
| `uvx openbase-coder setup` | Run published package once without installing (end-user flow) |

---

## Repo-Only Dev (start here)

```bash
# one-time: ./scripts/dev-sync.sh  (see Prerequisites)
cd openbase-coder
uv sync --extra dev --python 3.13
uv run openbase-coder --version
uv run pytest                    # full suite
uv run pytest tests/test_threads_api.py -v   # one file
```

**Run API server (foreground, hot reload):**

```bash
uv run openbase-coder server --reload --host 127.0.0.1 --port 7999
```

Useful flags:

| Flag | Effect |
|------|--------|
| `--reload` | Auto-restart on code changes (uvicorn) |
| `--skip-migrations` | Skip DB migrate on startup |
| `--skip-collectstatic` | Faster startup when not serving static assets |

**Smoke test:**

```bash
curl -s http://127.0.0.1:7999/api/health/
```

---

## Full Runtime (after setup)

```bash
openbase-coder setup                    # first time
openbase-coder doctor                   # health check
openbase-coder services status          # background jobs
openbase-coder services logs django-cli # tail API logs
openbase-coder services restart         # bounce all services
```

**Foreground server vs background service:**  
`openbase-coder server` is for dev. `django-cli` service is the same app via launchd/systemd for daily use.

---

## Ports & Services

| Service | Default port | Protocol |
|---------|--------------|----------|
| `django-cli` | 7999 | HTTP + WebSocket |
| `livekit-server` | 7880 (signaling), 7881/7882 (RTC) | WebSocket / UDP |
| `codex-app-server` | 4500 | WebSocket |
| Tailscale Serve (HTTP) | 18080 → 7999 | HTTP proxy for iOS |

Source: `openbase_coder_cli/services/definitions.py`

---

## Key Paths

| Path | Contents |
|------|----------|
| `~/.openbase/` | Runtime data root |
| `~/.openbase/installation.json` | Workspace + env file pointers |
| `~/.openbase/.env` | Secrets and config |
| `~/.openbase/workspace/` | Cloned workspace meta-repo |
| `~/.openbase/codex_home/` | Voice Codex session home |
| `~/.openbase/logs/` | Service stdout/stderr |
| `~/.openbase/db.sqlite3` | Django SQLite (minimal state) |

---

## Important Env Vars

| Variable | Purpose |
|----------|---------|
| `OPENBASE_CODER_CLI_DATA_DIR` | Override `~/.openbase` |
| `OPENBASE_CODER_CLI_SECRET_KEY` | Django secret (auto-generated by server) |
| `OPENBASE_CODER_CLI_DEBUG` | `true` for Django debug |
| `OPENBASE_CODING_BACKEND` | `codex`, `claude-agent-sdk`, `claude-tui` |
| `CODEX_APP_SERVER_URL` | Default `ws://127.0.0.1:4500` |
| `LIVEKIT_URL` | Default `ws://localhost:7880` |
| `OPENBASE_CODER_CLI_WEB_BACKEND_URL` | Openbase Cloud for JWT auth |

Full list: [docs/configuration.md](../configuration.md)

---

## Code Navigation Shortcuts

| I need… | Go to |
|---------|-------|
| CLI command registration | `openbase_coder_cli/cli/__init__.py` |
| API routes | `openbase_coder_cli_app/urls.py` |
| Thread endpoints | `openbase_coder_cli_app/threads.py` |
| Codex session logic | `mcp/session_manager.py` |
| WebSocket handlers | `openbase_coder_cli_app/consumers.py` |
| Voice worker entry | `livekit_agent/livekit.py` |
| Service install | `services/definitions.py`, `services/launchd.py` |
| Setup pipeline | `cli/setup.py` → see [ELIF_Setup](./2026-06-18%20ELIF_Setup.md) |
| Plugin registry | `plugins/store.py`, `plugins/manager.py` |

---

## Common Issues

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `Distribution not found at: .../super-agents` | Sibling repo not cloned | Run `./scripts/dev-sync.sh` |
| `spacy ... only has wheels ... cp313` | Python 3.14 used | Run `./scripts/dev-sync.sh` or `uv sync --python 3.13` |
| `installation.json not found` | Setup never run | `openbase-coder setup` or repo-only dev without service commands |
| Thread APIs error / timeout | `codex-app-server` not running | `openbase-coder services status`, start services |
| `SECRET_KEY is not set` | Missing `.env` | Run server once (auto-generates) or run setup |
| Console blank / 404 | Console not built | Run setup or build workspace `console/` |
| `uv sync` fails on super-agents | Wrong path or repo missing | Ensure `../super-agents` exists and contains `pyproject.toml` |
| WebSocket closes 4001 | No auth token | Login or use local token auth |

More: [docs/troubleshooting.md](../troubleshooting.md)

---

## Git Sync (fork workflow)

Interactive tool for diagnosing local vs `origin`/`upstream` divergence, predicting conflicts, and running a safe **feature branch → commit → push → PR** workflow.

**Requires:** `git`, `gh` (authenticated), `origin` + `upstream` remotes configured.

```bash
# Full interactive session
./scripts/git-sync.sh

# Diagnose only (no writes)
./scripts/git-sync.sh --dry-run

# Include merge-tree conflict prediction
./scripts/git-sync.sh --dry-run --deep

# Resume after resolving a rebase/merge conflict
./scripts/git-sync.sh --continue
```

**Typical flow when `main` has local changes and upstream is ahead:**

1. Script fetches `origin` and `upstream`, shows overlap with upstream commits
2. Recommends creating a feature branch (never commit directly on `main`)
3. Stashes or WIP-commits depending on dirty-tree state
4. Rebases or merges `upstream/main` (context-dependent)
5. Suggests a conventional commit message, pushes to `origin`, opens PR against upstream parent via `gh`

**Flags:** `--base-branch`, `--allow-secrets`, `--no-verify` (see `./scripts/git-sync.sh --help`).

---

## Lint & Format

```bash
uv run ruff check openbase_coder_cli tests
uv run ruff format openbase_coder_cli tests
```

---

## Related

- [00_Learning_Path](./00_Learning_Path.md)
- [01_Repo_vs_Workspace](./01_Repo_vs_Workspace.md)
- [03_Request_Trace_Threads](./03_Request_Trace_Threads.md)
