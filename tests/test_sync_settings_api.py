from __future__ import annotations

# ruff: noqa: E402, I001

import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("OPENBASE_CODER_CLI_SECRET_KEY", "test-secret")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "openbase_coder_cli.config.settings")

import django
from rest_framework.test import APIRequestFactory, force_authenticate

django.setup()

from openbase_coder_cli import sync_config
from openbase_coder_cli.code_sync import conflicts as conflicts_module
from openbase_coder_cli.code_sync import manager as sync_manager
from openbase_coder_cli.code_sync.eligibility import EligibilityResult, SyncPeer
from openbase_coder_cli.openbase_coder_cli_app import sync_settings


def _authenticated_request(method: str, path: str, data: dict | None = None):
    factory = APIRequestFactory()
    request_factory = {
        "GET": factory.get,
        "PUT": factory.put,
        "POST": factory.post,
    }[method]
    request = request_factory(path, data=data or {}, format="json")
    force_authenticate(request, user=SimpleNamespace(is_authenticated=True))
    return request


def _fake_eligibility(eligible: bool = True) -> EligibilityResult:
    return EligibilityResult(
        eligible=eligible,
        reason="" if eligible else "Add a second machine to enable sync.",
        peers=(
            SyncPeer(
                device_id="desktop-peer",
                name="Mac mini",
                kind="desktop",
                tailscale_magic_dns="mini.tail1234.ts.net.",
                syncthing_device_id="PEER-DEVICE-ID",
            ),
        ),
    )


def _patch_environment(monkeypatch, tmp_path: Path) -> Path:
    config_path = tmp_path / "sync-config.json"
    monkeypatch.setattr(sync_config, "SYNC_CONFIG_PATH", config_path)
    monkeypatch.setattr(
        sync_settings, "current_eligibility", lambda: _fake_eligibility()
    )
    monkeypatch.setattr(sync_settings, "stored_device_id", lambda: "SELF-DEVICE-ID")
    monkeypatch.setattr(sync_manager, "versions_usage_bytes", lambda: 1234)
    return config_path


def test_sync_settings_get_payload(monkeypatch, tmp_path: Path) -> None:
    _patch_environment(monkeypatch, tmp_path)
    sync_config.set_sync_folders(
        [{"relpath": "Projects/demo", "extra_ignores": ["*.log"]}]
    )
    sync_config.set_code_sync_enabled(True)

    response = sync_settings.sync_settings(
        _authenticated_request("GET", "/api/sync/settings/")
    )

    assert response.status_code == 200
    assert response.data["schema_version"] == 1
    assert response.data["enabled"] is True
    assert response.data["eligible"] is True
    assert response.data["self_device_id"] == "SELF-DEVICE-ID"
    assert response.data["peers"][0]["syncthing_device_id"] == "PEER-DEVICE-ID"
    assert response.data["folders"] == [
        {
            "id": sync_config.folder_id_for_relpath("Projects/demo"),
            "relpath": "Projects/demo",
            "extra_ignores": ["*.log"],
        }
    ]
    assert response.data["versions_usage_bytes"] == 1234
    assert response.data["lease_mode"] == "auto"


def test_sync_settings_put_replaces_folders_and_applies(
    monkeypatch, tmp_path: Path
) -> None:
    _patch_environment(monkeypatch, tmp_path)
    sync_config.set_code_sync_enabled(True)
    sync_config.set_sync_folders([{"relpath": "Projects/old"}])
    applied: list[str] = []
    monkeypatch.setattr(
        sync_manager,
        "apply_settings_change",
        lambda config_path=None: applied.append("apply") or {"applied": True},
    )

    response = sync_settings.sync_settings(
        _authenticated_request(
            "PUT",
            "/api/sync/settings/",
            {
                "folders": [{"relpath": "Projects/new", "extra_ignores": ["*.bin"]}],
                "lease_mode": "manual",
            },
        )
    )

    assert response.status_code == 200
    assert [folder["relpath"] for folder in response.data["folders"]] == [
        "Projects/new"
    ]
    assert response.data["lease_mode"] == "manual"
    assert applied == ["apply"]


def test_sync_settings_put_enables_and_disables(monkeypatch, tmp_path: Path) -> None:
    _patch_environment(monkeypatch, tmp_path)
    calls: list[str] = []
    monkeypatch.setattr(
        sync_manager,
        "enable_code_sync",
        lambda force=False, config_path=None: (
            calls.append("enable"),
            sync_config.set_code_sync_enabled(True),
        ),
    )
    monkeypatch.setattr(
        sync_manager,
        "disable_code_sync",
        lambda config_path=None: (
            calls.append("disable"),
            sync_config.set_code_sync_enabled(False),
        ),
    )

    response = sync_settings.sync_settings(
        _authenticated_request("PUT", "/api/sync/settings/", {"enabled": True})
    )
    assert response.status_code == 200
    assert calls == ["enable"]
    assert sync_config.code_sync_enabled() is True

    response = sync_settings.sync_settings(
        _authenticated_request("PUT", "/api/sync/settings/", {"enabled": False})
    )
    assert response.status_code == 200
    assert calls == ["enable", "disable"]


def test_sync_settings_put_rejects_bad_relpath(monkeypatch, tmp_path: Path) -> None:
    _patch_environment(monkeypatch, tmp_path)

    response = sync_settings.sync_settings(
        _authenticated_request(
            "PUT",
            "/api/sync/settings/",
            {"folders": [{"relpath": "../etc"}]},
        )
    )

    assert response.status_code == 400
    assert sync_config.sync_folders() == ()


def test_sync_settings_put_requires_a_field(monkeypatch, tmp_path: Path) -> None:
    _patch_environment(monkeypatch, tmp_path)
    response = sync_settings.sync_settings(
        _authenticated_request("PUT", "/api/sync/settings/", {})
    )
    assert response.status_code == 400


def test_sync_conflicts_list_and_resolve(monkeypatch, tmp_path: Path) -> None:
    conflicts_path = tmp_path / "conflicts.json"
    monkeypatch.setattr(conflicts_module, "CODE_SYNC_CONFLICTS_PATH", conflicts_path)
    record = conflicts_module.record_branch_conflict(
        folder_id="cs-test",
        repo_relpath="repo",
        branch="main",
        local_sha="a" * 40,
        remote_sha="b" * 40,
    )

    response = sync_settings.sync_conflicts(
        _authenticated_request("GET", "/api/sync/conflicts/")
    )
    assert response.status_code == 200
    assert response.data["unresolved_count"] == 1
    assert response.data["conflicts"][0]["id"] == record["id"]

    response = sync_settings.sync_conflicts_resolve(
        _authenticated_request(
            "POST",
            "/api/sync/conflicts/resolve/",
            {"id": record["id"], "action": "keep_local"},
        )
    )
    assert response.status_code == 200
    assert response.data["conflict"]["resolved"] is True

    response = sync_settings.sync_conflicts_resolve(
        _authenticated_request(
            "POST",
            "/api/sync/conflicts/resolve/",
            {"id": "missing", "action": "keep_local"},
        )
    )
    assert response.status_code == 400


def test_sync_versions_purge_reports_freed_bytes(monkeypatch, tmp_path: Path) -> None:
    versions_dir = tmp_path / "sync-versions"
    (versions_dir / "cs-demo").mkdir(parents=True)
    (versions_dir / "cs-demo" / "old.py").write_text("x" * 100, encoding="utf-8")
    monkeypatch.setattr(sync_manager, "SYNC_VERSIONS_DIR", versions_dir)

    response = sync_settings.sync_versions_purge(
        _authenticated_request("POST", "/api/sync/versions/purge/")
    )

    assert response.status_code == 200
    assert response.data["freed_bytes"] == 100
    assert not (versions_dir / "cs-demo").exists()
