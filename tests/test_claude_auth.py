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
        "verified_claude_auth_status",
        lambda: claude_auth.ClaudeAuthStatus(
            logged_in=False,
            raw_output='{"loggedIn": false}',
            returncode=0,
        ),
    )

    result = CliRunner().invoke(claude_cli.claude, ["status"])

    assert result.exit_code != 0
    assert "openbase-coder claude login" in result.output


def test_is_claude_auth_failure_text_matches_turn_failures() -> None:
    assert claude_auth.is_claude_auth_failure_text(
        "Failed to authenticate. API Error: 401 Invalid bearer token"
    )
    assert claude_auth.is_claude_auth_failure_text(
        "Failed to authenticate: OAuth session expired and could not be refreshed"
    )
    assert not claude_auth.is_claude_auth_failure_text("")
    assert not claude_auth.is_claude_auth_failure_text(None)
    assert not claude_auth.is_claude_auth_failure_text(
        "The tests failed to authenticate against the staging backend."
    )


def _status(logged_in: bool, output: str = "") -> claude_auth.ClaudeAuthStatus:
    return claude_auth.ClaudeAuthStatus(
        logged_in=logged_in, raw_output=output, returncode=0
    )


def test_verified_status_trusts_unexpired_credentials(monkeypatch) -> None:
    monkeypatch.setattr(
        claude_auth, "claude_auth_status", lambda **_: _status(True, "cached")
    )
    monkeypatch.setattr(
        claude_auth,
        "read_openbase_claude_credential_expiry",
        lambda *_: (claude_auth.time.time() + 3600) * 1000,
    )

    def _no_probe(**_kwargs):
        raise AssertionError("probe must not run for unexpired credentials")

    monkeypatch.setattr(claude_auth, "probe_claude_auth", _no_probe)

    assert claude_auth.verified_claude_auth_status().logged_in is True


def test_verified_status_reports_logout_when_expired_probe_fails(monkeypatch) -> None:
    failure = "Failed to authenticate: OAuth session expired and could not be refreshed"
    monkeypatch.setattr(
        claude_auth, "claude_auth_status", lambda **_: _status(True, "cached")
    )
    monkeypatch.setattr(
        claude_auth, "read_openbase_claude_credential_expiry", lambda *_: 1.0
    )
    monkeypatch.setattr(
        claude_auth, "probe_claude_auth", lambda **_: _status(False, failure)
    )

    result = claude_auth.verified_claude_auth_status()

    assert result.logged_in is False
    assert result.raw_output == failure


def test_verified_status_keeps_login_when_probe_refreshes(monkeypatch) -> None:
    monkeypatch.setattr(
        claude_auth, "claude_auth_status", lambda **_: _status(True, "cached")
    )
    monkeypatch.setattr(
        claude_auth, "read_openbase_claude_credential_expiry", lambda *_: 1.0
    )
    monkeypatch.setattr(
        claude_auth, "probe_claude_auth", lambda **_: _status(True, "ok")
    )

    result = claude_auth.verified_claude_auth_status()

    assert result.logged_in is True
    assert result.raw_output == "cached"


def test_read_credential_expiry_from_credentials_file(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(claude_auth.platform, "system", lambda: "Linux")
    config_dir = tmp_path / "claude_config"
    config_dir.mkdir()
    (config_dir / ".credentials.json").write_text(
        json.dumps({"claudeAiOauth": {"expiresAt": 1752000000000}}),
        encoding="utf-8",
    )

    assert (
        claude_auth.read_openbase_claude_credential_expiry(config_dir) == 1752000000000
    )
    assert (
        claude_auth.read_openbase_claude_credential_expiry(tmp_path / "missing") is None
    )


def test_heal_claude_auth_bridges_and_probes(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        claude_auth,
        "sync_normal_claude_state",
        lambda: calls.append("sync")
        or claude_auth.ClaudeAuthBridgeResult(True, "synced"),
    )
    monkeypatch.setattr(
        claude_auth,
        "copy_normal_claude_keychain",
        lambda **_: calls.append("copy") or True,
    )
    monkeypatch.setattr(
        claude_auth, "probe_claude_auth", lambda **_: _status(True, "ok")
    )

    result = claude_auth.heal_claude_auth()

    assert result.state_updated is True
    assert calls == ["sync", "copy"]


def test_heal_claude_auth_reports_missing_normal_login(monkeypatch) -> None:
    monkeypatch.setattr(
        claude_auth,
        "sync_normal_claude_state",
        lambda: claude_auth.ClaudeAuthBridgeResult(False, "no state"),
    )
    monkeypatch.setattr(claude_auth, "copy_normal_claude_keychain", lambda **_: False)

    def _no_probe(**_kwargs):
        raise AssertionError("probe must not run without a bridged credential")

    monkeypatch.setattr(claude_auth, "probe_claude_auth", _no_probe)

    result = claude_auth.heal_claude_auth()

    assert result.state_updated is False
