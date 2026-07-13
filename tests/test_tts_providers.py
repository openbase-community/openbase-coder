from __future__ import annotations

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
