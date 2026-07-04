"""Verbose diagnostic logging for LiveKit room events."""

import logging

from livekit import rtc

from openbase_coder_cli.livekit_agent.logging_utils import _event_text_hash

logger = logging.getLogger(__name__)


def _track_log_fields(track=None, publication=None) -> dict[str, str]:
    source = publication if publication is not None else track
    return {
        "track_sid": str(getattr(source, "sid", "") or ""),
        "track_name": str(getattr(source, "name", "") or ""),
        "track_kind": str(getattr(source, "kind", "") or ""),
        "track_source": str(getattr(source, "source", "") or ""),
        "mime_type": str(getattr(source, "mime_type", "") or ""),
        "muted": str(getattr(source, "muted", "")),
        "subscribed": str(getattr(publication, "subscribed", ""))
        if publication is not None
        else "",
    }


def _participant_log_fields(participant=None) -> dict[str, str]:
    return {
        "participant_identity": str(getattr(participant, "identity", "") or ""),
        "participant_sid": str(getattr(participant, "sid", "") or ""),
        "participant_name": str(getattr(participant, "name", "") or ""),
        "participant_kind": str(getattr(participant, "kind", "") or ""),
    }


def _register_room_diagnostics(room: rtc.Room):
    def on_participant_connected(participant) -> None:
        fields = _participant_log_fields(participant)
        logger.info(
            "dispatch_timing stage=room_participant_connected "
            "participant_identity=%s participant_sid=%s participant_name=%s "
            "participant_kind=%s publication_count=%d",
            fields["participant_identity"],
            fields["participant_sid"],
            fields["participant_name"],
            fields["participant_kind"],
            len(getattr(participant, "track_publications", {}) or {}),
        )

    def on_participant_disconnected(participant) -> None:
        fields = _participant_log_fields(participant)
        logger.info(
            "dispatch_timing stage=room_participant_disconnected "
            "participant_identity=%s participant_sid=%s participant_name=%s "
            "participant_kind=%s disconnect_reason=%s",
            fields["participant_identity"],
            fields["participant_sid"],
            fields["participant_name"],
            fields["participant_kind"],
            getattr(participant, "disconnect_reason", ""),
        )

    def on_track_published(publication, participant) -> None:
        participant_fields = _participant_log_fields(participant)
        track_fields = _track_log_fields(publication=publication)
        logger.info(
            "dispatch_timing stage=room_track_published participant_identity=%s "
            "participant_sid=%s track_sid=%s track_name=%s track_kind=%s "
            "track_source=%s mime_type=%s muted=%s subscribed=%s",
            participant_fields["participant_identity"],
            participant_fields["participant_sid"],
            track_fields["track_sid"],
            track_fields["track_name"],
            track_fields["track_kind"],
            track_fields["track_source"],
            track_fields["mime_type"],
            track_fields["muted"],
            track_fields["subscribed"],
        )

    def on_track_subscribed(track, publication, participant) -> None:
        participant_fields = _participant_log_fields(participant)
        track_fields = _track_log_fields(track=track, publication=publication)
        logger.info(
            "dispatch_timing stage=room_track_subscribed participant_identity=%s "
            "participant_sid=%s track_sid=%s track_name=%s track_kind=%s "
            "track_source=%s mime_type=%s muted=%s subscribed=%s track_class=%s",
            participant_fields["participant_identity"],
            participant_fields["participant_sid"],
            track_fields["track_sid"],
            track_fields["track_name"],
            track_fields["track_kind"],
            track_fields["track_source"],
            track_fields["mime_type"],
            track_fields["muted"],
            track_fields["subscribed"],
            type(track).__name__,
        )

    def on_track_unsubscribed(track, publication, participant) -> None:
        participant_fields = _participant_log_fields(participant)
        track_fields = _track_log_fields(track=track, publication=publication)
        logger.info(
            "dispatch_timing stage=room_track_unsubscribed participant_identity=%s "
            "participant_sid=%s track_sid=%s track_name=%s track_kind=%s "
            "track_source=%s mime_type=%s track_class=%s",
            participant_fields["participant_identity"],
            participant_fields["participant_sid"],
            track_fields["track_sid"],
            track_fields["track_name"],
            track_fields["track_kind"],
            track_fields["track_source"],
            track_fields["mime_type"],
            type(track).__name__,
        )

    def on_track_subscription_failed(participant, track_sid, error) -> None:
        participant_fields = _participant_log_fields(participant)
        logger.warning(
            "dispatch_timing stage=room_track_subscription_failed "
            "participant_identity=%s participant_sid=%s track_sid=%s error=%s",
            participant_fields["participant_identity"],
            participant_fields["participant_sid"],
            track_sid,
            error,
        )

    def on_track_muted(publication, participant) -> None:
        participant_fields = _participant_log_fields(participant)
        track_fields = _track_log_fields(publication=publication)
        logger.info(
            "dispatch_timing stage=room_track_muted participant_identity=%s "
            "participant_sid=%s track_sid=%s track_name=%s track_kind=%s "
            "track_source=%s",
            participant_fields["participant_identity"],
            participant_fields["participant_sid"],
            track_fields["track_sid"],
            track_fields["track_name"],
            track_fields["track_kind"],
            track_fields["track_source"],
        )

    def on_track_unmuted(publication, participant) -> None:
        participant_fields = _participant_log_fields(participant)
        track_fields = _track_log_fields(publication=publication)
        logger.info(
            "dispatch_timing stage=room_track_unmuted participant_identity=%s "
            "participant_sid=%s track_sid=%s track_name=%s track_kind=%s "
            "track_source=%s",
            participant_fields["participant_identity"],
            participant_fields["participant_sid"],
            track_fields["track_sid"],
            track_fields["track_name"],
            track_fields["track_kind"],
            track_fields["track_source"],
        )

    def on_active_speakers_changed(speakers) -> None:
        identities = [
            str(getattr(participant, "identity", "") or "") for participant in speakers
        ]
        logger.info(
            "dispatch_timing stage=room_active_speakers_changed count=%d identities=%s",
            len(identities),
            ",".join(identities),
        )

    def on_connection_state_changed(connection_state) -> None:
        logger.info(
            "dispatch_timing stage=room_connection_state_changed state=%s",
            connection_state,
        )

    def on_transcription_received(segments, participant, publication) -> None:
        participant_fields = _participant_log_fields(participant)
        track_fields = _track_log_fields(publication=publication)
        for segment in segments:
            text = str(getattr(segment, "text", "") or "")
            logger.info(
                "dispatch_timing stage=room_transcription_received "
                "participant_identity=%s participant_sid=%s track_sid=%s "
                "segment_id=%s final=%s text_len=%d text_hash=%s text_excerpt=%r",
                participant_fields["participant_identity"],
                participant_fields["participant_sid"],
                track_fields["track_sid"],
                getattr(segment, "id", ""),
                getattr(segment, "final", ""),
                len(text),
                _event_text_hash(text),
                text[:160],
            )

    handlers = (
        ("participant_connected", on_participant_connected),
        ("participant_disconnected", on_participant_disconnected),
        ("track_published", on_track_published),
        ("track_subscribed", on_track_subscribed),
        ("track_unsubscribed", on_track_unsubscribed),
        ("track_subscription_failed", on_track_subscription_failed),
        ("track_muted", on_track_muted),
        ("track_unmuted", on_track_unmuted),
        ("active_speakers_changed", on_active_speakers_changed),
        ("connection_state_changed", on_connection_state_changed),
        ("transcription_received", on_transcription_received),
    )
    for event_name, handler in handlers:
        room.on(event_name, handler)

    for participant in (room.remote_participants or {}).values():
        on_participant_connected(participant)
        for publication in (participant.track_publications or {}).values():
            on_track_published(publication, participant)
            if getattr(publication, "subscribed", False):
                track = getattr(publication, "track", None)
                if track is not None:
                    on_track_subscribed(track, publication, participant)
                else:
                    participant_fields = _participant_log_fields(participant)
                    track_fields = _track_log_fields(publication=publication)
                    logger.info(
                        "dispatch_timing stage=room_track_already_subscribed "
                        "participant_identity=%s participant_sid=%s track_sid=%s "
                        "track_name=%s track_kind=%s track_source=%s mime_type=%s",
                        participant_fields["participant_identity"],
                        participant_fields["participant_sid"],
                        track_fields["track_sid"],
                        track_fields["track_name"],
                        track_fields["track_kind"],
                        track_fields["track_source"],
                        track_fields["mime_type"],
                    )

    return handlers
