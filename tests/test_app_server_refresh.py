from __future__ import annotations

import time
from pathlib import Path

from openbase_coder_cli.services import app_server_refresh
from openbase_coder_cli.services.app_server_refresh import (
    run_pending_codex_app_server_refresh,
)


def _write_env(tmp_path: Path, backend: str) -> Path:
    env_path = tmp_path / ".env"
    env_path.write_text(f"OPENBASE_CODING_BACKEND={backend}\n", encoding="utf-8")
    return env_path


def _marker(tmp_path: Path) -> Path:
    marker = tmp_path / "refresh-pending"
    marker.write_text("test\n", encoding="utf-8")
    return marker


def test_no_marker_means_not_pending(tmp_path: Path) -> None:
    outcome = run_pending_codex_app_server_refresh(
        codex_home=tmp_path / "codex_home",
        env_path=_write_env(tmp_path, "codex"),
        marker_path=tmp_path / "refresh-pending",
    )
    assert outcome == "not_pending"


def test_claude_backend_clears_marker_without_restart(
    tmp_path: Path, monkeypatch
) -> None:
    marker = _marker(tmp_path)
    monkeypatch.setattr(
        app_server_refresh,
        "_restart_app_server",
        lambda: (_ for _ in ()).throw(AssertionError("must not restart")),
    )

    outcome = run_pending_codex_app_server_refresh(
        codex_home=tmp_path / "codex_home",
        env_path=_write_env(tmp_path, "claude_code"),
        marker_path=marker,
    )

    assert outcome == "backend_not_codex"
    assert not marker.exists()


def test_recent_rollout_write_defers_and_keeps_marker(
    tmp_path: Path, monkeypatch
) -> None:
    marker = _marker(tmp_path)
    codex_home = tmp_path / "codex_home"
    rollout = codex_home / "sessions" / "2026" / "07" / "14" / "rollout-a.jsonl"
    rollout.parent.mkdir(parents=True)
    rollout.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(app_server_refresh, "_voice_room_active", lambda: False)

    outcome = run_pending_codex_app_server_refresh(
        codex_home=codex_home,
        env_path=_write_env(tmp_path, "codex"),
        marker_path=marker,
        now=time.time(),
    )

    assert outcome == "deferred_threads_active"
    assert marker.exists()


def test_active_voice_room_defers_and_keeps_marker(tmp_path: Path, monkeypatch) -> None:
    marker = _marker(tmp_path)
    monkeypatch.setattr(app_server_refresh, "_voice_room_active", lambda: True)

    outcome = run_pending_codex_app_server_refresh(
        codex_home=tmp_path / "codex_home",
        env_path=_write_env(tmp_path, "codex"),
        marker_path=marker,
    )

    assert outcome == "deferred_voice_active"
    assert marker.exists()


def test_idle_machine_restarts_and_clears_marker(tmp_path: Path, monkeypatch) -> None:
    marker = _marker(tmp_path)
    codex_home = tmp_path / "codex_home"
    rollout = codex_home / "sessions" / "2026" / "07" / "01" / "rollout-old.jsonl"
    rollout.parent.mkdir(parents=True)
    rollout.write_text("{}\n", encoding="utf-8")
    restarted = []
    monkeypatch.setattr(app_server_refresh, "_voice_room_active", lambda: False)
    monkeypatch.setattr(
        app_server_refresh,
        "_restart_app_server",
        lambda: restarted.append(True) or True,
    )

    outcome = run_pending_codex_app_server_refresh(
        codex_home=codex_home,
        env_path=_write_env(tmp_path, "codex"),
        marker_path=marker,
        now=time.time() + 3600,
    )

    assert outcome == "refreshed"
    assert restarted == [True]
    assert not marker.exists()


def test_failed_restart_keeps_marker_for_retry(tmp_path: Path, monkeypatch) -> None:
    marker = _marker(tmp_path)
    monkeypatch.setattr(app_server_refresh, "_voice_room_active", lambda: False)
    monkeypatch.setattr(app_server_refresh, "_restart_app_server", lambda: False)

    outcome = run_pending_codex_app_server_refresh(
        codex_home=tmp_path / "codex_home",
        env_path=_write_env(tmp_path, "codex"),
        marker_path=marker,
    )

    assert outcome == "restart_failed"
    assert marker.exists()


def test_resolution_requests_refresh(tmp_path: Path, monkeypatch) -> None:
    marker = tmp_path / "refresh-pending"
    monkeypatch.setattr(app_server_refresh, "REFRESH_MARKER_PATH", marker)

    app_server_refresh.request_codex_app_server_refresh("test_reason")

    assert marker.read_text(encoding="utf-8") == "test_reason\n"
