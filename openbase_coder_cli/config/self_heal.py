"""Self-heal the dev API server from poisoned module state by exiting.

The workspace (dev) runtime serves Django via uvicorn without autoreload.
When source files change under the running process, a lazily imported module
— most often the root urlconf pulling a new name from an already-imported
module — fails to import against the stale modules in memory, and every
request 500s until the process restarts. launchd/systemd keep the service
alive, so exiting once the failure repeats is the recovery: the fresh
process imports the now-consistent files.

Standalone (production) installs never drift this way, so the wrapper is a
pass-through there; an ImportError in production means a broken install
where a restart loop would only add noise.
"""

import logging
import os
import threading
import time

from openbase_coder_cli.runtime import is_standalone_runtime

logger = logging.getLogger(__name__)

IMPORT_FAILURE_THRESHOLD = 2
IMPORT_FAILURE_WINDOW_SECONDS = 60.0
_EXIT_DELAY_SECONDS = 2.0


def _chain_contains_import_error(exc: BaseException) -> bool:
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        if isinstance(current, ImportError):
            return True
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return False


class ImportFailureSelfHeal:
    def __init__(self) -> None:
        self._failure_times: list[float] = []
        self._lock = threading.Lock()
        self._exiting = False

    def record_exception(self, exc: BaseException) -> None:
        if not _chain_contains_import_error(exc):
            return
        now = time.monotonic()
        with self._lock:
            cutoff = now - IMPORT_FAILURE_WINDOW_SECONDS
            self._failure_times = [
                failed_at for failed_at in self._failure_times if failed_at >= cutoff
            ]
            self._failure_times.append(now)
            if len(self._failure_times) < IMPORT_FAILURE_THRESHOLD:
                return
            if self._exiting:
                return
            self._exiting = True
        logger.critical(
            "Request handling raised ImportError %d times within %.0fs — "
            "module state is likely poisoned by source changes under the "
            "running dev server; exiting so the service manager restarts "
            "against the current files (error: %s)",
            IMPORT_FAILURE_THRESHOLD,
            IMPORT_FAILURE_WINDOW_SECONDS,
            exc,
        )
        self._initiate_exit()

    def _initiate_exit(self) -> None:
        threading.Thread(
            target=_exit_after_delay,
            name="openbase-self-heal-exit",
            daemon=True,
        ).start()


def _exit_after_delay() -> None:
    time.sleep(_EXIT_DELAY_SECONDS)
    os._exit(1)


def wrap_asgi_application(app):
    if is_standalone_runtime():
        return app

    self_heal = ImportFailureSelfHeal()

    async def application(scope, receive, send):
        try:
            await app(scope, receive, send)
        except BaseException as exc:
            self_heal.record_exception(exc)
            raise

    return application
