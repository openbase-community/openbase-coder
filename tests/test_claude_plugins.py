from __future__ import annotations

import json
from pathlib import Path

from openbase_coder_cli import claude_plugins


def _configure_managed_config(monkeypatch, tmp_path: Path) -> Path:
    config_path = tmp_path / "claude_config" / ".claude.json"
    monkeypatch.setattr(claude_plugins, "OPENBASE_CLAUDE_JSON_PATH", config_path)
    return config_path


def test_enable_adds_entry_and_preserves_other_servers(
    monkeypatch, tmp_path: Path
) -> None:
    config_path = _configure_managed_config(monkeypatch, tmp_path)
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        json.dumps(
            {
                "mcpServers": {"super-agents": {"type": "stdio", "command": "x"}},
                "other": True,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        claude_plugins,
        "openbase_coder_command_path",
        lambda: Path("/opt/openbase/bin/openbase-coder"),
    )

    assert claude_plugins.computer_use_enabled() is False
    assert claude_plugins.set_computer_use_enabled(True) is True
    assert claude_plugins.computer_use_enabled() is True

    payload = json.loads(config_path.read_text(encoding="utf-8"))
    assert payload["other"] is True
    assert payload["mcpServers"]["super-agents"] == {
        "type": "stdio",
        "command": "x",
    }
    assert payload["mcpServers"]["openbase-computer-use"] == {
        "type": "stdio",
        "command": "/opt/openbase/bin/openbase-coder",
        "args": ["claude", "computer-use-mcp"],
    }

    # Re-enabling with an identical entry is a no-op.
    assert claude_plugins.set_computer_use_enabled(True) is False


def test_disable_removes_entry(monkeypatch, tmp_path: Path) -> None:
    config_path = _configure_managed_config(monkeypatch, tmp_path)
    monkeypatch.setattr(
        claude_plugins,
        "openbase_coder_command_path",
        lambda: Path("/opt/openbase/bin/openbase-coder"),
    )

    assert claude_plugins.set_computer_use_enabled(False) is False
    assert claude_plugins.set_computer_use_enabled(True) is True
    assert claude_plugins.set_computer_use_enabled(False) is True
    assert claude_plugins.computer_use_enabled() is False

    payload = json.loads(config_path.read_text(encoding="utf-8"))
    assert payload["mcpServers"] == {}


def test_enable_creates_missing_config_file(monkeypatch, tmp_path: Path) -> None:
    config_path = _configure_managed_config(monkeypatch, tmp_path)
    monkeypatch.setattr(
        claude_plugins,
        "openbase_coder_command_path",
        lambda: Path("/opt/openbase/bin/openbase-coder"),
    )

    assert claude_plugins.set_computer_use_enabled(True) is True
    assert config_path.is_file()
    mode = config_path.stat().st_mode & 0o777
    assert mode == 0o600
