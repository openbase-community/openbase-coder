# Downloads

Download the Openbase Coder apps for your devices.

| Platform | Download |
|---|---|
| CLI | [Download the standalone CLI installer](https://github.com/openbase-community/openbase-coder/releases/latest/download/install.sh) |
| Mac | [Download the Apple Silicon Mac app](https://openbase-coder-desktop-releases-632795836081-us-east-1.s3.amazonaws.com/mac/Openbase-Coder-latest-arm64.dmg) |
| Multi Desktop | [Download the Apple Silicon Multi Desktop app](https://multi-desktop-releases-632795836081-us-east-1.s3.amazonaws.com/mac/Multi-Desktop-latest-arm64.dmg) |
| iOS | [Join the iOS beta on TestFlight](https://testflight.apple.com/join/DVTh9CMH) |
| Android | [Download the Android APK](https://openbase.cloud/downloads/openbase-coder-android.apk) |

What each one is for:

- The **Mac app** is the recommended starting point: it bundles the CLI,
  runs guided setup, and hosts the full dashboard. See
  [Desktop App](desktop-app.md).
- **Multi Desktop** is the companion app for inspecting and managing
  Multi workspaces.
- The **iOS app** is the phone client for voice calls, threads, approvals,
  reports, and diffs. See [iOS App](ios-tabs.md).
- The **CLI installer** sets up the same local runtime without the desktop
  app. See [Getting Started](getting-started.md).

Install the standalone CLI on macOS with:

```bash
curl -fsSL https://github.com/openbase-community/openbase-coder/releases/latest/download/install.sh | sh
```

The standalone CLI includes its own Python runtime, bundled console assets, bundled agent instructions and skills, and a packaged LiveKit server binary. Setup never clones a workspace; developers who want to work from source should clone `openbase-coder-workspace` and run its `./scripts/setup` instead.
