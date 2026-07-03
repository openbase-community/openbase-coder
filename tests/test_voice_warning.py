from __future__ import annotations

import logging

from openbase_coder_cli.livekit_announcer import (
    AnnouncerValidationError,
    NoActiveLiveKitRoomError,
)
from openbase_coder_cli.services import voice_warning


def test_warning_ignores_no_active_livekit_room(monkeypatch, tmp_path):
    sounds_dir = tmp_path / "sounds"
    sounds_dir.mkdir()
    (sounds_dir / "deactivate.wav").write_bytes(b"audio")

    async def fake_publish(audio_path):
        raise NoActiveLiveKitRoomError("No active LiveKit voice room was found.")

    monkeypatch.setattr(voice_warning, "OPENBASE_SOUNDS_DIR", sounds_dir)
    monkeypatch.setattr(voice_warning, "publish_announcer_audio_file", fake_publish)

    assert voice_warning.warn_before_voice_interruption(reason="test") is False


def test_warning_failure_does_not_raise(monkeypatch, tmp_path, caplog):
    sounds_dir = tmp_path / "sounds"
    sounds_dir.mkdir()
    (sounds_dir / "deactivate.wav").write_bytes(b"audio")

    async def fake_publish(audio_path):
        raise AnnouncerValidationError("bad sound")

    monkeypatch.setattr(voice_warning, "OPENBASE_SOUNDS_DIR", sounds_dir)
    monkeypatch.setattr(voice_warning, "publish_announcer_audio_file", fake_publish)
    caplog.set_level(logging.WARNING)

    assert (
        voice_warning.warn_before_voice_interruption(
            reason="test", emit_cli_warning=False
        )
        is False
    )
    assert "Unable to play voice interruption warning" in caplog.text


def test_warning_sends_sound_and_waits(monkeypatch, tmp_path):
    sounds_dir = tmp_path / "sounds"
    sounds_dir.mkdir()
    sound_path = sounds_dir / "deactivate.wav"
    sound_path.write_bytes(b"audio")
    calls = []
    delays = []

    async def fake_publish(audio_path):
        calls.append(audio_path)

    monkeypatch.setattr(voice_warning, "OPENBASE_SOUNDS_DIR", sounds_dir)
    monkeypatch.setattr(voice_warning, "publish_announcer_audio_file", fake_publish)
    monkeypatch.setattr(
        voice_warning.time, "sleep", lambda seconds: delays.append(seconds)
    )

    assert (
        voice_warning.warn_before_voice_interruption(reason="test", delay_seconds=1.2)
        is True
    )
    assert calls == [str(sound_path)]
    assert delays == [1.2]
