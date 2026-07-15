from __future__ import annotations

from openbase_coder_cli.livekit_agent.tts_selection import VoiceSelectingTTS
from openbase_coder_cli.tts_providers import (
    CARTESIA_WS_POOL_MAX_IDLE_SECONDS,
    CartesiaTTSProvider,
    OpenbaseCloudTTSProvider,
)


def test_cartesia_tts_pool_idle_lifetime_is_limited() -> None:
    tts_instance = CartesiaTTSProvider().create_livekit_tts(
        voice_id="voice-1",
        api_key="test-key",
    )
    assert tts_instance._pool._max_session_duration == CARTESIA_WS_POOL_MAX_IDLE_SECONDS


def test_openbase_cloud_tts_pool_idle_lifetime_is_limited() -> None:
    tts_instance = OpenbaseCloudTTSProvider().create_livekit_tts(
        voice_id="voice-1",
        api_key="test-key",
    )
    assert tts_instance._pool._max_session_duration == CARTESIA_WS_POOL_MAX_IDLE_SECONDS


def test_voice_selecting_tts_refreshes_api_key_on_synthesis() -> None:
    tokens = iter(["token-1", "token-2", "token-2"])
    tts = VoiceSelectingTTS(
        default_voice_id="voice-1",
        default_voice_name="Test Voice",
        active_voice_id=lambda: None,
        api_key="token-0",
        api_key_provider=lambda: next(tokens),
        provider=OpenbaseCloudTTSProvider(),
        role="direct",
    )

    instance = tts._tts_for_voice(None)
    assert instance._opts.api_key == "token-1"

    tts._tts_for_voice(None)
    assert instance._opts.api_key == "token-2"


def test_voice_selecting_tts_keeps_key_when_refresh_fails() -> None:
    def failing_provider() -> str:
        raise RuntimeError("cloud unreachable")

    tts = VoiceSelectingTTS(
        default_voice_id="voice-1",
        default_voice_name="Test Voice",
        active_voice_id=lambda: None,
        api_key="token-0",
        api_key_provider=failing_provider,
        provider=OpenbaseCloudTTSProvider(),
        role="direct",
    )

    instance = tts._tts_for_voice(None)
    assert instance._opts.api_key == "token-0"
