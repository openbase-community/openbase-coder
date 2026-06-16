# Manual Installation

Use this path when you want to run setup yourself instead of letting the
Electron app run shell commands.

The desktop app stops showing the setup flow when all of these checks pass:

- The local backend answers `http://127.0.0.1:7999/api/health/`.
- `~/.openbase/.env` contains non-empty `ASSEMBLY_AI_API_KEY` and
  `CARTESIA_API_KEY` values.
- `~/.openbase/auth.json` contains an Openbase access token or refresh token.

## Install Prerequisites

Install the tools the setup command expects:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
brew install git node livekit
brew install --cask tailscale
open -a Tailscale
```

Sign in to Tailscale before continuing if you want iPhone-to-Mac voice
networking.

## Run Setup Yourself

If the desktop app shows a pinned setup command, run that exact command in your
terminal. Otherwise, use the current published CLI:

```bash
export ASSEMBLY_AI_API_KEY="<assemblyai-api-key>"
export CARTESIA_API_KEY="<cartesia-api-key>"

uvx --python 3.13 openbase-coder setup
```

The setup command creates the Openbase workspace, writes
`~/.openbase/installation.json`, creates `~/.openbase/.env` if it is missing,
builds the console, installs background services, and configures Tailscale Serve
routes.

If `~/.openbase/.env` already existed before setup, the CLI leaves it unchanged.
Add the voice keys manually:

```bash
open -e ~/.openbase/.env
```

Make sure the file contains non-empty values:

```dotenv
ASSEMBLY_AI_API_KEY=<assemblyai-api-key>
CARTESIA_API_KEY=<cartesia-api-key>
```

## Authenticate

Run the CLI login flow from your terminal:

```bash
openbase-coder login
```

The desktop app checks `~/.openbase/auth.json`, so the setup page will continue
to show until login writes an access token or refresh token there.

## Start and Verify Services

Start the managed services:

```bash
openbase-coder services start
```

Then verify the install:

```bash
openbase-coder doctor
openbase-coder services status
curl -fsS http://127.0.0.1:7999/api/health/
```

If Tailscale Serve was not configured during setup, run:

```bash
tailscale serve --bg --http=18080 http://127.0.0.1:7999
tailscale serve --bg --tcp=7880 tcp://127.0.0.1:7880
```

## Open the Desktop App

After the health endpoint, voice keys, and login checks pass, reopen or recheck
the Electron app. It should skip the setup flow and load the main Openbase Coder
interface.

