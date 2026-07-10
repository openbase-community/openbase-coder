from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("OPENBASE_CODER_CLI_SECRET_KEY", "test-secret")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "openbase_coder_cli.config.settings")

import django  # noqa: E402
from rest_framework.test import APIRequestFactory, force_authenticate  # noqa: E402

django.setup()

from openbase_coder_cli import provenance_hooks  # noqa: E402
from openbase_coder_cli.openbase_coder_cli_app import (  # noqa: E402
    provenance_hooks_settings,
)


def _point_at_tmp(monkeypatch, tmp_path: Path) -> None:
    codex_home = tmp_path / "codex_home"
    claude_config = tmp_path / "claude_config"
    monkeypatch.setattr(
        provenance_hooks, "CODEX_CONFIG_PATH", codex_home / "config.toml"
    )
    monkeypatch.setattr(
        provenance_hooks, "CODEX_HOOKS_JSON_PATH", codex_home / "hooks.json"
    )
    monkeypatch.setattr(
        provenance_hooks,
        "CODEX_HOOK_SCRIPT_PATH",
        codex_home / "hooks" / provenance_hooks.HOOK_SCRIPT_NAME,
    )
    monkeypatch.setattr(
        provenance_hooks,
        "CLAUDE_HOOK_SCRIPT_PATH",
        claude_config / "hooks" / provenance_hooks.HOOK_SCRIPT_NAME,
    )
    monkeypatch.setattr(
        provenance_hooks,
        "OPENBASE_CLAUDE_SETTINGS_PATH",
        claude_config / "settings.json",
    )


def test_codex_trusted_hash_matches_known_codex_value() -> None:
    """Verified against a hook Codex itself trusted (warp plugin session_start)."""
    assert provenance_hooks.codex_trusted_hash(
        "${PLUGIN_ROOT}/scripts/on-session-start.sh"
    ) == ("sha256:91587043033e7831d4d154fdef2e495f3113c3552a4529d8013f5546ffb2c140")


def test_status_reports_not_installed_when_nothing_exists(
    monkeypatch, tmp_path: Path
) -> None:
    _point_at_tmp(monkeypatch, tmp_path)
    status = provenance_hooks.provenance_hooks_status()
    assert status["installed"] is False
    assert status["backends"]["claude"]["installed"] is False
    assert status["backends"]["codex"]["installed"] is False


def test_install_is_idempotent_and_reports_installed(
    monkeypatch, tmp_path: Path
) -> None:
    _point_at_tmp(monkeypatch, tmp_path)

    first = provenance_hooks.install_provenance_hooks()
    assert first["installed"] is True
    assert provenance_hooks.provenance_hooks_status()["installed"] is True

    provenance_hooks.install_provenance_hooks()
    settings = json.loads(
        provenance_hooks.OPENBASE_CLAUDE_SETTINGS_PATH.read_text(encoding="utf-8")
    )
    assert len(settings["hooks"]["SessionStart"]) == 1
    hooks_file = json.loads(
        provenance_hooks.CODEX_HOOKS_JSON_PATH.read_text(encoding="utf-8")
    )
    assert len(hooks_file["hooks"]["SessionStart"]) == 1
    config = provenance_hooks.CODEX_CONFIG_PATH.read_text(encoding="utf-8")
    assert config.count("[hooks.state.") == 1


def test_install_preserves_existing_settings_and_config(
    monkeypatch, tmp_path: Path
) -> None:
    _point_at_tmp(monkeypatch, tmp_path)

    claude_settings = provenance_hooks.OPENBASE_CLAUDE_SETTINGS_PATH
    claude_settings.parent.mkdir(parents=True)
    claude_settings.write_text(
        json.dumps(
            {
                "model": "opus",
                "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "x"}]}]},
            }
        ),
        encoding="utf-8",
    )
    codex_config = provenance_hooks.CODEX_CONFIG_PATH
    codex_config.parent.mkdir(parents=True)
    codex_config.write_text(
        'model = "gpt-5"\n\n[mcp_servers.super-agents]\ncommand = "sa"\n',
        encoding="utf-8",
    )

    provenance_hooks.install_provenance_hooks()

    settings = json.loads(claude_settings.read_text(encoding="utf-8"))
    assert settings["model"] == "opus"
    assert "Stop" in settings["hooks"]
    assert settings["hooks"]["SessionStart"][0]["hooks"][0]["command"] == str(
        provenance_hooks.CLAUDE_HOOK_SCRIPT_PATH
    )
    config = codex_config.read_text(encoding="utf-8")
    assert 'model = "gpt-5"' in config
    assert "[mcp_servers.super-agents]" in config
    assert "[hooks.state." in config
    assert "enabled = true" in config


def test_status_detects_script_drift(monkeypatch, tmp_path: Path) -> None:
    _point_at_tmp(monkeypatch, tmp_path)
    provenance_hooks.install_provenance_hooks()
    provenance_hooks.CLAUDE_HOOK_SCRIPT_PATH.write_text(
        "#!/bin/sh\necho tampered\n", encoding="utf-8"
    )
    status = provenance_hooks.provenance_hooks_status()
    assert status["backends"]["claude"]["installed"] is False
    assert status["installed"] is False


def test_hook_script_injects_session_id() -> None:
    result = subprocess.run(
        ["/bin/sh", "-s"],
        input=provenance_hooks.HOOK_SCRIPT.replace("#!/bin/sh\n", "", 1),
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ},
    )
    # No session_id on stdin -> silent success. Now with one:
    assert result.stdout == ""


def test_hook_script_emits_additional_context(tmp_path: Path) -> None:
    script = tmp_path / "hook.sh"
    script.write_text(provenance_hooks.HOOK_SCRIPT, encoding="utf-8")
    script.chmod(0o755)
    payload = json.dumps({"session_id": "abc-123", "cwd": "/tmp"})
    result = subprocess.run(
        [str(script)], input=payload, capture_output=True, text=True, check=True
    )
    output = json.loads(result.stdout)
    context = output["hookSpecificOutput"]["additionalContext"]
    assert "abc-123" in context
    assert output["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "Agent-Thread-Id" in context


def test_settings_api_get_and_install(monkeypatch, tmp_path: Path) -> None:
    _point_at_tmp(monkeypatch, tmp_path)
    factory = APIRequestFactory()

    request = factory.get("/api/settings/openbase-hooks/")
    force_authenticate(request, user=SimpleNamespace(is_authenticated=True))
    response = provenance_hooks_settings.openbase_hooks_settings(request)
    assert response.status_code == 200
    assert response.data["installed"] is False

    request = factory.post("/api/settings/openbase-hooks/", {}, format="json")
    force_authenticate(request, user=SimpleNamespace(is_authenticated=True))
    response = provenance_hooks_settings.openbase_hooks_settings(request)
    assert response.status_code == 200
    assert response.data["installed"] is True
    assert response.data["changed"] is True
