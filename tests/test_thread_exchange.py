from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from openbase_coder_cli.mcp.thread_exchange import (
    export_thread_snapshots,
    get_or_create_device_identity,
    import_thread_snapshots,
    thread_snapshot_status,
)


def _create_state_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE threads (
                id TEXT PRIMARY KEY,
                rollout_path TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                source TEXT NOT NULL,
                model_provider TEXT NOT NULL,
                cwd TEXT NOT NULL,
                title TEXT NOT NULL,
                sandbox_policy TEXT NOT NULL,
                approval_mode TEXT NOT NULL,
                archived INTEGER NOT NULL DEFAULT 0,
                cli_version TEXT NOT NULL DEFAULT '',
                first_user_message TEXT NOT NULL DEFAULT '',
                model TEXT,
                reasoning_effort TEXT,
                created_at_ms INTEGER,
                updated_at_ms INTEGER,
                preview TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE thread_dynamic_tools (
                thread_id TEXT NOT NULL,
                position INTEGER NOT NULL,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                input_schema TEXT NOT NULL,
                defer_loading INTEGER NOT NULL DEFAULT 0,
                namespace TEXT,
                PRIMARY KEY(thread_id, position)
            )
            """
        )


def _insert_thread(
    home: Path,
    thread_id: str,
    *,
    title: str,
    updated_at: int,
    terminal_message: str = "done",
) -> Path:
    rollout_path = (
        home
        / "sessions"
        / "2026"
        / "06"
        / "16"
        / f"rollout-2026-06-16T10-00-00-{thread_id}.jsonl"
    )
    rollout_path.parent.mkdir(parents=True, exist_ok=True)
    rollout_path.write_text(
        "\n".join(
            [
                json.dumps({"type": "session_meta", "payload": {"id": thread_id}}),
                json.dumps(
                    {
                        "timestamp": "2026-06-16T12:00:00.000Z",
                        "type": "event_msg",
                        "payload": {
                            "type": "task_complete",
                            "turn_id": "turn-1",
                            "last_agent_message": terminal_message,
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    with sqlite3.connect(home / "state_5.sqlite") as conn:
        conn.execute(
            """
            INSERT INTO threads (
                id, rollout_path, created_at, updated_at, source, model_provider,
                cwd, title, sandbox_policy, approval_mode, archived, cli_version,
                first_user_message, model, reasoning_effort, created_at_ms,
                updated_at_ms, preview
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                thread_id,
                str(rollout_path),
                updated_at - 5,
                updated_at,
                "cli",
                "openai",
                "/tmp/project",
                title,
                "danger-full-access",
                "never",
                0,
                "0.1.0",
                title,
                "gpt-test",
                "high",
                (updated_at - 5) * 1000,
                updated_at * 1000,
                title,
            ),
        )
    return rollout_path


def _append_index(home: Path, thread_id: str, name: str) -> None:
    with (home / "session_index.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "id": thread_id,
                    "thread_name": name,
                    "updated_at": "2026-06-16T12:00:00Z",
                }
            )
            + "\n"
        )


def _append_dynamic_tool(home: Path, thread_id: str, name: str) -> None:
    with sqlite3.connect(home / "state_5.sqlite") as conn:
        conn.execute(
            """
            INSERT INTO thread_dynamic_tools (
                thread_id, position, name, description, input_schema
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (thread_id, 0, name, "Example", "{}"),
        )


def test_device_identity_is_stable(tmp_path: Path) -> None:
    path = tmp_path / "device.json"

    first = get_or_create_device_identity(path)
    second = get_or_create_device_identity(path)

    assert first.device_id == second.device_id
    assert first.device_name == second.device_name


def test_export_thread_snapshot_writes_metadata_and_rollout(tmp_path: Path) -> None:
    home = tmp_path / "home"
    exchange_dir = tmp_path / "exchange"
    _create_state_db(home / "state_5.sqlite")
    source_rollout = _insert_thread(home, "thread-1", title="Thread title", updated_at=20)
    _append_index(home, "thread-1", "Indexed title")
    _append_dynamic_tool(home, "thread-1", "example_tool")

    results = export_thread_snapshots(
        codex_home=home,
        exchange_dir=exchange_dir,
        device_identity_path=tmp_path / "device.json",
        ledger_path=tmp_path / "ledger.json",
        stability_delay_seconds=0,
        max_age_days=None,
    )

    exported = [result for result in results if result.status == "exported"]
    assert len(exported) == 1
    snapshot_dir = Path(exported[0].snapshot_path or "")
    metadata = json.loads((snapshot_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["thread_id"] == "thread-1"
    assert metadata["thread_row"]["title"] == "Thread title"
    assert "rollout_path" not in metadata["thread_row"]
    assert metadata["session_index_entry"]["thread_name"] == "Indexed title"
    assert metadata["dynamic_tools"][0]["name"] == "example_tool"
    assert (snapshot_dir / "rollout.jsonl").read_text(
        encoding="utf-8"
    ) == source_rollout.read_text(encoding="utf-8")


def test_import_snapshot_creates_local_thread_state(tmp_path: Path) -> None:
    source_home = tmp_path / "source"
    target_home = tmp_path / "target"
    exchange_dir = tmp_path / "exchange"
    _create_state_db(source_home / "state_5.sqlite")
    _create_state_db(target_home / "state_5.sqlite")
    _insert_thread(source_home, "thread-1", title="Thread title", updated_at=20)
    _append_index(source_home, "thread-1", "Indexed title")
    _append_dynamic_tool(source_home, "thread-1", "example_tool")
    export_thread_snapshots(
        codex_home=source_home,
        exchange_dir=exchange_dir,
        device_identity_path=tmp_path / "source-device.json",
        ledger_path=tmp_path / "source-ledger.json",
        stability_delay_seconds=0,
        max_age_days=None,
    )

    results = import_thread_snapshots(
        codex_home=target_home,
        exchange_dir=exchange_dir,
        device_identity_path=tmp_path / "target-device.json",
        ledger_path=tmp_path / "target-ledger.json",
    )

    assert [result.status for result in results] == ["imported"]
    with sqlite3.connect(target_home / "state_5.sqlite") as conn:
        row = conn.execute(
            "SELECT title, rollout_path FROM threads WHERE id = ?",
            ("thread-1",),
        ).fetchone()
        tool_row = conn.execute(
            "SELECT name FROM thread_dynamic_tools WHERE thread_id = ?",
            ("thread-1",),
        ).fetchone()
    assert row[0] == "Thread title"
    assert Path(row[1]).exists()
    assert tool_row == ("example_tool",)
    index_lines = (target_home / "session_index.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()
    assert json.loads(index_lines[-1])["thread_name"] == "Indexed title"


def test_import_snapshot_is_idempotent(tmp_path: Path) -> None:
    source_home = tmp_path / "source"
    target_home = tmp_path / "target"
    exchange_dir = tmp_path / "exchange"
    target_ledger = tmp_path / "target-ledger.json"
    _create_state_db(source_home / "state_5.sqlite")
    _create_state_db(target_home / "state_5.sqlite")
    _insert_thread(source_home, "thread-1", title="Thread title", updated_at=20)
    export_thread_snapshots(
        codex_home=source_home,
        exchange_dir=exchange_dir,
        device_identity_path=tmp_path / "source-device.json",
        ledger_path=tmp_path / "source-ledger.json",
        stability_delay_seconds=0,
        max_age_days=None,
    )

    first = import_thread_snapshots(
        codex_home=target_home,
        exchange_dir=exchange_dir,
        device_identity_path=tmp_path / "target-device.json",
        ledger_path=target_ledger,
    )
    second = import_thread_snapshots(
        codex_home=target_home,
        exchange_dir=exchange_dir,
        device_identity_path=tmp_path / "target-device.json",
        ledger_path=target_ledger,
    )

    assert first[0].status == "imported"
    assert second[0].status == "already_imported"


def test_import_snapshot_detects_divergent_local_thread(tmp_path: Path) -> None:
    source_home = tmp_path / "source"
    target_home = tmp_path / "target"
    exchange_dir = tmp_path / "exchange"
    target_ledger = tmp_path / "target-ledger.json"
    _create_state_db(source_home / "state_5.sqlite")
    _create_state_db(target_home / "state_5.sqlite")
    _insert_thread(
        source_home,
        "thread-1",
        title="Remote title",
        updated_at=20,
        terminal_message="remote done",
    )
    _insert_thread(
        target_home,
        "thread-1",
        title="Local title",
        updated_at=30,
        terminal_message="local done",
    )
    export_thread_snapshots(
        codex_home=source_home,
        exchange_dir=exchange_dir,
        device_identity_path=tmp_path / "source-device.json",
        ledger_path=tmp_path / "source-ledger.json",
        stability_delay_seconds=0,
        max_age_days=None,
    )

    results = import_thread_snapshots(
        codex_home=target_home,
        exchange_dir=exchange_dir,
        device_identity_path=tmp_path / "target-device.json",
        ledger_path=target_ledger,
    )

    assert results[0].status == "conflict"
    assert results[0].reason == "divergent_fingerprint"
    status = thread_snapshot_status(
        exchange_dir=exchange_dir,
        device_identity_path=tmp_path / "target-device.json",
        ledger_path=target_ledger,
    )
    assert status["conflict_count"] == 1
