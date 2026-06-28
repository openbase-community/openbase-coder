# Openbase Coder

Openbase Coder is a local voice-coding runtime for working with AI coding
agents from your Mac, browser, and Openbase clients.

The `openbase-coder` command installs and runs the local services that power
Openbase Coder: a Django API, WebSocket endpoints, Codex/Super Agents
coordination, local project and diff APIs, LiveKit voice services, plugin
management, and the bundled web console.

This repository is the main open-source entrypoint for the Openbase Coder
runtime.

## What It Provides

- Local API and WebSocket server for coding sessions, diffs, approvals, reports,
  project metadata, and service status
- Local per-machine thread favorite metadata exposed on thread list/detail APIs
- Voice-agent runtime built around LiveKit and Codex app-server sessions
- One-command macOS setup for environment file, bundled runtime assets,
  background services, and default agent instructions
- Plugin installation and bootstrap commands for extending the local runtime
- Openbase Cloud login support for authenticated client workflows
- A local web console served by the CLI

## Requirements

- macOS (launchd) or Linux (systemd user services) for setup and service
  management. The standalone installer currently targets macOS first.
- Tailscale for iOS access to the local CLI.
- Codex and Openbase authentication for authenticated coding workflows.
- Git only for installing plugins from GitHub URLs or for development checkout mode.

## Quick Start

Recommended standalone setup on macOS:

```bash
curl -fsSL https://github.com/openbase-community/openbase-coder/releases/latest/download/install.sh | sh
openbase-coder setup
```

The standalone installer bundles Python, Openbase Coder dependencies, the web
console, and LiveKit server.

Local Kokoro/MLX audio is installed on demand when setup is run with
`--audio-provider local`. Release packages should be built with Python 3.12 so
that Kokoro's current Python `<3.13` package metadata is satisfied.

For source-based development, use the legacy `uv` flow:

```bash
uvx --python 3.13 openbase-coder setup --dev-workspace
```

Verify a persistent install:

```bash
openbase-coder --version
```

## First-Time Setup

If you already installed the persistent `openbase-coder` command, run:

```bash
openbase-coder setup
```

For fully local speech-to-text and text-to-speech:

```bash
openbase-coder setup --audio-provider local
```

Setup uses the bundled runtime package, generates `~/.openbase/.env` if needed,
installs launchd services, and prepares the local Codex home used by voice
sessions. Source development mode can still clone and sync the public workspace
with `--dev-workspace`.

After setup, check the local runtime:

```bash
openbase-coder doctor
openbase-coder services status
```

## Run The Server

For foreground development:

```bash
openbase-coder server --host 0.0.0.0 --port 7999
```

For normal macOS background operation:

```bash
openbase-coder services start
openbase-coder services status
```

## Common Commands

```bash
openbase-coder setup
openbase-coder doctor
openbase-coder login
openbase-coder services status
openbase-coder services logs django-cli
openbase-coder plugins list
openbase-coder bootstrap --help
```

For source development without a persistent install, prefix commands with
`uvx --python 3.13`.

## Documentation

- [Getting Started](docs/getting-started.md)
- [Downloads](docs/downloads.md)
- [Manual Setup](docs/manual-installation.md)
- [Local-Only Mode](docs/local-only.md)
- [Uninstall](docs/uninstall.md)
- [Commands](docs/commands/index.md)
- [Configuration](docs/configuration.md)
- [Files and Paths](docs/files-and-paths.md)
- [iOS App](docs/ios-tabs.md)
- [Troubleshooting](docs/troubleshooting.md)

## Development

From this repository:

```bash
# One-shot: clone ../super-agents if needed, sync with Python 3.13
./scripts/dev-sync.sh

uv run openbase-coder --version
uv run pytest
```

**Requirements:** Python **3.13** (not 3.14). Some dependencies (e.g. `spacy` via `kokoro`) only publish `cp313` wheels. The repo pins `requires-python = ">=3.13,<3.14"` and includes a `.python-version` file for `uv` and `pyenv`.

Clone [super-agents](https://github.com/montaguegabe/super-agents) as a sibling repo (`../super-agents`) if you prefer manual setup:

```bash
git clone https://github.com/montaguegabe/super-agents.git ../super-agents
uv sync --extra dev --python 3.13
```

The CLI is part of the larger Openbase Coder multi-workspace. The public setup
flow only syncs the runtime install set required by end users.

## License

Openbase Coder CLI is licensed under
[AGPL-3.0-only](LICENSE).
