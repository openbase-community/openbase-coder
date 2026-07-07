"""Lifecycle operations for the code-sync subsystem.

Shared by the CLI (``openbase-coder sync ...``) and the settings API so both
surfaces enable/disable/apply identically: identity, rendered Syncthing
config, managed ignores, and the ``code-sync`` service.
"""

from __future__ import annotations

import socket
from pathlib import Path
from typing import Any

import click

from openbase_coder_cli.code_sync import CodeSyncError
from openbase_coder_cli.code_sync.eligibility import (
    EligibilityResult,
    current_eligibility,
    syncable_peers,
)
from openbase_coder_cli.code_sync.ignores import update_all_ignores
from openbase_coder_cli.code_sync.syncthing import (
    PeerDevice,
    SyncthingClient,
    ensure_identity,
    peer_address,
    write_config,
)
from openbase_coder_cli.paths import SYNC_VERSIONS_DIR
from openbase_coder_cli.sync_config import (
    code_sync_enabled,
    set_code_sync_enabled,
)

CODE_SYNC_SERVICE_NAME = "code-sync"


def _peer_devices(eligibility: EligibilityResult) -> list[PeerDevice]:
    return [
        PeerDevice(
            device_id=peer.syncthing_device_id,
            name=peer.name,
            address=peer_address(peer.tailscale_magic_dns),
        )
        for peer in syncable_peers(eligibility)
    ]


def render_configuration(
    eligibility: EligibilityResult | None = None,
    *,
    config_path: Path | None = None,
) -> dict[str, Any]:
    """Render Syncthing config.xml + per-folder ignores from current state."""
    from openbase_coder_cli.sync_config import sync_folders

    device_id = ensure_identity()
    eligibility = eligibility or current_eligibility()
    peers = _peer_devices(eligibility)
    write_config(
        self_device_id=device_id,
        self_name=socket.gethostname(),
        peers=peers,
        folders=list(sync_folders(config_path)),
    )
    ignore_paths = update_all_ignores(config_path)
    return {
        "device_id": device_id,
        "peer_count": len(peers),
        "ignore_files": [str(path) for path in ignore_paths],
    }


def _service_definition():
    from openbase_coder_cli.services.registry import find_service

    return find_service(CODE_SYNC_SERVICE_NAME)


def install_and_start_service() -> None:
    from openbase_coder_cli.services.launchd import install_service
    from openbase_coder_cli.services.registry import require_installation

    try:
        install_service(require_installation(), _service_definition())
    except click.ClickException as exc:
        raise CodeSyncError(str(exc)) from exc


def restart_service_if_installed() -> None:
    from openbase_coder_cli.services.launchd import (
        launchctl_kickstart,
        launchctl_status,
    )

    service = _service_definition()
    if launchctl_status(service).get("installed"):
        launchctl_kickstart(service)


def stop_and_remove_service() -> bool:
    from openbase_coder_cli.services.launchd import remove_service

    return remove_service(_service_definition())


def enable_code_sync(
    *, force: bool = False, config_path: Path | None = None
) -> dict[str, Any]:
    """Turn code sync on: identity, config, ignores, service, registration."""
    eligibility = current_eligibility()
    if not eligibility.eligible and not force:
        raise CodeSyncError(eligibility.reason or "Code sync is not eligible.")

    rendered = render_configuration(eligibility, config_path=config_path)
    set_code_sync_enabled(True, config_path)
    SYNC_VERSIONS_DIR.mkdir(parents=True, exist_ok=True)
    install_and_start_service()

    # Advertise the new capabilities so peers can add this device.
    from openbase_coder_cli.services.cloud_registration import register_and_report

    report = register_and_report()
    return {
        "enabled": True,
        "eligible": eligibility.eligible,
        "eligible_reason": eligibility.reason,
        "registered": report.ok,
        **rendered,
    }


def disable_code_sync(config_path: Path | None = None) -> dict[str, Any]:
    """Turn code sync off; local data (versions, identity) is kept."""
    removed = stop_and_remove_service()
    set_code_sync_enabled(False, config_path)
    from openbase_coder_cli.services.cloud_registration import register_and_report

    register_and_report()
    return {"enabled": False, "service_removed": removed}


def apply_settings_change(config_path: Path | None = None) -> dict[str, Any]:
    """Re-render config/ignores after a settings mutation and reload sync."""
    if not code_sync_enabled(config_path):
        return {"applied": False, "reason": "code sync is disabled"}
    rendered = render_configuration(config_path=config_path)
    # syncthing runs with --no-restart; kick the service so the rendered
    # config.xml is reloaded, then request a rescan once it is back.
    restart_service_if_installed()
    try:
        SyncthingClient().rescan()
    except CodeSyncError:
        pass  # The restart itself rescans; REST may not be back up yet.
    return {"applied": True, **rendered}


def versions_usage_bytes(versions_dir: Path | None = None) -> int:
    root = versions_dir or SYNC_VERSIONS_DIR
    total = 0
    if not root.is_dir():
        return total
    for path in root.rglob("*"):
        try:
            if path.is_file() and not path.is_symlink():
                total += path.stat().st_size
        except OSError:
            continue
    return total


def purge_versions(versions_dir: Path | None = None) -> int:
    """Delete all staggered version copies; returns freed bytes."""
    import shutil

    root = versions_dir or SYNC_VERSIONS_DIR
    freed = versions_usage_bytes(root)
    if root.is_dir():
        for child in root.iterdir():
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)
    return freed
