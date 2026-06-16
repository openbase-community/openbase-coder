# Getting Started

This guide sets up Openbase locally using the `openbase-coder` CLI.

## Prerequisites

- macOS (`setup` and `services` use launchd) or Linux (systemd user services); screen sharing/computer use is macOS-only
- Python 3.13+
- Git
- `uv` (recommended)
- `npm` (for console build during setup)
- `livekit-server` on your `PATH` (for voice services)
- Tailscale, signed in and connected, for iOS app access to the local CLI

Optional but recommended:

- `multi` on your `PATH` for automatic workspace sub-repo sync

## Install

The preferred first-time setup path is `uvx`, which runs `openbase-coder` in an
isolated `uv` tool environment without requiring a separate install step:

```bash
uvx --python 3.13 openbase-coder setup
```

Use a persistent install when you want `openbase-coder` to remain on your
`PATH` after setup. The `uv tool` path is preferred:

=== "uv tool"

    ```bash
    uv tool install --python 3.13 openbase-coder
    ```

=== "pipx"

    ```bash
    pipx install --python python3.13 openbase-coder
    ```

=== "pip"

    ```bash
    pip install openbase-coder
    ```

Verify a persistent install:

```bash
openbase-coder --version
```

When using `uvx`, run one-off commands as `uvx --python 3.13 openbase-coder ...`.

## First-Time Setup

If you used the `uvx` one-liner above, setup has already started. Otherwise run:

```bash
openbase-coder setup
```

What setup does:

1. Clones or updates the Openbase workspace at `~/.openbase/workspace`.
2. Writes `~/.openbase/installation.json`.
3. Generates `~/.openbase/.env` (if it does not already exist).
4. Creates missing default instruction files in `~/.openbase/codex_home` from the workspace `instructions/` directory.
5. Symlinks workspace skills into `~/.openbase/codex_home/skills`.
6. Initializes the CLI workspace and bundled LiveKit worker (`uv sync`, LiveKit model downloads).
7. Writes Codex app-server defaults such as `CODEX_MODEL=gpt-5.5`, `CODEX_MODEL_REASONING_EFFORT=high`, `CODEX_SERVICE_TIER=fast`, `CODEX_APP_SERVER_URL`, and `LIVEKIT_CODEX_THREAD_CWD`.
8. Builds `console`.
9. Installs background services — launchd on macOS, systemd user units on Linux (unless `--skip-services`).
10. Configures Tailscale Serve routes for iOS access to the local CLI API and LiveKit:
    - `tailscale serve --bg --http=18080 http://127.0.0.1:7999`
    - `tailscale serve --bg --tcp=7880 tcp://127.0.0.1:7880`

If you do not want the Electron app to run setup commands for you, follow the
[Manual Installation](manual-installation.md) page and run the same CLI setup,
auth, service, and health-check steps from your own terminal.

## Start the Server

```bash
uvx --python 3.13 openbase-coder server --host 0.0.0.0 --port 7999
```

By default this command:

- Runs Django migrations
- Runs `collectstatic`
- Rebuilds the console
- Starts Gunicorn + Uvicorn worker(s)

## Health Check

```bash
uvx --python 3.13 openbase-coder doctor
uvx --python 3.13 openbase-coder services status
```

## Authenticate With Openbase Cloud (Optional)

```bash
uvx --python 3.13 openbase-coder login --email you@example.com
```

This stores tokens in `~/.openbase/auth.json` for JWT-based auth flows.

## Next Steps

- Learn command details in [Commands](commands/index.md)
- Install your first plugin: `uvx --python 3.13 openbase-coder plugins add <local-repo-or-github-url>`
- Discover bootstrap commands: `uvx --python 3.13 openbase-coder plugins bootstrappers`
- Run plugin bootstrap flow: `uvx --python 3.13 openbase-coder bootstrap <name> --params-file <file.json>`
- Review environment and auth settings in [Configuration](configuration.md)
- See all runtime artifacts in [Files and Paths](files-and-paths.md)
- Map backend behavior to the iOS UI in [iOS App Tabs](ios-tabs.md)
