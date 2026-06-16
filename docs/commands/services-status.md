# services status

Show launchd install/running state for all managed services.

## Usage

```bash
openbase-coder services status
```

Output includes whether each service is:

- `not installed`
- `running (pid ...)`
- `loaded (not running, last exit: ...)`

The command also verifies the Tailscale Serve routes that the iOS app uses:

```bash
tailscale serve --bg --http=18080 http://127.0.0.1:7999
tailscale serve --bg --tcp=7880 tcp://127.0.0.1:7880
```

`services status` exits non-zero if any managed service is unhealthy, either
Serve route is missing, or the external Openbase health check at the tailnet
`:18080` address fails.
