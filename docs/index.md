# Openbase CLI

The Openbase CLI (`openbase-coder`) runs your local Openbase runtime on macOS.

It provides:

- A local Django API + WebSocket server for Codex threads, turns, and diffs
- One-command setup for bundled runtime assets, `.env` generation, and service install
- Launchd service lifecycle management (`openbase-coder services ...`)
- Plugin lifecycle + bootstrap execution (`openbase-coder plugins ...`, `openbase-coder bootstrap ...`)
- Authentication flows for local token auth and Openbase JWT auth
- A backend used directly by the Openbase iOS app

## Quick Start

```bash
# Install the standalone macOS package
curl -fsSL https://github.com/openbase-community/openbase-coder/releases/latest/download/install.sh | sh

# Bootstrap Openbase locally
openbase-coder setup

# Run server in foreground
openbase-coder server --host 0.0.0.0 --port 7999
```

For source development, use:

```bash
uvx --python 3.13 openbase-coder setup --dev-workspace
```

## Documentation

- [Getting Started](getting-started.md)
- [Cloud DevSpace](cloud-devspace.md)
- [Downloads](downloads.md)
- [Manual Setup](manual-installation.md)
- [Local-Only Mode](local-only.md)
- [Uninstall](uninstall.md)
- [Commands](commands/index.md)
- [Configuration](configuration.md)
- [Files and Paths](files-and-paths.md)
- [iOS App](ios-tabs.md)
- [Release](release.md)
- [Troubleshooting](troubleshooting.md)
- [Codebase Companion](codebase-companion/INDEX.md) — ramp-up guides, architecture notes, and learning path
