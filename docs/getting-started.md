# Getting Started

This guide sets up Openbase locally using the `openbase-coder` CLI.

## Prerequisites

- macOS (`setup` and `services` use launchd) or Linux (systemd user services). The `computer-use` CLI is Linux-only for Openbase DevSpace Xorg/DCV desktops; macOS agents use native Computer Use tooling.
- Tailscale, signed in and connected, for iOS app access to the local CLI
- Codex CLI authenticated in your normal user account when using the `codex` backend

The standalone macOS installer bundles Python, the Openbase CLI Python
dependencies, LiveKit server, and the built console. Git, `uv`, and Node/npm are
only needed for source installs, plugin development with React component pages,
or Openbase Coder development.

Local Kokoro/MLX audio is optional. When setup is run with
`--audio-provider local`, the CLI installs the local-audio Python packages into
the bundled runtime and downloads the Kokoro voices and MLX Whisper model.

Optional:

- Openbase Cloud login for the `openbase_cloud` backend
- Claude Code login for the `claude-code` backend

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

For source development, run setup in dev-workspace mode. This clones the
workspace, builds the console from source, and uses workspace runtime assets:

```bash
uvx --python 3.13 openbase-coder setup --dev-workspace
```

## First-Time Setup

What setup does:

1. Detects the bundled runtime package, or clones/updates `~/.openbase/workspace` in dev-workspace mode.
2. Writes `~/.openbase/installation.json`.
3. Generates `~/.openbase/.env` (if it does not already exist).
4. Generates Openbase instruction files from bundled or workspace templates, links Openbase Claude instructions to the generated Openbase AGENTS file, and keeps normal Claude linked to normal Codex AGENTS.
5. Symlinks bundled or workspace skills into both Openbase Codex and Claude config skill homes.
6. Initializes the CLI workspace and LiveKit model downloads in dev-workspace mode.
7. Writes Codex app-server defaults such as `CODEX_MODEL=gpt-5.5`, `CODEX_MODEL_REASONING_EFFORT=high`, `CODEX_SERVICE_TIER=standard`, `CODEX_APP_SERVER_URL`, and `LIVEKIT_CODEX_THREAD_CWD`.
8. Uses the bundled console build, or builds `console` in dev-workspace mode.
9. Installs background services — launchd on macOS, systemd user units on Linux (unless `--skip-services`).
10. Configures Tailscale Serve routes for iOS access to the local CLI API and LiveKit:
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
- Uses the bundled console build, or rebuilds the console in dev-workspace mode
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
