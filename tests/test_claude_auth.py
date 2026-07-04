from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path

from click.testing import CliRunner

from openbase_coder_cli import claude_auth

claude_cli = importlib.import_module("openbase_coder_cli.cli.claude")


def test_openbase_claude_keychain_service_uses_config_dir_hash(tmp_path: Path) -> None:
    config_dir = tmp_path / "claude_config"
    expected = hashlib.sha256(str(config_dir).encode("utf-8")).hexdigest()[:8]

    assert (
        claude_auth.openbase_claude_keychain_service(config_dir)
        == f"Claude Code-credentials-{expected}"
    )


def test_sync_normal_claude_state_merges_into_config_dir_state(tmp_path) -> None:
    normal_state = tmp_path / ".claude.json"
    openbase_state = tmp_path / "openbase" / "claude_config" / ".claude.json"
    normal_state.write_text(
        json.dumps(
            {
                "oauthAccount": {"emailAddress": "test@example.com"},
                "hasCompletedOnboarding": True,
                "mcpServers": {"normal": {"command": "normal"}},
            }
        ),
        encoding="utf-8",
    )
    openbase_state.parent.mkdir(parents=True)
    openbase_state.write_text(
        json.dumps(
            {
                "machineID": "openbase-machine",
                "mcpServers": {"super-agents": {"command": "super-agents-mcp"}},
            }
        ),
        encoding="utf-8",
    )

    result = claude_auth.sync_normal_claude_state(
        normal_state_path=normal_state,
        openbase_state_path=openbase_state,
    )

    assert result.state_updated is True
    payload = json.loads(openbase_state.read_text(encoding="utf-8"))
    assert payload["oauthAccount"] == {"emailAddress": "test@example.com"}
    assert payload["hasCompletedOnboarding"] is True
    # Existing Openbase values win; mcpServers are unioned.
    assert payload["machineID"] == "openbase-machine"
    assert payload["mcpServers"] == {
        "normal": {"command": "normal"},
        "super-agents": {"command": "super-agents-mcp"},
    }


def test_claude_status_guides_login_when_not_authenticated(monkeypatch) -> None:
    monkeypatch.setattr(
        claude_cli,
        "claude_auth_status",
        lambda: claude_auth.ClaudeAuthStatus(
            logged_in=False,
            raw_output='{"loggedIn": false}',
            returncode=0,
        ),
    )

    result = CliRunner().invoke(claude_cli.claude, ["status"])

    assert result.exit_code != 0
    assert "openbase-coder claude login" in result.output
