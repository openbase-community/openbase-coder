# Codebase Companion

Onboarding and architecture notes for ramping up on `openbase-coder`. Complements user-facing docs in `docs/` (commands, configuration, troubleshooting).

**Primary audience:** You — ramp-up and keep-up. Also useful for contributors and AI agents.

---

## Start Here

1. **[INDEX.md](./INDEX.md)** — Master index of all documents and diagrams
2. **[00_Learning_Path.md](./00_Learning_Path.md)** — Progressive curriculum (read this first)
3. **[CHANGELOG.md](./CHANGELOG.md)** — What was added or updated

---

## Naming Convention

| Pattern | Purpose |
|---------|---------|
| `INDEX.md` | Master document index |
| `CHANGELOG.md` | Companion doc change history |
| `00_<Topic>.md` | Evergreen guides (ordered by learning sequence) |
| `YYYY-MM-DD ELIF_<Topic>.md` | Dated exploration snapshots |

Add new dated ELIF files when architecture changes materially. Update CHANGELOG and INDEX when adding or changing docs.

---

## Quick Links

| Doc | Description |
|-----|-------------|
| [SESSION_LOG](./SESSION_LOG.md) | **Resume here** — status, decisions, session index |
| [Learning Path](./00_Learning_Path.md) | 4-level ramp-up with exercises |
| [Repo vs Workspace](./01_Repo_vs_Workspace.md) | Three-repo mental model |
| [Dev Cheatsheet](./02_Dev_Cheatsheet.md) | UV primer, commands, ports, paths |
| [Request Trace: Threads](./03_Request_Trace_Threads.md) | `GET /api/threads/` walkthrough |
| [ELIF Codebase (2026-06-18)](./2026-06-18%20ELIF_Codebase.md) | Full-repo snapshot |
| [ELIF Setup (2026-06-18)](./2026-06-18%20ELIF_Setup.md) | `setup.py` phase map |

---

## Official Docs

- [Getting Started](../getting-started.md)
- [Commands](../commands/index.md)
- [Files and Paths](../files-and-paths.md)
