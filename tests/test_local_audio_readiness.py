from __future__ import annotations

from openbase_coder_cli import stt_providers, tts_providers


def test_kokoro_readiness_requires_runtime_package(monkeypatch) -> None:
    monkeypatch.setattr(
        tts_providers.importlib.util,
        "find_spec",
        lambda name: None if name == "kokoro" else object(),
    )

    status = tts_providers.get_tts_provider(
        tts_providers.KOKORO_PROVIDER_ID
    ).readiness()

    assert status.ready is False
    assert status.detail == "Kokoro runtime dependencies are not installed."


def test_local_whisper_readiness_requires_runtime_package(monkeypatch) -> None:
    monkeypatch.setattr(
        stt_providers.importlib.util,
        "find_spec",
        lambda name: None if name == "mlx_whisper" else object(),
    )

    status = stt_providers.local_mlx_whisper_readiness()

    assert status.ready is False
    assert status.detail == "MLX Whisper runtime dependencies are not installed."
