from __future__ import annotations

import os
from typing import Any

from openbase_coder_cli.backend_config import (
    CLAUDE_CODE_BACKEND,
    CODING_BACKEND_ENV_KEY,
    normalize_backend,
)

try:
    from super_agents.backend_clients import (  # type: ignore[import-not-found]
        backend_from_environment,
        client_from_environment,
    )
except ModuleNotFoundError as exc:
    if exc.name != "super_agents.backend_clients":
        raise

    from super_agents.app_server_client import CodexAppServerClient

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

    def backend_from_environment() -> str:
        return normalize_backend(os.getenv(CODING_BACKEND_ENV_KEY))

    def client_from_environment() -> Any:
        backend = backend_from_environment()
        if backend == CLAUDE_CODE_BACKEND:
            raise RuntimeError(
                "The installed super-agents package does not include Claude Code "
                "backend support. Update super-agents, or set "
                f"{CODING_BACKEND_ENV_KEY}=codex."
            )
        return _CompatCodexAppServerClient()
