"""Skill approval requests, backed by the openapprovals package.

Skills are the requesters in Openbase Coder, so this module keeps the
`skill_approval` naming as a stable surface for skills and the
`openbase-coder user approval` CLI while delegating the lifecycle to
openapprovals (where `skill` is the generic `requester`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import openapprovals
from openapprovals import (
    APPROVAL_DECISIONS,
    APPROVAL_METHOD,
    TERMINAL_DECISIONS,
)
from openapprovals import answer_approval_request as answer_skill_approval_request
from openapprovals import consume_approval_decision as consume_skill_approval_decision
from openapprovals import get_approval_decision as get_skill_approval_decision
from openapprovals import get_approval_request as get_skill_approval_request
from openapprovals import is_client_approval_request as is_skill_approval_request
from openapprovals import (
    is_pending_client_approval_request as is_pending_skill_approval_request,
)
from openapprovals import list_approval_requests as list_skill_approval_requests
from openapprovals import (
    normalize_approval_request as normalize_shared_approval_request,
)
from openapprovals import wait_for_approval as wait_for_skill_approval

__all__ = [
    "APPROVAL_DECISIONS",
    "APPROVAL_METHOD",
    "TERMINAL_DECISIONS",
    "answer_skill_approval_request",
    "consume_skill_approval_decision",
    "create_skill_approval_request",
    "get_skill_approval_decision",
    "get_skill_approval_request",
    "is_pending_skill_approval_request",
    "is_skill_approval_request",
    "list_skill_approval_requests",
    "normalize_shared_approval_request",
    "request_approval",
    "wait_for_skill_approval",
]


def create_skill_approval_request(
    *,
    skill: str,
    action: str,
    description: str,
    details: dict[str, Any] | None = None,
    command: str | None = None,
    timeout_seconds: float | None = None,
    path: Path | str | None = None,
) -> dict[str, Any]:
    """Create a skill approval in the same shared queue used by Codex requests."""
    return openapprovals.create_approval_request(
        requester=skill,
        action=action,
        description=description,
        details=details,
        command=command,
        timeout_seconds=timeout_seconds,
        path=path,
    )


def request_approval(
    *,
    skill: str,
    action: str,
    description: str,
    details: dict[str, Any] | None = None,
    command: str | None = None,
    timeout_seconds: float = 300,
    poll_interval_seconds: float = 1,
) -> dict[str, Any]:
    """Request user approval through the local Openbase Coder server."""
    from openbase_coder_cli.cli.local_server import local_server_request

    return openapprovals.request_approval(
        local_server_request,
        requester=skill,
        action=action,
        description=description,
        details=details,
        command=command,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
    )
