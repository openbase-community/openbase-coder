# openbase-tunneld (tsnet prototype)

Embeds a Tailscale node ([tsnet](https://tailscale.com/kb/1244/tsnet)) inside
the Openbase Coder runtime so users don't need to install the Tailscale app or
create a Tailscale account. See the "Onboarding v2: Embedded Tailscale (tsnet)"
plan in Notion for the full architecture.

## What it replaces

| v1 (Tailscale app required)                          | v2 (this daemon)                     |
| ---------------------------------------------------- | ------------------------------------ |
| `tailscale serve --http=18080 http://127.0.0.1:7999` | tailnet `:18080` reverse proxy       |
| `tailscale serve --tcp=7880 tcp://127.0.0.1:7880`    | tailnet `:7880` TCP forward          |
| `tailscale status --json` subprocess calls           | `GET http://127.0.0.1:7998/status`   |
| host-network HTTP probes of tailnet peers            | `GET http://127.0.0.1:7998/probe`    |

The `/status` payload is `ipnstate.Status`, the same JSON schema that
`tailscale status --json` prints, so existing CLI parsers work unchanged.

## Build

```sh
cd tunneld
go build -o bin/openbase-tunneld .
```

## Run the desktop daemon

```sh
# With a pre-provisioned auth key (the production plan: cloud mints these):
TS_AUTHKEY=tskey-auth-... ./bin/openbase-tunneld serve

# Or without a key: start it, then open the interactive login URL from
# `curl -s http://127.0.0.1:7998/health | jq -r .auth_url`.
```

State lives in `~/.openbase/tsnet` (`--statedir` / `OPENBASE_TSNET_STATE_DIR`).
Point at a self-hosted control plane (e.g. Headscale) with `--control-url` /
`OPENBASE_TSNET_CONTROL_URL`.

## Enable in the Python CLI

```sh
export OPENBASE_TSNET=1
export OPENBASE_TUNNELD_BIN=/path/to/bin/openbase-tunneld  # or put it on PATH
```

With the flag set, `configure_tailscale_serve()` starts the daemon instead of
configuring `tailscale serve`, and identity/peer lookups in
`services/tailnet_devices.py` go through the control API. Without the flag,
nothing changes.

## End-to-end demo (no Tailscale app anywhere)

1. Start the Openbase Coder runtime as usual (Django on `127.0.0.1:7999`).
2. Start the daemon with an auth key (above) and note the node's DNS name:
   `curl -s http://127.0.0.1:7998/health | jq -r .self_dns_name`
3. Simulate the phone from any machine — a second embedded node, no Tailscale
   app involved (ephemeral; it removes itself on exit):

   ```sh
   TS_AUTHKEY_PEER=tskey-auth-... ./bin/openbase-tunneld peer \
     --url http://<self_dns_name>:18080/api/health/
   ```

   Expected: `GET ... -> 200` with `{"status": "ok"}` — the same health check
   the iOS app performs during pairing.

## Prototype limitations

- LiveKit WebRTC media (voice) is not addressed here; only the `:7880`
  signaling forward. Media transport over the userspace stack is the open
  Phase 0 question in the plan.
- The daemon binds the control API to loopback without auth; production needs
  a local auth story (unix socket or token) before shipping.
- Electron (`desktop/electron/main.cjs`) still shells out to the Tailscale
  binary for its own identity display; wiring it to `/status` is a follow-up.
