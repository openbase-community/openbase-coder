# restart

Restart Openbase-managed services.

## Usage

```bash
openbase-coder restart [OPTIONS]
```

With no options, this schedules a detached restart of every Openbase-managed launchd service:

- all Openbase launchd services
- the Openbase Coder API/MCP host through `django-cli`

Dispatcher context is preserved by default.

The Super Agents MCP stdio process is owned by the client that spawned it, such as Codex.
`openbase-coder restart` does not kill or restart that process.

## Options

| Option | Default | Description |
|---|---|---|
| `--service NAME` | all services | Restart exactly one Openbase-managed service |
| `--delay FLOAT` | `8.0` | Seconds to wait before restarting |
| `--recreate-dispatcher` | off | Clear dispatcher state and recreate it during restart |

## Examples

```bash
openbase-coder restart
openbase-coder restart --service livekit-agent
openbase-coder restart --recreate-dispatcher
```
