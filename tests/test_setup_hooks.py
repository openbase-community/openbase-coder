from __future__ import annotations

from pathlib import Path

from openbase_coder_cli.cli.setup import hooks
from openbase_coder_cli.paths import INJECT_SESSION_ID_HOOK_PATH


def test_trusted_hash_matches_codex_fingerprint() -> None:
    # Known-answer test against codex's normalized hook trust hash
    # (codex-rs/config/src/fingerprint.rs): this is the [hooks.state] value
    # codex 0.144.1 records for the Warp plugin's SessionStart hook. If this
    # breaks after a codex upgrade, the fingerprint scheme changed and
    # session_start_hook_trusted_hash must be updated to match.
    assert hooks.session_start_hook_trusted_hash(
        "${PLUGIN_ROOT}/scripts/on-session-start.sh"
    ) == ("sha256:91587043033e7831d4d154fdef2e495f3113c3552a4529d8013f5546ffb2c140")


def test_merge_claude_hooks_adds_entry_and_preserves_existing() -> None:
    existing = {
        "PostToolUse": [
            {"matcher": "Edit", "hooks": [{"type": "command", "command": "x"}]}
        ],
        "SessionStart": [
            {"matcher": "", "hooks": [{"type": "command", "command": "other.sh"}]}
        ],
    }

    merged = hooks.merge_session_id_hook_into_claude_hooks(existing)

    assert merged["PostToolUse"] == existing["PostToolUse"]
    session_start = merged["SessionStart"]
    assert len(session_start) == 2
    assert session_start[0]["hooks"][0]["command"] == "other.sh"
    assert session_start[1]["hooks"][0]["command"] == str(INJECT_SESSION_ID_HOOK_PATH)


def test_merge_claude_hooks_is_idempotent() -> None:
    once = hooks.merge_session_id_hook_into_claude_hooks(None)
    twice = hooks.merge_session_id_hook_into_claude_hooks(once)
    assert twice == once
    assert len(twice["SessionStart"]) == 1


def test_ensure_codex_session_id_hook_appends_and_preserves(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        'sandbox_mode = "danger-full-access"\n'
        "\n"
        "[mcp_servers.super-agents]\n"
        'command = "/bin/super-agents-mcp"\n'
        "\n"
        '[hooks.state."warp@codex-warp:hooks/hooks.json:session_start:0:0"]\n'
        'trusted_hash = "sha256:unrelated"\n',
        encoding="utf-8",
    )

    assert hooks.ensure_codex_session_id_hook(config) is True
    text = config.read_text(encoding="utf-8")

    assert 'sandbox_mode = "danger-full-access"' in text
    assert "[mcp_servers.super-agents]" in text
    assert 'trusted_hash = "sha256:unrelated"' in text
    assert "[[hooks.SessionStart]]" in text
    assert f'command = "{INJECT_SESSION_ID_HOOK_PATH}"' in text
    state_key = f"{config.parent.resolve() / config.name}:session_start:0:0"
    assert f'[hooks.state."{state_key}"]' in text
    assert "enabled = true" in text


def test_ensure_codex_session_id_hook_is_idempotent(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text('model = "openbase-codex"\n', encoding="utf-8")

    assert hooks.ensure_codex_session_id_hook(config) is True
    first = config.read_text(encoding="utf-8")
    assert hooks.ensure_codex_session_id_hook(config) is False
    assert config.read_text(encoding="utf-8") == first
    assert first.count("[[hooks.SessionStart]]") == 1


def test_ensure_codex_session_id_hook_replaces_stale_block(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    state_key = f"{config.parent.resolve() / config.name}:session_start:0:0"
    config.write_text(
        "[[hooks.SessionStart]]\n"
        "\n"
        "[[hooks.SessionStart.hooks]]\n"
        'type = "command"\n'
        'command = "/old/path.sh"\n'
        "\n"
        f'[hooks.state."{state_key}"]\n'
        'trusted_hash = "sha256:stale"\n'
        "enabled = true\n",
        encoding="utf-8",
    )

    assert hooks.ensure_codex_session_id_hook(config) is True
    text = config.read_text(encoding="utf-8")

    assert "/old/path.sh" not in text
    assert "sha256:stale" not in text
    assert text.count("[[hooks.SessionStart]]") == 1
    assert text.count(f'[hooks.state."{state_key}"]') == 1
