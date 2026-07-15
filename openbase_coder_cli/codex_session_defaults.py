"""Shared Codex thread and turn permission defaults."""

from __future__ import annotations

import os
from collections.abc import Mapping

CODEX_APPROVAL_POLICY_ENV = "LIVEKIT_CODEX_APPROVAL_POLICY"
CODEX_SANDBOX_ENV = "LIVEKIT_CODEX_SANDBOX"
DEFAULT_CODEX_APPROVAL_POLICY = "never"
DEFAULT_CODEX_SANDBOX = "danger-full-access"


def codex_permission_defaults(
    env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    values = os.environ if env is None else env
    return {
        "approvalPolicy": values.get(
            CODEX_APPROVAL_POLICY_ENV,
            DEFAULT_CODEX_APPROVAL_POLICY,
        ),
        "sandbox": values.get(CODEX_SANDBOX_ENV, DEFAULT_CODEX_SANDBOX),
    }
