"""Compatibility boundary for APIs owned by the sibling ``super-agents`` package.

Prefer the canonical ``super_agents.backend_clients`` and
``super_agents.app_permissions.permission_response_for_request`` implementations
whenever they are installed. The fallback code only covers older/editable local
``super-agents`` checkouts that predate those exports; it should not become a
second source of truth for newer backend behavior.
"""

from __future__ import annotations

import os
from typing import Any

from super_agents.app_server_client import CodexAppServerClient

from openbase_coder_cli.backend_config import (
    CLAUDE_CODE_BACKEND,
    CODING_BACKEND_ENV_KEY,
    normalize_backend,
)


def _compat_permission_response_for_request(
    request: Any,
    decision: str,
) -> dict[str, Any]:
    method = (
        request.get("method", "")
        if isinstance(request, dict)
        else getattr(request, "method", "")
    )
    if str(method) == "mcpServer/elicitation/request":
        return {"action": decision, "content": None, "_meta": None}
    return {"decision": decision}


class _CompatCodexAppServerClient(CodexAppServerClient):
    backend = "codex"

    async def resume_thread(
        self,
        thread_id: str,
        *,
        label: str | None = None,
        agent_name: str | None = None,
        developer_instructions: str | None = None,
    ) -> dict[str, Any]:
        del agent_name
        return await super().resume_thread(
            thread_id,
            label=label,
            developer_instructions=developer_instructions,
        )

    async def steer_by_label(
        self,
        input_data: Any,
        prompt: str,
        turn_input: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del turn_input
        return await super().steer_by_label(input_data, prompt)


def _compat_backend_from_environment() -> str:
    return normalize_backend(os.getenv(CODING_BACKEND_ENV_KEY))


def _compat_client_from_environment() -> Any:
    backend = _compat_backend_from_environment()
    if backend == CLAUDE_CODE_BACKEND:
        raise RuntimeError(
            "The installed super-agents package does not include Claude Code "
            "backend support. Update super-agents, or set "
            f"{CODING_BACKEND_ENV_KEY}=codex."
        )
    return _CompatCodexAppServerClient()


try:
    from super_agents.app_permissions import (
        permission_response_for_request,  # type: ignore[attr-defined]
    )
except ImportError as exc:
    if exc.name != "super_agents.app_permissions":
        raise
    permission_response_for_request = _compat_permission_response_for_request


try:
    from super_agents.backend_clients import (  # type: ignore[import-not-found]
        backend_from_environment,
        client_from_environment,
    )
except ModuleNotFoundError as exc:
    if exc.name != "super_agents.backend_clients":
        raise
    backend_from_environment = _compat_backend_from_environment
    client_from_environment = _compat_client_from_environment
