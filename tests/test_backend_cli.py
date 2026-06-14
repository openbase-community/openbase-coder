from __future__ import annotations

from click.testing import CliRunner

from openbase_coder_cli.cli import main


def test_backend_status_defaults_when_env_file_missing(tmp_path) -> None:
    env_file = tmp_path / ".env"
    result = CliRunner().invoke(
        main, ["backend", "status", "--env-file", str(env_file)]
    )

    assert result.exit_code == 0
    assert "Backend: codex" in result.output
    assert "missing" in result.output


def test_backend_use_writes_canonical_backend_and_preserves_file(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("KEEP_ME=1\nOPENBASE_CODEX_BACKEND=codex\n", encoding="utf-8")

    result = CliRunner().invoke(
        main, ["backend", "use", "claude-code", "--env-file", str(env_file)]
    )

    assert result.exit_code == 0
    assert "Backend set to claude-agent-sdk" in result.output
    content = env_file.read_text(encoding="utf-8")
    assert "KEEP_ME=1" in content
    assert "OPENBASE_CODING_BACKEND=claude-agent-sdk" in content
    assert "OPENBASE_CODEX_BACKEND=codex" in content


def test_backend_use_creates_env_file(tmp_path) -> None:
    env_file = tmp_path / "nested" / ".env"

    result = CliRunner().invoke(
        main, ["backend", "use", "claude-tui", "--env-file", str(env_file)]
    )

    assert result.exit_code == 0
    assert (
        env_file.read_text(encoding="utf-8") == "OPENBASE_CODING_BACKEND=claude-tui\n"
    )


def test_backend_status_reports_unsupported_value(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("OPENBASE_CODING_BACKEND=surprise\n", encoding="utf-8")

    result = CliRunner().invoke(
        main, ["backend", "status", "--env-file", str(env_file)]
    )

    assert result.exit_code == 0
    assert "Backend: unsupported:surprise" in result.output


def test_backend_status_reads_legacy_env_key(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("OPENBASE_CODEX_BACKEND=claude-tui\n", encoding="utf-8")

    result = CliRunner().invoke(
        main, ["backend", "status", "--env-file", str(env_file)]
    )

    assert result.exit_code == 0
    assert "Backend: claude-tui" in result.output


def test_backend_list_shows_supported_values() -> None:
    result = CliRunner().invoke(main, ["backend", "list"])

    assert result.exit_code == 0
    assert "codex (default)" in result.output
    assert "claude-agent-sdk" in result.output
    assert "claude-tui" in result.output
    assert "proxy" not in result.output


def test_backend_use_rejects_unsupported_backend(tmp_path) -> None:
    env_file = tmp_path / ".env"

    result = CliRunner().invoke(
        main, ["backend", "use", "claude-code-proxy", "--env-file", str(env_file)]
    )

    assert result.exit_code != 0
    assert "Unsupported backend" in result.output
    assert not env_file.exists()
