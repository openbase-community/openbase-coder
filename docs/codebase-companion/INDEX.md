# Codebase Companion — Document Index

**Primary audience:** You (ramp-up and keep-up), plus contributors and AI agents.  
**Location:** `docs/codebase-companion/`  
**Convention:** `YYYY-MM-DD ELIF_<Topic>.md` for dated snapshots; `NN_<Topic>.md` for evergreen guides.

---

## Start Here

| Order | Document | Type | Time | What you get |
|-------|----------|------|------|--------------|
| 1 | [00_Learning_Path](./00_Learning_Path.md) | Guide | 10 min | Ordered curriculum — **read this first** |
| 2 | [01_Repo_vs_Workspace](./01_Repo_vs_Workspace.md) | Guide | 15 min | Two-repo mental model + coupling diagram |
| 3 | [2026-06-18 ELIF_Codebase](./2026-06-18%20ELIF_Codebase.md) | Snapshot | 20 min | Full-repo orientation (skim, refer back) |
| 4 | [02_Dev_Cheatsheet](./02_Dev_Cheatsheet.md) | Reference | 10 min | UV primer, commands, ports, paths, env vars |
| 5 | [03_Request_Trace_Threads](./03_Request_Trace_Threads.md) | Walkthrough | 30 min | Trace one API path end-to-end |

---

## Evergreen Guides

| Document | Status | Description |
|----------|--------|-------------|
| [00_Learning_Path](./00_Learning_Path.md) | Active | Progressive ramp-up curriculum with exercises |
| [01_Repo_vs_Workspace](./01_Repo_vs_Workspace.md) | Active | This repo vs workspace clone vs `super-agents` |
| [02_Dev_Cheatsheet](./02_Dev_Cheatsheet.md) | Active | Day-to-day dev commands and troubleshooting |
| [03_Request_Trace_Threads](./03_Request_Trace_Threads.md) | Active | `GET /api/threads/` trace with sequence diagram |
| [README](./README.md) | Active | Folder purpose and naming conventions |

---

## Dated ELIF Snapshots

Point-in-time exploration notes. Add new files when architecture changes; do not rewrite old snapshots.

| Date | Document | Scope |
|------|----------|-------|
| 2026-06-18 | [ELIF_Codebase](./2026-06-18%20ELIF_Codebase.md) | Full-repo orientation |
| 2026-06-18 | [ELIF_Setup](./2026-06-18%20ELIF_Setup.md) | `setup.py` phase map (read after Level 2) |

---

## Planned (not yet written)

| Document | Priority | Trigger |
|----------|----------|---------|
| `04_Request_Trace_WebSocket.md` | High | After completing Level 2 |
| `2026-06-XX ELIF_LiveKit.md` | Medium | Before touching voice code |
| `2026-06-XX ELIF_Session_Manager.md` | Medium | Before thread/MCP changes |
| `2026-06-XX ELIF_Plugins.md` | Low | Before plugin work |
| `05_Test_Map.md` | Medium | When navigating `tests/` |
| `ARCHITECTURE.md` | Low | Consolidate diagrams from ELIFs |

---

## Diagrams & Artifacts

| Artifact | Location | Description |
|----------|----------|-------------|
| Dev bootstrap script | `scripts/dev-sync.sh` | Clone super-agents + `uv sync` with Python 3.13 |
| Python version pin | `.python-version` | Tells uv/pyenv to use 3.13 |
| System architecture (mermaid) | [ELIF_Codebase](./2026-06-18%20ELIF_Codebase.md#architecture) | Clients → CLI → services → data |
| Repo vs workspace (mermaid) | [01_Repo_vs_Workspace](./01_Repo_vs_Workspace.md) | Three-repo dev layout |
| Setup phase flow (mermaid) | [ELIF_Setup](./2026-06-18%20ELIF_Setup.md) | `openbase-coder setup` pipeline |
| Thread list request (mermaid) | [03_Request_Trace_Threads](./03_Request_Trace_Threads.md) | HTTP → Django → Codex |

---

## Meta

| Document | Purpose |
|----------|---------|
| [SESSION_LOG](./SESSION_LOG.md) | **Resume here** — quick status, decisions, changes, session index |
| [CHANGELOG](./CHANGELOG.md) | History of companion doc additions and updates |
| [README](./README.md) | Naming conventions and folder overview |

### Session summaries

| Date | Session |
|------|---------|
| 2026-06-19 | [Ramp-up & dev bootstrap](./sessions/2026-06-19%20Session_RampUp.md) |

---

## External Docs (official)

| Document | Path |
|----------|------|
| Getting Started | [docs/getting-started.md](../getting-started.md) |
| Commands | [docs/commands/index.md](../commands/index.md) |
| Files and Paths | [docs/files-and-paths.md](../files-and-paths.md) |
| Configuration | [docs/configuration.md](../configuration.md) |
| Troubleshooting | [docs/troubleshooting.md](../troubleshooting.md) |

---

## Quick Navigation by Goal

| I want to… | Go to |
|------------|-------|
| Understand what this repo is | [01_Repo_vs_Workspace](./01_Repo_vs_Workspace.md) → [ELIF_Codebase](./2026-06-18%20ELIF_Codebase.md) |
| Learn `uv` and first commands | [02_Dev_Cheatsheet — UV primer](./02_Dev_Cheatsheet.md#uv--python-primer) |
| Fix `uv sync` / Python / super-agents errors | [02_Dev_Cheatsheet — Prerequisites](./02_Dev_Cheatsheet.md#clone-super-agents--sync-dependencies-required) or run `./scripts/dev-sync.sh` |
| Run the project locally | [02_Dev_Cheatsheet](./02_Dev_Cheatsheet.md) |
| Understand how API calls work | [03_Request_Trace_Threads](./03_Request_Trace_Threads.md) |
| Understand first-time install | [ELIF_Setup](./2026-06-18%20ELIF_Setup.md) |
| See where we left off | [SESSION_LOG](./SESSION_LOG.md) |
| See what changed in companion docs | [CHANGELOG](./CHANGELOG.md) |
