from __future__ import annotations

import os
from pathlib import Path


def brain_score_token_file() -> Path:
    return Path(
        os.getenv(
            "OPENBASE_BRAIN_SCORE_TOKEN_FILE",
            str(Path.home() / ".openbase" / "brain_score_token"),
        )
    ).expanduser()


def load_brain_score_token() -> str:
    configured = os.getenv("OPENBASE_BRAIN_SCORE_TOKEN", "").strip()
    if configured:
        return configured
    try:
        return brain_score_token_file().read_text(encoding="utf-8").strip()
    except (FileNotFoundError, OSError):
        return ""


def brain_score_token_configured() -> bool:
    return bool(load_brain_score_token())
