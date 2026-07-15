"""Shared normalization for comparing variants of the same spoken text.

STT can deliver one utterance in several near-identical forms (unformatted vs
formatted turns, punctuation/casing differences). Every layer that deduplicates
or matches transcribed text must normalize the same way, or twins slip through.
"""

import hashlib
import re


def normalize_spoken_text(text: str) -> str:
    # Contractions must collapse ("I'm" and "im" are the same utterance), so
    # apostrophes are removed rather than treated as word breaks.
    text = re.sub(r"['’ʼ]", "", text.lower())
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalized_text_hash(text: str) -> str:
    normalized = normalize_spoken_text(text)
    if not normalized:
        return ""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]
