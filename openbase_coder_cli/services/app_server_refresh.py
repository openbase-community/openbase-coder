"""Refresh the Codex app-server after external state-DB writes.

The app-server serves thread listings and name search from an in-memory
index built at startup. Thread sync imports and conflict resolutions write
``state_5.sqlite`` behind its back, so synced threads keep a stale ranking
(and can be missing from name search) until the process restarts.

Writers request a refresh by touching a marker file; the thread sync sweeps
perform the restart once the machine is provably idle — no live voice room,
and no recent or in-flight rollout writes — retrying every sweep until an
idle window appears.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path

from openbase_coder_cli.backend_config import (
    CODEX_BACKEND,
    OPENBASE_CLOUD_BACKEND,
)
from openbase_coder_cli.env_file import selected_backend_from_env_file
from openbase_coder_cli.paths import (
    CODEX_HOME_DIR,
    DEFAULT_ENV_FILE_PATH,
    OPENBASE_BASE_DIR,
)

logger = logging.getLogger(__name__)

REFRESH_MARKER_PATH = OPENBASE_BASE_DIR / "codex-app-server-refresh-pending"
APP_SERVER_SERVICE_NAME = "codex-app-server"
# A turn streams rollout events continuously, so a quiet window this long
# means no turn is running.
IDLE_ROLLOUT_WINDOW_SECONDS = 300.0
# lsof insurance for the freshest rollouts in case a turn goes quiet longer
# than the mtime window.
OPEN_WRITE_CHECK_LIMIT = 5


def request_codex_app_server_refresh(reason: str) -> None:
    """Mark the app-server index as stale; a sync sweep restarts it when idle."""
    try:
        REFRESH_MARKER_PATH.parent.mkdir(parents=True, exist_ok=True)
        REFRESH_MARKER_PATH.write_text(f"{reason}\n", encoding="utf-8")
    except OSError:
        logger.warning(
            "codex_app_server_refresh event=marker_write_failed", exc_info=True
        )
        return
    logger.info("codex_app_server_refresh event=requested reason=%s", reason)


def run_pending_codex_app_server_refresh(
    *,
    codex_home: Path = CODEX_HOME_DIR,
    env_path: Path = DEFAULT_ENV_FILE_PATH,
    marker_path: Path = REFRESH_MARKER_PATH,
    now: float | None = None,
) -> str:
    """Restart the app-server if a refresh is pending and the machine is idle.

    Returns an outcome string for sweep logging: ``not_pending``,
    ``backend_not_codex``, ``deferred_voice_active``,
    ``deferred_threads_active``, ``refreshed``, or ``restart_failed``.
    """
    if not marker_path.exists():
        return "not_pending"

    backend = selected_backend_from_env_file(env_path)
    if backend not in (CODEX_BACKEND, OPENBASE_CLOUD_BACKEND):
        _clear_marker(marker_path)
        return "backend_not_codex"

    current = now if now is not None else time.time()
    if _recent_rollout_activity(codex_home, current):
        return "deferred_threads_active"
    if _voice_room_active():
        return "deferred_voice_active"

    if not _restart_app_server():
        logger.warning("codex_app_server_refresh event=restart_failed")
        return "restart_failed"
    _clear_marker(marker_path)
    logger.info("codex_app_server_refresh event=refreshed")
    return "refreshed"


def _clear_marker(marker_path: Path) -> None:
    marker_path.unlink(missing_ok=True)


def _recent_rollout_activity(codex_home: Path, now: float) -> bool:
    sessions_dir = codex_home / "sessions"
    if not sessions_dir.is_dir():
        return False
    freshest: list[tuple[float, Path]] = []
    for root, _dirs, files in os.walk(sessions_dir):
        for name in files:
            if not name.endswith(".jsonl"):
                continue
            path = Path(root) / name
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if now - mtime <= IDLE_ROLLOUT_WINDOW_SECONDS:
                return True
            freshest.append((mtime, path))
    freshest.sort(reverse=True)
    from openbase_coder_cli.mcp.thread_import import _rollout_open_for_write

    return any(
        _rollout_open_for_write(path)
        for _mtime, path in freshest[:OPEN_WRITE_CHECK_LIMIT]
    )


def _voice_room_active() -> bool:
    """Whether a live voice call is in progress; unknown counts as inactive.

    Rollout-idleness is still required either way, so a failed LiveKit
    lookup (missing credentials, server down) cannot cause a restart during
    an active turn.
    """
    try:
        from openbase_coder_cli.livekit_announcer import active_voice_room_exists

        return asyncio.run(active_voice_room_exists())
    except Exception:
        return False


def _restart_app_server() -> bool:
    from openbase_coder_cli.services.launchd import launchctl_kickstart
    from openbase_coder_cli.services.registry import find_service

    return launchctl_kickstart(find_service(APP_SERVER_SERVICE_NAME))


__all__ = [
    "APP_SERVER_SERVICE_NAME",
    "REFRESH_MARKER_PATH",
    "request_codex_app_server_refresh",
    "run_pending_codex_app_server_refresh",
]
