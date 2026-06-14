# doctor

Validate Openbase local runtime health and security settings.

## Usage

```bash
openbase-coder doctor
```

## Checks Performed

- Installation file presence (`installation.json`)
- launchd service install/running state
- Listening ports and bind addresses
- Tailscale Serve routes for the iOS app:
  - `:18080 -> http://127.0.0.1:7999`
  - `:7880 -> tcp://127.0.0.1:7880`
- External Openbase health check through the tailnet `:18080` address
- Required credentials in `.env`
- Detection of known insecure defaults for some keys

## Required Environment Keys

- `OPENBASE_CODER_CLI_SECRET_KEY`
- `LIVEKIT_API_KEY`
- `LIVEKIT_API_SECRET`
