"""Agent service tier settings API views."""

from __future__ import annotations

from rest_framework import serializers, status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from openbase_coder_cli import dispatcher_config
from openbase_coder_cli.cli.setup import _upsert_env_file_values
from openbase_coder_cli.paths import DEFAULT_ENV_FILE_PATH

SERVICE_TIER_OPTIONS = ("fast", "standard")
SERVICE_TIER_DETAILS = {
    "fast": {
        "label": "Fast",
        "summary": "Use the faster service tier for Codex and the lower-effort lane for Claude.",
    },
    "standard": {
        "label": "Standard",
        "summary": "Use the standard Codex service tier and the higher-effort lane for Claude.",
    },
}


class ServiceTierSettingsSerializer(serializers.Serializer):
    codex_service_tier = serializers.ChoiceField(choices=SERVICE_TIER_OPTIONS)


def _service_tier_payload(*, changed: bool = False) -> dict:
    service_tier = dispatcher_config.codex_service_tier()
    return {
        "codex_service_tier": service_tier,
        "effective": {"codex_service_tier": service_tier},
        "options": [
            {"id": option, **SERVICE_TIER_DETAILS[option]}
            for option in SERVICE_TIER_OPTIONS
        ],
        "config_path": str(dispatcher_config.CODEX_DISPATCHER_CONFIG_PATH),
        "config_exists": dispatcher_config.CODEX_DISPATCHER_CONFIG_PATH.is_file(),
        "env_file_exists": DEFAULT_ENV_FILE_PATH.is_file(),
        "changed": changed,
        "restart_required": changed,
        "restart_hint": "Restart Openbase services for Codex app-server defaults to pick up the change. New LiveKit turns use the selected tier after the voice agent restarts.",
    }


@api_view(["GET", "PUT"])
def service_tier_settings(request):
    """Read or update the agent service tier used for new turns."""
    if request.method == "GET":
        return Response(_service_tier_payload(), status=status.HTTP_200_OK)

    serializer = ServiceTierSettingsSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    previous = dispatcher_config.codex_service_tier()
    next_tier = serializer.validated_data["codex_service_tier"]
    try:
        dispatcher_config.set_codex_service_tier(next_tier)
        DEFAULT_ENV_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _upsert_env_file_values(DEFAULT_ENV_FILE_PATH, {"CODEX_SERVICE_TIER": next_tier})
    except ValueError as exc:
        return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(
        _service_tier_payload(changed=previous != next_tier),
        status=status.HTTP_200_OK,
    )
