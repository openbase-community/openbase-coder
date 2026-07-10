from __future__ import annotations

import pytest

from openbase_coder_cli import super_agents_backend


def test_client_from_environment_falls_back_to_codex_app_server(monkeypatch) -> None:
    monkeypatch.setenv("OPENBASE_CODING_BACKEND", "codex")

    client = super_agents_backend.client_from_environment()

    assert getattr(client, "backend", None) == "codex"
    assert callable(getattr(client, "start_thread", None))
    assert callable(getattr(client, "start_turn", None))
    assert callable(getattr(client, "progress_by_label", None))


def test_client_from_environment_reports_missing_claude_backend(monkeypatch) -> None:
    monkeypatch.setenv("OPENBASE_CODING_BACKEND", "claude_code")

    with pytest.raises(RuntimeError, match="does not include Claude Code backend"):
        super_agents_backend.client_from_environment()
