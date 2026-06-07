from __future__ import annotations

import json
import os
import time
from types import SimpleNamespace

os.environ.setdefault("OPENBASE_CODER_CLI_SECRET_KEY", "test-secret")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "openbase_coder_cli.config.settings")

import django  # noqa: E402
from rest_framework.test import APIRequestFactory, force_authenticate  # noqa: E402

django.setup()

from openbase_coder_cli.openbase_coder_cli_app import views  # noqa: E402
from openbase_coder_cli.openbase_coder_cli_app.brain_readiness import (  # noqa: E402
    build_brain_readiness_response,
    parallel_voice_threshold_for_score,
)


def test_parallel_voice_threshold_for_score() -> None:
    assert parallel_voice_threshold_for_score(None) is None
    assert parallel_voice_threshold_for_score(0) == 1
    assert parallel_voice_threshold_for_score(24.9) == 1
    assert parallel_voice_threshold_for_score(25) == 2
    assert parallel_voice_threshold_for_score(50) == 4
    assert parallel_voice_threshold_for_score(75) == 7
    assert parallel_voice_threshold_for_score(99) == 7


def test_brain_readiness_response_reads_score_file(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("OPENBASE_BRAIN_SCORE_TOKEN", "token-1")
    score_path = tmp_path / "brain_score.json"
    updated_at = time.time() - 3
    score_path.write_text(
        json.dumps(
            {
                "brs": 62.4,
                "updated_at": updated_at,
                "computed_at": "2026-05-30T12:00:00Z",
                "chunk_index": 4,
            }
        ),
        encoding="utf-8",
    )

    response = build_brain_readiness_response(score_path)

    assert response["available"] is True
    assert response["brain_readiness_score"] == 62
    assert response["brs"] == 62.4
    assert response["parallel_voice_threshold"] == 4
    assert response["computed_at"] == "2026-05-30T12:00:00Z"
    assert response["chunk_index"] == 4
    assert response["age_seconds"] >= 0


def test_brain_readiness_response_is_disabled_without_token(monkeypatch, tmp_path) -> None:
    score_path = tmp_path / "brain_score.json"
    missing_token_path = tmp_path / "missing-token"
    score_path.write_text(json.dumps({"brs": 84}), encoding="utf-8")
    monkeypatch.delenv("OPENBASE_BRAIN_SCORE_TOKEN", raising=False)
    monkeypatch.setenv("OPENBASE_BRAIN_SCORE_TOKEN_FILE", str(missing_token_path))

    response = build_brain_readiness_response(score_path)

    assert response["available"] is False
    assert response["brain_readiness_score"] is None
    assert response["brs"] is None
    assert response["parallel_voice_threshold"] is None
    assert response["disabled_reason"] == "missing_token"


def test_brain_readiness_endpoint_uses_configured_score_path(monkeypatch, tmp_path) -> None:
    score_path = tmp_path / "brain_score.json"
    score_path.write_text(json.dumps({"brs": 19}), encoding="utf-8")
    monkeypatch.setenv("OPENBASE_BRAIN_SCORE_TOKEN", "token-1")
    monkeypatch.setenv("OPENBASE_BRAIN_SCORE_OUTPUT_PATH", str(score_path))

    request = APIRequestFactory().get("/api/brain-readiness/")
    force_authenticate(request, user=SimpleNamespace(is_authenticated=True))

    response = views.brain_readiness(request)

    assert response.status_code == 200
    assert response.data["brain_readiness_score"] == 19
    assert response.data["parallel_voice_threshold"] == 1
