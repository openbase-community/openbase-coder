# Session: Ramp-up & Dev Bootstrap

**Date:** 2026-06-18 – 2026-06-19  
**Participant:** Siddharth (+ Cursor agent)  
**Index:** [SESSION_LOG.md](../SESSION_LOG.md)

---

## Goal

Ramp up on `openbase-coder`, build durable onboarding docs, and get a working local dev environment.

---

## What we did

### 1. Codebase orientation (ELIF)

- Explored full repo: CLI, Django API, LiveKit voice worker, services, plugins, MCP
- Created initial snapshot: [2026-06-18 ELIF_Codebase](../2026-06-18%20ELIF_Codebase.md)

### 2. Companion documentation library

Built `docs/codebase-companion/`:

| Doc | Purpose |
|-----|---------|
| [INDEX.md](../INDEX.md) | Master index |
| [00_Learning_Path.md](../00_Learning_Path.md) | 4-level progressive curriculum |
| [01_Repo_vs_Workspace.md](../01_Repo_vs_Workspace.md) | Three-repo mental model |
| [02_Dev_Cheatsheet.md](../02_Dev_Cheatsheet.md) | Commands + UV primer |
| [03_Request_Trace_Threads.md](../03_Request_Trace_Threads.md) | API trace walkthrough |
| [2026-06-18 ELIF_Setup.md](../2026-06-18%20ELIF_Setup.md) | `setup.py` phase map |
| [CHANGELOG.md](../CHANGELOG.md) | Doc change history |

**Clarifications captured from you:**

- Primary audience: you (ramp-up/keep-up), plus contributors and agents
- `super-agents` always present in intended dev layout (sibling repo)
- Entry path: foundation first, not `setup.py` linear read
- Docs location: `docs/codebase-companion/` (linked from `docs/index.md`, `AGENTS.md`)

### 3. Dev environment blockers & fixes

#### Blocker A: Missing `super-agents`

```text
error: Distribution not found at: file:///.../super-agents
```

**Fix:** Clone `https://github.com/montaguegabe/super-agents.git` to `../super-agents`.

#### Blocker B: Python 3.14 / spacy wheels

```text
spacy==3.8.14 ... only has wheels ... cp313
You're using CPython 3.14 (cp314)
```

**Root cause:** `uv` picked pyenv 3.14.2; `kokoro` → `spacy` only publishes cp313 wheels.

**Repo-wide fix:**

| File | Change |
|------|--------|
| `pyproject.toml` | `requires-python = ">=3.13,<3.14"` |
| `.python-version` | `3.13` |
| `scripts/dev-sync.sh` | Clone sibling + `uv sync --extra dev --python 3.13` |
| `README.md`, `AGENTS.md` | Document bootstrap script |
| `openbase_coder_cli/cli/setup.py` | `_init_cli_workspace` passes `--python 3.13` to workspace `uv sync` |
| `uv.lock` | Regenerated for 3.13 |

### 4. Verification

```bash
./scripts/dev-sync.sh
uv run pytest -q
```

**Result:** 468 passed, 3 warnings.

---

## Key decisions

1. **Canonical dev command:** `./scripts/dev-sync.sh` (not bare `uv sync`)
2. **Python 3.13 only** until dependencies support 3.14
3. **Session continuity:** `SESSION_LOG.md` + dated session files in `sessions/`

---

## Files touched (uncommitted at session end)

```
 M AGENTS.md
 M README.md
 M docs/index.md
 M openbase_coder_cli/cli/setup.py
 M pyproject.toml
 M uv.lock
?? .python-version
?? docs/codebase-companion/
?? scripts/dev-sync.sh
```

Note: `openbase_coder_cli/cli/setup.py` was already modified at session start; we added `--python 3.13` to workspace init commands.

---

## Open items / next session

| Priority | Item |
|----------|------|
| High | Level 2: complete [03_Request_Trace_Threads](../03_Request_Trace_Threads.md) exercise |
| Medium | Commit companion docs + dev bootstrap tooling |
| Low | Inspect 3 pytest warnings |
| Planned doc | `04_Request_Trace_WebSocket.md` after Level 2 |

---

## Commands reference (working state)

```bash
cd openbase-coder
./scripts/dev-sync.sh
uv run pytest -q
uv run openbase-coder server --reload --skip-collectstatic
curl -s http://127.0.0.1:7999/api/health/
```

---

## Related docs

- [00_Learning_Path](../00_Learning_Path.md) — where to go next
- [02_Dev_Cheatsheet](../02_Dev_Cheatsheet.md) — UV primer and troubleshooting
- [01_Repo_vs_Workspace](../01_Repo_vs_Workspace.md) — three-repo layout
