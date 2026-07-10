from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from openbase_coder_cli.mcp import claude_thread_sync
from openbase_coder_cli.mcp.claude_thread_sync import (
    claude_thread_snapshot_status,
    export_claude_thread_snapshots,
    import_claude_thread_snapshots,
    sync_claude_thread_snapshots_once,
    sync_claude_threads_once,
)


def _project_key(cwd: str) -> str:
    return cwd.replace("/", "-")


def _session_path(home: Path, cwd: str, session_id: str) -> Path:
    return home / "projects" / _project_key(cwd) / f"{session_id}.jsonl"


def _write_session(
    home: Path,
    cwd: str,
    session_id: str,
    *,
    user_text: str = "Build the thing",
    assistant_text: str = "Done.",
    extra_events: list[dict] | None = None,
) -> Path:
    path = _session_path(home, cwd, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    events = [
        {
            "type": "user",
            "sessionId": session_id,
            "cwd": cwd,
            "timestamp": "2026-06-20T12:00:00.000Z",
            "message": {"role": "user", "content": user_text},
        },
        {
            "type": "assistant",
            "sessionId": session_id,
            "cwd": cwd,
            "timestamp": "2026-06-20T12:00:01.000Z",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": assistant_text}],
            },
        },
        *(extra_events or []),
    ]
    path.write_text(
        "".join(json.dumps(event) + "\n" for event in events),
        encoding="utf-8",
    )
    return path


def test_sync_claude_threads_once_transfers_normal_session_and_backfills_openbase_metadata(
    tmp_path: Path,
) -> None:
    normal_home = tmp_path / "normal"
    openbase_home = tmp_path / "openbase"
    db_path = tmp_path / "super-agents" / "state.sqlite3"
    session_id = "820661e7-4408-4ca3-a772-d933bba3c006"
    cwd = "/tmp/project"
    source = _write_session(
        normal_home,
        cwd,
        session_id,
        user_text="Investigate Claude sync",
        assistant_text="Claude sync is ready.",
    )

    results = sync_claude_threads_once(
        normal_home=normal_home,
        openbase_home=openbase_home,
        ledger_path=tmp_path / "ledger.json",
        super_agents_db_path=db_path,
        stability_delay_seconds=0,
        max_age_days=None,
    )

    assert results[0].status == "transferred"
    assert results[0].direction == "normal_to_openbase"
    target = openbase_home / source.relative_to(normal_home)
    assert target.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            select
                id, name, cwd, command_json, status, last_observed_state,
                last_useful_message, backend_session_id, log_path, raw_log_path,
                created_at, updated_at
            from sessions
            """
        ).fetchone()
    assert row[:5] == (
        "claude_820661e744084ca3a772d933bba3c006",
        "Investigate Claude sync",
        cwd,
        json.dumps(["claude", "--resume", session_id]),
        "waiting",
    )
    observed_state = json.loads(row[5])
    assert observed_state["source"] == "claude_thread_sync"
    assert observed_state["backend_session_id"] == session_id
    assert row[6:] == (
        "Claude sync is ready.",
        session_id,
        None,
        None,
        "2026-06-20T12:00:00.000Z",
        "2026-06-20T12:00:01.000Z",
    )


def test_sync_claude_threads_once_transfers_openbase_session_to_normal(
    tmp_path: Path,
) -> None:
    normal_home = tmp_path / "normal"
    openbase_home = tmp_path / "openbase"
    normal_home.mkdir()
    session_id = "033648c9-16f8-4a8c-9a1a-9bbf20aa0b7d"
    source = _write_session(openbase_home, "/tmp/project", session_id)

    results = sync_claude_threads_once(
        normal_home=normal_home,
        openbase_home=openbase_home,
        ledger_path=tmp_path / "ledger.json",
        super_agents_db_path=tmp_path / "state.sqlite3",
        stability_delay_seconds=0,
        max_age_days=None,
    )

    assert results[0].status == "transferred"
    assert results[0].direction == "openbase_to_normal"
    target = normal_home / source.relative_to(openbase_home)
    assert target.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")


def test_sync_claude_threads_once_copies_session_companion_files(tmp_path: Path) -> None:
    normal_home = tmp_path / "normal"
    openbase_home = tmp_path / "openbase"
    session_id = "0e18b84c-bbfc-448a-979e-cc9b46e333b0"
    source = _write_session(normal_home, "/tmp/project", session_id)
    tool_result = source.parent / session_id / "tool-results" / "result.txt"
    tool_result.parent.mkdir(parents=True)
    tool_result.write_text("tool output", encoding="utf-8")
    task_lock = normal_home / "tasks" / session_id / ".lock"
    task_lock.parent.mkdir(parents=True)
    task_lock.write_text("locked", encoding="utf-8")
    highwater = normal_home / "tasks" / session_id / ".highwatermark"
    highwater.write_text("42", encoding="utf-8")

    results = sync_claude_threads_once(
        normal_home=normal_home,
        openbase_home=openbase_home,
        ledger_path=tmp_path / "ledger.json",
        super_agents_db_path=tmp_path / "state.sqlite3",
        stability_delay_seconds=0,
        max_age_days=None,
    )

    assert results[0].status == "transferred"
    assert (
        openbase_home / tool_result.relative_to(normal_home)
    ).read_text(encoding="utf-8") == "tool output"
    assert (
        openbase_home / highwater.relative_to(normal_home)
    ).read_text(encoding="utf-8") == "42"
    assert not (openbase_home / task_lock.relative_to(normal_home)).exists()


def test_sync_claude_threads_once_skips_symlinked_companion_files(
    tmp_path: Path,
) -> None:
    normal_home = tmp_path / "normal"
    openbase_home = tmp_path / "openbase"
    outside = tmp_path / "outside-secret.txt"
    outside.write_text("do not copy", encoding="utf-8")
    session_id = "fb7d3584-262e-433e-8d3a-57eb45f3c89a"
    source = _write_session(normal_home, "/tmp/project", session_id)
    link = source.parent / session_id / "tool-results" / "outside.txt"
    link.parent.mkdir(parents=True)
    link.symlink_to(outside)

    results = sync_claude_threads_once(
        normal_home=normal_home,
        openbase_home=openbase_home,
        ledger_path=tmp_path / "ledger.json",
        super_agents_db_path=tmp_path / "state.sqlite3",
        stability_delay_seconds=0,
        max_age_days=None,
    )

    assert results[0].status == "transferred"
    assert not (openbase_home / link.relative_to(normal_home)).exists()


def test_sync_claude_threads_once_marks_same_content_synced(tmp_path: Path) -> None:
    normal_home = tmp_path / "normal"
    openbase_home = tmp_path / "openbase"
    session_id = "253d9d3a-c10f-4380-a927-47e6784f686b"
    normal = _write_session(normal_home, "/tmp/project", session_id)
    openbase = openbase_home / normal.relative_to(normal_home)
    openbase.parent.mkdir(parents=True, exist_ok=True)
    openbase.write_text(normal.read_text(encoding="utf-8"), encoding="utf-8")

    results = sync_claude_threads_once(
        normal_home=normal_home,
        openbase_home=openbase_home,
        ledger_path=tmp_path / "ledger.json",
        super_agents_db_path=tmp_path / "state.sqlite3",
        stability_delay_seconds=0,
        max_age_days=None,
    )

    assert results[0].status == "already_synced"
    assert results[0].reason == "same_content"


def test_sync_claude_threads_once_repairs_append_only_prefix_conflict(
    tmp_path: Path,
) -> None:
    normal_home = tmp_path / "normal"
    openbase_home = tmp_path / "openbase"
    session_id = "436d32b5-77d6-4ab4-8dc4-891c0e1f98a2"
    normal = _write_session(normal_home, "/tmp/project", session_id)
    openbase = openbase_home / normal.relative_to(normal_home)
    openbase.parent.mkdir(parents=True, exist_ok=True)
    openbase.write_text(normal.read_text(encoding="utf-8"), encoding="utf-8")
    with normal.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "type": "assistant",
                    "sessionId": session_id,
                    "timestamp": "2026-06-20T12:00:02.000Z",
                    "message": {"role": "assistant", "content": "More work."},
                }
            )
            + "\n"
        )

    results = sync_claude_threads_once(
        normal_home=normal_home,
        openbase_home=openbase_home,
        ledger_path=tmp_path / "ledger.json",
        super_agents_db_path=tmp_path / "state.sqlite3",
        stability_delay_seconds=0,
        max_age_days=None,
    )

    assert results[0].status == "transferred"
    assert results[0].reason == "synced_append_only_to_openbase"
    assert openbase.read_text(encoding="utf-8") == normal.read_text(encoding="utf-8")


def test_sync_claude_threads_once_marks_divergent_sessions_conflicted(
    tmp_path: Path,
) -> None:
    normal_home = tmp_path / "normal"
    openbase_home = tmp_path / "openbase"
    session_id = "9bcc34b6-2bbf-48b2-80c3-12a377b83908"
    _write_session(normal_home, "/tmp/project", session_id, assistant_text="Normal")
    _write_session(openbase_home, "/tmp/project", session_id, assistant_text="Openbase")

    results = sync_claude_threads_once(
        normal_home=normal_home,
        openbase_home=openbase_home,
        ledger_path=tmp_path / "ledger.json",
        super_agents_db_path=tmp_path / "state.sqlite3",
        stability_delay_seconds=0,
        max_age_days=None,
    )

    assert results[0].status == "conflict"
    assert results[0].reason == "both_homes_changed"


def test_sync_claude_threads_once_skips_old_sessions(tmp_path: Path) -> None:
    normal_home = tmp_path / "normal"
    openbase_home = tmp_path / "openbase"
    _write_session(
        normal_home,
        "/tmp/project",
        "bf4129a4-478d-45ae-9d9d-132eb5380309",
    )

    results = sync_claude_threads_once(
        normal_home=normal_home,
        openbase_home=openbase_home,
        ledger_path=tmp_path / "ledger.json",
        super_agents_db_path=tmp_path / "state.sqlite3",
        stability_delay_seconds=0,
        max_age_days=0,
    )

    assert results[0].status == "skipped"
    assert results[0].reason == "skipped_old"


def test_sync_claude_threads_once_skips_active_backend_session(tmp_path: Path) -> None:
    normal_home = tmp_path / "normal"
    openbase_home = tmp_path / "openbase"
    db_path = tmp_path / "state.sqlite3"
    session_id = "ecc60e22-9af9-4bcb-a6a8-638b25e6641f"
    _write_session(normal_home, "/tmp/project", session_id)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            create table sessions (
                id text primary key,
                name text not null unique,
                cwd text not null,
                command_json text not null,
                status text not null,
                active_turn_id text,
                backend_session_id text,
                created_at text not null,
                updated_at text not null
            )
            """
        )
        conn.execute(
            """
            insert into sessions (
                id, name, cwd, command_json, status, active_turn_id,
                backend_session_id, created_at, updated_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "s_active",
                "active",
                "/tmp/project",
                "[]",
                "running",
                "t_active",
                session_id,
                "2026-06-20T12:00:00.000Z",
                "2026-06-20T12:00:00.000Z",
            ),
        )

    results = sync_claude_threads_once(
        normal_home=normal_home,
        openbase_home=openbase_home,
        ledger_path=tmp_path / "ledger.json",
        super_agents_db_path=db_path,
        stability_delay_seconds=0,
        max_age_days=None,
    )

    assert results[0].status == "skipped"
    assert results[0].reason == "skipped_active"


def test_sync_claude_threads_once_does_not_treat_idle_waiting_session_as_active(
    tmp_path: Path,
) -> None:
    normal_home = tmp_path / "normal"
    openbase_home = tmp_path / "openbase"
    db_path = tmp_path / "state.sqlite3"
    session_id = "e04cf736-f39e-4e35-8f6c-0c46b67cee68"
    _write_session(normal_home, "/tmp/project", session_id)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            create table sessions (
                id text primary key,
                name text not null unique,
                cwd text not null,
                command_json text not null,
                status text not null,
                active_turn_id text,
                backend_session_id text,
                created_at text not null,
                updated_at text not null
            )
            """
        )
        conn.execute(
            """
            insert into sessions (
                id, name, cwd, command_json, status, active_turn_id,
                backend_session_id, created_at, updated_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "s_idle",
                "idle",
                "/tmp/project",
                "[]",
                "waiting",
                None,
                session_id,
                "2026-06-20T12:00:00.000Z",
                "2026-06-20T12:00:00.000Z",
            ),
        )

    results = sync_claude_threads_once(
        normal_home=normal_home,
        openbase_home=openbase_home,
        ledger_path=tmp_path / "ledger.json",
        super_agents_db_path=db_path,
        stability_delay_seconds=0,
        max_age_days=None,
    )

    assert results[0].status == "transferred"
    assert results[0].direction == "normal_to_openbase"


def test_backfill_preserves_custom_observed_state_while_updating_latest_message(
    tmp_path: Path,
) -> None:
    normal_home = tmp_path / "normal"
    openbase_home = tmp_path / "openbase"
    db_path = tmp_path / "state.sqlite3"
    session_id = "9b981e27-24bd-4dae-8dbf-82bd68732c94"
    _write_session(
        normal_home,
        "/tmp/project",
        session_id,
        assistant_text="New useful message.",
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            create table sessions (
                id text primary key,
                name text not null unique,
                cwd text not null,
                command_json text not null,
                status text not null,
                last_observed_state text,
                last_useful_message text,
                backend_session_id text,
                created_at text not null,
                updated_at text not null
            )
            """
        )
        conn.execute(
            """
            insert into sessions (
                id, name, cwd, command_json, status, last_observed_state,
                last_useful_message, backend_session_id, created_at, updated_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "existing",
                "existing",
                "/tmp/project",
                "[]",
                "waiting",
                '{"source": "custom"}',
                "Old useful message.",
                session_id,
                "2026-06-19T12:00:00.000Z",
                "2026-06-19T12:00:00.000Z",
            ),
        )

    results = sync_claude_threads_once(
        normal_home=normal_home,
        openbase_home=openbase_home,
        ledger_path=tmp_path / "ledger.json",
        super_agents_db_path=db_path,
        stability_delay_seconds=0,
        max_age_days=None,
    )

    assert results[0].status == "transferred"
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "select last_observed_state, last_useful_message, updated_at from sessions"
        ).fetchone()
    assert row == (
        '{"source": "custom"}',
        "New useful message.",
        "2026-06-20T12:00:01.000Z",
    )


def test_export_claude_thread_snapshot_writes_metadata_and_companions(
    tmp_path: Path,
) -> None:
    openbase_home = tmp_path / "openbase"
    exchange_dir = tmp_path / "exchange"
    session_id = "1153fd55-3866-4408-bf95-499aa32d3c0f"
    source = _write_session(openbase_home, "/tmp/project", session_id)
    tool_result = source.parent / session_id / "tool-results" / "result.txt"
    tool_result.parent.mkdir(parents=True)
    tool_result.write_text("tool output", encoding="utf-8")

    results = export_claude_thread_snapshots(
        openbase_home=openbase_home,
        exchange_dir=exchange_dir,
        device_identity_path=tmp_path / "source-device.json",
        ledger_path=tmp_path / "source-ledger.json",
        super_agents_db_path=tmp_path / "state.sqlite3",
        stability_delay_seconds=0,
        max_age_days=None,
    )

    assert results[0].status == "exported"
    snapshot_dir = Path(results[0].snapshot_path or "")
    metadata = json.loads((snapshot_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["session_id"] == session_id
    assert metadata["root_relative_path"] == source.relative_to(openbase_home).as_posix()
    assert source.relative_to(openbase_home).as_posix() in metadata["files"]
    assert (snapshot_dir / "files" / tool_result.relative_to(openbase_home)).read_text(
        encoding="utf-8"
    ) == "tool output"


def test_import_claude_thread_snapshot_creates_session_and_backfills_metadata(
    tmp_path: Path,
) -> None:
    source_home = tmp_path / "source"
    target_home = tmp_path / "target"
    exchange_dir = tmp_path / "exchange"
    db_path = tmp_path / "target-state.sqlite3"
    session_id = "1416448e-c428-455b-bceb-5ac34da8ee4e"
    _write_session(
        source_home,
        "/tmp/project",
        session_id,
        user_text="Build cross device",
        assistant_text="Cross device done.",
    )
    export_claude_thread_snapshots(
        openbase_home=source_home,
        exchange_dir=exchange_dir,
        device_identity_path=tmp_path / "source-device.json",
        ledger_path=tmp_path / "source-ledger.json",
        super_agents_db_path=tmp_path / "source-state.sqlite3",
        stability_delay_seconds=0,
        max_age_days=None,
    )

    results = import_claude_thread_snapshots(
        openbase_home=target_home,
        exchange_dir=exchange_dir,
        device_identity_path=tmp_path / "target-device.json",
        ledger_path=tmp_path / "target-ledger.json",
        super_agents_db_path=db_path,
    )

    assert results[0].status == "imported"
    target_session = _session_path(target_home, "/tmp/project", session_id)
    assert target_session.exists()
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "select name, backend_session_id, last_useful_message from sessions"
        ).fetchone()
    assert row == ("Build cross device", session_id, "Cross device done.")


def test_import_claude_thread_snapshot_is_idempotent(tmp_path: Path) -> None:
    source_home = tmp_path / "source"
    target_home = tmp_path / "target"
    exchange_dir = tmp_path / "exchange"
    session_id = "1aaa22b0-d887-4d15-8ed6-beafb084a924"
    _write_session(source_home, "/tmp/project", session_id)
    export_claude_thread_snapshots(
        openbase_home=source_home,
        exchange_dir=exchange_dir,
        device_identity_path=tmp_path / "source-device.json",
        ledger_path=tmp_path / "source-ledger.json",
        super_agents_db_path=tmp_path / "source-state.sqlite3",
        stability_delay_seconds=0,
        max_age_days=None,
    )

    first = import_claude_thread_snapshots(
        openbase_home=target_home,
        exchange_dir=exchange_dir,
        device_identity_path=tmp_path / "target-device.json",
        ledger_path=tmp_path / "target-ledger.json",
        super_agents_db_path=tmp_path / "target-state.sqlite3",
    )
    second = import_claude_thread_snapshots(
        openbase_home=target_home,
        exchange_dir=exchange_dir,
        device_identity_path=tmp_path / "target-device.json",
        ledger_path=tmp_path / "target-ledger.json",
        super_agents_db_path=tmp_path / "target-state.sqlite3",
    )

    assert first[0].status == "imported"
    assert second[0].status == "already_imported"


def test_import_claude_thread_snapshot_failed_commit_leaves_no_visible_session(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source_home = tmp_path / "source"
    target_home = tmp_path / "target"
    exchange_dir = tmp_path / "exchange"
    session_id = "4a91cc85-7601-42f1-a8c1-dcb8c58418ea"
    _write_session(source_home, "/tmp/project", session_id)
    export_claude_thread_snapshots(
        openbase_home=source_home,
        exchange_dir=exchange_dir,
        device_identity_path=tmp_path / "source-device.json",
        ledger_path=tmp_path / "source-ledger.json",
        super_agents_db_path=tmp_path / "source-state.sqlite3",
        stability_delay_seconds=0,
        max_age_days=None,
    )

    def fail_commit(**_kwargs):
        raise RuntimeError("commit failed")

    monkeypatch.setattr(claude_thread_sync, "_commit_staged_session", fail_commit)

    results = import_claude_thread_snapshots(
        openbase_home=target_home,
        exchange_dir=exchange_dir,
        device_identity_path=tmp_path / "target-device.json",
        ledger_path=tmp_path / "target-ledger.json",
        super_agents_db_path=tmp_path / "target-state.sqlite3",
    )

    assert results[0].status == "error"
    assert results[0].reason == "import_failed"
    assert not _session_path(target_home, "/tmp/project", session_id).exists()
    assert not (target_home / ".claude-thread-sync-staging").exists()


def test_import_claude_thread_snapshot_records_conflict_evidence(
    tmp_path: Path,
) -> None:
    source_home = tmp_path / "source"
    target_home = tmp_path / "target"
    exchange_dir = tmp_path / "exchange"
    target_ledger = tmp_path / "target-ledger.json"
    session_id = "1aca9dce-dd37-4558-a56a-8677dd981e34"
    _write_session(source_home, "/tmp/project", session_id, assistant_text="Remote")
    _write_session(target_home, "/tmp/project", session_id, assistant_text="Local")
    export_claude_thread_snapshots(
        openbase_home=source_home,
        exchange_dir=exchange_dir,
        device_identity_path=tmp_path / "source-device.json",
        ledger_path=tmp_path / "source-ledger.json",
        super_agents_db_path=tmp_path / "source-state.sqlite3",
        stability_delay_seconds=0,
        max_age_days=None,
    )

    results = import_claude_thread_snapshots(
        openbase_home=target_home,
        exchange_dir=exchange_dir,
        device_identity_path=tmp_path / "target-device.json",
        ledger_path=target_ledger,
        super_agents_db_path=tmp_path / "target-state.sqlite3",
    )

    assert results[0].status == "conflict"
    assert results[0].reason == "divergent_fingerprint"
    status = claude_thread_snapshot_status(
        exchange_dir=exchange_dir,
        device_identity_path=tmp_path / "target-device.json",
        ledger_path=target_ledger,
    )
    assert status["conflict_count"] == 1
    assert status["conflicts"][0]["session_id"] == session_id
    assert status["conflicts"][0]["snapshot_path"]


def test_claude_thread_sync_smoke_local_and_cross_device(tmp_path: Path) -> None:
    normal_home = tmp_path / "normal"
    source_openbase_home = tmp_path / "source-openbase"
    target_openbase_home = tmp_path / "target-openbase"
    exchange_dir = tmp_path / "exchange"
    session_id = "1b10c364-690a-49f3-99b9-c9d544817a85"
    _write_session(
        normal_home,
        "/tmp/project",
        session_id,
        user_text="Smoke test Claude sync",
        assistant_text="Smoke test complete.",
    )

    local_results = sync_claude_threads_once(
        normal_home=normal_home,
        openbase_home=source_openbase_home,
        ledger_path=tmp_path / "local-ledger.json",
        super_agents_db_path=tmp_path / "source-state.sqlite3",
        stability_delay_seconds=0,
        max_age_days=None,
    )
    device_result = sync_claude_thread_snapshots_once(
        openbase_home=source_openbase_home,
        exchange_dir=exchange_dir,
        device_identity_path=tmp_path / "source-device.json",
        ledger_path=tmp_path / "source-device-ledger.json",
        super_agents_db_path=tmp_path / "source-state.sqlite3",
        stability_delay_seconds=0,
        max_age_days=None,
    )
    imports = import_claude_thread_snapshots(
        openbase_home=target_openbase_home,
        exchange_dir=exchange_dir,
        device_identity_path=tmp_path / "target-device.json",
        ledger_path=tmp_path / "target-device-ledger.json",
        super_agents_db_path=tmp_path / "target-state.sqlite3",
    )

    assert local_results[0].status == "transferred"
    assert device_result["exports"][0].status == "exported"
    assert imports[0].status == "imported"
    assert _session_path(target_openbase_home, "/tmp/project", session_id).exists()
    with sqlite3.connect(tmp_path / "target-state.sqlite3") as conn:
        row = conn.execute(
            "select name, backend_session_id, last_useful_message from sessions"
        ).fetchone()
    assert row == ("Smoke test Claude sync", session_id, "Smoke test complete.")
