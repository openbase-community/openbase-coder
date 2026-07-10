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
Tailscale (the same channel the reconciler already uses). When nobody is
provably active the lease is sticky, but a recorded peer holder is honored
only while that peer is reachable and its own status agrees it holds;
otherwise this device reclaims. Holder records live per-device (they cannot
sync), so without that validation crossed records would flip both machines
receive-only and nothing would propagate. When both devices are active,
both stay send-receive — demoting a machine with live work would strand its
edits, and Syncthing's conflict copies cover genuine simultaneous edits.
``lease_mode: manual`` disables all automatic flipping (console override
for split work).
"""

from __future__ import annotations

import re
import time
from datetime import datetime
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
    """Whether this device had voice/agent/editing activity recently."""
    current = now if now is not None else time.time()
    for path in signal_files:
        try:
            mtime = path.stat().st_mtime
        except (FileNotFoundError, OSError):
            continue
        if current - mtime <= ACTIVITY_WINDOW_SECONDS:
            return True
    return _local_file_edit_recent(current)


def _local_file_edit_recent(now: float) -> bool:
    """Local file edits inside managed folders, per Syncthing's own watcher.

    Plain hand-editing leaves no voice/agent signal; without this the lease
    would flip a machine receive-only under the user's hands. Syncthing only
    emits LocalChangeDetected for locally-originated changes, so pulls from
    peers never count as activity.
    """
    try:
        stamp = SyncthingClient().latest_event_time("LocalChangeDetected")
    except CodeSyncError:
        return False
    if not stamp:
        return False
    # Syncthing emits RFC3339 with nanoseconds; fromisoformat takes <= 6
    # fractional digits.
    normalized = re.sub(r"(\.\d{1,6})\d*", r"\1", stamp)
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return False
    return now - parsed.timestamp() <= ACTIVITY_WINDOW_SECONDS


def _peer_status(peer: SyncPeer, auth_header: str | None) -> dict[str, Any] | None:
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
        return None
    return payload if isinstance(payload, dict) else None


def _peer_statuses(peers: tuple[SyncPeer, ...]) -> dict[str, dict[str, Any]]:
    """Reachable peers' status payloads, keyed by cloud device ID."""
    try:
        token = TokenManager(web_backend_url()).get_access_token()
        auth_header = f"Bearer {token}"
    except (AuthLoginRequiredError, AuthTransientError):
        return {}
    statuses: dict[str, dict[str, Any]] = {}
    for peer in peers:
        payload = _peer_status(peer, auth_header)
        if payload is not None:
            statuses[peer.device_id] = payload
    return statuses


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
        statuses = _peer_statuses(peers)
        active_id = next(
            (
                device_id
                for device_id, payload in statuses.items()
                if payload.get("active") is True
            ),
            None,
        )
        if active_id is not None:
            if holder != active_id:
                set_lease_holder_device_id(active_id, config_path)
            _set_all_folder_types("receiveonly", config_path)
            summary.update({"action": "yielded", "holder": active_id})
            return summary

        # Nobody is provably active: the lease is sticky, so plain manual
        # edits (which leave no activity signal) still propagate. A peer
        # holder is honored only while that peer is reachable and its own
        # record agrees it holds; holder records are per-device, so crossed
        # or stale records would otherwise leave BOTH machines receive-only
        # with nothing propagating until an activity signal appears.
        if holder and holder != self_id:
            peer_record = statuses.get(holder, {}).get("lease_holder_device_id")
            if peer_record == holder:
                _set_all_folder_types("receiveonly", config_path)
                summary["action"] = "sticky"
                return summary
            set_lease_holder_device_id(self_id, config_path)
            _set_all_folder_types("sendreceive", config_path)
            summary.update({"action": "reclaimed", "holder": self_id})
            return summary
        _set_all_folder_types("sendreceive", config_path)
        summary["action"] = "sticky"
    except CodeSyncError as exc:
        summary.update({"action": "error", "error": str(exc)})
    return summary
