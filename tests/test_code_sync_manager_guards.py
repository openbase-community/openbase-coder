from __future__ import annotations

import socket
from pathlib import Path

import pytest

from openbase_coder_cli.code_sync import CodeSyncError, manager
from openbase_coder_cli.sync_config import SyncFolder


def test_port_guard_raises_when_port_taken(monkeypatch) -> None:
    monkeypatch.setattr(manager, "_managed_service_running", lambda: False)
    monkeypatch.setattr(manager, "_user_managed_syncthing_running", lambda: True)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("0.0.0.0", 0))
        port = sock.getsockname()[1]
        monkeypatch.setattr(manager, "_listen_port_available", lambda p=port: False)
        with pytest.raises(CodeSyncError, match="user-managed"):
            manager.ensure_port_available()


def test_port_guard_skipped_when_own_service_running(monkeypatch) -> None:
    monkeypatch.setattr(manager, "_managed_service_running", lambda: True)
    monkeypatch.setattr(manager, "_listen_port_available", lambda: False)
    manager.ensure_port_available()  # must not raise


def test_user_syncthing_folder_parsing(tmp_path: Path) -> None:
    config_dir = tmp_path / "Library" / "Application Support" / "Syncthing"
    config_dir.mkdir(parents=True)
    (config_dir / "config.xml").write_text(
        """<configuration version="37">
  <folder id="projects" path="{home}/Projects" type="sendreceive"></folder>
  <folder id="desktop" path="{home}/Desktop" type="sendreceive"></folder>
</configuration>
""".format(home=tmp_path),
        encoding="utf-8",
    )

    folders = manager.user_managed_syncthing_folders(home=tmp_path)

    assert tmp_path / "Projects" in folders
    assert tmp_path / "Desktop" in folders


def test_overlap_guard_rejects_shared_directory(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(manager, "_user_managed_syncthing_running", lambda: True)
    monkeypatch.setattr(
        manager,
        "user_managed_syncthing_folders",
        lambda home=None: [tmp_path / "Projects"],
    )

    nested = [SyncFolder(relpath="Projects/demo")]
    with pytest.raises(CodeSyncError, match="overlaps"):
        manager.ensure_no_user_managed_overlap(nested, home=tmp_path)

    disjoint = [SyncFolder(relpath="Documents/notes")]
    manager.ensure_no_user_managed_overlap(disjoint, home=tmp_path)  # ok


def test_overlap_guard_noop_when_no_user_syncthing(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(manager, "_user_managed_syncthing_running", lambda: False)
    manager.ensure_no_user_managed_overlap(
        [SyncFolder(relpath="Projects/demo")], home=tmp_path
    )


def test_syncthing_process_matcher_ignores_scripts(monkeypatch) -> None:
    class FakeResult:
        returncode = 0
        stdout = (
            "100 /Users/u/.openbase/bin/syncthing serve --config "
            "/Users/u/.openbase/code-sync\n"
            "200 bash -c curl http://127.0.0.1:8384/rest/db/status syncthing\n"
        )

    monkeypatch.setattr(manager.subprocess, "run", lambda *a, **k: FakeResult())
    monkeypatch.setattr(manager, "CODE_SYNC_DIR", Path("/Users/u/.openbase/code-sync"))
    assert manager._user_managed_syncthing_running() is False

    FakeResult.stdout = (
        "300 /Applications/Syncthing.app/Contents/Resources/syncthing/syncthing "
        "--no-browser\n"
    )
    assert manager._user_managed_syncthing_running() is True
