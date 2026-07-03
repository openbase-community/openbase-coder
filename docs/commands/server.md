# server

Run the local Openbase API and WebSocket server.

## Usage

```bash
openbase-coder server [OPTIONS]
```

## Options

| Option | Default | Description |
|---|---|---|
| `--host TEXT` | `127.0.0.1` | Bind host |
| `--port INTEGER` | `7999` | Bind port |
| `--workers INTEGER` | `1` | Gunicorn worker count |
| `--reload` | `false` | Enable auto-reload |
| `--skip-migrations` | `false` | Skip Django migrations |
| `--skip-collectstatic` | `false` | Skip static collection |

## Startup Sequence

By default `server` does the following:

1. Sets Django environment.
2. Creates data directory (`~/.openbase` by default).
3. Runs migrations.
4. Runs `collectstatic` into `~/.openbase/staticfiles`.
5. Builds the console bundle.
6. Starts Gunicorn with Uvicorn workers.

## Example

```bash
openbase-coder server --host 0.0.0.0 --port 7999 --workers 2
```

## Related Endpoints

- REST API: `http://<host>:<port>/api/...`
- WebSockets: `ws://<host>:<port>/ws/threads/...`
- Console SPA: `http://<host>:<port>/`
