from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from rest_framework.decorators import api_view
from rest_framework.response import Response

from openbase_coder_cli.brain_score import brain_score_token_configured


def default_brain_score_output_path() -> Path:
    return Path(
        os.getenv(
            "OPENBASE_BRAIN_SCORE_OUTPUT_PATH",
            str(Path.home() / ".openbase" / "brain_score.json"),
        )
    ).expanduser()


def parallel_voice_threshold_for_score(score: float | int | None) -> int | None:
    if score is None:
        return None
    if score < 25:
        return 1
    if score < 50:
        return 2
    if score < 75:
        return 4
    return 7


def _coerce_score(value: Any) -> float | None:
    if value is None:
        return None
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(score, 100.0))


def _read_brain_score_file(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _unavailable_response(*, disabled_reason: str | None = None) -> dict[str, Any]:
    return {
        "available": False,
        "brain_readiness_score": None,
        "brs": None,
        "parallel_voice_threshold": None,
        "updated_at": None,
        "computed_at": None,
        "chunk_index": None,
        "age_seconds": None,
        "disabled_reason": disabled_reason,
    }


def build_brain_readiness_response(path: Path | None = None) -> dict[str, Any]:
    if not brain_score_token_configured():
        return _unavailable_response(disabled_reason="missing_token")

    payload = _read_brain_score_file(path or default_brain_score_output_path())
    if payload is None:
        return _unavailable_response()

    score = _coerce_score(payload.get("brs"))
    updated_at = payload.get("updated_at")
    age_seconds = None
    if isinstance(updated_at, (int, float)):
        age_seconds = max(0.0, time.time() - float(updated_at))

    return {
        "available": score is not None,
        "brain_readiness_score": int(round(score)) if score is not None else None,
        "brs": score,
        "parallel_voice_threshold": parallel_voice_threshold_for_score(score),
        "updated_at": updated_at,
        "computed_at": payload.get("computed_at"),
        "chunk_index": payload.get("chunk_index"),
        "age_seconds": age_seconds,
        "disabled_reason": None,
    }


@api_view(["GET"])
def brain_readiness(request):
    _ = request
    return Response(build_brain_readiness_response())
