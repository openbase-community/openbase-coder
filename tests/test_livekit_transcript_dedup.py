"""Twin final-transcript dedup: normalization helpers and the STT wrapper."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from livekit.agents import stt as livekit_stt

from openbase_coder_cli.livekit_agent import transcript_dedup
from openbase_coder_cli.livekit_agent.text_normalization import (
    normalize_spoken_text,
    normalized_text_hash,
)
from openbase_coder_cli.livekit_agent.transcript_dedup import (
    FinalTranscriptDedupStream,
)


def test_normalization_collapses_formatting_variants():
    assert normalize_spoken_text("What is 22?") == normalize_spoken_text("what is 22")
    assert normalized_text_hash("I'm not, like, what did Fable do?") == (
        normalized_text_hash("im not like what did fable do")
    )


def test_normalization_keeps_distinct_content_distinct():
    assert normalized_text_hash("what is 22") != normalized_text_hash(
        "what is two plus two"
    )
    assert normalized_text_hash("") == ""


def _speech_event(event_type, text: str):
    return SimpleNamespace(
        type=event_type,
        alternatives=[SimpleNamespace(text=text)],
    )


class FakeRecognizeStream:
    def __init__(self, events):
        self._events = list(events)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._events:
            raise StopAsyncIteration
        return self._events.pop(0)


async def _collect(stream):
    events = []
    async for event in stream:
        events.append(event)
    return events


@pytest.mark.asyncio
async def test_dedup_stream_drops_formatted_twin_final():
    final = livekit_stt.SpeechEventType.FINAL_TRANSCRIPT
    interim = livekit_stt.SpeechEventType.INTERIM_TRANSCRIPT
    stream = FinalTranscriptDedupStream(
        FakeRecognizeStream(
            [
                _speech_event(interim, "what is"),
                _speech_event(final, "what is 22"),
                _speech_event(final, "What is 22?"),
                _speech_event(final, "and something else"),
            ]
        ),
        provider="test",
    )

    events = await _collect(stream)

    final_texts = [
        event.alternatives[0].text for event in events if event.type == final
    ]
    assert final_texts == ["what is 22", "and something else"]
    assert len([event for event in events if event.type == interim]) == 1


@pytest.mark.asyncio
async def test_dedup_stream_allows_repeat_outside_window(monkeypatch):
    final = livekit_stt.SpeechEventType.FINAL_TRANSCRIPT
    clock = {"now": 100.0}
    monkeypatch.setattr(transcript_dedup.time, "monotonic", lambda: clock["now"])

    inner = FakeRecognizeStream(
        [
            _speech_event(final, "are you there"),
            _speech_event(final, "Are you there?"),
        ]
    )
    stream = FinalTranscriptDedupStream(inner, provider="test")

    first = await stream.__anext__()
    assert first.alternatives[0].text == "are you there"

    clock["now"] += transcript_dedup.FINAL_TRANSCRIPT_DEDUP_WINDOW_SECONDS + 0.1
    second = await stream.__anext__()
    assert second.alternatives[0].text == "Are you there?"


@pytest.mark.asyncio
async def test_dedup_stream_passes_empty_finals_through():
    final = livekit_stt.SpeechEventType.FINAL_TRANSCRIPT
    stream = FinalTranscriptDedupStream(
        FakeRecognizeStream(
            [
                _speech_event(final, ""),
                _speech_event(final, ""),
            ]
        ),
        provider="test",
    )

    events = await _collect(stream)
    assert len(events) == 2
