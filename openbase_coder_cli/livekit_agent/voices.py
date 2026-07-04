"""Voice catalog helpers for the dispatcher and Super Agent voice pools."""

import hashlib
from dataclasses import dataclass
from pathlib import Path

from openbase_coder_cli.dispatcher_config import (
    dispatcher_voice,
    selected_tts_provider_id,
)
from openbase_coder_cli.livekit_agent.config import LIVEKIT_DISPATCHER_CONFIG_PATH
from openbase_coder_cli.tts_providers import (
    CARTESIA_PROVIDER_ID,
    get_tts_provider,
)


@dataclass(frozen=True)
class CartesiaVoice:
    voice_id: str
    name: str
    provider: str = CARTESIA_PROVIDER_ID


def dispatcher_voice_config(
    *,
    config_path: str | Path | None = None,
) -> CartesiaVoice:
    configured = dispatcher_voice(
        Path(config_path or LIVEKIT_DISPATCHER_CONFIG_PATH).expanduser()
    )
    return CartesiaVoice(
        voice_id=configured["id"],
        name=configured["name"],
        provider=configured.get("provider", CARTESIA_PROVIDER_ID),
    )


def _voices_from_ids(voice_ids) -> tuple[CartesiaVoice, ...]:
    provider = get_tts_provider(CARTESIA_PROVIDER_ID)
    return tuple(
        CartesiaVoice(
            voice_id=voice_id,
            name=provider.voice_for_id(voice_id).name
            if provider.voice_for_id(voice_id)
            else f"Voice {index + 1}",
        )
        for index, voice_id in enumerate(voice_ids)
    )


SUPER_AGENT_VOICE_IDS = tuple(
    voice.id for voice in get_tts_provider(CARTESIA_PROVIDER_ID).super_agent_voices()
)
SUPER_AGENT_VOICES = _voices_from_ids(SUPER_AGENT_VOICE_IDS)


def _current_super_agent_voices() -> tuple[CartesiaVoice, ...]:
    provider = get_tts_provider(selected_tts_provider_id())
    if provider.provider_id != CARTESIA_PROVIDER_ID:
        return tuple(
            CartesiaVoice(
                voice_id=voice.id, name=voice.name, provider=provider.provider_id
            )
            for voice in provider.super_agent_voices()
        )
    voice_ids = tuple(voice.voice_id for voice in SUPER_AGENT_VOICES)
    if voice_ids == tuple(SUPER_AGENT_VOICE_IDS):
        return SUPER_AGENT_VOICES
    return tuple(
        CartesiaVoice(voice_id=voice.id, name=voice.name, provider=provider.provider_id)
        for voice in provider.super_agent_voices()
    )


def stable_super_agent_voice_id(
    thread_id: str | None,
    label: str | None = None,
) -> str | None:
    voice = stable_super_agent_voice(thread_id, label)
    return voice.voice_id if voice else None


def stable_super_agent_voice(
    thread_id: str | None,
    label: str | None = None,
) -> CartesiaVoice | None:
    voices = _current_super_agent_voices()
    if not voices:
        return None
    key = (thread_id or label or "").strip()
    if not key:
        return None
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    index = int.from_bytes(digest[:4], "big") % len(voices)
    return voices[index]
