"""Keep the local Mac awake while Openbase Coder services are running."""

from __future__ import annotations

import contextlib
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterator

CAFFEINATE_ARGS = ("-i", "-d")


def start_keep_awake(
    *, warn: Callable[[str], None] | None = None
) -> subprocess.Popen[bytes] | None:
    """Start macOS caffeinate for idle and display sleep prevention."""
    if sys.platform != "darwin":
        return None

    caffeinate = shutil.which("caffeinate")
    if not caffeinate:
        if warn:
            warn("Keep-awake unavailable: caffeinate was not found.")
        return None

    try:
        return subprocess.Popen(
            [caffeinate, *CAFFEINATE_ARGS],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        if warn:
            warn(f"Keep-awake unavailable: {exc}")
        return None


def stop_keep_awake(process: subprocess.Popen[bytes] | None) -> None:
    """Stop a caffeinate process started by start_keep_awake."""
    if process is None or process.poll() is not None:
        return

    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


@contextlib.contextmanager
def keep_system_awake(
    *, warn: Callable[[str], None] | None = None
) -> Iterator[None]:
    """Hold a caffeinate process for the duration of the context."""
    process = start_keep_awake(warn=warn)
    try:
        yield
    finally:
        stop_keep_awake(process)
