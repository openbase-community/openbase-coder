import subprocess

from openbase_coder_cli.runtime import RuntimePackage
from openbase_coder_cli.services import launchd
from openbase_coder_cli.services.definitions import ServiceDefinition
from openbase_coder_cli.services.installation import InstallationConfig


def test_generate_wrapper_includes_user_bin_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(launchd, "LAUNCHD_WRAPPER_DIR", tmp_path / "launchd")
    monkeypatch.setattr(launchd, "OPENBASE_BASE_DIR", tmp_path / "openbase")

    service = ServiceDefinition(
        name="sample",
        description="Sample",
        command_template="command -v openbase-coder",
        workdir_template="{workspace}",
    )
    config = InstallationConfig(
        workspace_path=str(tmp_path / "workspace"),
        env_file=str(tmp_path / ".env"),
    )

    wrapper = launchd.generate_wrapper(service, config, {})

    assert (
        'export PATH="$HOME/.openbase/bin:$HOME/.local/bin:$HOME/bin:'
        '/opt/homebrew/bin:/usr/local/bin:$PATH"' in wrapper.read_text()
    )


def test_resolve_binaries_prefers_standalone_paths(tmp_path, monkeypatch):
    package_dir = tmp_path / "package"
    bin_dir = package_dir / "bin"
    bin_dir.mkdir(parents=True)
    openbase_coder = bin_dir / "openbase-coder"
    livekit = bin_dir / "livekit-server"
    python = package_dir / "python" / "bin" / "python"
    python.parent.mkdir(parents=True)
    for path in (openbase_coder, livekit, python):
        path.write_text("#!/bin/sh\n")
        path.chmod(0o755)

    monkeypatch.setattr(launchd.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        launchd, "stable_runtime_package", lambda: RuntimePackage(root=package_dir)
    )
    monkeypatch.setattr(launchd, "OPENBASE_BASE_DIR", tmp_path / "openbase")

    config = InstallationConfig(
        workspace_path="",
        env_file=str(tmp_path / ".env"),
        standalone=True,
    )

    binaries = launchd._resolve_binaries(config)

    assert binaries["openbase_coder"] == str(openbase_coder)
    assert binaries["livekit"] == str(livekit)
    assert binaries["python"] == str(python)
    assert binaries["runtime_workdir"] == str(package_dir)


def test_launchctl_bootstrap_reenables_disabled_label(tmp_path, monkeypatch):
    service = ServiceDefinition(
        name="sample",
        description="Sample",
        command_template="exec true",
        workdir_template="{workspace}",
    )
    plist = tmp_path / "sample.plist"
    calls = []

    def fake_launchctl(*args, check=True):
        calls.append(args)
        return subprocess.CompletedProcess(["launchctl", *args], 0, "", "")

    monkeypatch.setattr(launchd, "_is_macos", lambda: True)
    monkeypatch.setattr(launchd, "_uid", lambda: 501)
    monkeypatch.setattr(launchd, "_plist_path", lambda _svc: plist)
    monkeypatch.setattr(launchd, "_prepare_service_start", lambda _svc: None)
    monkeypatch.setattr(launchd.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(launchd, "_launchctl", fake_launchctl)

    launchd.launchctl_bootstrap(service)

    assert ("enable", "gui/501/com.openbase.coder.sample") in calls
    assert calls.index(("enable", "gui/501/com.openbase.coder.sample")) < calls.index(
        ("bootstrap", "gui/501", str(plist))
    )


def test_launchctl_bootstrap_kickstarts_once_after_successful_bootstrap(
    tmp_path, monkeypatch
):
    service = ServiceDefinition(
        name="sample",
        description="Sample",
        command_template="exec true",
        workdir_template="{workspace}",
    )
    plist = tmp_path / "sample.plist"
    calls = []
    bootstrap_returncodes = iter([5, 5, 0])

    def fake_launchctl(*args, check=True):
        calls.append(args)
        code = next(bootstrap_returncodes) if args[0] == "bootstrap" else 0
        return subprocess.CompletedProcess(["launchctl", *args], code, "", "")

    monkeypatch.setattr(launchd, "_is_macos", lambda: True)
    monkeypatch.setattr(launchd, "_uid", lambda: 501)
    monkeypatch.setattr(launchd, "_plist_path", lambda _svc: plist)
    monkeypatch.setattr(launchd, "_prepare_service_start", lambda _svc: None)
    monkeypatch.setattr(launchd.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(launchd, "_launchctl", fake_launchctl)

    launchd.launchctl_bootstrap(service)

    target = "gui/501/com.openbase.coder.sample"
    bootstrap_indexes = [i for i, c in enumerate(calls) if c[0] == "bootstrap"]
    kickstart_calls = [c for c in calls if c[0] == "kickstart"]

    # Exactly one kickstart, for the same service target, without -k.
    assert kickstart_calls == [("kickstart", target)]
    # It immediately follows the successful (final) bootstrap, so the two
    # failed attempts before it ran without a kickstart.
    assert len(bootstrap_indexes) == 3
    assert calls.index(("kickstart", target)) == bootstrap_indexes[-1] + 1


def test_generate_wrapper_quotes_binary_paths_with_spaces(tmp_path, monkeypatch):
    monkeypatch.setattr(launchd, "LAUNCHD_WRAPPER_DIR", tmp_path / "launchd")
    monkeypatch.setattr(launchd, "OPENBASE_BASE_DIR", tmp_path / "openbase")

    service = ServiceDefinition(
        name="sample",
        description="Sample",
        command_template='exec {openbase_coder} server --port "$PORT"',
        workdir_template="{workspace}",
    )
    config = InstallationConfig(
        workspace_path=str(tmp_path / "workspace"),
        env_file=str(tmp_path / ".env"),
    )
    bundled = "/Applications/Openbase Coder.app/Contents/Resources/OpenbaseCoderCLI/bin/openbase-coder"

    wrapper = launchd.generate_wrapper(
        service, config, {"openbase_coder": bundled}
    )

    content = wrapper.read_text()
    assert f"exec '{bundled}' server" in content
    assert f"exec {bundled} server" not in content
