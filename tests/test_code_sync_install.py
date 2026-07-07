"""Tests for the on-demand Syncthing installer."""

from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

import click
import pytest

from openbase_coder_cli.code_sync import install


def _fake_zip_asset() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("syncthing-macos-arm64-vtest/syncthing", b"#!/bin/sh\n")
    return buffer.getvalue()


class _FakeStream:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        return None

    def raise_for_status(self) -> None:
        return None

    def iter_bytes(self):
        yield self._payload


def _patch_platform(monkeypatch, system="Darwin", machine="arm64") -> None:
    monkeypatch.setattr(install.platform, "system", lambda: system)
    monkeypatch.setattr(install.platform, "machine", lambda: machine)
    # Keep tests independent of whether the host has syncthing on PATH.
    monkeypatch.setattr(install.shutil, "which", lambda _name: None)


def test_install_honors_syncthing_on_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        install, "MANAGED_SYNCTHING_PATH", tmp_path / "managed" / "syncthing"
    )
    monkeypatch.setattr(install.shutil, "which", lambda _name: "/usr/bin/syncthing")

    result = install.ensure_syncthing_installed(echo=lambda *_: None)

    assert str(result) == "/usr/bin/syncthing"


def test_install_verifies_checksum_and_installs(tmp_path: Path, monkeypatch) -> None:
    payload = _fake_zip_asset()
    _patch_platform(monkeypatch)
    monkeypatch.setattr(
        install,
        "_ASSETS",
        {
            ("Darwin", "arm64"): (
                "syncthing-macos-arm64-vtest.zip",
                hashlib.sha256(payload).hexdigest(),
            )
        },
    )
    target = tmp_path / "bin" / "syncthing"
    monkeypatch.setattr(install, "MANAGED_SYNCTHING_PATH", target)
    monkeypatch.setattr(install.httpx, "stream", lambda *a, **k: _FakeStream(payload))

    result = install.ensure_syncthing_installed(echo=lambda *_: None)

    assert result == target
    assert target.is_file()
    assert target.stat().st_mode & 0o111


def test_install_rejects_checksum_mismatch(tmp_path: Path, monkeypatch) -> None:
    payload = _fake_zip_asset()
    _patch_platform(monkeypatch)
    monkeypatch.setattr(
        install,
        "_ASSETS",
        {("Darwin", "arm64"): ("syncthing-macos-arm64-vtest.zip", "0" * 64)},
    )
    target = tmp_path / "bin" / "syncthing"
    monkeypatch.setattr(install, "MANAGED_SYNCTHING_PATH", target)
    monkeypatch.setattr(install.httpx, "stream", lambda *a, **k: _FakeStream(payload))

    with pytest.raises(click.ClickException, match="checksum mismatch"):
        install.ensure_syncthing_installed(echo=lambda *_: None)
    assert not target.exists()


def test_install_short_circuits_when_present(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "syncthing"
    target.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(install, "MANAGED_SYNCTHING_PATH", target)

    assert install.ensure_syncthing_installed(echo=lambda *_: None) == target


def test_install_rejects_unknown_platform(monkeypatch, tmp_path: Path) -> None:
    _patch_platform(monkeypatch, system="Plan9", machine="mips")
    monkeypatch.setattr(install, "MANAGED_SYNCTHING_PATH", tmp_path / "syncthing")

    with pytest.raises(click.ClickException, match="No pinned Syncthing build"):
        install.ensure_syncthing_installed(echo=lambda *_: None)
