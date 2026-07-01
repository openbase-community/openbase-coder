# Commands Overview

Openbase CLI command structure:

```bash
openbase-coder [OPTIONS] COMMAND [ARGS]
```

## Global Options

| Option | Description |
|---|---|
| `--version` | Print CLI version and exit |
| `--help` | Show help |

## Top-Level Commands

| Command | Description |
|---|---|
| [`backend`](backend.md) | View or switch the selected coding backend |
| [`claude`](claude.md) | Manage Openbase's Claude Code auth |
| [`claude-sync`](claude-sync.md) | Synchronize Claude Code sessions between normal and Openbase config homes |
| [`setup`](setup.md) | Full local bootstrap flow |
| [`server`](server.md) | Run local Django/ASGI server |
| [`restart`](restart.md) | Restart Openbase-managed services |
| [`services`](services.md) | Manage launchd services |
| [`doctor`](doctor.md) | Verify install, service health, and secrets |
| [`login`](login.md) | Email-code login to Openbase cloud |
| [`logout`](logout.md) | Remove saved auth tokens |
| [`plugins`](plugins.md) | Install and manage Openbase plugins |
| [`bootstrap`](bootstrap.md) | Run plugin-provided bootstrap commands |
| [`voice routing`](../voice-routing.md) | Route the active LiveKit voice room between the dispatcher and Super Agents |

## Common Examples

```bash
# Full bootstrap
openbase-coder setup

# Start API server
openbase-coder server --host 0.0.0.0 --port 7999

# Check service states
openbase-coder services status

# Switch coding backend
openbase-coder backend use codex

# Restart Openbase-managed services
openbase-coder restart

# Check or change the active voice route
openbase-coder user voice-route
openbase-coder user transfer-to-agent "Lucy"
openbase-coder exit-to-dispatch

# Tail logs for one service
openbase-coder services logs django-cli

# Validate local environment
openbase-coder doctor

# Install plugin from local repo
openbase-coder plugins add ~/code/my-openbase-plugin

# List plugin-provided bootstrappers
openbase-coder plugins bootstrappers

# Run a bootstrapper
openbase-coder bootstrap django-app --params-file bootstrap.json
```
