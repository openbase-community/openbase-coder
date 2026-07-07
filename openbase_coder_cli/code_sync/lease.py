"""Active-device write lease for code-sync (layer 3.5).

Excluding ``.git`` from sync fixes torn git state but not the echo-race
class (a stale peer re-sending an old working-tree file mid-edit). Syncthing
folders support per-device receive-only mode, so the code-sync service holds
a simple lease: the device with recent user/agent activity keeps its folders
send-receive; a device that is idle while a peer is active flips its own
folders receive-only.

Activity heuristic (v1, deliberately cheap and local): this device is
"active" when any of these files was modified in the last 15 minutes —

- ``~/.openbase/livekit-voice-route.json`` (a voice route is/was live)
- the codex/claude thread-sync ledgers (agent turns are being synced)

Peer activity is read from the peer's ``GET /api/sync/status/`` over
Tailscale (the same channel the reconciler already uses); when no peer is
reachable the lease is sticky — the current holder keeps send-receive, so
two idle machines never deadlock in receive-only. ``lease_mode: manual``
disables all automatic flipping (console override for split work).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import httpx

from openbase_coder_cli.code_sync import CodeSyncError
from openbase_coder_cli.code_sync.eligibility import (
    SyncPeer,
    current_eligibility,
    syncable_peers,
)
from openbase_coder_cli.code_sync.syncthing import SyncthingClient
from openbase_coder_cli.config.token_manager import (
    AuthLoginRequiredError,
    AuthTransientError,
    TokenManager,
)
from openbase_coder_cli.paths import OPENBASE_BASE_DIR
from openbase_coder_cli.services.cloud_registration import local_device_id
from openbase_coder_cli.services.onboarding import web_backend_url
from openbase_coder_cli.sync_config import (
    lease_holder_device_id,
    lease_mode,
    set_lease_holder_device_id,
    sync_folders,
)

ACTIVITY_WINDOW_SECONDS = 15 * 60
ACTIVITY_SIGNAL_FILES = (
    OPENBASE_BASE_DIR / "livekit-voice-route.json",
    OPENBASE_BASE_DIR / "codex-thread-sync-ledger.json",
    OPENBASE_BASE_DIR / "codex-thread-device-sync-ledger.json",
    OPENBASE_BASE_DIR / "claude-thread-sync-ledger.json",
    OPENBASE_BASE_DIR / "claude-thread-device-sync-ledger.json",
)
PEER_API_PORT = 18080
PEER_STATUS_TIMEOUT_SECONDS = 5


def local_activity_recent(
    now: float | None = None,
    signal_files: tuple[Path, ...] = ACTIVITY_SIGNAL_FILES,
) -> bool:
    """Whether this device had voice/agent activity in the last 15 minutes."""
    current = now if now is not None else time.time()
    for path in signal_files:
        try:
            mtime = path.stat().st_mtime
        except (FileNotFoundError, OSError):
            continue
        if current - mtime <= ACTIVITY_WINDOW_SECONDS:
            return True
    return False


def _peer_active(peer: SyncPeer, auth_header: str | None) -> bool:
    host = peer.tailscale_magic_dns.rstrip(".")
    headers = {"Authorization": auth_header} if auth_header else {}
    try:
        response = httpx.get(
            f"http://{host}:{PEER_API_PORT}/api/sync/status/",
            headers=headers,
            timeout=PEER_STATUS_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        return False
    return isinstance(payload, dict) and payload.get("active") is True


def _active_peer(peers: tuple[SyncPeer, ...]) -> SyncPeer | None:
    auth_header = None
    try:
        token = TokenManager(web_backend_url()).get_access_token()
        auth_header = f"Bearer {token}"
    except (AuthLoginRequiredError, AuthTransientError):
        return None
    for peer in peers:
        if _peer_active(peer, auth_header):
            return peer
    return None


def _set_all_folder_types(folder_type: str, config_path: Path | None) -> list[str]:
    """PATCH folder types, skipping folders that already match (cheap ticks)."""
    client = SyncthingClient()
    changed: list[str] = []
    for folder in sync_folders(config_path):
        current = client.folder_config(folder.folder_id).get("type")
        if current == folder_type:
            continue
        client.set_folder_type(folder.folder_id, folder_type)
        changed.append(folder.folder_id)
    return changed


def run_lease_tick(config_path: Path | None = None) -> dict[str, Any]:
    """Evaluate the lease and apply folder types via the Syncthing REST API."""
    mode = lease_mode(config_path)
    summary: dict[str, Any] = {"mode": mode, "action": "none"}
    if mode == "manual":
        return summary

    self_id = local_device_id()
    holder = lease_holder_device_id(config_path)
    summary["holder"] = holder

    try:
        if local_activity_recent():
            if holder != self_id:
                set_lease_holder_device_id(self_id, config_path)
            _set_all_folder_types("sendreceive", config_path)
            summary.update({"action": "claimed", "holder": self_id})
            return summary

        peers = syncable_peers(current_eligibility())
        active_peer = _active_peer(peers)
        if active_peer is not None:
            if holder != active_peer.device_id:
                set_lease_holder_device_id(active_peer.device_id, config_path)
            _set_all_folder_types("receiveonly", config_path)
            summary.update({"action": "yielded", "holder": active_peer.device_id})
            return summary

        # Nobody is provably active: the lease is sticky. The last holder
        # keeps send-receive so plain manual edits still propagate.
        if holder and holder != self_id:
            _set_all_folder_types("receiveonly", config_path)
        else:
            _set_all_folder_types("sendreceive", config_path)
        summary["action"] = "sticky"
    except CodeSyncError as exc:
        summary.update({"action": "error", "error": str(exc)})
    return summary
