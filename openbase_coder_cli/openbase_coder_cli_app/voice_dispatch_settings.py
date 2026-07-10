"""Voice dispatch provider settings API views.

Selects how voice calls reach a dispatcher agent: the local LiveKit stack
(the default vanilla behavior) or hosted VocalBridge dispatch. The provider
choice lives in the dispatcher config JSON; VocalBridge credentials live in
the Openbase env file and are never echoed back to clients.
"""

from __future__ import annotations

from rest_framework import serializers, status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from openbase_coder_cli import dispatcher_config
from openbase_coder_cli.env_file import upsert_env_file_values
from openbase_coder_cli.paths import DEFAULT_ENV_FILE_PATH
from openbase_coder_cli.vocalbridge.config import (
    DEFAULT_VOCALBRIDGE_API_URL,
    VOCALBRIDGE_AGENT_ID_ENV,
    VOCALBRIDGE_API_KEY_ENV,
    VOCALBRIDGE_API_URL_ENV,
    vocalbridge_agent_id,
    vocalbridge_api_key,
    vocalbridge_api_url,
)

VOICE_DISPATCH_PROVIDER_DETAILS = {
    dispatcher_config.LIVEKIT_VOICE_DISPATCH_PROVIDER: {
        "label": "Local LiveKit",
        "summary": "The built-in voice pipeline on this machine.",
        "description": (
            "Calls connect to the local LiveKit server and the full Openbase "
            "Coder dispatcher answers directly."
        ),
    },
    dispatcher_config.VOCALBRIDGE_VOICE_DISPATCH_PROVIDER: {
        "label": "VocalBridge",
        "summary": "Hosted VocalBridge voice agent with a restricted dispatcher.",
        "description": (
            "Calls connect to your VocalBridge voice agent, which handles "
            "speech and delegates dispatch questions to a restricted local "
            "agent that can only coordinate Super Agents and explore the "
            "file system read-only."
        ),
    },
}


class VoiceDispatchSettingsSerializer(serializers.Serializer):
    provider = serializers.ChoiceField(
        choices=sorted(dispatcher_config.VOICE_DISPATCH_PROVIDERS),
        required=False,
    )
    vocalbridge_api_key = serializers.CharField(
        required=False, allow_blank=True, trim_whitespace=True, max_length=512
    )
    vocalbridge_agent_id = serializers.CharField(
        required=False, allow_blank=True, trim_whitespace=True, max_length=256
    )
    vocalbridge_api_url = serializers.CharField(
        required=False, allow_blank=True, trim_whitespace=True, max_length=512
    )


def _voice_dispatch_payload(*, changed: bool = False) -> dict:
    provider = dispatcher_config.voice_dispatch_provider()
    return {
        "provider": provider,
        "default_provider": dispatcher_config.DEFAULT_VOICE_DISPATCH_PROVIDER,
        "providers": [
            {"id": provider_id, **VOICE_DISPATCH_PROVIDER_DETAILS[provider_id]}
            for provider_id in (
                dispatcher_config.LIVEKIT_VOICE_DISPATCH_PROVIDER,
                dispatcher_config.VOCALBRIDGE_VOICE_DISPATCH_PROVIDER,
            )
        ],
        "vocalbridge": {
            "api_key_configured": bool(vocalbridge_api_key()),
            "agent_id": vocalbridge_agent_id(),
            "api_url": vocalbridge_api_url(),
            "default_api_url": DEFAULT_VOCALBRIDGE_API_URL,
        },
        "changed": changed,
        "restart_required": False,
        "restart_hint": "New calls use the selected provider immediately.",
    }


@api_view(["GET", "PUT"])
def voice_dispatch_settings(request):
    """Read or update the voice dispatch provider and VocalBridge settings."""
    if request.method == "GET":
        return Response(_voice_dispatch_payload(), status=status.HTTP_200_OK)

    serializer = VoiceDispatchSettingsSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    if not data:
        return Response(
            {
                "error": (
                    "Provide provider, vocalbridge_api_key, "
                    "vocalbridge_agent_id, or vocalbridge_api_url."
                )
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    env_updates: dict[str, str] = {}
    if "vocalbridge_api_key" in data:
        env_updates[VOCALBRIDGE_API_KEY_ENV] = data["vocalbridge_api_key"]
    if "vocalbridge_agent_id" in data:
        env_updates[VOCALBRIDGE_AGENT_ID_ENV] = data["vocalbridge_agent_id"]
    if "vocalbridge_api_url" in data:
        env_updates[VOCALBRIDGE_API_URL_ENV] = data["vocalbridge_api_url"].rstrip("/")
    if env_updates:
        DEFAULT_ENV_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        upsert_env_file_values(DEFAULT_ENV_FILE_PATH, env_updates)

    previous_provider = dispatcher_config.voice_dispatch_provider()
    requested_provider = data.get("provider") or previous_provider
    if (
        requested_provider == dispatcher_config.VOCALBRIDGE_VOICE_DISPATCH_PROVIDER
        and not vocalbridge_api_key()
    ):
        return Response(
            {
                "error": (
                    "Add a VocalBridge API key before switching voice "
                    "dispatch to VocalBridge."
                )
            },
            status=status.HTTP_400_BAD_REQUEST,
        )
    if "provider" in data:
        try:
            dispatcher_config.set_voice_dispatch_provider(data["provider"])
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    return Response(
        _voice_dispatch_payload(
            changed=dispatcher_config.voice_dispatch_provider() != previous_provider
            or bool(env_updates)
        ),
        status=status.HTTP_200_OK,
    )
