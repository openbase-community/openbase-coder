from __future__ import annotations

import os
import time
from pathlib import Path

from openbase_coder_cli import sync_config
from openbase_coder_cli.code_sync import lease


def test_local_activity_recent_from_signal_file_mtimes(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(lease, "_local_file_edit_recent", lambda now: False)
    fresh = tmp_path / "livekit-voice-route.json"
    fresh.write_text("{}", encoding="utf-8")
    stale = tmp_path / "claude-thread-sync-ledger.json"
    stale.write_text("{}", encoding="utf-8")
    old = time.time() - lease.ACTIVITY_WINDOW_SECONDS - 60
    os.utime(stale, (old, old))

    assert lease.local_activity_recent(signal_files=(fresh,)) is True
    assert lease.local_activity_recent(signal_files=(stale,)) is False
    assert (
        lease.local_activity_recent(signal_files=(tmp_path / "missing.json",)) is False
    )


def test_lease_tick_is_a_noop_in_manual_mode(tmp_path: Path) -> None:
    config_path = tmp_path / "sync-config.json"
    sync_config.set_lease_mode("manual", config_path)

    summary = lease.run_lease_tick(config_path)

    assert summary == {"mode": "manual", "action": "none"}


def _fake_client(monkeypatch, applied: list[tuple[str, str]], current="sendreceive"):
    class FakeClient:
        def folder_config(self, folder_id):
            return {"type": current}

        def set_folder_type(self, folder_id, folder_type):
            applied.append((folder_id, folder_type))

    monkeypatch.setattr(lease, "SyncthingClient", FakeClient)


def _idle_setup(
    monkeypatch, tmp_path: Path, statuses: dict, current="sendreceive"
) -> tuple[Path, list]:
    """An idle self with fake peers/statuses; returns (config_path, applied)."""
    config_path = tmp_path / "sync-config.json"
    sync_config.set_sync_folders([{"relpath": "Projects/demo"}], config_path)
    monkeypatch.setattr(lease, "local_activity_recent", lambda: False)
    monkeypatch.setattr(lease, "local_device_id", lambda: "desktop-self")
    monkeypatch.setattr(lease, "current_eligibility", lambda: None)
    monkeypatch.setattr(lease, "syncable_peers", lambda eligibility: ())
    monkeypatch.setattr(lease, "_peer_statuses", lambda peers: statuses)
    applied: list[tuple[str, str]] = []
    _fake_client(monkeypatch, applied, current=current)
    return config_path, applied


def test_lease_tick_claims_when_locally_active(monkeypatch, tmp_path: Path) -> None:
    config_path = tmp_path / "sync-config.json"
    sync_config.set_sync_folders([{"relpath": "Projects/demo"}], config_path)
    monkeypatch.setattr(lease, "local_activity_recent", lambda: True)
    monkeypatch.setattr(lease, "local_device_id", lambda: "desktop-self")
    applied: list[tuple[str, str]] = []
    _fake_client(monkeypatch, applied, current="receiveonly")

    summary = lease.run_lease_tick(config_path)

    assert summary["action"] == "claimed"
    assert summary["holder"] == "desktop-self"
    assert sync_config.lease_holder_device_id(config_path) == "desktop-self"
    folder_id = sync_config.folder_id_for_relpath("Projects/demo")
    assert applied == [(folder_id, "sendreceive")]


def test_lease_tick_yields_to_an_active_peer(monkeypatch, tmp_path: Path) -> None:
    config_path, applied = _idle_setup(
        monkeypatch, tmp_path, {"mini-peer": {"active": True}}
    )

    summary = lease.run_lease_tick(config_path)

    assert summary["action"] == "yielded"
    assert summary["holder"] == "mini-peer"
    folder_id = sync_config.folder_id_for_relpath("Projects/demo")
    assert applied == [(folder_id, "receiveonly")]


def test_sticky_peer_holder_honored_when_peer_record_agrees(
    monkeypatch, tmp_path: Path
) -> None:
    statuses = {"mini-peer": {"active": False, "lease_holder_device_id": "mini-peer"}}
    config_path, applied = _idle_setup(monkeypatch, tmp_path, statuses)
    sync_config.set_lease_holder_device_id("mini-peer", config_path)

    summary = lease.run_lease_tick(config_path)

    assert summary["action"] == "sticky"
    folder_id = sync_config.folder_id_for_relpath("Projects/demo")
    assert applied == [(folder_id, "receiveonly")]


def test_crossed_holder_records_reclaim_instead_of_deadlocking(
    monkeypatch, tmp_path: Path
) -> None:
    """Peer's record points back at us: honoring ours would flip both
    machines receive-only with nothing propagating."""
    statuses = {
        "mini-peer": {"active": False, "lease_holder_device_id": "desktop-self"}
    }
    config_path, applied = _idle_setup(
        monkeypatch, tmp_path, statuses, current="receiveonly"
    )
    sync_config.set_lease_holder_device_id("mini-peer", config_path)

    summary = lease.run_lease_tick(config_path)

    assert summary["action"] == "reclaimed"
    assert summary["holder"] == "desktop-self"
    assert sync_config.lease_holder_device_id(config_path) == "desktop-self"
    folder_id = sync_config.folder_id_for_relpath("Projects/demo")
    assert applied == [(folder_id, "sendreceive")]


def test_unreachable_peer_holder_reclaims(monkeypatch, tmp_path: Path) -> None:
    config_path, applied = _idle_setup(monkeypatch, tmp_path, {}, current="receiveonly")
    sync_config.set_lease_holder_device_id("mini-peer", config_path)

    summary = lease.run_lease_tick(config_path)

    assert summary["action"] == "reclaimed"
    folder_id = sync_config.folder_id_for_relpath("Projects/demo")
    assert applied == [(folder_id, "sendreceive")]


def test_local_file_edit_signal_from_syncthing_events(monkeypatch) -> None:
    import time as time_module

    now = time_module.time()
    stamp = (
        __import__("datetime")
        .datetime.fromtimestamp(now - 60)
        .astimezone()
        .isoformat()
    )
    # Simulate Syncthing's RFC3339-with-nanoseconds formatting.
    stamp = stamp.replace("+", "123+") if "." in stamp else stamp

    class FakeClient:
        def latest_event_time(self, event_type):
            assert event_type == "LocalChangeDetected"
            return stamp

    monkeypatch.setattr(lease, "SyncthingClient", FakeClient)
    assert lease._local_file_edit_recent(now) is True

    class StaleClient:
        def latest_event_time(self, event_type):
            return "2020-01-01T00:00:00.000000000-05:00"

    monkeypatch.setattr(lease, "SyncthingClient", StaleClient)
    assert lease._local_file_edit_recent(now) is False

    class DownClient:
        def __init__(self):
            from openbase_coder_cli.code_sync import CodeSyncError

            raise CodeSyncError("no api key")

    monkeypatch.setattr(lease, "SyncthingClient", DownClient)
    assert lease._local_file_edit_recent(now) is False
