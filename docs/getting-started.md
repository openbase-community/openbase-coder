# Getting Started

This guide sets up Openbase locally using the `openbase-coder` CLI.

## Prerequisites

- macOS (`setup` and `services` use launchd) or Linux (systemd user services). The `computer-use` CLI is Linux-only for Openbase DevSpace Xorg/DCV desktops; macOS agents use native Computer Use tooling.
- Tailscale, signed in and connected, for iOS app access to the local CLI
- Codex CLI authenticated in your normal user account when using the `codex` backend

Openbase Coder has exactly two deployment modes:

- **Standalone (production)**: a bundled runtime package, shipped inside the
  desktop app or installed via `install.sh`, containing Python, the CLI,
  LiveKit server, a prebuilt console, agent instructions, and skills. It is
  detected automatically via `openbase-coder-package.json`.
- **Development**: a cloned `openbase-coder-workspace` checkout set up with the
  workspace's `./scripts/setup` script, with the CLI installed editable
  (`uv tool install -e ./cli`) or run via `uv run`.

Git, `uv`, and Node/npm are only needed for Openbase Coder development.
Plugins no longer need Node/npm: plugin console pages ship prebuilt static
assets rendered in iframes.

Local Kokoro/MLX audio is optional. When setup is run with
`--audio-provider local`, the CLI installs the local-audio Python packages into
the bundled runtime and downloads the Kokoro voices and MLX Whisper model.

Optional:

- Openbase Cloud login for the `openbase_cloud` backend
- Claude Code login for the `claude-code` backend (on macOS, setup bridges
  your normal Claude Code login into Openbase's managed config automatically
  when it can; `openbase-coder claude login` is the fallback)

## Install

The preferred first-time setup path is the standalone installer:

```bash
curl -fsSL https://raw.githubusercontent.com/openbase-community/openbase-coder/main/cli/scripts/install.sh | sh
openbase-coder setup
```

For fully local speech-to-text and text-to-speech:

```bash
openbase-coder setup --audio-provider local
```

For source development, clone the workspace repo yourself and run its setup
script from the workspace root. It syncs the sub-repos with `multi`, builds
the console from source, and runs `openbase-coder setup` against your checkout:

```bash
git clone https://github.com/openbase-community/openbase-coder-workspace
cd openbase-coder-workspace
./scripts/setup
```

Setup never clones or git-updates a workspace itself. When run without
`--workspace-dir` (and no bundled runtime package is present), it discovers
the workspace from the one recorded in `~/.openbase/installation.json`, then
from the checkout behind an editable CLI install; otherwise it errors and asks
you to clone the workspace or use the standalone install.

## First-Time Setup

What setup does:

1. Detects the bundled runtime package (standalone mode), or locates your workspace checkout (development mode).
2. Writes `~/.openbase/installation.json`.
3. Generates `~/.openbase/.env` (if it does not already exist), prompting for the coding backend when `--backend` is omitted.
4. Installs the selected backend's CLI on demand if missing (codex from GitHub release binaries into `~/.openbase/bin`, claude via Anthropic's official installer).
5. Generates Openbase instruction files from bundled or workspace templates, links Openbase Claude instructions to the generated Openbase AGENTS file, and keeps normal Claude linked to normal Codex AGENTS.
6. Symlinks bundled or workspace skills into both Openbase Codex and Claude config skill homes.
7. Downloads LiveKit agent model files (VAD, turn detector) in both modes, and initializes the CLI venv with `uv sync` in development mode.
8. Writes Codex app-server defaults such as `CODEX_MODEL=gpt-5.5`, `CODEX_MODEL_REASONING_EFFORT=high`, `CODEX_SERVICE_TIER=standard`, `CODEX_APP_SERVER_URL`, and `LIVEKIT_CODEX_THREAD_CWD`.
9. Uses the bundled console build, or builds `console` in development mode.
10. Installs background services — launchd on macOS, systemd user units on Linux (unless `--skip-services`). Backend-specific services such as `codex-app-server` are only installed for the codex/openbase-cloud backends.
11. Configures Tailscale Serve routes for iOS access to the local CLI API and LiveKit:
    - `tailscale serve --bg --http=18080 http://127.0.0.1:7999`
    - `tailscale serve --bg --tcp=7880 tcp://127.0.0.1:7880`

If you do not want the Electron app to run setup commands for you, follow the
[Manual Installation](manual-installation.md) page and run the same CLI setup,
auth, service, and health-check steps from your own terminal.

## Start the Server

```bash
openbase-coder server --host 0.0.0.0 --port 7999
```

By default this command:

- Runs Django migrations
- Runs `collectstatic`
- Uses the bundled console build, or rebuilds the console in development mode
- Starts Gunicorn + Uvicorn worker(s)

## Health Check

```bash
openbase-coder doctor
openbase-coder services status
openbase-coder onboarding status
```

`onboarding status` summarizes the state the desktop/iOS onboarding flow
cares about: CLI configured, login, Tailscale identity, and Tailscale Serve
health. See [onboarding](commands/onboarding.md).

## Uninstalling Openbase

Uninstall is handled with normal system and package-manager commands, not the
`openbase-coder` CLI. Follow the [Uninstall Openbase CLI](uninstall.md) page to
stop and remove launchd/systemd services, remove the CLI package, then either
delete or archive `~/.openbase`.

## Authenticate With Openbase Cloud (Optional)

```bash
openbase-coder login --email you@example.com
```

This stores tokens in `~/.openbase/auth.json` for JWT-based auth flows.

## Next Steps

- Learn command details in [Commands](commands/index.md)
- Install your first plugin: `openbase-coder plugins add <local-repo-or-github-url>`
- Discover bootstrap commands: `openbase-coder plugins bootstrappers`
- Run plugin bootstrap flow: `openbase-coder bootstrap <name> --params-file <file.json>`
- Review environment and auth settings in [Configuration](configuration.md)
- See all runtime artifacts in [Files and Paths](files-and-paths.md)
- Map backend behavior to the iOS UI in [iOS App](ios-tabs.md)
