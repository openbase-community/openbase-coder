from __future__ import annotations

from openbase_coder_cli import tts_providers


def test_kokoro_readiness_requires_importable_runtime(monkeypatch) -> None:
    def missing_kokoro(module_name: str):
        if module_name == "kokoro":
            raise ImportError("kokoro is missing")
        raise AssertionError(f"Unexpected module import: {module_name}")

    monkeypatch.setattr(tts_providers.importlib, "import_module", missing_kokoro)

    status = tts_providers.get_tts_provider("kokoro").readiness()

    assert status.ready is False
    assert status.cached_files == 0
    assert status.detail == "Kokoro dependencies are not installed."


def test_kokoro_download_requires_importable_runtime(monkeypatch) -> None:
    def missing_kokoro(module_name: str):
        if module_name == "kokoro":
            raise ImportError("kokoro is missing")
        raise AssertionError(f"Unexpected module import: {module_name}")

    monkeypatch.setattr(tts_providers.importlib, "import_module", missing_kokoro)

    status = tts_providers.get_tts_provider("kokoro").download_all_voices()

    assert status.ready is False
    assert status.detail == "Kokoro dependencies are not installed."


def test_kokoro_readiness_requires_english_language_model(monkeypatch) -> None:
    real_import_module = tts_providers.importlib.import_module

    def missing_english_model(module_name: str, package: str | None = None):
        if module_name == "en_core_web_sm":
            raise ImportError("English model is missing")
        return real_import_module(module_name, package)

    monkeypatch.setattr(tts_providers.importlib, "import_module", missing_english_model)

    status = tts_providers.get_tts_provider("kokoro").readiness()

    assert status.ready is False
    assert status.detail == "Kokoro dependencies are not installed."
