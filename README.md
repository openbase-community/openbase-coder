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

Openbase Coder has exactly two deployment modes: a standalone (production)
install for end users, and a development-workspace install for contributors.

Recommended standalone setup on macOS — either install the Openbase Coder
desktop app (which bundles and activates the CLI package for you), or run:

```bash
curl -fsSL https://github.com/openbase-community/openbase-coder/releases/latest/download/install.sh | sh
openbase-coder setup
```

The standalone runtime package bundles Python, Openbase Coder dependencies,
the prebuilt web console, agent instructions and skills, and LiveKit server.
It is detected automatically via its `openbase-coder-package.json`.

Local Kokoro/MLX audio is installed on demand when setup is run with
`--audio-provider local`. Release packages should be built with Python 3.12 so
that Kokoro's current Python `<3.13` package metadata is satisfied.

After setup (in either mode), run `openbase-coder login` to authenticate
with Openbase Cloud — required for iOS app pairing and cloud onboarding.

For source-based development, clone the workspace repo and run its setup
script from the workspace root:

```bash
git clone https://github.com/openbase-community/openbase-coder-workspace
cd openbase-coder-workspace
./scripts/setup
```

The script runs `multi sync --install-set default` and then
`openbase-coder setup --workspace-dir <workspace-root>` against your checkout.
The CLI is typically installed editable (`uv tool install -e ./cli`) or run
via `uv run` from the `cli` repo. `openbase-coder setup` never clones or
git-updates a workspace itself; when `--workspace-dir` is omitted it discovers
the workspace from the recorded installation or an editable CLI install.

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

Setup uses the bundled runtime package, generates `~/.openbase/.env` if needed
(prompting for a coding backend — codex, claude-code, or openbase-cloud — when
`--backend` is omitted), installs launchd services, and prepares the local
Codex home used by voice sessions. In development mode, run `./scripts/setup`
from your workspace checkout instead.

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

For source development without a persistent install, run commands from the
`cli` repo with `uv run` (for example `uv run openbase-coder doctor`).

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
- [Voice Routing](docs/voice-routing.md)
- [Troubleshooting](docs/troubleshooting.md)

## Development

From this repository:

```bash
uv sync --extra dev
uv run openbase-coder --version
uv run pytest
```

The CLI is part of the larger Openbase Coder multi-workspace. For the full
development setup, clone the workspace repo and run `./scripts/setup` from the
workspace root; install the CLI editable with `uv tool install -e ./cli` to
get a persistent `openbase-coder` command backed by your checkout.

## License

Openbase Coder CLI is licensed under
[AGPL-3.0-only](LICENSE).
