# Release

Standalone CLI releases are built by the `Release Standalone CLI` GitHub Actions workflow. The workflow is manual-only and the build job runs only on `main`.

## Standalone CLI

The workflow builds a macOS standalone tarball that includes:

- Openbase Coder CLI installed into a bundled standalone Python 3.12 runtime
- Console static assets
- Agent instructions and bundled skills
- A real `livekit-server` binary installed from Homebrew on the macOS runner
- `install.sh` for one-line install and upgrade
- SHA-256 checksums

Run it from GitHub Actions with a release version such as `0.4.0` or `v0.4.0`. The workflow creates a tag like `v0.4.0`.

## Optional Apple Signing

If these repository secrets are present, the workflow code signs Mach-O binaries before archiving:

- `APPLE_DEVELOPER_ID_APPLICATION_CERT_BASE64`
- `APPLE_DEVELOPER_ID_APPLICATION_CERT_PASSWORD`
- `APPLE_CODESIGN_IDENTITY`
- `APPLE_CODESIGN_KEYCHAIN_PASSWORD`

If these repository secrets are also present, the workflow submits a notarization zip to Apple:

- `APPLE_NOTARY_KEY`
- `APPLE_NOTARY_KEY_ID`
- `APPLE_NOTARY_ISSUER_ID`

The distributed asset is a tarball, so there is no stapled `.app`, `.pkg`, or `.dmg`. Notarization still validates the signed binaries in the package.
