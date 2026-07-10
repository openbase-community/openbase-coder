from __future__ import annotations

from openbase_coder_cli.voice_tags import (
    VOICE_TAG_CLOSE,
    VOICE_TAG_OPEN,
    wrap_voice_prompt,
)


def test_wrap_voice_prompt_wraps_content_in_voice_tags():
    assert wrap_voice_prompt("fix the login bug") == (
        "<voice>fix the login bug</voice>"
    )


def test_wrap_voice_prompt_uses_tag_constants():
    wrapped = wrap_voice_prompt("hello")

    assert wrapped.startswith(VOICE_TAG_OPEN)
    assert wrapped.endswith(VOICE_TAG_CLOSE)
    assert wrapped == f"{VOICE_TAG_OPEN}hello{VOICE_TAG_CLOSE}"


def test_wrap_voice_prompt_preserves_prompt_verbatim():
    prompt = "  multi\nline  prompt with <tags> "

    assert wrap_voice_prompt(prompt) == f"<voice>{prompt}</voice>"


def test_wrap_voice_prompt_handles_empty_prompt():
    assert wrap_voice_prompt("") == "<voice></voice>"
