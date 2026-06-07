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
- Voice-agent runtime built around LiveKit and Codex app-server sessions
- One-command macOS setup for the Openbase workspace, environment file,
  console build, launchd services, and default agent instructions
- Plugin installation and bootstrap commands for extending the local runtime
- Openbase Cloud login support for authenticated client workflows
- A local web console served by the CLI

## Requirements

- macOS for full setup and launchd service management
- Python 3.13+
- Git
- `uv` recommended for install and local development
- Node package tooling for the bundled console build
- `livekit-server` on `PATH` for voice services

## Install

With `uv`:

```bash
uv tool install openbase-coder
```

With `pipx`:

```bash
pipx install openbase-coder
```

Verify the install:

```bash
openbase-coder --version
```

## First-Time Setup

Run:

```bash
openbase-coder setup
```

Setup clones the public Openbase Coder workspace into `~/.openbase/workspace`,
syncs the runtime install set, generates `~/.openbase/.env` if needed, builds
the web console, installs launchd services, and prepares the local Codex home
used by voice sessions.

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

## Documentation

- [Getting Started](docs/getting-started.md)
- [Commands](docs/commands/index.md)
- [Configuration](docs/configuration.md)
- [Files and Paths](docs/files-and-paths.md)
- [Troubleshooting](docs/troubleshooting.md)

## Development

From this repository:

```bash
uv sync --extra dev
uv run openbase-coder --version
uv run pytest
```

The CLI is part of the larger Openbase Coder multi-workspace. The public setup
flow only syncs the runtime install set required by end users.

## License

Openbase Coder CLI is licensed under
[AGPL-3.0-only](LICENSE).
