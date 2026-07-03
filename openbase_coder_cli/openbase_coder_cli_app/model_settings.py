"""Backend model settings API views."""

from __future__ import annotations

from rest_framework import serializers, status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from openbase_coder_cli import dispatcher_config
from openbase_coder_cli.backend_config import normalize_backend
from openbase_coder_cli.cli.backend import read_backend
from openbase_coder_cli.paths import DEFAULT_ENV_FILE_PATH


class BackendModelSerializer(serializers.Serializer):
    backend = serializers.CharField(required=False, allow_blank=True)
    role = serializers.ChoiceField(
        choices=(
            dispatcher_config.DISPATCHER_MODEL_ROLE,
            dispatcher_config.SUPER_AGENTS_MODEL_ROLE,
        ),
        default=dispatcher_config.SUPER_AGENTS_MODEL_ROLE,
    )
    model = serializers.CharField()


def _backend_model_payload(*, changed: bool = False) -> dict:
    configured_backend = read_backend(DEFAULT_ENV_FILE_PATH)
    options = dispatcher_config.model_options_for_backend(configured_backend)
    return {
        "backend": configured_backend,
        "models": {
            "dispatcher": dispatcher_config.backend_model(
                dispatcher_config.DISPATCHER_MODEL_ROLE,
                backend=configured_backend,
            ),
            "super_agents": dispatcher_config.backend_model(
                dispatcher_config.SUPER_AGENTS_MODEL_ROLE,
                backend=configured_backend,
            ),
        },
        "effective": {
            "dispatcher": dispatcher_config.backend_model(
                dispatcher_config.DISPATCHER_MODEL_ROLE,
                backend=configured_backend,
            )
            or "backend default",
            "super_agents": dispatcher_config.backend_model(
                dispatcher_config.SUPER_AGENTS_MODEL_ROLE,
                backend=configured_backend,
            )
            or "backend default",
        },
        "options": list(options),
        "allows_custom": not options,
        "config_path": str(dispatcher_config.CODEX_DISPATCHER_CONFIG_PATH),
        "changed": changed,
        "restart_required": changed,
        "restart_hint": "Restart or recreate the dispatcher/MCP host for model changes to apply.",
    }


@api_view(["GET", "PUT"])
def backend_model_settings(request):
    """Read or update backend-specific dispatcher/Super Agents model settings."""
    if request.method == "GET":
        return Response(_backend_model_payload())

    serializer = BackendModelSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    role = serializer.validated_data["role"]
    model = serializer.validated_data["model"]
    backend = normalize_backend(
        serializer.validated_data.get("backend")
        or read_backend(DEFAULT_ENV_FILE_PATH)
    )
    options = dispatcher_config.model_options_for_backend(backend)
    if options and not dispatcher_config.is_known_backend_model(model, backend=backend):
        allowed = ", ".join(option["id"] for option in options)
        return Response(
            {"error": f"Model must be one of: {allowed}."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    previous = dispatcher_config.backend_model(role, backend=backend)
    try:
        dispatcher_config.set_backend_model(role, model, backend=backend)
    except ValueError as exc:
        return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(_backend_model_payload(changed=previous != " ".join(model.split())))
