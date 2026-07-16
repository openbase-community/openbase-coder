# Cloud DevSpace

This guide starts from an Openbase Cloud Sandbox/DevSpace image that already
has `openbase-coder`, Tailscale, NICE DCV, LiveKit, Codex, and the Openbase
Coder service wrappers installed.

Use this flow when you want the only external services to be Tailscale and
Openbase Cloud. You do not need direct Cartesia or AssemblyAI accounts for this
path; current setup defaults voice audio to Openbase Cloud, and the commands
below switch coding sessions to the Openbase Cloud backend.

From the apps' point of view a DevSpace is just another backend host: once it
is on your tailnet, the [iOS app](ios-tabs.md) adds it under
**Settings → Backend Host** exactly like a Mac, and the
[web console](console.md) is reachable at `http://<host>:18080`.

## Start the Sandbox

1. Open `https://app.openbase.cloud` and sign in.
2. Go to the dashboard. The dashboard opens the Sandboxes page.
3. In `Get access`, click `Subscribe` if access is not active, or ask a
   coordinator to activate complimentary access and then click `Refresh access`.
4. Click `Continue to launch`.
5. In `Spin up your Sandbox`, choose a sandbox size. Use `m6i.2xlarge
   (recommended)` unless you have a reason to choose another size.
6. Click `Spin up Sandbox` or `Start Sandbox`.
7. Wait on `Waiting for Sandbox` until the page says the credentials are ready.
8. Choose the browser connection flow and click `Open Sandbox in Browser`.
9. Continue past the certificate prompt only if the IP address matches the
   Sandbox URL shown on the page.
10. On `Sign in to your Sandbox`, sign in with:
    - Username: `ubuntu`
    - Password: the password shown on the page
    - Session: `openbase`

The browser connection is the Amazon DCV web client. It gives you a Linux
desktop in the cloud instance.

## Prepare the Linux Desktop

Open the first terminal inside the DCV desktop:

1. Click `Activities`.
2. Search for `Terminal`.
3. Open `Terminal`.

Start a browser inside the Linux desktop before running the auth commands:

```bash
firefox &
```

If Firefox is not installed in the image, install it and start it:

```bash
sudo snap install firefox
firefox &
```

## Connect Tailscale

Run:

```bash
sudo tailscale up
```

Tailscale prints an authentication URL. Open that URL in Firefox, sign in to the
same tailnet your iPhone uses, and approve the new Linux device.

Confirm Tailscale is connected:

```bash
tailscale status
tailscale ip -4
```

The IP should be a `100.x.y.z` address.

## Log In to Openbase Cloud

Log in from the Linux terminal:

```bash
openbase-coder login
```

If Firefox does not open automatically, copy the URL printed by the command into
Firefox. Sign in with the same Openbase Cloud account you use in the iOS app.

Switch coding sessions to Openbase Cloud:

```bash
openbase-coder backend use openbase_cloud
```

Use the underscore spelling, `openbase_cloud`, for compatibility with cloud
images that have an older `openbase-coder` CLI installed.

This avoids requiring local OpenAI, Anthropic, Cartesia, or AssemblyAI account
setup for the basic voice-agent path.

## Start Openbase Services

Start the default services:

```bash
openbase-coder services start
```

Starting the default service set also configures the Tailscale Serve routes used
by the iOS app:

```bash
tailscale serve --bg --http=18080 http://127.0.0.1:7999
tailscale serve --bg --tcp=7880 tcp://127.0.0.1:7880
```

Check the instance:

```bash
openbase-coder services status
openbase-coder doctor
```

Both commands should report healthy services and healthy Tailscale Serve routes.

If `doctor` reports missing Openbase Cloud audio configuration on an older
image, refresh setup in Openbase Cloud mode and start services again:

```bash
openbase-coder setup --backend openbase_cloud --audio-provider openbase-cloud
openbase-coder services start
openbase-coder doctor
```

## Get the iOS Host Name

Prefer the Tailscale DNS name when MagicDNS is enabled:

```bash
tailscale status --json | jq -r '.Self.DNSName // empty' | sed 's/[.]$//'
```

If that prints nothing, use the Tailscale IPv4 address:

```bash
tailscale ip -4
```

The iOS app builds these URLs from the host:

- Openbase API: `http://<host>:18080`
- LiveKit signaling: `ws://<host>:7880`

## Connect From the iOS App

1. On the iPhone, open Tailscale and sign in to the same tailnet.
2. Open the Openbase iOS app and sign in to Openbase Cloud.
3. Open `Settings`.
4. In `Backend Host`, enter a friendly `Name`.
5. In `Tailscale DNS or IP`, enter the DNS name or `100.x.y.z` IP from the
   Linux instance.
6. Tap `Add Backend`.
7. Select the new backend in `Selected Backend`.
8. Open `Call`.
9. Start a voice call and speak to the dispatcher.

The first call should request a room token from the Linux instance, connect to
LiveKit over Tailscale, and dispatch the `livekit-agent` worker running in the
cloud desktop.

## Quick Recovery

If the iOS app cannot connect:

```bash
tailscale status
tailscale serve status
openbase-coder services status
openbase-coder doctor
```

If services started before Tailscale was authenticated, start them again:

```bash
openbase-coder services start
```

If the call reaches `Connecting...` or `Waiting for Agent`, inspect recent logs:

```bash
openbase-coder services logs livekit-server
openbase-coder services logs livekit-agent
```
