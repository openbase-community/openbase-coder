"""The restricted Super Agents client behind VocalBridge dispatch.

The VocalBridge voice agent owns the conversation; this client only answers
delegated queries. It runs with a read-only sandbox so the dispatcher can
coordinate Super Agents over MCP and explore the file system, but cannot do
coding work itself.
"""

from __future__ import annotations

import os

from openbase_coder_cli.dispatcher_config import dispatcher_service_tier
from openbase_coder_cli.livekit_agent.super_agents_client import (
    SuperAgentsLiveKitClient,
)
from openbase_coder_cli.paths import VOCALBRIDGE_THREAD_STATE_PATH
from openbase_coder_cli.vocalbridge.config import (
    load_vocalbridge_dispatcher_instructions,
)

VOCALBRIDGE_DISPATCHER_LABEL = "vocalbridge-dispatcher"
VOCALBRIDGE_DISPATCHER_SANDBOX = "read-only"


def build_vocalbridge_dispatcher_client() -> SuperAgentsLiveKitClient:
    return SuperAgentsLiveKitClient(
        cwd=os.environ.get("LIVEKIT_CODEX_THREAD_CWD") or os.path.expanduser("~"),
        state_path=str(VOCALBRIDGE_THREAD_STATE_PATH),
        developer_instructions=load_vocalbridge_dispatcher_instructions(),
        approval_policy="never",
        sandbox=VOCALBRIDGE_DISPATCHER_SANDBOX,
        service_tier=dispatcher_service_tier(),
        persist_thread=True,
        super_agent_name=VOCALBRIDGE_DISPATCHER_LABEL,
    )
