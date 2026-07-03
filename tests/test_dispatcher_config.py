from __future__ import annotations

import json
from pathlib import Path

from openbase_coder_cli import dispatcher_config


def test_backend_model_uses_env_backend(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "dispatcher-config.json"
    config_path.write_text(
        json.dumps(
            {
                "backend_models": {
                    "codex": {"dispatcher": "gpt-5.5", "super_agents": "gpt-5.5"},
                    "claude_code": {
                        "dispatcher": "sonnet",
                        "super_agents": "opus",
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENBASE_CODING_BACKEND", "claude_code")

    assert dispatcher_config.dispatcher_model(config_path) == "sonnet"
    assert dispatcher_config.super_agents_model(config_path) == "opus"


def test_claude_model_options_include_fable_alias(monkeypatch) -> None:
    monkeypatch.setenv("OPENBASE_CODING_BACKEND", "claude_code")

    options = dispatcher_config.model_options_for_backend()

    assert options[0]["id"] == "fable"
    assert dispatcher_config.is_known_backend_model("fable")


def test_backend_model_uses_env_file_backend(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    config_path = tmp_path / "dispatcher-config.json"
    env_file.write_text("OPENBASE_CODING_BACKEND=openbase_cloud\n", encoding="utf-8")
    config_path.write_text(
        json.dumps(
            {
                "backend_models": {
                    "codex": {"super_agents": "gpt-5.5"},
                    "openbase_cloud": {"super_agents": "openbase-codex"},
                },
                "super_agents_model": "legacy-model",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("OPENBASE_CODING_BACKEND", raising=False)
    monkeypatch.delenv("OPENBASE_CODEX_BACKEND", raising=False)
    monkeypatch.setattr(dispatcher_config, "DEFAULT_ENV_FILE_PATH", env_file)

    assert dispatcher_config.super_agents_model(config_path) == "gpt-5.5"


def test_super_agents_model_ignores_legacy_key(
    tmp_path: Path, monkeypatch
) -> None:
    config_path = tmp_path / "dispatcher-config.json"
    config_path.write_text(
        json.dumps({"super_agents_model": "legacy-model"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENBASE_CODING_BACKEND", "claude_code")

    assert dispatcher_config.super_agents_model(config_path) is None


def test_codex_service_tier_uses_config_before_env(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "dispatcher-config.json"
    env_file = tmp_path / ".env"
    config_path.write_text(
        json.dumps({"codex_service_tier": "standard"}),
        encoding="utf-8",
    )
    env_file.write_text("CODEX_SERVICE_TIER=fast\n", encoding="utf-8")
    monkeypatch.setattr(dispatcher_config, "DEFAULT_ENV_FILE_PATH", env_file)
    monkeypatch.setenv("CODEX_SERVICE_TIER", "fast")

    assert dispatcher_config.codex_service_tier(config_path) == "standard"


def test_codex_service_tier_defaults_to_standard(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    monkeypatch.delenv("CODEX_SERVICE_TIER", raising=False)
    monkeypatch.setattr(dispatcher_config, "DEFAULT_ENV_FILE_PATH", env_file)

    assert dispatcher_config.codex_service_tier(tmp_path / "missing.json") == "standard"


def test_set_codex_service_tier_persists_config(tmp_path: Path) -> None:
    config_path = tmp_path / "dispatcher-config.json"

    dispatcher_config.set_codex_service_tier("standard", config_path)

    assert json.loads(config_path.read_text(encoding="utf-8"))["codex_service_tier"] == "standard"
