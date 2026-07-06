# services

Manage Openbase launchd background services.

## Usage

```bash
openbase-coder services COMMAND [ARGS]
```

## Subcommands

| Subcommand | Description |
|---|---|
| [`install`](services-install.md) | Generate wrappers/plists and load default services |
| `up` | Alias for `install`; also configures Tailscale Serve routes |
| [`start`](services-start.md) | Start default services or one named service |
| [`stop`](services-stop.md) | Stop all or one service |
| [`status`](services-status.md) | Show service state summary |
| [`logs`](services-logs.md) | Tail one service's logs |
| [`regenerate`](services-regenerate.md) | Rebuild wrappers/plists from `installation.json` |

## Managed Service Names

- `livekit-server` (port `7880`)
- `codex-app-server` (port `4500`)
- `codex-thread-sync`
- `codex-thread-device-sync` (optional; explicit start/install only)
- `openbase-routines`
- `livekit-agent`
- `django-cli` (port `7999`)

## Examples

```bash
openbase-coder services install
openbase-coder services up
openbase-coder services status
openbase-coder restart --service django-cli
openbase-coder services logs codex-app-server
```
