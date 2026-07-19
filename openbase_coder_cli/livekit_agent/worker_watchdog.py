"""Exit the agent when its LiveKit worker is permanently broken.

Two failure modes leave launchd/systemd keeping a useless process alive:

- Job workers that repeatedly fail to initialize (for example after the
  virtualenv was rebuilt for a different Python while the service kept
  running): the agent stays registered with LiveKit while every dispatched
  job dies — calls connect and then silently never get an agent.
- The worker's reconnect loop raising after exhausting its retries (for
  example when livekit-server stays down for a few minutes): the SDK never
  restarts its connection task, so the agent lingers unregistered forever
  and calls wait for an agent that can never arrive.

Exiting is the recovery in both cases: the service manager restarts the
agent, which boots against the current environment and re-registers.
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
# livekit-agents logs this (via @log_exceptions) when _connection_task
# raises — after max_retry failed connect attempts it is terminal: the SDK
# never restarts the task, so the worker can never reconnect.
_CONNECTION_FAILURE_MESSAGE = "Error in _connection_task"


class WorkerFailureWatchdog(logging.Handler):
    """Log handler that exits the service on unrecoverable worker failures."""

    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self._failure_times: list[float] = []
        self._lock = threading.Lock()
        self._exiting = False

    def emit(self, record: logging.LogRecord) -> None:
        message = str(record.getMessage())
        if _CONNECTION_FAILURE_MESSAGE in message:
            self._exit_once(
                "livekit-agent's LiveKit connection task died (the SDK never "
                "restarts it); exiting so the service manager restarts the "
                "agent"
            )
            return
        if _INIT_FAILURE_MESSAGE not in message:
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
        self._exit_once(
            "livekit-agent job workers failed to initialize "
            f"{WORKER_INIT_FAILURE_THRESHOLD} times within "
            f"{WORKER_INIT_FAILURE_WINDOW_SECONDS:.0f}s; exiting so the "
            "service manager restarts the agent under the current environment"
        )

    def _exit_once(self, reason: str) -> None:
        with self._lock:
            if self._exiting:
                return
            self._exiting = True
        logger.critical(reason)
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


def install_worker_failure_watchdog() -> WorkerFailureWatchdog:
    handler = WorkerFailureWatchdog()
    logging.getLogger("livekit.agents").addHandler(handler)
    return handler
