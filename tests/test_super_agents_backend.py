from __future__ import annotations

import pytest

from openbase_coder_cli import super_agents_backend


def test_compat_client_from_environment_uses_codex_app_server(monkeypatch) -> None:
    monkeypatch.setenv("OPENBASE_CODING_BACKEND", "codex")

    client = super_agents_backend._compat_client_from_environment()

    assert getattr(client, "backend", None) == "codex"
    assert callable(getattr(client, "start_thread", None))
    assert callable(getattr(client, "start_turn", None))
    assert callable(getattr(client, "progress_by_label", None))


def test_compat_client_reports_missing_claude_backend(monkeypatch) -> None:
    monkeypatch.setenv("OPENBASE_CODING_BACKEND", "claude_code")

    with pytest.raises(RuntimeError, match="does not include Claude Code backend"):
        super_agents_backend._compat_client_from_environment()


def test_compat_permission_response_handles_approval_request() -> None:
    result = super_agents_backend._compat_permission_response_for_request(
        {"method": "exec/requestApproval"},
        "decline",
    )

    assert result == {"decision": "decline"}


def test_compat_permission_response_handles_mcp_elicitation() -> None:
    result = super_agents_backend._compat_permission_response_for_request(
        {"method": "mcpServer/elicitation/request"},
        "accept",
    )

    assert result == {"action": "accept", "content": None, "_meta": None}


def test_compat_permission_response_does_not_generalize_elicitation_methods() -> None:
    result = super_agents_backend._compat_permission_response_for_request(
        {"method": "custom/elicitation/request"},
        "decline",
    )

    assert result == {"decision": "decline"}
