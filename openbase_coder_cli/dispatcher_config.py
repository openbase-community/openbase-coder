from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from openbase_coder_cli.paths import CODEX_DISPATCHER_CONFIG_PATH
from openbase_coder_cli.stt_providers import (
    DEFAULT_STT_PROVIDER_ID,
    LOCAL_MLX_WHISPER_STT_PROVIDER_ID,
    local_mlx_whisper_readiness,
    normalize_stt_provider_id,
)
from openbase_coder_cli.tts_providers import (
    CARTESIA_PROVIDER_ID,
    DEFAULT_CARTESIA_VOICE_ID,
    DEFAULT_TTS_PROVIDER_ID,
    KOKORO_PROVIDER_ID,
    OPENBASE_CLOUD_TTS_PROVIDER_ID,
    get_tts_provider,
    normalize_tts_provider_id,
)

REASONING_EFFORTS = {"low", "medium", "high", "xhigh"}
DISPATCHER_REASONING_EFFORT_KEY = "dispatcher_reasoning_effort"
SUPER_AGENTS_REASONING_EFFORT_KEY = "super_agents_reasoning_effort"
SUPER_AGENTS_MODEL_KEY = "super_agents_model"
TTS_PROVIDER_KEY = "tts_provider"
STT_PROVIDER_KEY = "stt_provider"
DISPATCHER_VOICE_ID_KEY = "dispatcher_voice_id"
DISPATCHER_VOICE_NAME_KEY = "dispatcher_voice_name"
DEFAULT_DISPATCHER_VOICE_ID = DEFAULT_CARTESIA_VOICE_ID
DEFAULT_DISPATCHER_VOICE_NAME = "Jacqueline"


def read_dispatcher_config(path: Path | None = None) -> dict[str, Any]:
    config_path = path or CODEX_DISPATCHER_CONFIG_PATH
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def dispatcher_reasoning_effort(path: Path | None = None) -> str | None:
    value = _reasoning_effort_for_key(DISPATCHER_REASONING_EFFORT_KEY, path)
    return value if isinstance(value, str) and value in REASONING_EFFORTS else None


def super_agents_reasoning_effort(path: Path | None = None) -> str | None:
    value = _reasoning_effort_for_key(SUPER_AGENTS_REASONING_EFFORT_KEY, path)
    return value if isinstance(value, str) and value in REASONING_EFFORTS else None


def set_dispatcher_reasoning_effort(value: str, path: Path | None = None) -> Path:
    return _set_reasoning_effort(DISPATCHER_REASONING_EFFORT_KEY, value, path)


def set_super_agents_reasoning_effort(value: str, path: Path | None = None) -> Path:
    return _set_reasoning_effort(SUPER_AGENTS_REASONING_EFFORT_KEY, value, path)


def super_agents_model(path: Path | None = None) -> str | None:
    payload = read_dispatcher_config(path)
    configured = _optional_str(payload.get(SUPER_AGENTS_MODEL_KEY))
    if configured:
        return configured
    env_model = _optional_str(os.getenv("SUPER_AGENTS_MODEL"))
    return env_model


def set_super_agents_model(value: str, path: Path | None = None) -> Path:
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError("Super Agents model cannot be blank.")
    config_path = path or CODEX_DISPATCHER_CONFIG_PATH
    _write_dispatcher_config(
        {
            **read_dispatcher_config(config_path),
            SUPER_AGENTS_MODEL_KEY: normalized,
        },
        config_path,
    )
    return config_path


def selected_tts_provider_id(path: Path | None = None) -> str:
    payload = read_dispatcher_config(path)
    configured = _optional_str(payload.get(TTS_PROVIDER_KEY))
    if configured:
        try:
            return normalize_tts_provider_id(configured)
        except ValueError:
            return DEFAULT_TTS_PROVIDER_ID
    return DEFAULT_TTS_PROVIDER_ID


def selected_stt_provider_id(path: Path | None = None) -> str:
    payload = read_dispatcher_config(path)
    configured = _optional_str(payload.get(STT_PROVIDER_KEY))
    if configured:
        try:
            return normalize_stt_provider_id(configured)
        except ValueError:
            return DEFAULT_STT_PROVIDER_ID
    env_provider = _optional_str(os.getenv("LIVEKIT_STT_PROVIDER"))
    if env_provider:
        try:
            return normalize_stt_provider_id(env_provider)
        except ValueError:
            return DEFAULT_STT_PROVIDER_ID
    return DEFAULT_STT_PROVIDER_ID


def set_stt_provider(provider_id: str, path: Path | None = None) -> dict[str, str]:
    normalized_provider_id = normalize_stt_provider_id(provider_id)
    if (
        normalized_provider_id == LOCAL_MLX_WHISPER_STT_PROVIDER_ID
        and not local_mlx_whisper_readiness().ready
    ):
        raise ValueError("Download local MLX Whisper before selecting local STT.")

    config_path = path or CODEX_DISPATCHER_CONFIG_PATH
    _write_dispatcher_config(
        {
            **read_dispatcher_config(config_path),
            STT_PROVIDER_KEY: normalized_provider_id,
        },
        config_path,
    )
    return {"provider": normalized_provider_id}


def dispatcher_voice(path: Path | None = None) -> dict[str, str]:
    payload = read_dispatcher_config(path)
    provider_id = selected_tts_provider_id(path)
    provider = get_tts_provider(provider_id)
    default_voice = provider.default_dispatcher_voice()
    legacy_env_voice_id = os.getenv("CARTESIA_VOICE_ID", "").strip()
    configured_voice_id = _optional_str(payload.get(DISPATCHER_VOICE_ID_KEY))
    voice_id = (
        configured_voice_id
        or (
            legacy_env_voice_id
            if provider_id in {CARTESIA_PROVIDER_ID, OPENBASE_CLOUD_TTS_PROVIDER_ID}
            else ""
        )
        or default_voice.id
    )
    catalog_voice = provider.voice_for_id(voice_id)
    configured_voice_name = _optional_str(payload.get(DISPATCHER_VOICE_NAME_KEY))
    if catalog_voice is None and configured_voice_id and configured_voice_name:
        return {
            "id": configured_voice_id,
            "name": configured_voice_name,
            "provider": provider_id,
        }
    if catalog_voice is None and provider_id in {
        CARTESIA_PROVIDER_ID,
        OPENBASE_CLOUD_TTS_PROVIDER_ID,
    }:
        voice_id = DEFAULT_DISPATCHER_VOICE_ID
        catalog_voice = provider.voice_for_id(voice_id)
    if catalog_voice is None:
        voice_id = default_voice.id
        catalog_voice = default_voice
    voice_name = (
        catalog_voice.name or configured_voice_name or DEFAULT_DISPATCHER_VOICE_NAME
    )
    return {
        "id": voice_id,
        "name": voice_name,
        "provider": provider_id,
    }


def set_tts_provider_and_dispatcher_voice(
    *,
    provider_id: str,
    voice_id: str,
    path: Path | None = None,
) -> dict[str, str]:
    normalized_provider_id = normalize_tts_provider_id(provider_id)
    provider = get_tts_provider(normalized_provider_id)
    if normalized_provider_id == KOKORO_PROVIDER_ID and not provider.readiness().ready:
        raise ValueError("Download Kokoro local voices before selecting Kokoro.")
    normalized = voice_id.strip()
    voice = provider.voice_for_id(normalized)
    if voice is None:
        raise ValueError("Dispatcher voice must be selected from the provider catalog.")

    config_path = path or CODEX_DISPATCHER_CONFIG_PATH
    _write_dispatcher_config(
        {
            **read_dispatcher_config(config_path),
            TTS_PROVIDER_KEY: normalized_provider_id,
            DISPATCHER_VOICE_ID_KEY: voice.id,
            DISPATCHER_VOICE_NAME_KEY: voice.name,
        },
        config_path,
    )
    return {"id": voice.id, "name": voice.name, "provider": normalized_provider_id}


def set_dispatcher_voice(voice_id: str, path: Path | None = None) -> dict[str, str]:
    return set_tts_provider_and_dispatcher_voice(
        provider_id=selected_tts_provider_id(path),
        voice_id=voice_id,
        path=path,
    )


def _reasoning_effort_for_key(key: str, path: Path | None = None) -> str | None:
    value = read_dispatcher_config(path).get(key)
    return value if isinstance(value, str) else None


def _set_reasoning_effort(key: str, value: str, path: Path | None = None) -> Path:
    if value not in REASONING_EFFORTS:
        allowed = ", ".join(sorted(REASONING_EFFORTS))
        raise ValueError(f"Reasoning effort must be one of: {allowed}.")

    config_path = path or CODEX_DISPATCHER_CONFIG_PATH
    payload = {**read_dispatcher_config(config_path), key: value}
    _write_dispatcher_config(payload, config_path)
    return config_path


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _write_dispatcher_config(payload: dict[str, Any], config_path: Path) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=config_path.parent, delete=False
    ) as tmp:
        json.dump(payload, tmp, indent=2, sort_keys=True)
        tmp.write("\n")
        tmp_path = Path(tmp.name)
    os.replace(tmp_path, config_path)
