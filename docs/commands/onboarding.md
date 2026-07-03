# onboarding

Inspect local onboarding state and report it to Openbase cloud.

## Usage

```bash
openbase-coder onboarding status [--json]
openbase-coder onboarding report
```

## status

Shows the CLI-side onboarding state used by the desktop app's onboarding flow:

- `cli_configured` — `installation.json` present and readable, the shared
  `.env` file exists, and all default background services are installed.
- `authenticated` — `~/.openbase/auth.json` holds a refresh token from
  `openbase-coder login`.
- Tailscale identity — the local node's MagicDNS name, tailnet, and IPs.
- Tailscale Serve — the same health checks as `doctor` (routes configured and
  the external Openbase health check passing).
- Cloud — the last device registration/report results cached in
  `~/.openbase/onboarding.json`.

With `--json`, prints the full machine-readable payload. The same payload is
served at `GET /api/onboarding/status/` on the local server; use the command
when the server is not running yet (before setup completes).

## report

Registers this device (including its Tailscale identity) with Openbase cloud
and reports `cli_configured` and Tailscale Serve health, so other devices —
e.g. the iOS app — can observe onboarding progress. `login` and `setup` run
the same report automatically; use this command to retry after Tailscale
comes up.

Requires `openbase-coder login`. If the backend does not implement the device
registration endpoints yet, the command prints a notice and exits
successfully.

## Backend URL

Uses `OPENBASE_CODER_CLI_WEB_BACKEND_URL` if set.
Default: `https://app.openbase.cloud`.
