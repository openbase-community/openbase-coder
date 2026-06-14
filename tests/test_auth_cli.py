from __future__ import annotations

import importlib

from click.testing import CliRunner

from openbase_coder_cli.cli import main
from openbase_coder_cli.config.token_manager import AuthLoginRequiredError

auth_cli = importlib.import_module("openbase_coder_cli.cli.auth")


def test_auth_print_access_token_outputs_token(monkeypatch):
    class FakeTokenManager:
        def __init__(self, web_backend_url):
            self.web_backend_url = web_backend_url

        def get_access_token(self):
            return "jwt.token.value"

    monkeypatch.setattr(auth_cli, "TokenManager", FakeTokenManager)
    monkeypatch.setenv("OPENBASE_CODER_CLI_WEB_BACKEND_URL", "https://backend.example")

    result = CliRunner().invoke(main, ["auth", "print-access-token"])

    assert result.exit_code == 0
    assert result.output == "jwt.token.value\n"


def test_auth_print_access_token_reports_login_required(monkeypatch):
    class FakeTokenManager:
        def __init__(self, web_backend_url):
            pass

        def get_access_token(self):
            raise AuthLoginRequiredError("missing")

    monkeypatch.setattr(auth_cli, "TokenManager", FakeTokenManager)

    result = CliRunner().invoke(main, ["auth", "print-access-token"])

    assert result.exit_code != 0
    assert "openbase-coder login" in result.output


def test_auth_print_machine_token_outputs_token(monkeypatch):
    class FakeMachineTokenManager:
        def __init__(self, web_backend_url):
            self.web_backend_url = web_backend_url

        def get_machine_token(self, *, rotate=False):
            assert rotate is False
            return "obmt_machine_token"

    monkeypatch.setattr(auth_cli, "MachineTokenManager", FakeMachineTokenManager)
    monkeypatch.setenv("OPENBASE_CODER_CLI_WEB_BACKEND_URL", "https://backend.example")

    result = CliRunner().invoke(main, ["auth", "print-machine-token"])

    assert result.exit_code == 0
    assert result.output == "obmt_machine_token\n"


def test_auth_print_machine_token_can_rotate(monkeypatch):
    class FakeMachineTokenManager:
        def __init__(self, web_backend_url):
            pass

        def get_machine_token(self, *, rotate=False):
            assert rotate is True
            return "obmt_rotated"

    monkeypatch.setattr(auth_cli, "MachineTokenManager", FakeMachineTokenManager)

    result = CliRunner().invoke(main, ["auth", "print-machine-token", "--rotate"])

    assert result.exit_code == 0
    assert result.output == "obmt_rotated\n"
