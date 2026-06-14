from __future__ import annotations

import importlib

import click
from click.testing import CliRunner

codex_home_instructions = importlib.import_module(
    "openbase_coder_cli.codex_home_instructions"
)
main_cli = importlib.import_module("openbase_coder_cli.cli")


def test_ensure_openbase_agents_md_preserves_user_h2_sections(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    source = workspace / "instructions" / "AGENTS.md"
    codex_home = tmp_path / "codex_home"
    agents = codex_home / "AGENTS.md"
    source.parent.mkdir(parents=True)
    agents.parent.mkdir(parents=True)
    source.write_text("- New repo rule\n", encoding="utf-8")
    agents.write_text(
        "# Personal instructions\n\n"
        "- Keep this custom top-level note.\n\n"
        "## Openbase Coder Instructions\n\n"
        "- Old generated note.\n"
        "- Old repo rule.\n\n"
        "## My Project Notes\n\n"
        "- Keep this project note.\n",
        encoding="utf-8",
    )

    changed = codex_home_instructions.ensure_openbase_agents_md(
        workspace,
        codex_home_dir=codex_home,
    )

    assert changed is True
    assert agents.read_text(encoding="utf-8") == (
        "# Personal instructions\n\n"
        "- Keep this custom top-level note.\n\n"
        "## Openbase Coder Instructions\n\n"
        f"- These instructions are auto generated from {source}.\n\n"
        "- New repo rule\n"
        "\n"
        "## My Project Notes\n\n"
        "- Keep this project note.\n"
    )


def test_ensure_openbase_agents_md_demotes_generated_h2s(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    source = workspace / "instructions" / "AGENTS.md"
    codex_home = tmp_path / "codex_home"
    source.parent.mkdir(parents=True)
    source.write_text("## Repo Section\n\n- Standard rule\n", encoding="utf-8")

    codex_home_instructions.ensure_openbase_agents_md(
        workspace,
        codex_home_dir=codex_home,
    )

    content = (codex_home / "AGENTS.md").read_text(encoding="utf-8")
    assert "## Repo Section" not in content.splitlines()
    assert "### Repo Section" in content.splitlines()


def test_refresh_openbase_agents_md_from_installation_uses_saved_workspace(
    tmp_path, monkeypatch
) -> None:
    workspace = tmp_path / "workspace"
    source = workspace / "instructions" / "AGENTS.md"
    codex_home = tmp_path / "codex_home"
    source.parent.mkdir(parents=True)
    source.write_text("- Standard rule\n", encoding="utf-8")

    class FakeInstallationConfig:
        @classmethod
        def exists(cls) -> bool:
            return True

        @classmethod
        def load(cls):
            return cls()

        workspace_path = str(workspace)

    monkeypatch.setattr(
        codex_home_instructions,
        "InstallationConfig",
        FakeInstallationConfig,
    )
    monkeypatch.setattr(codex_home_instructions, "CODEX_HOME_DIR", codex_home)

    assert codex_home_instructions.refresh_openbase_agents_md_from_installation()
    assert (codex_home / "AGENTS.md").read_text(encoding="utf-8") == (
        "## Openbase Coder Instructions\n\n"
        f"- These instructions are auto generated from {source}.\n\n"
        "- Standard rule\n"
    )


def test_cli_launch_refreshes_openbase_agents_md(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        main_cli,
        "refresh_openbase_agents_md_from_installation",
        lambda: calls.append("refresh"),
    )

    @click.command("noop-refresh-test")
    def noop_refresh_test() -> None:
        click.echo("ok")

    main_cli.main.add_command(noop_refresh_test)
    try:
        result = CliRunner().invoke(main_cli.main, ["noop-refresh-test"])
    finally:
        del main_cli.main.commands["noop-refresh-test"]

    assert result.exit_code == 0
    assert calls == ["refresh"]
