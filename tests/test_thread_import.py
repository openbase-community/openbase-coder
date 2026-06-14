from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path

from openbase_coder_cli.mcp.thread_import import (
    CodexThreadSyncResult,
    _log_sync_result,
    export_voice_codex_threads,
    import_normal_codex_threads,
    list_normal_codex_threads,
    list_voice_codex_threads,
    sync_codex_threads_once,
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


def _insert_thread(home: Path, thread_id: str, *, title: str, updated_at: int) -> Path:
    rollout_path = (
        home
        / "sessions"
        / "2026"
        / "05"
        / "21"
        / f"rollout-2026-05-21T10-00-00-{thread_id}.jsonl"
    )
    rollout_path.parent.mkdir(parents=True, exist_ok=True)
    rollout_path.write_text(
        json.dumps({"type": "session_meta", "payload": {"id": thread_id}}) + "\n",
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


def _append_index(home: Path, thread_id: str, name: str, updated_at: str) -> None:
    with (home / "session_index.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps({"id": thread_id, "thread_name": name, "updated_at": updated_at})
            + "\n"
        )


def _append_terminal(
    rollout_path: Path, turn_id: str = "turn-1", message: str = "done"
) -> None:
    with rollout_path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "timestamp": "2026-05-21T12:00:00.000Z",
                    "type": "event_msg",
                    "payload": {
                        "type": "task_complete",
                        "turn_id": turn_id,
                        "last_agent_message": message,
                    },
                }
            )
            + "\n"
        )


def test_list_normal_codex_threads_uses_latest_index_metadata(tmp_path: Path) -> None:
    normal_home = tmp_path / "normal"
    voice_home = tmp_path / "voice"
    _create_state_db(normal_home / "state_5.sqlite")
    _create_state_db(voice_home / "state_5.sqlite")
    _insert_thread(normal_home, "thread-1", title="Original title", updated_at=10)
    _append_index(normal_home, "thread-1", "Old name", "2026-05-21T10:00:00Z")
    _append_index(normal_home, "thread-1", "New name", "2026-05-21T11:00:00Z")

    threads = list_normal_codex_threads(
        normal_home=normal_home,
        voice_home=voice_home,
    )

    assert len(threads) == 1
    assert threads[0].thread_id == "thread-1"
    assert threads[0].title == "New name"
    assert threads[0].imported is False


def test_list_voice_codex_threads_marks_exported_threads(tmp_path: Path) -> None:
    normal_home = tmp_path / "normal"
    voice_home = tmp_path / "voice"
    _create_state_db(normal_home / "state_5.sqlite")
    _create_state_db(voice_home / "state_5.sqlite")
    _insert_thread(voice_home, "thread-1", title="Voice title", updated_at=10)
    _insert_thread(normal_home, "thread-1", title="Normal title", updated_at=20)

    threads = list_voice_codex_threads(
        normal_home=normal_home,
        voice_home=voice_home,
    )

    assert len(threads) == 1
    assert threads[0].thread_id == "thread-1"
    assert threads[0].transferred is True
    assert threads[0].imported is True
    assert threads[0].exported is True


def test_import_normal_codex_thread_copies_rollout_index_and_state(
    tmp_path: Path,
) -> None:
    normal_home = tmp_path / "normal"
    voice_home = tmp_path / "voice"
    _create_state_db(normal_home / "state_5.sqlite")
    _create_state_db(voice_home / "state_5.sqlite")
    source_rollout = _insert_thread(
        normal_home,
        "thread-1",
        title="Thread title",
        updated_at=20,
    )
    _append_index(normal_home, "thread-1", "Indexed title", "2026-05-21T12:00:00Z")
    with sqlite3.connect(normal_home / "state_5.sqlite") as conn:
        conn.execute(
            """
            INSERT INTO thread_dynamic_tools (
                thread_id, position, name, description, input_schema
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            ("thread-1", 0, "example_tool", "Example", "{}"),
        )

    results = import_normal_codex_threads(
        ["thread-1"],
        normal_home=normal_home,
        voice_home=voice_home,
    )

    assert results[0].imported is True
    target_rollout = voice_home / source_rollout.relative_to(normal_home)
    assert target_rollout.read_text(encoding="utf-8") == source_rollout.read_text(
        encoding="utf-8"
    )
    index_lines = (
        (voice_home / "session_index.jsonl").read_text(encoding="utf-8").splitlines()
    )
    assert json.loads(index_lines[-1])["thread_name"] == "Indexed title"
    with sqlite3.connect(voice_home / "state_5.sqlite") as conn:
        thread_row = conn.execute(
            "SELECT rollout_path, title FROM threads WHERE id = ?",
            ("thread-1",),
        ).fetchone()
        dynamic_tool_row = conn.execute(
            "SELECT name FROM thread_dynamic_tools WHERE thread_id = ?",
            ("thread-1",),
        ).fetchone()
    assert thread_row == (str(target_rollout), "Thread title")
    assert dynamic_tool_row == ("example_tool",)


def test_import_normal_codex_thread_skips_existing_thread(tmp_path: Path) -> None:
    normal_home = tmp_path / "normal"
    voice_home = tmp_path / "voice"
    _create_state_db(normal_home / "state_5.sqlite")
    _create_state_db(voice_home / "state_5.sqlite")
    _insert_thread(normal_home, "thread-1", title="Thread title", updated_at=20)
    _insert_thread(voice_home, "thread-1", title="Existing title", updated_at=30)

    results = import_normal_codex_threads(
        ["thread-1"],
        normal_home=normal_home,
        voice_home=voice_home,
    )

    assert results[0].imported is False
    assert results[0].reason == "already_imported"


def test_export_voice_codex_thread_copies_rollout_index_and_state(
    tmp_path: Path,
) -> None:
    normal_home = tmp_path / "normal"
    voice_home = tmp_path / "voice"
    _create_state_db(normal_home / "state_5.sqlite")
    _create_state_db(voice_home / "state_5.sqlite")
    source_rollout = _insert_thread(
        voice_home,
        "thread-voice",
        title="Voice title",
        updated_at=20,
    )
    _append_index(voice_home, "thread-voice", "Voice index", "2026-05-21T12:00:00Z")
    with sqlite3.connect(voice_home / "state_5.sqlite") as conn:
        conn.execute(
            """
            INSERT INTO thread_dynamic_tools (
                thread_id, position, name, description, input_schema
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            ("thread-voice", 0, "voice_tool", "Example", "{}"),
        )

    results = export_voice_codex_threads(
        ["thread-voice"],
        normal_home=normal_home,
        voice_home=voice_home,
    )

    assert results[0].transferred is True
    assert results[0].exported is True
    assert results[0].reason == "exported"
    target_rollout = normal_home / source_rollout.relative_to(voice_home)
    assert target_rollout.read_text(encoding="utf-8") == source_rollout.read_text(
        encoding="utf-8"
    )
    index_lines = (
        (normal_home / "session_index.jsonl").read_text(encoding="utf-8").splitlines()
    )
    assert json.loads(index_lines[-1])["thread_name"] == "Voice index"
    with sqlite3.connect(normal_home / "state_5.sqlite") as conn:
        thread_row = conn.execute(
            "SELECT rollout_path, title FROM threads WHERE id = ?",
            ("thread-voice",),
        ).fetchone()
        dynamic_tool_row = conn.execute(
            "SELECT name FROM thread_dynamic_tools WHERE thread_id = ?",
            ("thread-voice",),
        ).fetchone()
    assert thread_row == (str(target_rollout), "Voice title")
    assert dynamic_tool_row == ("voice_tool",)


def test_export_voice_codex_thread_skips_existing_thread(tmp_path: Path) -> None:
    normal_home = tmp_path / "normal"
    voice_home = tmp_path / "voice"
    _create_state_db(normal_home / "state_5.sqlite")
    _create_state_db(voice_home / "state_5.sqlite")
    _insert_thread(voice_home, "thread-1", title="Voice title", updated_at=20)
    _insert_thread(normal_home, "thread-1", title="Normal title", updated_at=30)

    results = export_voice_codex_threads(
        ["thread-1"],
        normal_home=normal_home,
        voice_home=voice_home,
    )

    assert results[0].transferred is False
    assert results[0].reason == "already_exported"


def test_sync_codex_threads_once_transfers_completed_normal_thread(
    tmp_path: Path,
) -> None:
    normal_home = tmp_path / "normal"
    voice_home = tmp_path / "voice"
    ledger = tmp_path / "ledger.json"
    _create_state_db(normal_home / "state_5.sqlite")
    _create_state_db(voice_home / "state_5.sqlite")
    source_rollout = _insert_thread(
        normal_home,
        "thread-1",
        title="Thread title",
        updated_at=20,
    )
    _append_terminal(source_rollout)

    results = sync_codex_threads_once(
        normal_home=normal_home,
        voice_home=voice_home,
        ledger_path=ledger,
        stability_delay_seconds=0,
        max_age_days=None,
    )

    assert [(result.thread_id, result.status) for result in results] == [
        ("thread-1", "transferred")
    ]
    target_rollout = voice_home / source_rollout.relative_to(normal_home)
    assert target_rollout.exists()
    with sqlite3.connect(voice_home / "state_5.sqlite") as conn:
        assert conn.execute(
            "SELECT title FROM threads WHERE id = ?", ("thread-1",)
        ).fetchone() == ("Thread title",)


def test_sync_codex_threads_once_transfers_terminal_rollout_with_open_handle(
    tmp_path: Path,
    monkeypatch,
) -> None:
    normal_home = tmp_path / "normal"
    voice_home = tmp_path / "voice"
    ledger = tmp_path / "ledger.json"
    _create_state_db(normal_home / "state_5.sqlite")
    _create_state_db(voice_home / "state_5.sqlite")
    source_rollout = _insert_thread(
        voice_home,
        "thread-1",
        title="Thread title",
        updated_at=1_779_641_351,
    )
    _append_terminal(source_rollout)
    monkeypatch.setattr(
        "openbase_coder_cli.mcp.thread_import._rollout_open_for_write",
        lambda path: path == source_rollout,
    )
    _append_index(
        voice_home,
        "thread-1",
        "Indexed title",
        "2026-05-21T10:00:00Z",
    )

    results = sync_codex_threads_once(
        normal_home=normal_home,
        voice_home=voice_home,
        ledger_path=ledger,
        stability_delay_seconds=0,
        max_age_days=None,
    )

    assert [
        (result.thread_id, result.status, result.direction) for result in results
    ] == [("thread-1", "transferred", "voice_to_normal")]
    target_rollout = normal_home / source_rollout.relative_to(voice_home)
    assert target_rollout.exists()
    index_lines = (
        (normal_home / "session_index.jsonl").read_text(encoding="utf-8").splitlines()
    )
    latest_index_entry = json.loads(index_lines[-1])
    assert latest_index_entry["thread_name"] == "Indexed title"
    assert latest_index_entry["updated_at"] == "2026-05-24T16:49:11Z"


def test_sync_codex_threads_once_skips_active_thread(tmp_path: Path) -> None:
    normal_home = tmp_path / "normal"
    voice_home = tmp_path / "voice"
    _create_state_db(normal_home / "state_5.sqlite")
    _create_state_db(voice_home / "state_5.sqlite")
    source_rollout = _insert_thread(
        normal_home,
        "thread-1",
        title="Thread title",
        updated_at=20,
    )
    _append_terminal(source_rollout)

    results = sync_codex_threads_once(
        normal_home=normal_home,
        voice_home=voice_home,
        ledger_path=tmp_path / "ledger.json",
        stability_delay_seconds=0,
        max_age_days=None,
        active_thread_ids={"thread-1"},
    )

    assert results[0].status == "skipped"
    assert results[0].reason == "skipped_active"
    with sqlite3.connect(voice_home / "state_5.sqlite") as conn:
        assert conn.execute("SELECT COUNT(*) FROM threads").fetchone() == (0,)


def test_sync_codex_threads_once_logs_conflict_and_continues(
    tmp_path: Path,
    caplog,
) -> None:
    normal_home = tmp_path / "normal"
    voice_home = tmp_path / "voice"
    ledger = tmp_path / "ledger.json"
    _create_state_db(normal_home / "state_5.sqlite")
    _create_state_db(voice_home / "state_5.sqlite")
    normal_conflict = _insert_thread(
        normal_home,
        "thread-conflict",
        title="Normal title",
        updated_at=20,
    )
    voice_conflict = _insert_thread(
        voice_home,
        "thread-conflict",
        title="Voice title",
        updated_at=30,
    )
    ok_rollout = _insert_thread(normal_home, "thread-ok", title="OK", updated_at=10)
    _append_terminal(normal_conflict, message="normal")
    _append_terminal(voice_conflict, message="voice")
    _append_terminal(ok_rollout, message="ok")
    caplog.set_level(logging.WARNING, logger="openbase_coder_cli.mcp.thread_import")

    results = sync_codex_threads_once(
        normal_home=normal_home,
        voice_home=voice_home,
        ledger_path=ledger,
        stability_delay_seconds=0,
        max_age_days=None,
    )

    assert {result.thread_id: result.status for result in results} == {
        "thread-conflict": "conflict",
        "thread-ok": "transferred",
    }
    assert "event=conflict" in caplog.text
    ledger_payload = json.loads(ledger.read_text(encoding="utf-8"))
    assert ledger_payload["threads"]["thread-conflict"]["status"] == "conflict"


def test_sync_codex_threads_once_marks_same_content_duplicate_synced(
    tmp_path: Path,
) -> None:
    normal_home = tmp_path / "normal"
    voice_home = tmp_path / "voice"
    _create_state_db(normal_home / "state_5.sqlite")
    _create_state_db(voice_home / "state_5.sqlite")
    normal_rollout = _insert_thread(
        normal_home, "thread-1", title="Normal", updated_at=20
    )
    voice_rollout = _insert_thread(voice_home, "thread-1", title="Voice", updated_at=20)
    _append_terminal(normal_rollout)
    _append_terminal(voice_rollout)

    results = sync_codex_threads_once(
        normal_home=normal_home,
        voice_home=voice_home,
        ledger_path=tmp_path / "ledger.json",
        stability_delay_seconds=0,
        max_age_days=None,
    )

    assert results[0].status == "already_synced"
    assert results[0].reason == "same_content"


def test_sync_codex_threads_once_skips_threads_older_than_max_age(
    tmp_path: Path,
) -> None:
    normal_home = tmp_path / "normal"
    voice_home = tmp_path / "voice"
    _create_state_db(normal_home / "state_5.sqlite")
    _create_state_db(voice_home / "state_5.sqlite")
    old_updated_at = int(time.time()) - (16 * 24 * 60 * 60)
    source_rollout = _insert_thread(
        normal_home,
        "thread-old",
        title="Old",
        updated_at=old_updated_at,
    )
    _append_terminal(source_rollout)

    results = sync_codex_threads_once(
        normal_home=normal_home,
        voice_home=voice_home,
        ledger_path=tmp_path / "ledger.json",
        stability_delay_seconds=0,
        max_age_days=15,
    )

    assert results[0].status == "skipped"
    assert results[0].reason == "skipped_old"
    with sqlite3.connect(voice_home / "state_5.sqlite") as conn:
        assert conn.execute("SELECT COUNT(*) FROM threads").fetchone() == (0,)


def test_sync_result_logging_suppresses_routine_results(caplog) -> None:
    caplog.set_level(logging.INFO, logger="openbase_coder_cli.mcp.thread_import")

    _log_sync_result(
        CodexThreadSyncResult("thread-old", "skipped", None, "skipped_old")
    )
    _log_sync_result(
        CodexThreadSyncResult("thread-synced", "already_synced", None, "same_content")
    )
    _log_sync_result(
        CodexThreadSyncResult("thread-non-terminal", "skipped", None, "non_terminal")
    )
    _log_sync_result(
        CodexThreadSyncResult("thread-active", "skipped", None, "skipped_active")
    )
    _log_sync_result(
        CodexThreadSyncResult(
            "thread-transferred",
            "transferred",
            "normal_to_voice",
            "synced_to_voice",
        )
    )
    _log_sync_result(
        CodexThreadSyncResult("thread-unexpected", "skipped", None, "rollout_malformed")
    )

    assert "thread-old" not in caplog.text
    assert "thread-synced" not in caplog.text
    assert "thread-non-terminal" not in caplog.text
    assert "thread-active" in caplog.text
    assert "thread-transferred" in caplog.text
    assert "thread-unexpected" in caplog.text


def test_mcp_module_registers_thread_import_toolset(monkeypatch) -> None:
    import django
    from django.apps import apps

    monkeypatch.setenv(
        "DJANGO_SETTINGS_MODULE",
        "openbase_coder_cli.config.settings",
    )
    if not apps.ready:
        django.setup()

    from mcp_server.djangomcp import global_mcp_server

    import openbase_coder_cli.mcp.mcp as mcp_module

    assert hasattr(mcp_module, "CodexThreadImportTools")
    tools = global_mcp_server._tool_manager._tools
    assert "list_normal_codex_threads" in tools
    assert "import_normal_codex_threads" in tools
    assert "list_voice_codex_threads" in tools
    assert "export_voice_codex_threads" in tools
    assert "get_dispatcher_reasoning_effort" in tools
    assert "set_dispatcher_reasoning_effort" in tools
    assert "get_super_agents_reasoning_effort" in tools
    assert "set_super_agents_reasoning_effort" in tools
    assert "get_super_agents_model" in tools
    assert "set_super_agents_model" in tools


def test_mcp_dispatcher_reasoning_tools_share_cli_config(
    monkeypatch, tmp_path: Path
) -> None:
    import django
    from django.apps import apps

    monkeypatch.setenv(
        "DJANGO_SETTINGS_MODULE",
        "openbase_coder_cli.config.settings",
    )
    if not apps.ready:
        django.setup()

    import openbase_coder_cli.dispatcher_config as dispatcher_config
    import openbase_coder_cli.mcp.mcp as mcp_module

    config_path = tmp_path / "dispatcher-config.json"
    monkeypatch.setattr(dispatcher_config, "CODEX_DISPATCHER_CONFIG_PATH", config_path)

    result = mcp_module.CodexThreadImportTools.set_dispatcher_reasoning_effort(
        None, "low"
    )

    assert result["reasoning_effort"] == "low"
    assert result["applies_to"] == "next dispatcher turn"
    assert (
        json.loads(config_path.read_text(encoding="utf-8"))[
            "dispatcher_reasoning_effort"
        ]
        == "low"
    )

    current = mcp_module.CodexThreadImportTools.get_dispatcher_reasoning_effort(None)

    assert current["reasoning_effort"] == "low"
    assert current["effective"] == "low"


def test_mcp_super_agents_reasoning_tools_share_cli_config(
    monkeypatch, tmp_path: Path
) -> None:
    import django
    from django.apps import apps

    monkeypatch.setenv(
        "DJANGO_SETTINGS_MODULE",
        "openbase_coder_cli.config.settings",
    )
    if not apps.ready:
        django.setup()

    import openbase_coder_cli.dispatcher_config as dispatcher_config
    import openbase_coder_cli.mcp.mcp as mcp_module

    config_path = tmp_path / "dispatcher-config.json"
    monkeypatch.setattr(dispatcher_config, "CODEX_DISPATCHER_CONFIG_PATH", config_path)

    result = mcp_module.CodexThreadImportTools.set_super_agents_reasoning_effort(
        None, "xhigh"
    )

    assert result["reasoning_effort"] == "xhigh"
    assert result["applies_to"] == "next Super Agents turn"
    assert (
        json.loads(config_path.read_text(encoding="utf-8"))[
            "super_agents_reasoning_effort"
        ]
        == "xhigh"
    )

    current = mcp_module.CodexThreadImportTools.get_super_agents_reasoning_effort(None)

    assert current["reasoning_effort"] == "xhigh"
    assert current["effective"] == "xhigh"


def test_mcp_super_agents_model_tools_share_cli_config(
    monkeypatch, tmp_path: Path
) -> None:
    import django
    from django.apps import apps

    monkeypatch.setenv(
        "DJANGO_SETTINGS_MODULE",
        "openbase_coder_cli.config.settings",
    )
    if not apps.ready:
        django.setup()

    import openbase_coder_cli.dispatcher_config as dispatcher_config
    import openbase_coder_cli.mcp.mcp as mcp_module

    config_path = tmp_path / "dispatcher-config.json"
    monkeypatch.setattr(dispatcher_config, "CODEX_DISPATCHER_CONFIG_PATH", config_path)

    result = mcp_module.CodexThreadImportTools.set_super_agents_model(None, "opus")

    assert result["model"] == "opus"
    assert result["applies_to"] == "next Super Agents turn"
    assert (
        json.loads(config_path.read_text(encoding="utf-8"))["super_agents_model"]
        == "opus"
    )

    current = mcp_module.CodexThreadImportTools.get_super_agents_model(None)

    assert current["model"] == "opus"
    assert current["effective"] == "opus"
