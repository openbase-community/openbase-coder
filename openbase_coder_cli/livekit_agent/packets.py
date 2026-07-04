"""Parsing of announcer and voice-route data packets from the LiveKit room."""

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass

from livekit import rtc

from openbase_coder_cli.livekit_agent.config import (
    ANNOUNCER_AUDIO_KIND,
    ANNOUNCER_TOPIC,
    VOICE_ROUTE_TOPIC,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AnnouncerMessage:
    message_id: str
    text: str
    voice_id: str | None = None


@dataclass(frozen=True)
class AnnouncerAudioMessage:
    message_id: str
    audio_path: str


AnnouncerQueueItem = AnnouncerMessage | AnnouncerAudioMessage


@dataclass(frozen=True)
class QueuedAnnouncerItem:
    message: AnnouncerQueueItem
    enqueued_at: float


@dataclass(frozen=True)
class VoiceRouteCommand:
    action: str
    thread_id: str | None = None
    cwd: str | None = None
    label: str | None = None
    active_target_voice_id: str | None = None
    active_target_voice_name: str | None = None


def _packet_json_payload(
    data_packet: rtc.DataPacket,
    *,
    topic: str,
    label: str,
) -> dict | None:
    if data_packet.topic != topic:
        return None

    try:
        payload = json.loads(data_packet.data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        logger.warning(
            "dispatch_timing stage=data_packet_malformed label=%s topic=%s "
            "payload_bytes=%d payload_hash=%s",
            label,
            data_packet.topic,
            len(data_packet.data),
            _packet_hash(data_packet),
        )
        return None

    if not isinstance(payload, dict):
        logger.warning(
            "dispatch_timing stage=data_packet_unexpected_payload label=%s topic=%s "
            "payload_type=%s payload_bytes=%d payload_hash=%s",
            label,
            data_packet.topic,
            type(payload).__name__,
            len(data_packet.data),
            _packet_hash(data_packet),
        )
        return None

    return payload


def parse_announcer_packet(data_packet: rtc.DataPacket) -> AnnouncerMessage | None:
    payload = _packet_json_payload(
        data_packet,
        topic=ANNOUNCER_TOPIC,
        label="announcer",
    )
    if payload is None:
        return None
    if payload.get("kind") == ANNOUNCER_AUDIO_KIND:
        return None

    text = str(payload.get("text") or "").strip()
    if not text:
        logger.warning(
            "dispatch_timing stage=announcer_packet_missing_text topic=%s "
            "payload_bytes=%d payload_hash=%s",
            data_packet.topic,
            len(data_packet.data),
            _packet_hash(data_packet),
        )
        return None

    message_id = str(payload.get("message_id") or f"announcer-{uuid.uuid4().hex}")
    return AnnouncerMessage(
        message_id=message_id,
        text=text,
        voice_id=_optional_packet_str(payload.get("voice_id")),
    )


def parse_announcer_audio_packet(
    data_packet: rtc.DataPacket,
) -> AnnouncerAudioMessage | None:
    payload = _packet_json_payload(
        data_packet,
        topic=ANNOUNCER_TOPIC,
        label="announcer audio",
    )
    if payload is None or payload.get("kind") != ANNOUNCER_AUDIO_KIND:
        return None

    audio_path = str(payload.get("audio_path") or "").strip()
    if not audio_path:
        logger.warning(
            "dispatch_timing stage=announcer_audio_packet_missing_path topic=%s "
            "payload_bytes=%d payload_hash=%s",
            data_packet.topic,
            len(data_packet.data),
            _packet_hash(data_packet),
        )
        return None

    message_id = str(payload.get("message_id") or f"announcer-audio-{uuid.uuid4().hex}")
    return AnnouncerAudioMessage(
        message_id=message_id,
        audio_path=audio_path,
    )


def _packet_participant_identity(data_packet: rtc.DataPacket) -> str:
    participant = getattr(data_packet, "participant", None)
    return str(getattr(participant, "identity", "") or "")


def _packet_hash(data_packet: rtc.DataPacket) -> str:
    return hashlib.sha256(data_packet.data).hexdigest()[:12]


def parse_voice_route_packet(data_packet: rtc.DataPacket) -> VoiceRouteCommand | None:
    payload = _packet_json_payload(
        data_packet,
        topic=VOICE_ROUTE_TOPIC,
        label="voice route",
    )
    if payload is None:
        return None

    action = str(payload.get("action") or "").strip()
    if not action:
        return None
    state = payload.get("state") if isinstance(payload.get("state"), dict) else {}
    return VoiceRouteCommand(
        action=action,
        thread_id=_optional_packet_str(payload.get("thread_id")),
        cwd=_optional_packet_str(payload.get("cwd")),
        label=_optional_packet_str(payload.get("label")),
        active_target_voice_id=_optional_packet_str(
            state.get("active_target_voice_id")
        ),
        active_target_voice_name=_optional_packet_str(
            state.get("active_target_voice_name")
        )
        or _optional_packet_str(payload.get("agent_name")),
    )


def _optional_packet_str(value) -> str | None:
    return value if isinstance(value, str) and value else None
