from openbase_coder_cli.codex_session_defaults import codex_permission_defaults


def test_codex_permission_defaults_match_existing_livekit_behavior() -> None:
    assert codex_permission_defaults({}) == {
        "approvalPolicy": "never",
        "sandbox": "danger-full-access",
    }


def test_codex_permission_defaults_honor_existing_environment_overrides() -> None:
    assert codex_permission_defaults(
        {
            "LIVEKIT_CODEX_APPROVAL_POLICY": "on-request",
            "LIVEKIT_CODEX_SANDBOX": "read-only",
        }
    ) == {
        "approvalPolicy": "on-request",
        "sandbox": "read-only",
    }
