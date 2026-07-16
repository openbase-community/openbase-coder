from __future__ import annotations

import subprocess

from openbase_coder_cli.services import keep_awake


class FakeProcess:
    def __init__(self) -> None:
        self.killed = False
        self.terminated = False
        self.wait_calls = 0

    def poll(self):
        return None

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True

    def wait(self, timeout=None):
        self.wait_calls += 1
        return 0


def test_start_keep_awake_runs_caffeinate_idle_and_display(monkeypatch) -> None:
    popen_calls = []
    fake_process = FakeProcess()

    monkeypatch.setattr(keep_awake.sys, "platform", "darwin")
    monkeypatch.setattr(keep_awake.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        keep_awake.subprocess,
        "Popen",
        lambda *args, **kwargs: popen_calls.append((args, kwargs)) or fake_process,
    )

    process = keep_awake.start_keep_awake()

    assert process is fake_process
    assert popen_calls[0][0][0] == ["/usr/bin/caffeinate", "-i", "-d"]
    assert popen_calls[0][1]["stdout"] == subprocess.DEVNULL
    assert popen_calls[0][1]["stderr"] == subprocess.DEVNULL


def test_start_keep_awake_noops_when_disabled(monkeypatch) -> None:
    popen_calls = []

    monkeypatch.setattr(keep_awake, "get_keep_system_awake_enabled", lambda: False)
    monkeypatch.setattr(keep_awake.sys, "platform", "darwin")
    monkeypatch.setattr(keep_awake.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        keep_awake.subprocess,
        "Popen",
        lambda *args, **kwargs: popen_calls.append((args, kwargs)),
    )

    assert keep_awake.start_keep_awake() is None
    assert popen_calls == []


def test_start_keep_awake_noops_off_macos(monkeypatch) -> None:
    monkeypatch.setattr(keep_awake.sys, "platform", "linux")

    assert keep_awake.start_keep_awake() is None


def test_start_keep_awake_warns_when_caffeinate_missing(monkeypatch) -> None:
    warnings = []

    monkeypatch.setattr(keep_awake.sys, "platform", "darwin")
    monkeypatch.setattr(keep_awake.shutil, "which", lambda _name: None)

    assert keep_awake.start_keep_awake(warn=warnings.append) is None
    assert warnings == ["Keep-awake unavailable: caffeinate was not found."]


def test_keep_awake_status_reflects_disabled_setting(monkeypatch) -> None:
    monkeypatch.setattr(keep_awake, "get_keep_system_awake_enabled", lambda: False)
    monkeypatch.setattr(keep_awake.sys, "platform", "darwin")
    monkeypatch.setattr(keep_awake.shutil, "which", lambda _name: "/usr/bin/caffeinate")

    payload = keep_awake.keep_awake_status_payload()

    assert payload["enabled"] is False
    assert payload["running"] is False
    assert payload["command"] == "caffeinate -i -d"


def test_stop_keep_awake_terminates_process() -> None:
    process = FakeProcess()

    keep_awake.stop_keep_awake(process)

    assert process.terminated is True
    assert process.killed is False
    assert process.wait_calls == 1


def test_stop_keep_awake_kills_if_process_does_not_exit() -> None:
    class StubbornProcess(FakeProcess):
        def wait(self, timeout=None):
            self.wait_calls += 1
            if self.wait_calls == 1:
                raise subprocess.TimeoutExpired("caffeinate", timeout)
            return 0

    process = StubbornProcess()

    keep_awake.stop_keep_awake(process)

    assert process.terminated is True
    assert process.killed is True
    assert process.wait_calls == 2
