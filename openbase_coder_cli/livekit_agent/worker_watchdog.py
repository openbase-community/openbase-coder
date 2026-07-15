"""Exit the agent when its job workers repeatedly fail to initialize.

A worker subprocess that cannot initialize (for example after the virtualenv
was rebuilt for a different Python while the service kept running) leaves the
agent registered with LiveKit while every dispatched job dies — calls connect
and then silently never get an agent. launchd/systemd keep the service alive,
so exiting is the recovery: the restarted parent boots against the current
environment.
"""

import logging
import os
import signal
import threading
import time

logger = logging.getLogger(__name__)

WORKER_INIT_FAILURE_THRESHOLD = 3
WORKER_INIT_FAILURE_WINDOW_SECONDS = 120.0
_FORCED_EXIT_GRACE_SECONDS = 15.0
_INIT_FAILURE_MESSAGE = "error initializing process"


class WorkerInitFailureWatchdog(logging.Handler):
    """Log handler that exits the service on repeated worker-init failures."""

    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self._failure_times: list[float] = []
        self._lock = threading.Lock()
        self._exiting = False

    def emit(self, record: logging.LogRecord) -> None:
        if _INIT_FAILURE_MESSAGE not in str(record.getMessage()):
            return
        now = time.monotonic()
        with self._lock:
            cutoff = now - WORKER_INIT_FAILURE_WINDOW_SECONDS
            self._failure_times = [
                failed_at for failed_at in self._failure_times if failed_at >= cutoff
            ]
            self._failure_times.append(now)
            if len(self._failure_times) < WORKER_INIT_FAILURE_THRESHOLD:
                return
            if self._exiting:
                return
            self._exiting = True
        logger.critical(
            "livekit-agent job workers failed to initialize %d times within "
            "%.0fs; exiting so the service manager restarts the agent under "
            "the current environment",
            WORKER_INIT_FAILURE_THRESHOLD,
            WORKER_INIT_FAILURE_WINDOW_SECONDS,
        )
        self._initiate_exit()

    def _initiate_exit(self) -> None:
        threading.Thread(
            target=_force_exit_after_grace,
            name="openbase-worker-watchdog-exit",
            daemon=True,
        ).start()
        os.kill(os.getpid(), signal.SIGTERM)


def _force_exit_after_grace() -> None:
    time.sleep(_FORCED_EXIT_GRACE_SECONDS)
    os._exit(1)


def install_worker_init_failure_watchdog() -> WorkerInitFailureWatchdog:
    handler = WorkerInitFailureWatchdog()
    logging.getLogger("livekit.agents").addHandler(handler)
    return handler
