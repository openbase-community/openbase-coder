"""Coding backend settings API views."""

from __future__ import annotations

from rest_framework import serializers, status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from openbase_coder_cli.backend_config import (
    DEFAULT_CODING_BACKEND,
    SUPPORTED_BACKENDS,
    normalize_backend,
)
from openbase_coder_cli.cli.backend import read_backend, write_backend
from openbase_coder_cli.paths import DEFAULT_ENV_FILE_PATH

BACKEND_OPTIONS = {
    "claude-agent-sdk": {
        "label": "Claude Agent SDK",
        "summary": "Direct Claude backend.",
        "description": "Uses local Claude auth and billing through the Agent SDK for Super Agents UI-driver sessions; ANTHROPIC_API_KEY is not supported.",
    },
    "claude-tui": {
        "label": "Claude Code TUI",
        "summary": "No Anthropic API key required.",
        "description": "Uses your local Claude Code CLI/TUI login directly for Super Agents UI-driver sessions.",
    },
    "codex": {
        "label": "Codex",
        "summary": "Native OpenAI Codex app-server.",
        "description": "Uses codex-app-server for native OpenAI Codex sessions.",
    },
}


class CodingBackendSerializer(serializers.Serializer):
    backend = serializers.ChoiceField(choices=SUPPORTED_BACKENDS)


def _restart_hint(backend: str) -> str:
    if backend == "codex":
        return "Restart or recreate the dispatcher/MCP host for Super Agents to pick up the change."
    return "Restart or recreate the dispatcher/MCP host for the Claude backend to pick up the change; keep Openbase services running."


def _backend_payload(*, changed: bool = False) -> dict:
    backend = read_backend(DEFAULT_ENV_FILE_PATH)
    return {
        "backend": backend,
        "default_backend": DEFAULT_CODING_BACKEND,
        "supported_backends": [
            {
                "id": backend_name,
                **BACKEND_OPTIONS[backend_name],
            }
            for backend_name in SUPPORTED_BACKENDS
        ],
        "env_file_exists": DEFAULT_ENV_FILE_PATH.is_file(),
        "changed": changed,
        "restart_required": changed,
        "restart_hint": _restart_hint(backend),
    }


@api_view(["GET", "PUT"])
def coding_backend_settings(request):
    """Read or update the coding backend used by Super Agents."""
    if request.method == "GET":
        return Response(_backend_payload())

    serializer = CodingBackendSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    previous_backend = read_backend(DEFAULT_ENV_FILE_PATH)
    next_backend = normalize_backend(serializer.validated_data["backend"])
    try:
        write_backend(DEFAULT_ENV_FILE_PATH, next_backend)
    except ValueError as exc:
        return Response(
            {"error": str(exc)},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return Response(_backend_payload(changed=previous_backend != next_backend))
