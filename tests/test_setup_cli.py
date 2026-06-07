from __future__ import annotations

import importlib
import json
import subprocess

setup_cli = importlib.import_module("openbase_coder_cli.cli.setup")


def test_update_existing_default_workspace_resets_dirty_checkout(
    tmp_path, monkeypatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    commands = []

    monkeypatch.setattr(setup_cli, "DEFAULT_WORKSPACE_DIR", workspace)

    def fake_run(command, **kwargs):
        commands.append((command, kwargs))
        if command[3:] == ["status", "--porcelain"]:
            return subprocess.CompletedProcess(command, 0, stdout=" M pnpm-lock.yaml\n")
        return subprocess.CompletedProcess(command, 0, stdout="")

    monkeypatch.setattr(setup_cli.subprocess, "run", fake_run)

    setup_cli._update_existing_workspace(workspace)

    assert [command for command, _kwargs in commands] == [
        ["git", "-C", str(workspace), "status", "--porcelain"],
        ["git", "-C", str(workspace), "fetch", "origin", "main"],
        ["git", "-C", str(workspace), "reset", "--hard", "origin/main"],
    ]


def test_update_existing_custom_workspace_uses_pull(tmp_path, monkeypatch) -> None:
    workspace = tmp_path / "custom-workspace"
    default_workspace = tmp_path / "default-workspace"
    workspace.mkdir()
    commands = []

    monkeypatch.setattr(setup_cli, "DEFAULT_WORKSPACE_DIR", default_workspace)

    def fake_run(command, **kwargs):
        commands.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="")

    monkeypatch.setattr(setup_cli.subprocess, "run", fake_run)

    setup_cli._update_existing_workspace(workspace)

    assert [command for command, _kwargs in commands] == [
        ["git", "-C", str(workspace), "pull", "--ff-only"],
    ]


def test_remove_managed_repo_symlinks_removes_selected_symlink(
    tmp_path, monkeypatch
) -> None:
    workspace = tmp_path / "workspace"
    target = tmp_path / "target"
    workspace.mkdir()
    target.mkdir()
    (workspace / "multi.json").write_text(
        json.dumps(
            {
                "repos": [
                    {"name": "console", "installSets": ["default"]},
                    {"name": "ios", "installSets": ["dev"]},
                ],
            }
        ),
        encoding="utf-8",
    )
    (workspace / "console").symlink_to(target)
    (workspace / "ios").symlink_to(target)
    monkeypatch.setattr(setup_cli, "DEFAULT_WORKSPACE_DIR", workspace)

    setup_cli._remove_managed_repo_symlinks(workspace)

    assert not (workspace / "console").exists()
    assert (workspace / "ios").is_symlink()


def test_update_install_set_repos_resets_managed_repos(tmp_path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    repo = workspace / "console"
    (repo / ".git").mkdir(parents=True)
    (workspace / "multi.json").write_text(
        json.dumps({"repos": [{"name": "console", "installSets": ["default"]}]}),
        encoding="utf-8",
    )
    commands = []

    monkeypatch.setattr(setup_cli, "DEFAULT_WORKSPACE_DIR", workspace)

    def fake_run(command, **kwargs):
        commands.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="")

    monkeypatch.setattr(setup_cli.subprocess, "run", fake_run)

    setup_cli._update_install_set_repos(workspace)

    assert [command for command, _kwargs in commands] == [
        ["git", "-C", str(repo), "fetch", "origin", "main"],
        ["git", "-C", str(repo), "reset", "--hard", "origin/main"],
    ]


def test_ensure_codex_home_default_files_creates_missing_files(
    tmp_path, monkeypatch
) -> None:
    workspace = tmp_path / "workspace"
    instructions = workspace / "instructions"
    instructions.mkdir(parents=True)
    codex_home = tmp_path / "codex_home"
    targets = tuple(
        (resource_name, codex_home / resource_name)
        for resource_name, _target_path in setup_cli.CODEX_HOME_DEFAULT_FILES
    )
    for resource_name, _target_path in targets:
        (instructions / resource_name).write_text(
            f"default {resource_name}\n",
            encoding="utf-8",
        )
    monkeypatch.setattr(setup_cli, "CODEX_HOME_DIR", codex_home)
    monkeypatch.setattr(setup_cli, "CODEX_HOME_DEFAULT_FILES", targets)

    setup_cli._ensure_codex_home_default_files(str(workspace))

    for resource_name, target_path in targets:
        assert target_path.read_text(encoding="utf-8") == f"default {resource_name}\n"


def test_ensure_codex_home_default_files_preserves_existing_files(
    tmp_path, monkeypatch
) -> None:
    workspace = tmp_path / "workspace"
    instructions = workspace / "instructions"
    instructions.mkdir(parents=True)
    codex_home = tmp_path / "codex_home"
    existing_path = codex_home / "AGENTS.md"
    missing_path = codex_home / "VOICE_INSTRUCTIONS.md"
    existing_path.parent.mkdir(parents=True)
    existing_path.write_text("custom instructions\n", encoding="utf-8")
    (instructions / "AGENTS.md").write_text("default agents\n", encoding="utf-8")
    (instructions / "VOICE_INSTRUCTIONS.md").write_text(
        "default voice\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(setup_cli, "CODEX_HOME_DIR", codex_home)
    monkeypatch.setattr(
        setup_cli,
        "CODEX_HOME_DEFAULT_FILES",
        (
            ("AGENTS.md", existing_path),
            ("VOICE_INSTRUCTIONS.md", missing_path),
        ),
    )

    setup_cli._ensure_codex_home_default_files(str(workspace))

    assert existing_path.read_text(encoding="utf-8") == "custom instructions\n"
    assert missing_path.read_text(encoding="utf-8") == "default voice\n"


def test_ensure_codex_home_default_files_skips_missing_sources(
    tmp_path, monkeypatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    codex_home = tmp_path / "codex_home"
    target_path = codex_home / "AGENTS.md"
    monkeypatch.setattr(setup_cli, "CODEX_HOME_DIR", codex_home)
    monkeypatch.setattr(
        setup_cli,
        "CODEX_HOME_DEFAULT_FILES",
        (("AGENTS.md", target_path),),
    )

    setup_cli._ensure_codex_home_default_files(str(workspace))

    assert not target_path.exists()


def test_ensure_codex_home_dispatcher_config_creates_default(
    tmp_path, monkeypatch
) -> None:
    config_path = tmp_path / "codex_home" / "dispatcher-config.json"
    monkeypatch.setattr(setup_cli, "CODEX_DISPATCHER_CONFIG_PATH", config_path)

    setup_cli._ensure_codex_home_dispatcher_config()

    assert json.loads(config_path.read_text(encoding="utf-8")) == {
        "dispatcher_reasoning_effort": "low",
        "super_agents_reasoning_effort": "high",
    }
    assert config_path.read_text(encoding="utf-8") == (
        "{\n"
        '  "dispatcher_reasoning_effort": "low",\n'
        '  "super_agents_reasoning_effort": "high"\n'
        "}\n"
    )


def test_ensure_codex_home_dispatcher_config_preserves_existing(
    tmp_path, monkeypatch
) -> None:
    config_path = tmp_path / "codex_home" / "dispatcher-config.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        "{\n"
        '  "dispatcher_reasoning_effort": "medium",\n'
        '  "super_agents_reasoning_effort": "xhigh"\n'
        "}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(setup_cli, "CODEX_DISPATCHER_CONFIG_PATH", config_path)

    setup_cli._ensure_codex_home_dispatcher_config()

    assert json.loads(config_path.read_text(encoding="utf-8")) == {
        "dispatcher_reasoning_effort": "medium",
        "super_agents_reasoning_effort": "xhigh",
    }


def test_symlink_codex_home_skills_links_workspace_skills(
    tmp_path, monkeypatch
) -> None:
    workspace = tmp_path / "workspace"
    skill = workspace / "skills" / "skills" / "sample-skill"
    codex_home = tmp_path / "codex_home"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# Sample\n", encoding="utf-8")
    monkeypatch.setattr(setup_cli, "CODEX_HOME_DIR", codex_home)

    setup_cli._symlink_codex_home_skills(str(workspace))

    target = codex_home / "skills" / "sample-skill"
    assert target.is_symlink()
    assert target.resolve() == skill.resolve()


def test_symlink_codex_home_skills_replaces_existing_symlink(
    tmp_path, monkeypatch
) -> None:
    workspace = tmp_path / "workspace"
    skill = workspace / "skills" / "skills" / "sample-skill"
    stale_skill = tmp_path / "stale-skill"
    codex_home = tmp_path / "codex_home"
    target = codex_home / "skills" / "sample-skill"
    skill.mkdir(parents=True)
    stale_skill.mkdir()
    target.parent.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# Sample\n", encoding="utf-8")
    target.symlink_to(stale_skill)
    monkeypatch.setattr(setup_cli, "CODEX_HOME_DIR", codex_home)

    setup_cli._symlink_codex_home_skills(str(workspace))

    assert target.is_symlink()
    assert target.resolve() == skill.resolve()


def test_symlink_codex_home_skills_preserves_real_directories(
    tmp_path, monkeypatch
) -> None:
    workspace = tmp_path / "workspace"
    skill = workspace / "skills" / "skills" / "sample-skill"
    codex_home = tmp_path / "codex_home"
    target = codex_home / "skills" / "sample-skill"
    skill.mkdir(parents=True)
    target.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# Sample\n", encoding="utf-8")
    (target / "SKILL.md").write_text("# Custom\n", encoding="utf-8")
    monkeypatch.setattr(setup_cli, "CODEX_HOME_DIR", codex_home)

    setup_cli._symlink_codex_home_skills(str(workspace))

    assert not target.is_symlink()
    assert (target / "SKILL.md").read_text(encoding="utf-8") == "# Custom\n"


def test_ensure_codex_home_config_creates_config(
    tmp_path, monkeypatch
) -> None:
    workspace = tmp_path / "workspace"
    command = workspace / ".venv" / "bin" / "super-agents-mcp"
    codex_home = tmp_path / "codex_home"
    command.parent.mkdir(parents=True)
    command.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(setup_cli, "CODEX_HOME_DIR", codex_home)

    setup_cli._ensure_codex_home_config(str(workspace))

    assert (codex_home / "config.toml").read_text(encoding="utf-8") == (
        'sandbox_mode = "danger-full-access"\n'
        "approval_policy = { granular = { sandbox_approval = false, rules = false, "
        "mcp_elicitations = false, request_permissions = false, "
        "skill_approval = false } }\n"
        "\n"
        "[mcp_servers.super-agents]\n"
        f"command = {json.dumps(str(command))}\n"
    )


def test_ensure_codex_home_config_replaces_stale_values(
    tmp_path, monkeypatch
) -> None:
    workspace = tmp_path / "workspace"
    command = workspace / ".venv" / "bin" / "super-agents-mcp"
    codex_home = tmp_path / "codex_home"
    config_path = codex_home / "config.toml"
    command.parent.mkdir(parents=True)
    command.write_text("#!/bin/sh\n", encoding="utf-8")
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        "\n".join(
            [
                'sandbox_mode = "workspace-write"',
                'approval_policy = "on-request"',
                "",
                '[projects."/Users/gabemontague"]',
                'trust_level = "trusted"',
                "",
                "[mcp_servers.super-agents]",
                'command = "/Users/gabemontague/.local/bin/uv"',
                'args = ["--directory", "/bad", "run", "super-agents-mcp"]',
                "",
                "[mcp_servers.playwright]",
                'command = "npx"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(setup_cli, "CODEX_HOME_DIR", codex_home)

    setup_cli._ensure_codex_home_config(str(workspace))

    updated = config_path.read_text(encoding="utf-8")
    assert 'sandbox_mode = "workspace-write"' not in updated
    assert 'approval_policy = "on-request"' not in updated
    assert 'sandbox_mode = "danger-full-access"' in updated
    assert (
        "approval_policy = { granular = { sandbox_approval = false, rules = false, "
        "mcp_elicitations = false, request_permissions = false, "
        "skill_approval = false } }"
    ) in updated
    assert updated.count("[mcp_servers.super-agents]") == 1
    assert "/Users/gabemontague/.local/bin/uv" not in updated
    assert "args =" not in updated
    assert "[projects.\"/Users/gabemontague\"]\ntrust_level = \"trusted\"" in updated
    assert f"command = {json.dumps(str(command))}" in updated
    assert "[mcp_servers.playwright]\ncommand = \"npx\"" in updated


def test_ensure_codex_home_config_falls_back_to_resolved_uv(
    tmp_path, monkeypatch
) -> None:
    workspace = tmp_path / "workspace"
    cli_dir = workspace / "cli"
    codex_home = tmp_path / "codex_home"
    uv_bin = tmp_path / "homebrew" / "bin" / "uv"
    cli_dir.mkdir(parents=True)
    uv_bin.parent.mkdir(parents=True)
    uv_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(setup_cli, "CODEX_HOME_DIR", codex_home)
    monkeypatch.setattr(
        setup_cli,
        "which",
        lambda command: str(uv_bin) if command == "uv" else None,
    )

    setup_cli._ensure_codex_home_config(str(workspace))

    assert (codex_home / "config.toml").read_text(encoding="utf-8") == (
        'sandbox_mode = "danger-full-access"\n'
        "approval_policy = { granular = { sandbox_approval = false, rules = false, "
        "mcp_elicitations = false, request_permissions = false, "
        "skill_approval = false } }\n"
        "\n"
        "[mcp_servers.super-agents]\n"
        f"command = {json.dumps(str(uv_bin))}\n"
        f"args = {json.dumps(['--directory', str(cli_dir), 'run', 'super-agents-mcp'])}\n"
    )


def test_workspace_skill_sources_supports_direct_skill_dirs(tmp_path) -> None:
    source_root = tmp_path / "skills"
    direct_skill = source_root / "direct-skill"
    nested_skill = source_root / "skills" / "nested-skill"
    direct_skill.mkdir(parents=True)
    nested_skill.mkdir(parents=True)
    (direct_skill / "SKILL.md").write_text("# Direct\n", encoding="utf-8")
    (nested_skill / "SKILL.md").write_text("# Nested\n", encoding="utf-8")

    assert setup_cli._workspace_skill_sources(source_root) == [
        nested_skill,
        direct_skill,
    ]


def test_build_console_does_not_sync_plugin_generated_files(
    tmp_path, monkeypatch
) -> None:
    workspace = tmp_path / "workspace"
    console_dir = workspace / "console"
    generated_registry = console_dir / "src" / "generated" / "pluginRegistry.ts"
    console_dir.mkdir(parents=True)
    commands = []

    def fake_run_workspace_package_command(workspace_dir, package_dir, *args):
        commands.append((workspace_dir, package_dir, args))
        return True

    def fail_if_plugin_registry_is_loaded():
        raise AssertionError("setup should not sync plugin console integration")

    monkeypatch.setattr(
        setup_cli,
        "run_workspace_package_command",
        fake_run_workspace_package_command,
    )
    monkeypatch.setattr(setup_cli, "load_registry", fail_if_plugin_registry_is_loaded, raising=False)

    setup_cli._build_console(str(workspace))

    assert commands == [
        (workspace, console_dir, ("install",)),
        (workspace, console_dir, ("run", "build")),
    ]
    assert not generated_registry.exists()
