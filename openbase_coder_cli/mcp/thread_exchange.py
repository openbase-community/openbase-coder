"""Cross-device Codex thread snapshot exchange."""

from __future__ import annotations

import json
import logging
import os
import platform
import shutil
import sqlite3
import tempfile
import time
import uuid
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openbase_coder_cli.paths import CODEX_HOME_DIR, OPENBASE_BASE_DIR

from .thread_import import (
    DEFAULT_SYNC_MAX_AGE_DAYS,
    SESSION_INDEX_NAME,
    STATE_DB_NAME,
    ThreadTransferError,
    _active_super_agent_thread_ids,
    _connect,
    _fingerprint_from_rollout_path,
    _has_table,
    _latest_session_index_entries,
    _row_updated_ms,
    _source_rollout_path,
    _string,
    _sync_cutoff_ms,
    _table_columns,
    _target_row_safe_for_overwrite,
    _thread_fingerprint,
    _thread_rows,
    _thread_safe_for_sync,
)

SCHEMA_VERSION = 1
DEVICE_IDENTITY_NAME = "thread-sync-device.json"
LEDGER_NAME = "codex-thread-device-sync-ledger.json"
DEFAULT_EXCHANGE_DIR = OPENBASE_BASE_DIR / "thread-sync"
DEFAULT_DEVICE_IDENTITY_PATH = OPENBASE_BASE_DIR / DEVICE_IDENTITY_NAME
DEFAULT_LEDGER_PATH = OPENBASE_BASE_DIR / LEDGER_NAME

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeviceIdentity:
    device_id: str
    device_name: str
    created_at: float

    def to_json(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "device_name": self.device_name,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class ThreadSnapshotResult:
    thread_id: str
    status: str
    reason: str
    snapshot_path: str | None = None
    fingerprint: str | None = None
    source_device_id: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "thread_id": self.thread_id,
            "status": self.status,
            "reason": self.reason,
            "snapshot_path": self.snapshot_path,
            "fingerprint": self.fingerprint,
            "source_device_id": self.source_device_id,
        }


def get_or_create_device_identity(
    path: Path = DEFAULT_DEVICE_IDENTITY_PATH,
) -> DeviceIdentity:
    existing = read_device_identity(path)
    if existing is not None:
        return existing
    identity = DeviceIdentity(
        device_id=str(uuid.uuid4()),
        device_name=platform.node() or "unknown-device",
        created_at=time.time(),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_json_atomic(path, identity.to_json())
    return identity


def read_device_identity(path: Path = DEFAULT_DEVICE_IDENTITY_PATH) -> DeviceIdentity | None:
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, dict):
        return None
    device_id = _string(raw.get("device_id"))
    if not device_id:
        return None
    return DeviceIdentity(
        device_id=device_id,
        device_name=_string(raw.get("device_name")) or "unknown-device",
        created_at=float(raw.get("created_at") or 0),
    )


def sync_thread_snapshots_once(
    *,
    codex_home: Path = CODEX_HOME_DIR,
    exchange_dir: Path = DEFAULT_EXCHANGE_DIR,
    device_identity_path: Path = DEFAULT_DEVICE_IDENTITY_PATH,
    ledger_path: Path = DEFAULT_LEDGER_PATH,
    stability_delay_seconds: float = 0.2,
    max_age_days: int | None = DEFAULT_SYNC_MAX_AGE_DAYS,
) -> dict[str, list[ThreadSnapshotResult]]:
    exports = export_thread_snapshots(
        codex_home=codex_home,
        exchange_dir=exchange_dir,
        device_identity_path=device_identity_path,
        ledger_path=ledger_path,
        stability_delay_seconds=stability_delay_seconds,
        max_age_days=max_age_days,
    )
    imports = import_thread_snapshots(
        codex_home=codex_home,
        exchange_dir=exchange_dir,
        device_identity_path=device_identity_path,
        ledger_path=ledger_path,
    )
    return {"exports": exports, "imports": imports}


def export_thread_snapshots(
    *,
    codex_home: Path = CODEX_HOME_DIR,
    exchange_dir: Path = DEFAULT_EXCHANGE_DIR,
    device_identity_path: Path = DEFAULT_DEVICE_IDENTITY_PATH,
    ledger_path: Path = DEFAULT_LEDGER_PATH,
    stability_delay_seconds: float = 0.2,
    max_age_days: int | None = DEFAULT_SYNC_MAX_AGE_DAYS,
    active_thread_ids: set[str] | None = None,
) -> list[ThreadSnapshotResult]:
    state_db = codex_home / STATE_DB_NAME
    if not state_db.exists():
        raise ThreadTransferError(f"Codex state database not found: {state_db}")

    identity = get_or_create_device_identity(device_identity_path)
    active_ids = set(active_thread_ids or set()) | _active_super_agent_thread_ids()
    ledger = _read_exchange_ledger(ledger_path)
    cutoff_ms = _sync_cutoff_ms(max_age_days)
    index_entries = _latest_session_index_entries(codex_home / SESSION_INDEX_NAME)

    results: list[ThreadSnapshotResult] = []
    for row in _thread_rows(state_db):
        thread_id = _string(row.get("id"))
        if not thread_id:
            continue
        if cutoff_ms is not None and _row_updated_ms(row) < cutoff_ms:
            results.append(ThreadSnapshotResult(thread_id, "skipped", "skipped_old"))
            continue
        if thread_id in active_ids:
            results.append(ThreadSnapshotResult(thread_id, "skipped", "skipped_active"))
            continue

        safety = _thread_safe_for_sync(
            row,
            codex_home,
            thread_id,
            stability_delay_seconds=stability_delay_seconds,
        )
        if not safety.safe:
            results.append(ThreadSnapshotResult(thread_id, "skipped", safety.reason))
            continue

        rollout = _source_rollout_path(row, codex_home, thread_id)
        fingerprint = _fingerprint_from_rollout_path(rollout, row)
        if rollout is None or fingerprint is None:
            results.append(ThreadSnapshotResult(thread_id, "skipped", "rollout_not_found"))
            continue
        fingerprint_id = _fingerprint_id(fingerprint)
        thread_ledger = _ledger_thread(ledger, thread_id)
        if fingerprint_id in _device_exported_fingerprints(thread_ledger, identity.device_id):
            thread_ledger["local_fingerprint"] = fingerprint_id
            results.append(
                ThreadSnapshotResult(
                    thread_id,
                    "already_exported",
                    "fingerprint_current",
                    fingerprint=fingerprint_id,
                )
            )
            continue

        parent_fingerprint = _parent_fingerprint_for_export(thread_ledger, fingerprint_id)
        snapshot_path = _write_snapshot(
            exchange_dir=exchange_dir,
            identity=identity,
            codex_home=codex_home,
            row=row,
            rollout=rollout,
            fingerprint=fingerprint,
            fingerprint_id=fingerprint_id,
            parent_fingerprint=parent_fingerprint,
            index_entry=index_entries.get(thread_id),
            dynamic_tools=_thread_dynamic_tools(state_db, thread_id),
        )
        _record_device_snapshot(
            thread_ledger,
            device_id=identity.device_id,
            fingerprint_id=fingerprint_id,
            snapshot_path=snapshot_path,
            status="exported",
        )
        thread_ledger["local_fingerprint"] = fingerprint_id
        results.append(
            ThreadSnapshotResult(
                thread_id,
                "exported",
                "snapshot_written",
                str(snapshot_path),
                fingerprint_id,
                identity.device_id,
            )
        )

    _write_exchange_ledger(ledger_path, ledger)
    return results


def import_thread_snapshots(
    *,
    codex_home: Path = CODEX_HOME_DIR,
    exchange_dir: Path = DEFAULT_EXCHANGE_DIR,
    device_identity_path: Path = DEFAULT_DEVICE_IDENTITY_PATH,
    ledger_path: Path = DEFAULT_LEDGER_PATH,
) -> list[ThreadSnapshotResult]:
    state_db = codex_home / STATE_DB_NAME
    if not state_db.exists():
        raise ThreadTransferError(f"Codex state database not found: {state_db}")

    identity = get_or_create_device_identity(device_identity_path)
    ledger = _read_exchange_ledger(ledger_path)
    results: list[ThreadSnapshotResult] = []
    for snapshot_dir in _snapshot_dirs(exchange_dir):
        metadata_path = snapshot_dir / "metadata.json"
        try:
            metadata = _read_snapshot_metadata(metadata_path)
        except ThreadTransferError as exc:
            results.append(
                ThreadSnapshotResult(
                    thread_id=snapshot_dir.parent.name,
                    status="skipped",
                    reason=str(exc),
                    snapshot_path=str(snapshot_dir),
                )
            )
            continue

        thread_id = metadata["thread_id"]
        source_device_id = metadata["source_device_id"]
        fingerprint_id = metadata["fingerprint"]
        if source_device_id == identity.device_id:
            results.append(
                ThreadSnapshotResult(
                    thread_id,
                    "skipped",
                    "same_device",
                    str(snapshot_dir),
                    fingerprint_id,
                    source_device_id,
                )
            )
            continue

        thread_ledger = _ledger_thread(ledger, thread_id)
        if _snapshot_already_imported(thread_ledger, source_device_id, fingerprint_id):
            results.append(
                ThreadSnapshotResult(
                    thread_id,
                    "already_imported",
                    "fingerprint_seen",
                    str(snapshot_dir),
                    fingerprint_id,
                    source_device_id,
                )
            )
            continue
        if thread_ledger.get("conflict"):
            _record_device_snapshot(
                thread_ledger,
                device_id=source_device_id,
                fingerprint_id=fingerprint_id,
                snapshot_path=snapshot_dir,
                status="seen_after_conflict",
            )
            results.append(
                ThreadSnapshotResult(
                    thread_id,
                    "conflict",
                    "conflict_unresolved",
                    str(snapshot_dir),
                    fingerprint_id,
                    source_device_id,
                )
            )
            continue

        validation_error = _validate_snapshot(snapshot_dir, metadata)
        if validation_error:
            results.append(
                ThreadSnapshotResult(
                    thread_id,
                    "skipped",
                    validation_error,
                    str(snapshot_dir),
                    fingerprint_id,
                    source_device_id,
                )
            )
            continue

        local_row = _exchange_thread_row(state_db, thread_id)
        local_fingerprint = (
            _fingerprint_id(_thread_fingerprint(local_row, codex_home, thread_id))
            if local_row is not None
            else None
        )
        parent_fingerprint = _string(metadata.get("parent_fingerprint"))
        decision = _import_decision(
            local_row=local_row,
            local_fingerprint=local_fingerprint,
            incoming_fingerprint=fingerprint_id,
            parent_fingerprint=parent_fingerprint,
            thread_ledger=thread_ledger,
        )
        if decision == "same_content":
            _record_device_snapshot(
                thread_ledger,
                device_id=source_device_id,
                fingerprint_id=fingerprint_id,
                snapshot_path=snapshot_dir,
                status="same_content",
            )
            results.append(
                ThreadSnapshotResult(
                    thread_id,
                    "already_imported",
                    "same_content",
                    str(snapshot_dir),
                    fingerprint_id,
                    source_device_id,
                )
            )
            continue
        if decision == "conflict":
            _record_conflict(
                thread_ledger,
                local_fingerprint=local_fingerprint,
                incoming_fingerprint=fingerprint_id,
                source_device_id=source_device_id,
                reason="divergent_fingerprint",
            )
            results.append(
                ThreadSnapshotResult(
                    thread_id,
                    "conflict",
                    "divergent_fingerprint",
                    str(snapshot_dir),
                    fingerprint_id,
                    source_device_id,
                )
            )
            continue
        if local_row is not None and not _target_row_safe_for_overwrite(
            local_row,
            codex_home,
            thread_id,
        ):
            results.append(
                ThreadSnapshotResult(
                    thread_id,
                    "skipped",
                    "target_active",
                    str(snapshot_dir),
                    fingerprint_id,
                    source_device_id,
                )
            )
            continue

        _import_snapshot_into_home(
            snapshot_dir=snapshot_dir,
            metadata=metadata,
            codex_home=codex_home,
            overwrite=local_row is not None,
        )
        _record_device_snapshot(
            thread_ledger,
            device_id=source_device_id,
            fingerprint_id=fingerprint_id,
            snapshot_path=snapshot_dir,
            status="imported",
        )
        thread_ledger["local_fingerprint"] = fingerprint_id
        results.append(
            ThreadSnapshotResult(
                thread_id,
                "imported",
                "snapshot_imported",
                str(snapshot_dir),
                fingerprint_id,
                source_device_id,
            )
        )

    _write_exchange_ledger(ledger_path, ledger)
    return results


def thread_snapshot_status(
    *,
    exchange_dir: Path = DEFAULT_EXCHANGE_DIR,
    device_identity_path: Path = DEFAULT_DEVICE_IDENTITY_PATH,
    ledger_path: Path = DEFAULT_LEDGER_PATH,
) -> dict[str, Any]:
    identity = read_device_identity(device_identity_path)
    ledger = _read_exchange_ledger(ledger_path)
    conflicts = [
        {"thread_id": thread_id, **value["conflict"]}
        for thread_id, value in ledger.get("threads", {}).items()
        if isinstance(value, dict) and isinstance(value.get("conflict"), dict)
    ]
    snapshots = list(_snapshot_dirs(exchange_dir))
    return {
        "device": identity.to_json() if identity else None,
        "exchange_dir": str(exchange_dir),
        "ledger_path": str(ledger_path),
        "snapshot_count": len(snapshots),
        "thread_count": len(ledger.get("threads", {})),
        "conflict_count": len(conflicts),
        "conflicts": conflicts,
    }


def _write_snapshot(
    *,
    exchange_dir: Path,
    identity: DeviceIdentity,
    codex_home: Path,
    row: dict[str, Any],
    rollout: Path,
    fingerprint: dict[str, Any],
    fingerprint_id: str,
    parent_fingerprint: str | None,
    index_entry: dict[str, Any] | None,
    dynamic_tools: list[dict[str, Any]],
) -> Path:
    thread_id = _string(row.get("id"))
    if not thread_id:
        raise ThreadTransferError("thread row missing id")
    target_dir = (
        exchange_dir
        / "devices"
        / identity.device_id
        / "snapshots"
        / thread_id
        / fingerprint_id
    )
    if target_dir.exists():
        return target_dir
    tmp_dir = target_dir.parent / f".tmp-{fingerprint_id}-{uuid.uuid4()}"
    tmp_dir.mkdir(parents=True, exist_ok=False)
    try:
        shutil.copy2(rollout, tmp_dir / "rollout.jsonl")
        metadata = _snapshot_metadata(
            identity=identity,
            codex_home=codex_home,
            row=row,
            rollout=rollout,
            fingerprint=fingerprint,
            fingerprint_id=fingerprint_id,
            parent_fingerprint=parent_fingerprint,
            index_entry=index_entry,
            dynamic_tools=dynamic_tools,
        )
        (tmp_dir / "metadata.json").write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp_dir, target_dir)
    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise
    return target_dir


def _snapshot_metadata(
    *,
    identity: DeviceIdentity,
    codex_home: Path,
    row: dict[str, Any],
    rollout: Path,
    fingerprint: dict[str, Any],
    fingerprint_id: str,
    parent_fingerprint: str | None,
    index_entry: dict[str, Any] | None,
    dynamic_tools: list[dict[str, Any]],
) -> dict[str, Any]:
    thread_row = dict(row)
    thread_row.pop("rollout_path", None)
    try:
        rollout_relative_path = str(rollout.relative_to(codex_home))
    except ValueError:
        rollout_relative_path = str(Path("sessions") / rollout.name)
    return {
        "schema_version": SCHEMA_VERSION,
        "source_device_id": identity.device_id,
        "source_device_name": identity.device_name,
        "thread_id": row["id"],
        "fingerprint": fingerprint_id,
        "parent_fingerprint": parent_fingerprint,
        "exported_at": time.time(),
        "rollout_relative_path": rollout_relative_path,
        "rollout_sha256": fingerprint["rollout_sha256"],
        "rollout_size": fingerprint["rollout_size"],
        "thread_row": thread_row,
        "session_index_entry": index_entry,
        "dynamic_tools": dynamic_tools,
    }


def _read_snapshot_metadata(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ThreadTransferError("metadata_not_found")
    try:
        metadata = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ThreadTransferError("metadata_malformed") from exc
    if not isinstance(metadata, dict):
        raise ThreadTransferError("metadata_malformed")
    if metadata.get("schema_version") != SCHEMA_VERSION:
        raise ThreadTransferError("unsupported_schema")
    for key in ("source_device_id", "thread_id", "fingerprint", "rollout_sha256"):
        if not _string(metadata.get(key)):
            raise ThreadTransferError(f"metadata_missing_{key}")
    return metadata


def _validate_snapshot(snapshot_dir: Path, metadata: dict[str, Any]) -> str | None:
    rollout = snapshot_dir / "rollout.jsonl"
    fingerprint = _fingerprint_from_rollout_path(rollout, None)
    if fingerprint is None:
        return "rollout_not_found"
    if fingerprint["rollout_sha256"] != metadata.get("rollout_sha256"):
        return "rollout_hash_mismatch"
    if fingerprint["rollout_size"] != metadata.get("rollout_size"):
        return "rollout_size_mismatch"
    return None


def _import_snapshot_into_home(
    *,
    snapshot_dir: Path,
    metadata: dict[str, Any],
    codex_home: Path,
    overwrite: bool,
) -> None:
    thread_id = metadata["thread_id"]
    relative_path = Path(_string(metadata.get("rollout_relative_path")) or "sessions")
    if relative_path.is_absolute() or ".." in relative_path.parts:
        relative_path = Path("sessions") / f"rollout-{thread_id}.jsonl"
    target_rollout = codex_home / relative_path
    target_rollout.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(snapshot_dir / "rollout.jsonl", target_rollout)

    state_db = codex_home / STATE_DB_NAME
    _upsert_thread_row(
        state_db,
        thread_id,
        metadata.get("thread_row") if isinstance(metadata.get("thread_row"), dict) else {},
        target_rollout,
        overwrite=overwrite,
    )
    _replace_thread_dynamic_tools(
        state_db,
        thread_id,
        metadata.get("dynamic_tools") if isinstance(metadata.get("dynamic_tools"), list) else [],
    )
    thread_row = metadata.get("thread_row")
    thread_row = thread_row if isinstance(thread_row, dict) else {}
    _append_session_index_metadata(
        codex_home / SESSION_INDEX_NAME,
        metadata.get("session_index_entry"),
        thread_id=thread_id,
        fallback_title=_string(thread_row.get("title")) or thread_id,
    )


def _upsert_thread_row(
    db_path: Path,
    thread_id: str,
    row: dict[str, Any],
    rollout_path: Path,
    *,
    overwrite: bool,
) -> None:
    with closing(_connect(db_path)) as conn:
        target_columns = _table_columns(conn, "threads")
        values = {key: value for key, value in row.items() if key in target_columns}
        values["id"] = thread_id
        values["rollout_path"] = str(rollout_path)
        columns = [column for column in target_columns if column in values]
        placeholders = ", ".join("?" for _ in columns)
        column_sql = ", ".join(columns)
        verb = "INSERT OR REPLACE" if overwrite else "INSERT OR IGNORE"
        conn.execute(
            f"{verb} INTO threads ({column_sql}) VALUES ({placeholders})",
            [values[column] for column in columns],
        )
        conn.commit()


def _replace_thread_dynamic_tools(
    db_path: Path,
    thread_id: str,
    rows: list[Any],
) -> None:
    with closing(_connect(db_path)) as conn:
        if not _has_table(conn, "thread_dynamic_tools"):
            return
        columns = _table_columns(conn, "thread_dynamic_tools")
        conn.execute("DELETE FROM thread_dynamic_tools WHERE thread_id = ?", (thread_id,))
        for raw_row in rows:
            if not isinstance(raw_row, dict):
                continue
            values = {key: value for key, value in raw_row.items() if key in columns}
            values["thread_id"] = thread_id
            insert_columns = [column for column in columns if column in values]
            placeholders = ", ".join("?" for _ in insert_columns)
            column_sql = ", ".join(insert_columns)
            conn.execute(
                f"INSERT OR REPLACE INTO thread_dynamic_tools ({column_sql}) VALUES ({placeholders})",
                [values[column] for column in insert_columns],
            )
        conn.commit()


def _append_session_index_metadata(
    path: Path,
    entry: Any,
    *,
    thread_id: str,
    fallback_title: str,
) -> None:
    index_entry = dict(entry) if isinstance(entry, dict) else {}
    index_entry["id"] = thread_id
    index_entry.setdefault("thread_name", fallback_title)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(index_entry, separators=(",", ":")) + "\n")


def _thread_dynamic_tools(db_path: Path, thread_id: str) -> list[dict[str, Any]]:
    with closing(_connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        if not _has_table(conn, "thread_dynamic_tools"):
            return []
        columns = _table_columns(conn, "thread_dynamic_tools")
        rows = conn.execute(
            f"SELECT {', '.join(columns)} FROM thread_dynamic_tools WHERE thread_id = ? ORDER BY position",
            (thread_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def _exchange_thread_row(db_path: Path, thread_id: str) -> dict[str, Any] | None:
    if not db_path.exists():
        return None
    with closing(_connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM threads WHERE id = ?",
            (thread_id,),
        ).fetchone()
        return dict(row) if row is not None else None


def _snapshot_dirs(exchange_dir: Path) -> list[Path]:
    root = exchange_dir / "devices"
    if not root.exists():
        return []
    return sorted(
        path
        for path in root.glob("*/snapshots/*/*")
        if path.is_dir() and (path / "metadata.json").exists()
    )


def _import_decision(
    *,
    local_row: dict[str, Any] | None,
    local_fingerprint: str | None,
    incoming_fingerprint: str,
    parent_fingerprint: str | None,
    thread_ledger: dict[str, Any],
) -> str:
    if local_fingerprint == incoming_fingerprint:
        return "same_content"
    if local_row is None:
        return "import"
    if parent_fingerprint and local_fingerprint == parent_fingerprint:
        return "import"
    if thread_ledger.get("local_fingerprint") == parent_fingerprint and parent_fingerprint:
        return "import"
    return "conflict"


def _parent_fingerprint_for_export(
    thread_ledger: dict[str, Any],
    fingerprint_id: str,
) -> str | None:
    parent = _string(thread_ledger.get("local_fingerprint"))
    return parent if parent and parent != fingerprint_id else None


def _fingerprint_id(fingerprint: dict[str, Any] | None) -> str | None:
    if not fingerprint:
        return None
    return _string(fingerprint.get("rollout_sha256"))


def _read_exchange_ledger(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"threads": {}}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("codex_thread_exchange event=ledger_malformed path=%s", path)
        return {"threads": {}}
    if not isinstance(raw, dict):
        return {"threads": {}}
    if not isinstance(raw.get("threads"), dict):
        raw["threads"] = {}
    return raw


def _write_exchange_ledger(path: Path, ledger: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_json_atomic(path, ledger)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
        tmp.write(body)
        tmp_name = tmp.name
    os.replace(tmp_name, path)


def _ledger_thread(ledger: dict[str, Any], thread_id: str) -> dict[str, Any]:
    threads = ledger.setdefault("threads", {})
    thread = threads.setdefault(thread_id, {})
    thread.setdefault("devices", {})
    return thread


def _device_exported_fingerprints(thread_ledger: dict[str, Any], device_id: str) -> set[str]:
    device = thread_ledger.get("devices", {}).get(device_id)
    snapshots = device.get("snapshots") if isinstance(device, dict) else None
    if not isinstance(snapshots, dict):
        return set()
    return {
        fingerprint
        for fingerprint, value in snapshots.items()
        if isinstance(fingerprint, str)
        and isinstance(value, dict)
        and value.get("status") == "exported"
    }


def _snapshot_already_imported(
    thread_ledger: dict[str, Any],
    device_id: str,
    fingerprint_id: str,
) -> bool:
    device = thread_ledger.get("devices", {}).get(device_id)
    snapshots = device.get("snapshots") if isinstance(device, dict) else None
    snapshot = snapshots.get(fingerprint_id) if isinstance(snapshots, dict) else None
    return isinstance(snapshot, dict) and snapshot.get("status") in {
        "imported",
        "same_content",
    }


def _record_device_snapshot(
    thread_ledger: dict[str, Any],
    *,
    device_id: str,
    fingerprint_id: str,
    snapshot_path: Path,
    status: str,
) -> None:
    devices = thread_ledger.setdefault("devices", {})
    device = devices.setdefault(device_id, {})
    snapshots = device.setdefault("snapshots", {})
    snapshots[fingerprint_id] = {
        "fingerprint": fingerprint_id,
        "snapshot_path": str(snapshot_path),
        "status": status,
        "seen_at": time.time(),
    }


def _record_conflict(
    thread_ledger: dict[str, Any],
    *,
    local_fingerprint: str | None,
    incoming_fingerprint: str,
    source_device_id: str,
    reason: str,
) -> None:
    thread_ledger["conflict"] = {
        "reason": reason,
        "local_fingerprint": local_fingerprint,
        "incoming_fingerprint": incoming_fingerprint,
        "source_device_id": source_device_id,
        "detected_at": time.time(),
    }
