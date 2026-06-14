from __future__ import annotations

import importlib
import json
import subprocess
from pathlib import Path

from click.testing import CliRunner

from openbase_coder_cli import claude_auth

setup_cli = importlib.import_module("openbase_coder_cli.cli.setup")


def _patch_openbase_agent_paths(monkeypatch, tmp_path: Path) -> tuple[Path, Path]:
    codex_home = tmp_path / "codex_home"
    claude_config = tmp_path / "claude_config"
    instructions = tmp_path / "openbase" / "instructions"
    monkeypatch.setattr(setup_cli, "CODEX_HOME_DIR", codex_home)
    monkeypatch.setattr(setup_cli, "OPENBASE_CLAUDE_CONFIG_DIR", claude_config)
    monkeypatch.setattr(
        setup_cli, "OPENBASE_CLAUDE_MD_PATH", claude_config / "CLAUDE.md"
    )
    monkeypatch.setattr(
        setup_cli,
        "OPENBASE_CLAUDE_SETTINGS_PATH",
        claude_config / "settings.json",
    )
    monkeypatch.setattr(
        setup_cli,
        "NORMAL_CLAUDE_SETTINGS_PATH",
        tmp_path / "normal_claude" / "settings.json",
    )
    monkeypatch.setattr(
        setup_cli,
        "NORMAL_CLAUDE_CONFIG_DIR",
        tmp_path / "normal_claude",
    )
    monkeypatch.setattr(
        setup_cli,
        "CODEX_DIRECT_LIVEKIT_INSTRUCTIONS_PATH",
        instructions / "VOICE_INSTRUCTIONS.md",
    )
    monkeypatch.setattr(
        setup_cli,
        "CODEX_DISPATCHER_INSTRUCTIONS_PATH",
        instructions / "DISPATCHER_INSTRUCTIONS.md",
    )
    monkeypatch.setattr(
        setup_cli,
        "CODEX_SUPER_AGENT_INSTRUCTIONS_PATH",
        instructions / "SUPER_AGENT_INSTRUCTIONS.md",
    )
    monkeypatch.setattr(
        setup_cli,
        "LEGACY_CODEX_HOME_DEFAULT_FILES",
        (
            (
                instructions / "VOICE_INSTRUCTIONS.md",
                codex_home / "VOICE_INSTRUCTIONS.md",
            ),
            (
                instructions / "DISPATCHER_INSTRUCTIONS.md",
                codex_home / "DISPATCHER_INSTRUCTIONS.md",
            ),
            (
                instructions / "SUPER_AGENT_INSTRUCTIONS.md",
                codex_home / "SUPER_AGENT_INSTRUCTIONS.md",
            ),
        ),
    )
    return codex_home, claude_config


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


def test_ensure_codex_home_default_files_links_missing_files(
    tmp_path, monkeypatch
) -> None:
    workspace = tmp_path / "workspace"
    instructions = workspace / "instructions"
    instructions.mkdir(parents=True)
    codex_home, _claude_config = _patch_openbase_agent_paths(monkeypatch, tmp_path)
    shared_instructions = tmp_path / "openbase" / "instructions"
    targets = (
        ("VOICE_INSTRUCTIONS.md", shared_instructions / "VOICE_INSTRUCTIONS.md"),
        (
            "DISPATCHER_INSTRUCTIONS.md",
            shared_instructions / "DISPATCHER_INSTRUCTIONS.md",
        ),
        (
            "SUPER_AGENT_INSTRUCTIONS.md",
            shared_instructions / "SUPER_AGENT_INSTRUCTIONS.md",
        ),
    )
    for resource_name, _target_path in targets:
        (instructions / resource_name).write_text(
            f"default {resource_name}\n",
            encoding="utf-8",
        )
    monkeypatch.setattr(setup_cli, "CODEX_HOME_DEFAULT_FILES", targets)

    setup_cli._ensure_codex_home_default_files(str(workspace))

    for resource_name, target_path in targets:
        assert target_path.is_symlink()
        assert target_path.resolve() == (instructions / resource_name).resolve()
        assert target_path.read_text(encoding="utf-8") == f"default {resource_name}\n"
        legacy_path = codex_home / resource_name
        assert legacy_path.is_symlink()
        assert legacy_path.readlink() == target_path


def test_ensure_codex_home_default_files_preserves_custom_existing_files(
    tmp_path, monkeypatch
) -> None:
    workspace = tmp_path / "workspace"
    instructions = workspace / "instructions"
    instructions.mkdir(parents=True)
    codex_home, _claude_config = _patch_openbase_agent_paths(monkeypatch, tmp_path)
    shared_instructions = tmp_path / "openbase" / "instructions"
    existing_path = codex_home / "AGENTS.md"
    missing_path = shared_instructions / "VOICE_INSTRUCTIONS.md"
    existing_path.parent.mkdir(parents=True)
    existing_path.write_text("custom instructions\n", encoding="utf-8")
    (instructions / "AGENTS.md").write_text("default agents\n", encoding="utf-8")
    (instructions / "VOICE_INSTRUCTIONS.md").write_text(
        "default voice\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        setup_cli,
        "CODEX_HOME_DEFAULT_FILES",
        (
            ("AGENTS.md", existing_path),
            ("VOICE_INSTRUCTIONS.md", missing_path),
        ),
    )

    setup_cli._ensure_codex_home_default_files(str(workspace))

    assert not existing_path.is_symlink()
    updated_agents = existing_path.read_text(encoding="utf-8")
    assert updated_agents.startswith("custom instructions\n\n")
    assert "## Openbase Coder Instructions\n\n" in updated_agents
    assert (
        f"- These instructions are auto generated from {instructions / 'AGENTS.md'}."
        in updated_agents
    )
    assert "default agents\n" in updated_agents
    assert missing_path.is_symlink()
    assert missing_path.resolve() == (instructions / "VOICE_INSTRUCTIONS.md").resolve()
    assert missing_path.read_text(encoding="utf-8") == "default voice\n"
    assert (codex_home / "VOICE_INSTRUCTIONS.md").readlink() == missing_path


def test_ensure_codex_home_default_files_rewrites_matching_agents_file(
    tmp_path, monkeypatch
) -> None:
    workspace = tmp_path / "workspace"
    instructions = workspace / "instructions"
    instructions.mkdir(parents=True)
    codex_home, _claude_config = _patch_openbase_agent_paths(monkeypatch, tmp_path)
    target_path = codex_home / "AGENTS.md"
    target_path.parent.mkdir(parents=True)
    (instructions / "AGENTS.md").write_text("default agents\n", encoding="utf-8")
    target_path.write_text("default agents\n", encoding="utf-8")
    monkeypatch.setattr(
        setup_cli,
        "CODEX_HOME_DEFAULT_FILES",
        (("AGENTS.md", target_path),),
    )

    setup_cli._ensure_codex_home_default_files(str(workspace))

    assert not target_path.is_symlink()
    assert target_path.read_text(encoding="utf-8") == (
        "## Openbase Coder Instructions\n\n"
        f"- These instructions are auto generated from {instructions / 'AGENTS.md'}."
        "\n\n"
        "default agents\n"
    )


def test_ensure_codex_home_default_files_converts_stale_agents_symlink(
    tmp_path, monkeypatch
) -> None:
    workspace = tmp_path / "workspace"
    instructions = workspace / "instructions"
    stale_instructions = tmp_path / "stale-instructions"
    instructions.mkdir(parents=True)
    stale_instructions.mkdir()
    codex_home, _claude_config = _patch_openbase_agent_paths(monkeypatch, tmp_path)
    target_path = codex_home / "AGENTS.md"
    target_path.parent.mkdir(parents=True)
    (instructions / "AGENTS.md").write_text("default agents\n", encoding="utf-8")
    (stale_instructions / "AGENTS.md").write_text("stale agents\n", encoding="utf-8")
    target_path.symlink_to(stale_instructions / "AGENTS.md")
    monkeypatch.setattr(
        setup_cli,
        "CODEX_HOME_DEFAULT_FILES",
        (("AGENTS.md", target_path),),
    )

    setup_cli._ensure_codex_home_default_files(str(workspace))

    assert not target_path.is_symlink()
    updated = target_path.read_text(encoding="utf-8")
    assert updated.startswith("stale agents\n\n")
    assert "## Openbase Coder Instructions\n\n" in updated
    assert "default agents\n" in updated


def test_ensure_codex_home_default_files_converts_current_agents_symlink(
    tmp_path, monkeypatch
) -> None:
    workspace = tmp_path / "workspace"
    instructions = workspace / "instructions"
    instructions.mkdir(parents=True)
    codex_home, _claude_config = _patch_openbase_agent_paths(monkeypatch, tmp_path)
    target_path = codex_home / "AGENTS.md"
    target_path.parent.mkdir(parents=True)
    source_path = instructions / "AGENTS.md"
    source_path.write_text("default agents\n", encoding="utf-8")
    target_path.symlink_to(source_path)
    monkeypatch.setattr(
        setup_cli,
        "CODEX_HOME_DEFAULT_FILES",
        (("AGENTS.md", target_path),),
    )

    setup_cli._ensure_codex_home_default_files(str(workspace))

    assert not target_path.is_symlink()
    assert target_path.read_text(encoding="utf-8") == (
        "## Openbase Coder Instructions\n\n"
        f"- These instructions are auto generated from {source_path}.\n\n"
        "default agents\n"
    )


def test_ensure_codex_home_default_files_skips_missing_sources(
    tmp_path, monkeypatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    codex_home, _claude_config = _patch_openbase_agent_paths(monkeypatch, tmp_path)
    target_path = codex_home / "AGENTS.md"
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
    config_path = tmp_path / "dispatcher-config.json"
    legacy_path = tmp_path / "codex_home" / "dispatcher-config.json"
    monkeypatch.setattr(setup_cli, "CODEX_DISPATCHER_CONFIG_PATH", config_path)
    monkeypatch.setattr(setup_cli, "LEGACY_CODEX_DISPATCHER_CONFIG_PATH", legacy_path)

    setup_cli._ensure_codex_home_dispatcher_config()

    assert json.loads(config_path.read_text(encoding="utf-8")) == {
        "backend_models": {
            "claude_code": {
                "dispatcher": "opus",
                "super_agents": "opus",
            },
            "codex": {
                "dispatcher": "gpt-5.5",
                "super_agents": "gpt-5.5",
            },
        },
        "dispatcher_voice_id": "9626c31c-bec5-4cca-baa8-f8ba9e84c8bc",
        "dispatcher_voice_name": "Jacqueline",
        "dispatcher_reasoning_effort": "low",
        "stt_provider": "openbase_cloud",
        "super_agents_reasoning_effort": "high",
        "tts_provider": "openbase_cloud",
    }
    assert legacy_path.is_symlink()
    assert legacy_path.resolve() == config_path.resolve()


def test_ensure_codex_home_dispatcher_config_preserves_existing(
    tmp_path, monkeypatch
) -> None:
    config_path = tmp_path / "dispatcher-config.json"
    legacy_path = tmp_path / "codex_home" / "dispatcher-config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        "{\n"
        '  "dispatcher_reasoning_effort": "medium",\n'
        '  "super_agents_reasoning_effort": "xhigh"\n'
        "}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(setup_cli, "CODEX_DISPATCHER_CONFIG_PATH", config_path)
    monkeypatch.setattr(setup_cli, "LEGACY_CODEX_DISPATCHER_CONFIG_PATH", legacy_path)

    setup_cli._ensure_codex_home_dispatcher_config()

    assert json.loads(config_path.read_text(encoding="utf-8")) == {
        "dispatcher_reasoning_effort": "medium",
        "super_agents_reasoning_effort": "xhigh",
    }
    assert legacy_path.is_symlink()
    assert legacy_path.resolve() == config_path.resolve()


def test_ensure_codex_home_dispatcher_config_updates_audio_provider_when_requested(
    tmp_path, monkeypatch
) -> None:
    config_path = tmp_path / "dispatcher-config.json"
    legacy_path = tmp_path / "codex_home" / "dispatcher-config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        "{\n"
        '  "dispatcher_reasoning_effort": "medium",\n'
        '  "super_agents_reasoning_effort": "xhigh"\n'
        "}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(setup_cli, "CODEX_DISPATCHER_CONFIG_PATH", config_path)
    monkeypatch.setattr(setup_cli, "LEGACY_CODEX_DISPATCHER_CONFIG_PATH", legacy_path)

    setup_cli._ensure_codex_home_dispatcher_config(audio_provider="local")

    assert json.loads(config_path.read_text(encoding="utf-8")) == {
        "dispatcher_reasoning_effort": "medium",
        "dispatcher_voice_id": "af_heart",
        "dispatcher_voice_name": "Heart",
        "stt_provider": "local_mlx_whisper",
        "super_agents_reasoning_effort": "xhigh",
        "tts_provider": "kokoro",
    }
    assert legacy_path.is_symlink()
    assert legacy_path.resolve() == config_path.resolve()


def test_ensure_codex_home_dispatcher_config_migrates_legacy_file(
    tmp_path, monkeypatch
) -> None:
    config_path = tmp_path / "dispatcher-config.json"
    legacy_path = tmp_path / "codex_home" / "dispatcher-config.json"
    legacy_path.parent.mkdir(parents=True)
    legacy_path.write_text(
        "{\n"
        '  "dispatcher_reasoning_effort": "medium",\n'
        '  "super_agents_reasoning_effort": "xhigh"\n'
        "}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(setup_cli, "CODEX_DISPATCHER_CONFIG_PATH", config_path)
    monkeypatch.setattr(setup_cli, "LEGACY_CODEX_DISPATCHER_CONFIG_PATH", legacy_path)

    setup_cli._ensure_codex_home_dispatcher_config()

    assert json.loads(config_path.read_text(encoding="utf-8")) == {
        "dispatcher_reasoning_effort": "medium",
        "super_agents_reasoning_effort": "xhigh",
    }
    assert legacy_path.is_symlink()
    assert legacy_path.resolve() == config_path.resolve()


def test_symlink_codex_home_skills_links_workspace_skills(
    tmp_path, monkeypatch
) -> None:
    workspace = tmp_path / "workspace"
    skill = workspace / "skills" / "skills" / "sample-skill"
    codex_home, claude_config = _patch_openbase_agent_paths(monkeypatch, tmp_path)
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# Sample\n", encoding="utf-8")

    setup_cli._symlink_codex_home_skills(str(workspace))

    target = codex_home / "skills" / "sample-skill"
    assert target.is_symlink()
    assert target.resolve() == skill.resolve()
    claude_target = claude_config / "skills" / "sample-skill"
    assert claude_target.is_symlink()
    assert claude_target.resolve() == skill.resolve()


def test_symlink_codex_home_skills_replaces_existing_symlink(
    tmp_path, monkeypatch
) -> None:
    workspace = tmp_path / "workspace"
    skill = workspace / "skills" / "skills" / "sample-skill"
    stale_skill = tmp_path / "stale-skill"
    codex_home, _claude_config = _patch_openbase_agent_paths(monkeypatch, tmp_path)
    target = codex_home / "skills" / "sample-skill"
    skill.mkdir(parents=True)
    stale_skill.mkdir()
    target.parent.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# Sample\n", encoding="utf-8")
    target.symlink_to(stale_skill)

    setup_cli._symlink_codex_home_skills(str(workspace))

    assert target.is_symlink()
    assert target.resolve() == skill.resolve()


def test_symlink_codex_home_skills_preserves_real_directories(
    tmp_path, monkeypatch
) -> None:
    workspace = tmp_path / "workspace"
    skill = workspace / "skills" / "skills" / "sample-skill"
    codex_home, _claude_config = _patch_openbase_agent_paths(monkeypatch, tmp_path)
    target = codex_home / "skills" / "sample-skill"
    skill.mkdir(parents=True)
    target.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# Sample\n", encoding="utf-8")
    (target / "SKILL.md").write_text("# Custom\n", encoding="utf-8")

    setup_cli._symlink_codex_home_skills(str(workspace))

    assert not target.is_symlink()
    assert (target / "SKILL.md").read_text(encoding="utf-8") == "# Custom\n"


def test_ensure_codex_home_config_creates_config(tmp_path, monkeypatch) -> None:
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
        'model = "gpt-5.5"\n'
        "\n"
        "[mcp_servers.super-agents]\n"
        f"command = {json.dumps(str(command))}\n"
    )


def test_ensure_codex_home_config_replaces_stale_values(tmp_path, monkeypatch) -> None:
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
    assert '[projects."/Users/gabemontague"]\ntrust_level = "trusted"' in updated
    assert f"command = {json.dumps(str(command))}" in updated
    assert '[mcp_servers.playwright]\ncommand = "npx"' in updated


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
        'model = "gpt-5.5"\n'
        "\n"
        "[mcp_servers.super-agents]\n"
        f"command = {json.dumps(str(uv_bin))}\n"
        f"args = {json.dumps(['--directory', str(cli_dir), 'run', 'super-agents-mcp'])}\n"
    )


def test_ensure_claude_config_installs_super_agents_mcp(tmp_path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    command = workspace / ".venv" / "bin" / "super-agents-mcp"
    dispatcher_config = tmp_path / "dispatcher-config.json"
    _codex_home, claude_config = _patch_openbase_agent_paths(monkeypatch, tmp_path)
    claude_json = claude_config / ".claude.json"
    command.parent.mkdir(parents=True)
    command.write_text("#!/bin/sh\n", encoding="utf-8")
    claude_json.parent.mkdir(parents=True)
    claude_json.write_text(
        json.dumps(
            {
                "firstStartTime": "2026-06-18T00:00:00.000Z",
                "mcpServers": {"playwright": {"command": "npx"}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(setup_cli, "OPENBASE_CLAUDE_JSON_PATH", claude_json)
    monkeypatch.setattr(setup_cli, "CODEX_DISPATCHER_CONFIG_PATH", dispatcher_config)

    setup_cli._ensure_claude_config(str(workspace))

    payload = json.loads(claude_json.read_text(encoding="utf-8"))
    assert payload["firstStartTime"] == "2026-06-18T00:00:00.000Z"
    assert payload["mcpServers"]["playwright"] == {"command": "npx"}
    assert payload["mcpServers"]["super-agents"] == {
        "type": "stdio",
        "command": str(command),
        "env": {
            "CLAUDE_CONFIG_DIR": str(claude_config),
            "SUPER_AGENTS_DEFAULT_CONFIG_PATH": str(dispatcher_config),
            "CODEX_SUPER_AGENT_INSTRUCTIONS_PATH": str(
                setup_cli.CODEX_SUPER_AGENT_INSTRUCTIONS_PATH
            ),
        },
    }
    settings = json.loads((claude_config / "settings.json").read_text(encoding="utf-8"))
    assert settings["permissions"]["defaultMode"] == "bypassPermissions"
    assert settings["skipDangerousModePermissionPrompt"] is True
    assert settings["skipAutoPermissionPrompt"] is True
    assert settings["claudeMdExcludes"] == [
        str(setup_cli.NORMAL_CLAUDE_CONFIG_DIR / "CLAUDE.md")
    ]


def test_ensure_claude_settings_seeds_from_normal_claude_settings(
    tmp_path,
    monkeypatch,
) -> None:
    _codex_home, claude_config = _patch_openbase_agent_paths(monkeypatch, tmp_path)
    normal_settings = setup_cli.NORMAL_CLAUDE_SETTINGS_PATH
    normal_settings.parent.mkdir(parents=True)
    normal_settings.write_text(
        json.dumps(
            {
                "model": "sonnet",
                "theme": "light",
                "permissions": {
                    "allow": ["Bash(git status:*)"],
                    "deny": [],
                    "defaultMode": "auto",
                },
                "skipDangerousModePermissionPrompt": False,
                "skipAutoPermissionPrompt": False,
                "claudeMdExcludes": ["/tmp/other-team/CLAUDE.md"],
            }
        ),
        encoding="utf-8",
    )

    setup_cli._ensure_claude_settings()

    settings = json.loads((claude_config / "settings.json").read_text(encoding="utf-8"))
    assert settings["model"] == "sonnet"
    assert settings["theme"] == "light"
    assert settings["permissions"] == {
        "allow": ["Bash(git status:*)"],
        "deny": [],
        "defaultMode": "bypassPermissions",
    }
    assert settings["skipDangerousModePermissionPrompt"] is True
    assert settings["skipAutoPermissionPrompt"] is True
    assert settings["claudeMdExcludes"] == [
        "/tmp/other-team/CLAUDE.md",
        str(setup_cli.NORMAL_CLAUDE_CONFIG_DIR / "CLAUDE.md"),
    ]


def test_ensure_claude_auth_bridge_runs_login_when_requested(monkeypatch) -> None:
    statuses = iter(
        [
            claude_auth.ClaudeAuthStatus(
                logged_in=False, raw_output="{}", returncode=0
            ),
            claude_auth.ClaudeAuthStatus(
                logged_in=False, raw_output="{}", returncode=0
            ),
            claude_auth.ClaudeAuthStatus(logged_in=True, raw_output="{}", returncode=0),
        ]
    )
    login_calls = []
    monkeypatch.setattr(setup_cli, "claude_auth_status", lambda: next(statuses))
    monkeypatch.setattr(
        setup_cli,
        "sync_normal_claude_state",
        lambda: claude_auth.ClaudeAuthBridgeResult(
            state_updated=False,
            message="already synced",
        ),
    )
    monkeypatch.setattr(
        setup_cli,
        "run_claude_login",
        lambda: login_calls.append(True) or 0,
    )

    setup_cli._ensure_claude_auth_bridge(login_if_needed=True)

    assert login_calls == [True]


def test_ensure_claude_auth_bridge_does_not_login_unless_requested(monkeypatch) -> None:
    login_calls = []
    monkeypatch.setattr(
        setup_cli,
        "claude_auth_status",
        lambda: claude_auth.ClaudeAuthStatus(
            logged_in=False,
            raw_output="{}",
            returncode=0,
        ),
    )
    monkeypatch.setattr(
        setup_cli,
        "sync_normal_claude_state",
        lambda: claude_auth.ClaudeAuthBridgeResult(
            state_updated=False,
            message="already synced",
        ),
    )
    monkeypatch.setattr(
        setup_cli,
        "run_claude_login",
        lambda: login_calls.append(True) or 0,
    )

    setup_cli._ensure_claude_auth_bridge(login_if_needed=False)

    assert login_calls == []


def test_selected_coding_backend_reads_existing_env(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("OPENBASE_CODING_BACKEND=claude_code\n", encoding="utf-8")

    assert setup_cli._selected_coding_backend(env_file, None) == "claude_code"


def test_ensure_codex_home_config_can_link_normal_codex_config(
    tmp_path, monkeypatch
) -> None:
    workspace = tmp_path / "custom-workspace"
    command = workspace / "cli" / ".venv" / "bin" / "super-agents-mcp"
    codex_home = tmp_path / "openbase" / "codex_home"
    normal_config = tmp_path / "codex" / "config.toml"
    command.parent.mkdir(parents=True)
    command.write_text("#!/bin/sh\n", encoding="utf-8")
    normal_config.parent.mkdir(parents=True)
    normal_config.write_text(
        "\n".join(
            [
                '[projects."/repo"]',
                'trust_level = "trusted"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(setup_cli, "CODEX_HOME_DIR", codex_home)
    monkeypatch.setattr(setup_cli, "NORMAL_CODEX_CONFIG_PATH", normal_config)

    setup_cli._ensure_codex_home_config(
        str(workspace),
        link_codex_config=True,
    )

    service_config = codex_home / "config.toml"
    updated = normal_config.read_text(encoding="utf-8")
    assert service_config.is_symlink()
    assert service_config.resolve() == normal_config.resolve()
    assert service_config.read_text(encoding="utf-8") == updated
    assert f"command = {json.dumps(str(command))}" in updated
    assert '[projects."/repo"]\ntrust_level = "trusted"' in updated


def test_symlink_codex_home_config_preserves_existing_service_config(
    tmp_path, monkeypatch
) -> None:
    codex_home = tmp_path / "openbase" / "codex_home"
    service_config = codex_home / "config.toml"
    normal_config = tmp_path / "codex" / "config.toml"
    service_config.parent.mkdir(parents=True)
    service_config.write_text('sandbox_mode = "danger-full-access"\n', encoding="utf-8")
    monkeypatch.setattr(setup_cli, "CODEX_HOME_DIR", codex_home)
    monkeypatch.setattr(setup_cli, "NORMAL_CODEX_CONFIG_PATH", normal_config)

    setup_cli._symlink_codex_home_config()

    assert service_config.is_symlink()
    assert service_config.resolve() == normal_config.resolve()
    assert normal_config.read_text(encoding="utf-8") == (
        'sandbox_mode = "danger-full-access"\n'
    )


def test_ensure_env_file_documents_coding_backend_default(tmp_path) -> None:
    env_file = tmp_path / ".env"

    setup_cli._ensure_env_file(
        str(env_file),
        assembly_ai_api_key="",
        cartesia_api_key="",
    )

    content = env_file.read_text(encoding="utf-8")
    assert "OPENBASE_CODING_BACKEND=codex" in content
    assert "# OPENBASE_CODEX_BACKEND is still read as a fallback" in content
    assert "# Claude Code applies to Super Agents UI-driver sessions" in content
    assert "CODEX_CLAUDE_" not in content
    assert "SUPER_AGENTS_CLAUDE_TUI_CMD" not in content
    assert "CLAUDE_CONFIG_DIR=" in content
    assert "SUPER_AGENTS_DEFAULT_CONFIG_PATH=" in content
    assert "CODEX_MODEL=" not in content


def test_ensure_env_file_can_select_backend(tmp_path) -> None:
    env_file = tmp_path / ".env"

    setup_cli._ensure_env_file(
        str(env_file),
        assembly_ai_api_key="",
        cartesia_api_key="",
        coding_backend="openbase-cloud",
    )

    assert "OPENBASE_CODING_BACKEND=openbase_cloud" in env_file.read_text(
        encoding="utf-8"
    )


def test_ensure_openbase_cloud_machine_token_uses_env_backend_url(
    tmp_path,
    monkeypatch,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "OPENBASE_CODER_CLI_WEB_BACKEND_URL=https://backend.example\n",
        encoding="utf-8",
    )
    calls = []

    class FakeTokenManager:
        def __init__(self, web_backend_url):
            self.web_backend_url = web_backend_url
            self.has_refresh_token = True

    class FakeMachineTokenManager:
        def __init__(self, web_backend_url, token_manager):
            calls.append((web_backend_url, token_manager.web_backend_url))

        def get_machine_token(self):
            calls.append("minted")
            return "obmt_token"

    monkeypatch.setattr(setup_cli, "TokenManager", FakeTokenManager)
    monkeypatch.setattr(setup_cli, "MachineTokenManager", FakeMachineTokenManager)

    setup_cli._ensure_openbase_cloud_machine_token(env_file)

    assert calls == [("https://backend.example", "https://backend.example"), "minted"]


def test_ensure_env_file_updates_existing_backend_only_when_requested(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("KEEP_ME=1\nOPENBASE_CODEX_BACKEND=codex\n", encoding="utf-8")

    setup_cli._ensure_env_file(
        str(env_file),
        assembly_ai_api_key="",
        cartesia_api_key="",
    )
    assert "OPENBASE_CODEX_BACKEND=codex" in env_file.read_text(encoding="utf-8")

    setup_cli._ensure_env_file(
        str(env_file),
        assembly_ai_api_key="",
        cartesia_api_key="",
        coding_backend="claude-code",
    )

    content = env_file.read_text(encoding="utf-8")
    assert "KEEP_ME=1" in content
    assert "OPENBASE_CODEX_BACKEND=codex" in content
    assert "OPENBASE_CODING_BACKEND=claude_code" in content


def test_ensure_thread_sync_exchange_dir_creates_syncthing_files(
    tmp_path, monkeypatch
) -> None:
    openbase_dir = tmp_path / "openbase"
    global_ignore = tmp_path / "syncthing" / "global.stignore"
    monkeypatch.setattr(setup_cli, "OPENBASE_BASE_DIR", openbase_dir)
    monkeypatch.setattr(
        setup_cli,
        "_syncthing_global_ignore_path",
        lambda: global_ignore,
    )

    setup_cli._ensure_thread_sync_exchange_dir()

    exchange_dir = openbase_dir / "thread-sync"
    assert exchange_dir.is_dir()
    assert (
        exchange_dir / ".stfolder" / setup_cli.THREAD_SYNC_MARKER_FILE_NAME
    ).is_file()
    assert (exchange_dir / ".stignore").read_text(encoding="utf-8") == (
        "#include .stglobalignore\n"
    )
    assert global_ignore.read_text(encoding="utf-8") == "(?d).DS_Store\n"
    assert (exchange_dir / ".stglobalignore").is_symlink()
    assert (exchange_dir / ".stglobalignore").resolve() == global_ignore.resolve()


def test_ensure_thread_sync_exchange_dir_replaces_stale_global_ignore_symlink(
    tmp_path, monkeypatch
) -> None:
    openbase_dir = tmp_path / "openbase"
    exchange_dir = openbase_dir / "thread-sync"
    stale_global_ignore = tmp_path / "stale" / "global.stignore"
    global_ignore = tmp_path / "syncthing" / "global.stignore"
    exchange_dir.mkdir(parents=True)
    stale_global_ignore.parent.mkdir()
    stale_global_ignore.write_text("stale\n", encoding="utf-8")
    (exchange_dir / ".stglobalignore").symlink_to(stale_global_ignore)
    monkeypatch.setattr(setup_cli, "OPENBASE_BASE_DIR", openbase_dir)
    monkeypatch.setattr(
        setup_cli,
        "_syncthing_global_ignore_path",
        lambda: global_ignore,
    )

    setup_cli._ensure_thread_sync_exchange_dir()

    assert (exchange_dir / ".stglobalignore").resolve() == global_ignore.resolve()


def test_ensure_bundled_sounds_installs_wilhelm(tmp_path, monkeypatch) -> None:
    sounds_dir = tmp_path / "sounds"
    monkeypatch.setattr(setup_cli, "OPENBASE_SOUNDS_DIR", sounds_dir)

    setup_cli._ensure_bundled_sounds()

    target = sounds_dir / "wilhelm.wav"
    assert target.is_file()
    assert target.read_bytes().startswith(b"RIFF")


def test_ensure_bundled_sounds_preserves_custom_existing_file(
    tmp_path, monkeypatch
) -> None:
    sounds_dir = tmp_path / "sounds"
    target = sounds_dir / "wilhelm.wav"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"custom sound")
    monkeypatch.setattr(setup_cli, "OPENBASE_SOUNDS_DIR", sounds_dir)

    setup_cli._ensure_bundled_sounds()

    assert target.read_bytes() == b"custom sound"


def test_setup_configures_tailscale_serve(tmp_path, monkeypatch) -> None:
    calls = []
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    env_file = tmp_path / ".env"

    monkeypatch.setattr(setup_cli, "_clone_workspace", lambda _workspace_dir: None)
    monkeypatch.setattr(
        setup_cli,
        "_ensure_thread_sync_exchange_dir",
        lambda: calls.append("thread-sync"),
    )
    monkeypatch.setattr(
        setup_cli, "_ensure_bundled_sounds", lambda: calls.append("sounds")
    )
    monkeypatch.setattr(setup_cli, "_ensure_env_file", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(setup_cli, "_symlink_codex_auth", lambda: None)
    monkeypatch.setattr(
        setup_cli,
        "_ensure_codex_home_default_files",
        lambda _workspace_dir: None,
    )
    monkeypatch.setattr(
        setup_cli, "_ensure_codex_home_dispatcher_config", lambda **_kwargs: None
    )
    monkeypatch.setattr(setup_cli, "_download_local_audio_models", lambda: None)
    monkeypatch.setattr(
        setup_cli, "_symlink_codex_home_skills", lambda _workspace_dir: None
    )
    monkeypatch.setattr(setup_cli, "_init_cli_workspace", lambda _workspace_dir: None)
    monkeypatch.setattr(
        setup_cli, "_ensure_codex_home_config", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(setup_cli, "_ensure_claude_config", lambda _workspace_dir: None)
    monkeypatch.setattr(setup_cli, "_install_cli_shim", lambda _workspace_dir: None)
    monkeypatch.setattr(setup_cli, "_build_console", lambda _workspace_dir: None)
    monkeypatch.setattr(setup_cli, "install_all_services", lambda _config: None)
    monkeypatch.setattr(
        setup_cli.InstallationConfig,
        "save",
        lambda self: None,
    )

    def fake_configure_tailscale_serve():
        calls.append("configure")

    monkeypatch.setattr(
        setup_cli,
        "configure_tailscale_serve",
        fake_configure_tailscale_serve,
    )
    monkeypatch.setattr(
        setup_cli,
        "tailscale_serve_health",
        lambda: type(
            "Health",
            (),
            {
                "healthy": True,
                "openbase_url": "http://mac.tailnet.ts.net:18080",
                "error": None,
            },
        )(),
    )

    runner = CliRunner()
    result = runner.invoke(
        setup_cli.setup,
        [
            "--workspace-dir",
            str(workspace),
            "--env-file",
            str(env_file),
            "--backend",
            "claude-code",
            "--skip-clone",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls == ["thread-sync", "sounds", "configure"]


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
    monkeypatch.setattr(
        setup_cli, "load_registry", fail_if_plugin_registry_is_loaded, raising=False
    )

    setup_cli._build_console(str(workspace))

    assert commands == [
        (workspace, console_dir, ("install",)),
        (workspace, console_dir, ("run", "build")),
    ]
    assert not generated_registry.exists()
