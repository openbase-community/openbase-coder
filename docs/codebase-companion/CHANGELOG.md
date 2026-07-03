# Codebase Companion — Changelog

All notable additions and updates to `docs/codebase-companion/`.

Format based on [Keep a Changelog](https://keepachangelog.com/). This log tracks **companion documentation only**, not application code.

---

## [2026-06-18] — Initial companion library

### Added

- **INDEX.md** — Master index for all companion docs, diagrams, and planned topics
- **CHANGELOG.md** — This file
- **00_Learning_Path.md** — Progressive 4-level ramp-up curriculum with exercises
- **01_Repo_vs_Workspace.md** — Mental model for `openbase-coder` vs workspace vs `super-agents`
- **02_Dev_Cheatsheet.md** — Local dev commands, ports, paths, common workflows
- **03_Request_Trace_Threads.md** — End-to-end trace of `GET /api/threads/` with sequence diagram
- **2026-06-18 ELIF_Setup.md** — Phase map of `cli/setup.py` (~1200 lines) without line-by-line read
- **2026-06-18 ELIF_Codebase.md** — Full-repo orientation snapshot (from initial ELIF session)
- **README.md** — Folder purpose, naming conventions, index stub

### Updated

- **docs/index.md** — Link to codebase companion from main docs index

### Notes

- Entry point chosen: **Learning Path → Repo vs Workspace → Dev Cheatsheet → Request Trace**, not `setup.py` (too deep for day 1)
- `setup.py` deferred to Level 3 via ELIF_Setup phase map
- Assumes `../super-agents` is always present in local dev layout

---

## [2026-06-19] — Session log infrastructure

### Added

- **SESSION_LOG.md** — Rolling quick status, decisions log, changes log, maintenance instructions
- **sessions/2026-06-19 Session_RampUp.md** — Full narrative for ramp-up + dev bootstrap session

### Updated

- **INDEX.md** — Session summaries section; "resume here" points to SESSION_LOG

---

## [2026-06-19] — Dev sync script + Python 3.13 pin

### Added

- **scripts/dev-sync.sh** — Clones `../super-agents` if missing; runs `uv sync --extra dev --python 3.13`
- **.python-version** — Pins `3.13` for `uv` and `pyenv`

### Updated

- **pyproject.toml** — `requires-python = ">=3.13,<3.14"` (blocks 3.14; fixes `spacy` cp313 wheel issue)
- **README.md** — Development section uses `./scripts/dev-sync.sh`
- **02_Dev_Cheatsheet.md** — Canonical dev-sync flow, Python 3.13 errors table
- **00_Learning_Path.md** — Level 1 step 1.0 uses `dev-sync.sh`

---

### Updated

- **02_Dev_Cheatsheet.md** — "Clone super-agents first" prerequisite, error/fix, Common Issues entry
- **01_Repo_vs_Workspace.md** — Clone instructions; removed "always present" assumption
- **00_Learning_Path.md** — Level 1 step 1.0: clone super-agents before `uv sync`

---

## [2026-06-18] — UV & Python primer

### Updated

- **02_Dev_Cheatsheet.md** — Added "UV & Python Primer" section (first-30-minutes command breakdown)
- **00_Learning_Path.md** — Level 1 step 1.3 links to UV primer
- **INDEX.md** — Quick nav entry for UV primer; updated cheatsheet time estimate

---

## Template for future entries

```markdown
## [YYYY-MM-DD] — Short title

### Added
- **filename.md** — One-line description

### Updated
- **filename.md** — What changed

### Deprecated / Removed
- **filename.md** — Reason
```
