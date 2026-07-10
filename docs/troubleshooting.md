# Troubleshooting

Where problems surface in the apps: the [desktop app](desktop-app.md) and
[console](console.md) show service health on their **Status** page and a
warning banner on the Overview page; the [iOS app](ios-tabs.md) shows a
warning banner when the local runtime is unreachable and can upload logs from
**Settings → Diagnostics**. The checks below are the CLI-side diagnosis for
the most common failures.

## iPhone Stays On Connecting

The iOS app reaches the Mac through Tailscale Serve, not directly through the
local Django port. The expected routes are:

```bash
tailscale serve --bg --http=18080 http://127.0.0.1:7999
tailscale serve --bg --tcp=7880 tcp://127.0.0.1:7880
```

Check the configured routes:

```bash
tailscale serve status
```

Then check local service health:

```bash
openbase-coder doctor
openbase-coder services status
```

Both commands should fail if either Serve route is missing or the Openbase API
health check cannot be reached through the machine's tailnet `:18080` address.

## iPhone LiveKit Call Times Out Over Tailscale

Symptoms:

- The iOS app can reach the local CLI API.
- `POST /api/livekit-room-token/` returns `200`.
- The app logs a LiveKit URL such as `ws://<machine>.tailnet-name.ts.net:7880`.
- The LiveKit agent joins the room, but the iPhone fails during `room.connect` or times out before publishing the microphone.

This usually means signaling is working but WebRTC media cannot complete ICE. One known cause is LiveKit advertising the machine's Tailscale IP while its UDP media socket is only bound to loopback.

Check the local LiveKit listeners:

```bash
lsof -nP -iTCP:7880 -iTCP:7881 -iUDP:7882
```

For Tailscale iPhone calls, LiveKit should have UDP listeners on both loopback and the machine's Tailscale addresses, for example:

```text
UDP 127.0.0.1:7882
UDP 100.x.y.z:7882
UDP [fd7a:115c:a1e0::...]:7882
TCP *:7881 (LISTEN)
TCP 127.0.0.1:7880 (LISTEN)
```

If UDP is only bound on `127.0.0.1:7882`, regenerate and reload the launchd service wrappers from a version of `openbase-coder` that includes the Tailscale interface fix:

```bash
openbase-coder services regenerate
openbase-coder services install
```

Then restart the LiveKit services:

```bash
openbase-coder restart --service livekit-server
openbase-coder restart --service livekit-agent
```

For new installs, `openbase-coder setup` generates the corrected LiveKit wrapper automatically. Existing installs need regenerated wrappers because launchd runs the generated shell scripts in `~/.openbase/launchd/`.

The corrected wrapper derives `LIVEKIT_INTERFACE` from the interface that owns `LIVEKIT_NODE_IP`, rather than trusting a route lookup while Tailscale is still settling. You can still override the values in `~/.openbase/.env` when needed:

```bash
LIVEKIT_NETWORK_MODE=tailscale
LIVEKIT_NODE_IP=100.x.y.z
LIVEKIT_INTERFACE=utunN
LIVEKIT_BIND_IP=127.0.0.1
LIVEKIT_TCP_PORT=7881
LIVEKIT_UDP_PORT=7882
```

## Voice Route Exit Returns 502 With Invalid LiveKit URL

Symptoms:

- `POST /api/livekit-voice-route/exit/` returns `502 Bad Gateway`.
- The Django log contains `ValueError: Invalid URL: port can't be converted to integer`.
- The bad URL contains Tailscale CLI error text, for example `http://The Tailscale CLI failed to start: ...:7880/...`.

This means the Django launchd service started while `tailscale ip -4` returned an error string instead of an IPv4 address, and that string was captured into `LIVEKIT_URL`.

Regenerate wrappers and restart Django:

```bash
openbase-coder services regenerate
openbase-coder restart --service django-cli
```

The service wrapper validates the derived Tailscale IPv4 address before exporting `LIVEKIT_URL`. If Tailscale cannot provide a valid IPv4 address in `tailscale` mode, the service now exits with a clear startup error instead of running with a malformed LiveKit URL.

## Enable iOS Auth Diagnostics

iOS keeps a small redacted `AuthDiagnostics` buffer in memory for the Upload iOS Logs action. Verbose console printing is disabled by default. Enable it only while debugging auth, CLI API, or LiveKit call setup.

You can enable it from code with:

```swift
AuthDiagnostics.setEnabled(true)
```

Or set the process environment variable in an Xcode scheme:

```text
OPENBASE_AUTH_DIAGNOSTICS=1
```

Upload payloads redact secret-like values and email addresses before they are written to the local runtime log directory. Do not leave verbose console diagnostics enabled for routine development sessions unless you need the extra local output.
