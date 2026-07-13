# provision

Non-interactive first-boot setup for Openbase Cloud workspace instances.
You do not run this yourself: Openbase Cloud invokes it on a freshly
launched DevSpace/Sandbox instance (built from the workspace AMI) with a
provisioning bundle injected through instance user-data. It is the
machine-driven counterpart of [`setup`](setup.md) and exists only on
Linux images.

See [Cloud DevSpace](../cloud-devspace.md) for what a provisioned
workspace looks like once it is running.

## Usage

```bash
openbase-coder provision --input-file /path/to/bundle.json [--kind full|headless]
```

## What It Does

1. Stores the bundle's Openbase Cloud auth tokens (no interactive login).
2. Joins the tailnet with the bundle's Tailscale auth key and hostname.
3. For `--kind headless`, disables the Linux desktop session.
4. Runs the same setup flow as [`setup`](setup.md) against the
   `openbase_cloud` backend, installs the background services, and starts
   the cloud idle heartbeat.
5. Optionally enables [code sync](../code-sync.md) when the bundle asks
   for it.

## Options

| Option | Description |
|---|---|
| `--input-file PATH` | JSON provisioning bundle (from openbase-cloud user-data) |
| `--kind full\|headless` | Workspace kind; `headless` disables the desktop |
| `--access-token` / `--refresh-token` | Override the bundle's auth tokens |
| `--tailscale-authkey` / `--tailscale-hostname` | Override the bundle's Tailscale values |

## Notes

- Linux-only; the command refuses to run elsewhere.
- The backend and provider are fixed to Openbase Cloud; this command never
  applies to Mac desktop or development installs (see
  [Getting Started](../getting-started.md) for those pathways).
