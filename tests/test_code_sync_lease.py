from __future__ import annotations

import os
import time
from pathlib import Path

from openbase_coder_cli import sync_config
from openbase_coder_cli.code_sync import lease


def test_local_activity_recent_from_signal_file_mtimes(tmp_path: Path) -> None:
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


def test_lease_tick_claims_when_locally_active(monkeypatch, tmp_path: Path) -> None:
    config_path = tmp_path / "sync-config.json"
    sync_config.set_sync_folders([{"relpath": "Projects/demo"}], config_path)
    monkeypatch.setattr(lease, "local_activity_recent", lambda: True)
    monkeypatch.setattr(lease, "local_device_id", lambda: "desktop-self")
    applied: list[tuple[str, str]] = []

    class FakeClient:
        def folder_config(self, folder_id):
            return {"type": "receiveonly"}

        def set_folder_type(self, folder_id, folder_type):
            applied.append((folder_id, folder_type))

    monkeypatch.setattr(lease, "SyncthingClient", FakeClient)

    summary = lease.run_lease_tick(config_path)

    assert summary["action"] == "claimed"
    assert summary["holder"] == "desktop-self"
    assert sync_config.lease_holder_device_id(config_path) == "desktop-self"
    folder_id = sync_config.folder_id_for_relpath("Projects/demo")
    assert applied == [(folder_id, "sendreceive")]
