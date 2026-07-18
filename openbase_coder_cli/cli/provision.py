"""Non-interactive provisioning for cloud workspaces.

`openbase-cloud` injects a JSON bundle (minted allauth JWTs, a Tailscale auth
key, and a MagicDNS hostname) into EC2 user-data. This command consumes it so a
freshly booted workspace configures itself with zero human interaction: it
writes the same `auth.json` that `openbase-coder login` would, points the CLI at
Openbase Cloud, joins the tailnet, (for headless) turns off the desktop, and
runs the normal `setup` flow to install/start services and Tailscale Serve.

Everything here reuses existing helpers; it only sequences them for a headless
boot rather than reimplementing setup.
"""

from __future__ import annotations

import getpass
import json
import platform
import subprocess
import time
from pathlib import Path

import click

from openbase_coder_cli.config.token_manager import (
    DEFAULT_WEB_BACKEND_URL,
    TokenManager,
)
from openbase_coder_cli.env_file import upsert_env_file_values
from openbase_coder_cli.paths import DEFAULT_ENV_FILE_PATH

from .setup import setup

WEB_BACKEND_ENV_KEY = "OPENBASE_CODER_CLI_WEB_BACKEND_URL"


def _load_bundle(input_file: str | None, overrides: dict) -> dict:
    bundle: dict = {}
    if input_file:
        bundle = json.loads(Path(input_file).read_text(encoding="utf-8"))
    # Explicit flags win over the file so the command is also usable by hand.
    for key, value in overrides.items():
        if value:
            bundle[key] = value
    return bundle


def _store_auth(bundle: dict, web_backend_url: str) -> None:
    access_token = bundle.get("access_token", "")
    refresh_token = bundle.get("refresh_token", "")
    if not access_token or not refresh_token:
        raise click.ClickException(
            "Provisioning bundle is missing access_token/refresh_token."
        )
    expires_at = bundle.get("access_expires_at")
    expires_in = max(int(expires_at - time.time()), 60) if expires_at else 300

    manager = TokenManager(web_backend_url=web_backend_url)
    manager.store_tokens(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
    )


def _join_tailnet(authkey: str, hostname: str) -> None:
    if not authkey:
        return
    # --ssh: workspaces must accept Tailscale SSH from the owner's devices.
    # --operator: the session user manages Tailscale Serve without sudo, which
    # the later setup step requires.
    command = [
        "sudo",
        "tailscale",
        "up",
        "--authkey",
        authkey,
        "--ssh",
        f"--operator={getpass.getuser()}",
    ]
    if hostname:
        command += ["--hostname", hostname]
    subprocess.run(command, check=True)


def _disable_desktop() -> None:
    """Turn off the GUI on headless workspaces so a shared AMI stays cheap."""
    subprocess.run(
        ["sudo", "systemctl", "set-default", "multi-user.target"], check=False
    )
    for unit in ("gdm3", "dcvserver"):
        subprocess.run(["sudo", "systemctl", "disable", "--now", unit], check=False)


@click.command()
@click.option(
    "--input-file",
    type=click.Path(exists=True, dir_okay=False, path_type=str),
    default=None,
    help="Path to a JSON provisioning bundle (from openbase-cloud user-data).",
)
@click.option(
    "--kind",
    type=click.Choice(["full", "headless"]),
    default=None,
    help="Workspace kind. Headless disables the desktop.",
)
@click.option("--access-token", default=None, help="Override bundle access token.")
@click.option("--refresh-token", default=None, help="Override bundle refresh token.")
@click.option(
    "--tailscale-authkey", default=None, help="Override bundle Tailscale auth key."
)
@click.option(
    "--tailscale-hostname", default=None, help="Override bundle Tailscale hostname."
)
@click.pass_context
def provision(
    ctx: click.Context,
    input_file: str | None,
    kind: str | None,
    access_token: str | None,
    refresh_token: str | None,
    tailscale_authkey: str | None,
    tailscale_hostname: str | None,
) -> None:
    """Provision this workspace from an injected credential bundle."""
    if platform.system() != "Linux":
        raise click.ClickException("provision is only supported on Linux workspaces.")

    bundle = _load_bundle(
        input_file,
        {
            "kind": kind,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "tailscale_authkey": tailscale_authkey,
            "tailscale_hostname": tailscale_hostname,
        },
    )

    kind = bundle.get("kind", "full")
    web_backend_url = bundle.get("web_backend_url") or DEFAULT_WEB_BACKEND_URL

    # 1. Point the CLI at Openbase Cloud and store the owner's credentials.
    DEFAULT_ENV_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    upsert_env_file_values(
        DEFAULT_ENV_FILE_PATH, {WEB_BACKEND_ENV_KEY: web_backend_url}
    )
    _store_auth(bundle, web_backend_url)

    # 2. Join the tailnet so the box is reachable / heartbeats can be sent.
    _join_tailnet(
        bundle.get("tailscale_authkey", ""), bundle.get("tailscale_hostname", "")
    )

    # 3. Headless workspaces have no desktop.
    if kind == "headless":
        _disable_desktop()

    # 4. Normal setup: install/start services, configure Tailscale Serve, and
    #    register the device with Openbase Cloud.
    ctx.invoke(
        setup,
        env_file=str(DEFAULT_ENV_FILE_PATH),
        coding_backend="openbase_cloud",
        audio_provider="openbase-cloud",
        skip_services=False,
        json_progress=False,
    )

    # 5. Install cloud-only boot services.
    _install_cloud_workspace_services()

    # 6. Optional code sync (bundles may omit the field entirely).
    if bundle.get("code_sync") is True:
        _enable_code_sync()

    click.echo(f"Provisioned {kind} workspace against {web_backend_url}.")


def _install_cloud_workspace_services() -> None:
    from openbase_coder_cli.services.launchd import install_service
    from openbase_coder_cli.services.registry import find_service, require_installation

    config = require_installation()
    install_service(config, find_service("openbase-cloud-auth-rehydrate"))
    install_service(config, find_service("openbase-cloud-heartbeat"))


SYNCTHING_RELEASES_API = (
    "https://api.github.com/repos/syncthing/syncthing/releases/latest"
)
_SYNCTHING_ARCHES = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64"}


def _ensure_syncthing_linux() -> None:
    """Install syncthing on a Linux workspace via the managed installer."""
    from openbase_coder_cli.code_sync.install import ensure_syncthing_installed

    ensure_syncthing_installed()


def _download_syncthing_release() -> None:
    """Download the latest static syncthing binary into ~/.openbase/bin."""
    import tarfile
    import tempfile

    import httpx

    from openbase_coder_cli.paths import OPENBASE_BIN_DIR

    machine = platform.machine().lower()
    arch = _SYNCTHING_ARCHES.get(machine)
    if arch is None:
        raise click.ClickException(f"Unsupported syncthing architecture: {machine}")

    release = httpx.get(SYNCTHING_RELEASES_API, timeout=30).json()
    version = str(release.get("tag_name", "")).strip()
    if not version:
        raise click.ClickException("Could not determine the latest syncthing release.")
    archive_name = f"syncthing-linux-{arch}-{version}.tar.gz"
    url = (
        "https://github.com/syncthing/syncthing/releases/download/"
        f"{version}/{archive_name}"
    )

    OPENBASE_BIN_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp_dir:
        archive_path = Path(tmp_dir) / archive_name
        with httpx.stream("GET", url, timeout=120, follow_redirects=True) as response:
            response.raise_for_status()
            with archive_path.open("wb") as handle:
                for chunk in response.iter_bytes():
                    handle.write(chunk)
        with tarfile.open(archive_path) as archive:
            member = next(
                (
                    item
                    for item in archive.getmembers()
                    if item.isfile() and Path(item.name).name == "syncthing"
                ),
                None,
            )
            if member is None:
                raise click.ClickException(
                    f"No syncthing binary found in {archive_name}."
                )
            member.name = "syncthing"
            archive.extract(member, OPENBASE_BIN_DIR)
    (OPENBASE_BIN_DIR / "syncthing").chmod(0o755)


def _enable_code_sync() -> None:
    """Best-effort code-sync arming for provisioned workspaces.

    Forced because the user's other devices may register their sync
    capabilities after this workspace boots; the rendered config is refreshed
    on every settings change and reconcile tick.
    """
    from openbase_coder_cli.code_sync import CodeSyncError
    from openbase_coder_cli.code_sync.manager import enable_code_sync

    try:
        _ensure_syncthing_linux()
        enable_code_sync(force=True)
    except (click.ClickException, CodeSyncError) as exc:
        click.echo(click.style(f"  WARN  code sync not enabled: {exc}", fg="yellow"))
    else:
        click.echo("Enabled code sync.")
