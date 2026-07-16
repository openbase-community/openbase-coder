"""Coding backend settings API views."""

from __future__ import annotations

from rest_framework import serializers, status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from openbase_coder_cli.backend_config import (
    CLAUDE_CODE_BACKEND,
    CODEX_BACKEND,
    DEFAULT_CODING_BACKEND,
    OPENBASE_CLOUD_BACKEND,
    normalize_backend,
)
from openbase_coder_cli.claude_auth import (
    claude_auth_status,
    copy_normal_claude_keychain,
    sync_normal_claude_state,
)
from openbase_coder_cli.cli.backend import read_backend, write_backend
from openbase_coder_cli.paths import DEFAULT_ENV_FILE_PATH

BACKEND_OPTIONS = {
    "codex": {
        "label": "Codex",
        "summary": "Native OpenAI Codex app-server.",
        "description": "Uses Codex app-server directly with OpenAI models.",
    },
    "openbase_cloud": {
        "label": "Openbase Cloud",
        "summary": "Managed Openbase model proxy.",
        "description": "Uses your Openbase login with the Openbase Cloud model proxy for Codex-compatible sessions.",
    },
    "claude_code": {
        "label": "Claude Code",
        "summary": "Claude Code Agent SDK.",
        "description": "Uses local Claude auth and billing through the Claude Code Agent SDK for Super Agents UI-driver sessions.",
    },
}

SELECTABLE_BACKENDS = (CODEX_BACKEND, OPENBASE_CLOUD_BACKEND, CLAUDE_CODE_BACKEND)


class CodingBackendSerializer(serializers.Serializer):
    backend = serializers.ChoiceField(choices=SELECTABLE_BACKENDS)


def _restart_hint(backend: str) -> str:
    if backend in {"codex", "openbase_cloud"}:
        return "Restart or recreate the dispatcher/MCP host for Super Agents to pick up the change."
    return "Restart or recreate the dispatcher/MCP host for Claude Code to pick up the change; keep Openbase services running."


def _backend_note(backend: str) -> str | None:
    if backend == OPENBASE_CLOUD_BACKEND:
        return "Codex is configured to use the Openbase Cloud model proxy."
    return None


def _claude_auth_payload(*, sync: bool = False) -> dict:
    state_updated = False
    keychain_copied = False
    message = None
    if sync:
        sync_result = sync_normal_claude_state()
        state_updated = sync_result.state_updated
        message = sync_result.message
        keychain_copied = copy_normal_claude_keychain()

    status_result = claude_auth_status()
    if sync and not status_result.logged_in and keychain_copied:
        status_result = claude_auth_status()

    return {
        "command": "openbase-coder claude sync-state",
        "logged_in": status_result.logged_in,
        "raw_output": status_result.raw_output,
        "returncode": status_result.returncode,
        "state_updated": state_updated,
        "keychain_copied": keychain_copied,
        "message": message,
    }


def _backend_payload(*, changed: bool = False) -> dict:
    configured_backend = read_backend(DEFAULT_ENV_FILE_PATH)
    payload = {
        "backend": configured_backend,
        "configured_backend": configured_backend,
        "codex_provider": "openbase_cloud"
        if configured_backend == OPENBASE_CLOUD_BACKEND
        else "direct",
        "backend_note": _backend_note(configured_backend),
        "default_backend": DEFAULT_CODING_BACKEND,
        "supported_backends": [
            {
                "id": backend_name,
                **BACKEND_OPTIONS[backend_name],
            }
            for backend_name in SELECTABLE_BACKENDS
        ],
        "env_file_exists": DEFAULT_ENV_FILE_PATH.is_file(),
        "changed": changed,
        "restart_required": changed,
        "restart_hint": _restart_hint(configured_backend),
    }
    if configured_backend == CLAUDE_CODE_BACKEND:
        payload["claude_auth"] = _claude_auth_payload()
    return payload


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


@api_view(["GET", "POST"])
def claude_auth_settings(request):
    """Read or sync Openbase's managed Claude Code auth status."""
    configured_backend = read_backend(DEFAULT_ENV_FILE_PATH)
    if configured_backend != CLAUDE_CODE_BACKEND:
        return Response(
            {
                "error": "Claude auth settings are available only when the coding backend is Claude Code.",
                "backend": configured_backend,
            },
            status=status.HTTP_400_BAD_REQUEST,
        )
    return Response(_claude_auth_payload(sync=request.method == "POST"))
