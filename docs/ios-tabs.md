# iOS App

The Openbase iOS app is a client for the local Openbase Coder runtime that the
`openbase-coder` CLI installs and runs on the Mac. The app does not replace the
CLI setup; it connects to the CLI server, LiveKit server, and Codex/agent
services started by `openbase-coder setup` and `openbase-coder services ...`.

## CLI Connection

In the app's Account tab, the selected backend host is a Tailscale DNS name, IP
address, or hostname. The app builds these runtime URLs from that host:

- Codex/Openbase API: `http://<host>:18080`
- LiveKit signaling: `ws://<host>:7880`

For iPhone access over Tailscale, the local setup must expose the CLI API and
LiveKit ports from the Mac. The troubleshooting guide documents the expected
shape:

- `18080` forwards to the local Django/Openbase API on `127.0.0.1:7999`.
- `7880` forwards to the local LiveKit server on `127.0.0.1:7880`.
- LiveKit media uses TCP `7881` and UDP `7882`.

Before using the app, confirm the local runtime is healthy:

```bash
openbase-coder doctor
openbase-coder services status
```

If an iPhone call reaches the room token endpoint but hangs during LiveKit
connection, see [Troubleshooting](troubleshooting.md) for the Tailscale and
LiveKit listener checks.

## Action Button Mute Shortcut

The iOS app exposes an App Intent named `Toggle Voice Session Mute`, with the
shortcut title `Toggle Mute`. It toggles the microphone mute state for the
currently connected Openbase voice session; if there is no active connected
voice session, it has no CLI-side effect.

To bind it to the iPhone Action Button/action key, create or choose an iOS
Shortcut that runs the Openbase `Toggle Voice Session Mute` action, then set the
Action Button to run that shortcut in iOS Settings. Supported shortcut phrases
include `Toggle Openbase mute` and `Toggle voice session mute in Openbase`.

## App Tabs

The Openbase iOS app (`ios/Openbase/OpenbaseApp.swift`) has four tabs backed by this CLI server.

## 1. Call Tab

Label: `Call` (`AgentCallTabView`)

Responsibilities:

- Hosts the primary LiveKit call UI
- Requests room tokens from the local CLI server
- Connects voice turns to the shared Codex app-server thread through the LiveKit worker

Requirements:

- CLI auth token configured in Account tab
- Active network configuration selected

## 2. Threads Tab

Label: `Threads` (`CodeThreadsView`)

Responsibilities:

- Lists active Codex threads
- Creates threads from recent projects
- Archives threads
- Shows the current turn and turn history
- Handles realtime turn events over WebSocket

CLI endpoints used:

- `GET/POST /api/threads/`
- `GET/DELETE /api/threads/<thread_id>/`
- `POST /api/threads/<thread_id>/interrupt/`
- `POST /api/threads/<thread_id>/turns/`
- `GET /api/projects/recent/`
- `ws://.../ws/threads/`
- `ws://.../ws/threads/<thread_id>/`

Requirements:

- CLI auth token configured in Account tab
- Local coder URL configured and reachable

## 3. Diff Tab

Label: `Diff` (`BrowserView`)

Responsibilities:

- Opens web console diff UI in `WKWebView`
- Loads `/dashboard/diff?token=<cli_token>`
- Injects token into browser `localStorage` for console auth

Requirements:

- CLI auth token configured
- Local coder URL configured and reachable
- Console assets available (built by setup/server)

## 4. Account Tab

Label: `Account` (`HomeView`)

Responsibilities:

- Openbase account/security screens (email, password, sessions, MFA, providers)
- CLI token management (Keychain)
- Network configuration CRUD and active selection (UserDefaults)

Local persistence used by app:

- Keychain: `com.openbase.coder.cli.authtoken`
- UserDefaults: `openbase_agent_hosts`
- UserDefaults: `openbase_selected_host_id`
