# Openbase CLI

The Openbase CLI (`openbase-coder`) runs your local Openbase runtime on macOS.

It provides:

- A local Django API + WebSocket server for Codex threads, turns, and diffs
- One-command setup for workspace clone, `.env` generation, and service install
- Launchd service lifecycle management (`openbase-coder services ...`)
- Plugin lifecycle + bootstrap execution (`openbase-coder plugins ...`, `openbase-coder bootstrap ...`)
- Authentication flows for local token auth and Openbase JWT auth
- A backend used directly by the Openbase iOS app

## Quick Start

```bash
# Bootstrap Openbase locally with uvx (macOS)
uvx --python 3.13 openbase-coder setup

# Run server in foreground
uvx --python 3.13 openbase-coder server --host 0.0.0.0 --port 7999
```

For a persistent `openbase-coder` command, use:

```bash
uv tool install --python 3.13 openbase-coder
```

Then omit `uvx --python 3.13` from later commands.

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
- [Troubleshooting](troubleshooting.md)
