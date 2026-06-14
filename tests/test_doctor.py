from openbase_coder_cli.cli.doctor import _check_livekit_client_credentials


def _collect_credential_check(env):
    messages = []

    def warn(message):
        messages.append(("warn", message))

    def ok(message):
        messages.append(("ok", message))

    _check_livekit_client_credentials(env, warn, ok)
    return messages


def test_livekit_client_credential_check_warns_when_missing():
    messages = _collect_credential_check(
        {
            "LIVEKIT_API_KEY": "server-key",
            "LIVEKIT_API_SECRET": "server-secret",
        }
    )

    assert messages == [
        (
            "warn",
            "LiveKit client token credentials missing "
            "(LIVEKIT_CLIENT_API_KEY, LIVEKIT_CLIENT_API_SECRET): "
            "run 'openbase-coder setup' and restart services",
        )
    ]


def test_livekit_client_credential_check_warns_when_reusing_server_credentials():
    messages = _collect_credential_check(
        {
            "LIVEKIT_API_KEY": "same-key",
            "LIVEKIT_API_SECRET": "same-secret",
            "LIVEKIT_CLIENT_API_KEY": "same-key",
            "LIVEKIT_CLIENT_API_SECRET": "same-secret",
        }
    )

    assert messages == [
        (
            "warn",
            "LiveKit client token credentials reuse local server credentials "
            "(LIVEKIT_CLIENT_API_KEY, LIVEKIT_CLIENT_API_SECRET): "
            "run 'openbase-coder setup' and restart services",
        )
    ]


def test_livekit_client_credential_check_accepts_separate_credentials():
    messages = _collect_credential_check(
        {
            "LIVEKIT_API_KEY": "server-key",
            "LIVEKIT_API_SECRET": "server-secret",
            "LIVEKIT_CLIENT_API_KEY": "client-key",
            "LIVEKIT_CLIENT_API_SECRET": "client-secret",
        }
    )

    assert messages == [
        (
            "ok",
            "LiveKit client token credentials: set and separate from server credentials",
        )
    ]
