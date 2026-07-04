# login

Authenticate to Openbase cloud in your browser.

In the apps: the [desktop app](../desktop-app.md) runs this during its
sign-in step, and the [iOS app](../ios-tabs.md) signs in to the same Openbase
account directly (Settings → Account).

## Usage

```bash
openbase-coder login
```

## Flow

1. Opens the Openbase web login in your browser.
2. Waits for the local OAuth callback.
3. Exchanges the authorization code for access/refresh tokens.
4. Stores tokens in `~/.openbase/auth.json`.
5. Registers this device (including its Tailscale identity, when available)
   with Openbase cloud for the onboarding flow. Failures only warn; see
   [`onboarding`](onboarding.md) to retry.

## Backend URL

Uses `OPENBASE_CODER_CLI_WEB_BACKEND_URL` if set.
Default: `https://app.openbase.cloud`.
