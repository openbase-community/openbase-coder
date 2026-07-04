"""Tests for the two-way deployment behaviors: backend gating, lazy binary
resolution, shim safety, and backend selection."""

from __future__ import annotations

import pytest

from openbase_coder_cli.cli.setup import _require_backend_choice
from openbase_coder_cli.cli.setup import workspace as workspace_phase
from openbase_coder_cli.runtime import RuntimePackage
from openbase_coder_cli.services import launchd
from openbase_coder_cli.services.definitions import (
    ServiceDefinition,
    default_services,
)
from openbase_coder_cli.services.installation import InstallationConfig


def test_default_services_gates_codex_app_server_by_backend() -> None:
    claude_names = {svc.name for svc in default_services("claude_code")}
    codex_names = {svc.name for svc in default_services("codex")}
    cloud_names = {svc.name for svc in default_services("openbase_cloud")}

    assert "codex-app-server" not in claude_names
    assert "codex-app-server" in codex_names
    assert "codex-app-server" in cloud_names
    # Backend-agnostic services stay in all sets.
    assert "django-cli" in claude_names
    assert "livekit-agent" in claude_names


def test_resolve_binaries_only_resolves_referenced_binaries(
    tmp_path, monkeypatch
) -> None:
    # Nothing is findable on PATH; resolution would raise for any binary it
    # actually attempts, so this passes only if unreferenced binaries
    # (codex, uv, livekit) are never resolved.
    monkeypatch.setattr(launchd.shutil, "which", lambda _name: None)
    service = ServiceDefinition(
        name="sample",
        description="Sample",
        command_template="exec {python} -m something",
        workdir_template="{data_dir}",
    )
    config = InstallationConfig(env_file=str(tmp_path / ".env"))

    binaries = launchd._resolve_binaries(config, [service])

    assert set(binaries) == {"python"}


def test_selected_backend_reads_env_file(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("OPENBASE_CODING_BACKEND=claude_code\n", encoding="utf-8")
    config = InstallationConfig(env_file=str(env_file))

    assert launchd._selected_backend(config) == "claude_code"


def test_install_cli_shim_leaves_uv_tool_script_alone(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(workspace_phase.Path, "home", classmethod(lambda cls: tmp_path))
    shim_path = tmp_path / ".local" / "bin" / "openbase-coder"
    shim_path.parent.mkdir(parents=True)
    uv_tool_script = (
        "#!/home/user/.local/share/uv/tools/openbase-coder/bin/python\nimport sys\n"
    )
    shim_path.write_text(uv_tool_script, encoding="utf-8")

    workspace_phase._install_cli_shim(str(tmp_path / "workspace"))

    assert shim_path.read_text(encoding="utf-8") == uv_tool_script


def test_install_cli_shim_dev_mode_execs_workspace_venv(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(workspace_phase.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(workspace_phase, "current_runtime_package", lambda: None)
    workspace = tmp_path / "workspace"
    venv_cli = workspace / "cli" / ".venv" / "bin" / "openbase-coder"
    venv_cli.parent.mkdir(parents=True)
    venv_cli.write_text("#!/bin/sh\n", encoding="utf-8")

    workspace_phase._install_cli_shim(str(workspace))

    shim = (tmp_path / ".local" / "bin" / "openbase-coder").read_text(encoding="utf-8")
    assert str(venv_cli) in shim
    assert "uv run" not in shim


def test_install_cli_shim_standalone_points_at_current_launcher(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(workspace_phase.Path, "home", classmethod(lambda cls: tmp_path))
    releases_dir = tmp_path / "packages" / "standalone" / "releases"
    release_root = releases_dir / "1.0.0-aarch64-apple-darwin"
    (release_root / "bin").mkdir(parents=True)
    release_launcher = release_root / "bin" / "openbase-coder"
    release_launcher.write_text("#!/bin/sh\n", encoding="utf-8")
    current_dir = tmp_path / "packages" / "standalone" / "current"
    current_dir.symlink_to(release_root)

    monkeypatch.setattr(workspace_phase, "STANDALONE_RELEASES_DIR", releases_dir)
    monkeypatch.setattr(workspace_phase, "STANDALONE_CURRENT_DIR", current_dir)
    monkeypatch.setattr(
        workspace_phase,
        "current_runtime_package",
        lambda: RuntimePackage(root=release_root),
    )

    workspace_phase._install_cli_shim("")

    shim = (tmp_path / ".local" / "bin" / "openbase-coder").read_text(encoding="utf-8")
    assert str(current_dir / "bin" / "openbase-coder") in shim
    assert str(release_root) not in shim
    assert "OPENBASE_CODER_PACKAGE_DIR" not in shim


def test_require_backend_choice_keeps_existing_env(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("OPENBASE_CODING_BACKEND=claude_code\n", encoding="utf-8")

    assert _require_backend_choice(str(env_file), None, interactive=True) is None


def test_require_backend_choice_passes_through_flag(tmp_path) -> None:
    assert (
        _require_backend_choice(
            str(tmp_path / ".env"), "claude_code", interactive=False
        )
        == "claude_code"
    )


def test_require_backend_choice_errors_non_interactive_fresh_install(
    tmp_path,
) -> None:
    with pytest.raises(Exception, match="--backend"):
        _require_backend_choice(str(tmp_path / ".env"), None, interactive=False)
