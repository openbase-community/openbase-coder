from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, cast

from super_agents.app_server_client import (
    PendingServerRequest,
    clear_shared_permission_request,
    read_permission_store,
    record_shared_permission_request,
    shared_permission_requests,
    write_shared_permission_decision,
)

APPROVAL_METHOD = "openbaseSkill/requestApproval"
APPROVAL_DECISIONS = {"accept", "decline", "cancel"}
TERMINAL_DECISIONS = APPROVAL_DECISIONS | {"timeout"}


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
    request = PendingServerRequest(
        id=f"skill-{uuid.uuid4().hex}",
        method=APPROVAL_METHOD,
        params=_skill_approval_params(
            skill=skill,
            action=action,
            description=description,
            details=details,
            command=command,
            timeout_seconds=timeout_seconds,
        ),
        received_at=_now_iso(),
    )
    record_shared_permission_request(request, path)
    return normalize_shared_approval_request(request.to_json())


def list_skill_approval_requests(
    path: Path | str | None = None,
) -> list[dict[str, Any]]:
    """Return pending skill approvals from the shared queue."""
    return sorted(
        [
            normalize_shared_approval_request(request)
            for request in shared_permission_requests(path)
            if is_pending_skill_approval_request(request, path=path)
        ],
        key=lambda request: request.get("received_at", ""),
    )


def is_pending_skill_approval_request(
    request: dict[str, Any],
    *,
    path: Path | str | None = None,
) -> bool:
    """Whether a shared request is a not-yet-answered skill approval."""
    request_id = request.get("id")
    return (
        request_id is not None
        and is_skill_approval_request(request)
        and str(request_id) not in _decision_map(path)
    )


def is_skill_approval_request(request: dict[str, Any]) -> bool:
    params = request.get("params")
    return (
        isinstance(params, dict)
        and params.get("source") == "skill"
        and request.get("method") == APPROVAL_METHOD
    )


def normalize_shared_approval_request(request: dict[str, Any]) -> dict[str, Any]:
    params = request.get("params")
    params = params if isinstance(params, dict) else {}
    return {
        "id": request.get("id"),
        "method": request.get("method"),
        "params": params,
        "received_at": request.get("receivedAt") or request.get("received_at"),
        "thread_id": params.get("threadId") or params.get("thread_id"),
        "turn_id": params.get("turnId") or params.get("turn_id"),
    }


def get_skill_approval_request(
    request_id: str,
    path: Path | str | None = None,
) -> dict[str, Any] | None:
    request = _request_map(path).get(str(request_id))
    if request is None or not is_skill_approval_request(request):
        return None
    return normalize_shared_approval_request(request)


def get_skill_approval_decision(
    request_id: str,
    path: Path | str | None = None,
) -> dict[str, Any] | None:
    raw_decision = _decision_map(path).get(str(request_id))
    request = get_skill_approval_request(request_id, path)
    if raw_decision is None or request is None:
        return None
    decision = str(raw_decision.get("decision") or "")
    return _decision_record(
        request_id=request_id,
        decision=decision,
        request=request,
        answered_at=raw_decision.get("decidedAt") or raw_decision.get("answered_at"),
    )


def answer_skill_approval_request(
    request_id: str,
    decision: str,
    path: Path | str | None = None,
) -> dict[str, Any]:
    normalized_decision = _validate_decision(decision)
    request = get_skill_approval_request(request_id, path)
    if request is None:
        raise ValueError(f"approval request not found: {request_id}")
    write_shared_permission_decision(request_id, normalized_decision, path)
    decision_record = get_skill_approval_decision(request_id, path)
    if decision_record is None:
        raise ValueError(f"approval decision could not be recorded: {request_id}")
    return decision_record


def consume_skill_approval_decision(
    request_id: str,
    path: Path | str | None = None,
) -> dict[str, Any]:
    decision = get_skill_approval_decision(request_id, path)
    if decision is None:
        raise ValueError(f"approval decision not found: {request_id}")
    clear_shared_permission_request(request_id, path)
    return decision


def wait_for_skill_approval(
    request_id: str,
    *,
    timeout_seconds: float = 300,
    poll_interval_seconds: float = 1,
    path: Path | str | None = None,
) -> dict[str, Any]:
    deadline = time.monotonic() + max(timeout_seconds, 0)
    interval = max(poll_interval_seconds, 0.1)
    while True:
        decision = get_skill_approval_decision(request_id, path)
        if decision is not None:
            return consume_skill_approval_decision(request_id, path)

        if time.monotonic() >= deadline:
            timeout_decision = answer_skill_approval_request(request_id, "cancel", path)
            consume_skill_approval_decision(request_id, path)
            return {**timeout_decision, "decision": "timeout", "accepted": False}

        time.sleep(interval)


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

    payload: dict[str, Any] = {
        "skill": skill,
        "action": action,
        "description": description,
        "details": details or {},
        "timeout_seconds": timeout_seconds,
    }
    if command:
        payload["command"] = command

    response = local_server_request(
        "POST",
        "/api/skill-approval-requests/",
        json=payload,
    )
    request_id = response.json()["request"]["id"]
    deadline = time.monotonic() + max(timeout_seconds, 0)
    interval = max(poll_interval_seconds, 0.1)
    while True:
        status_response = local_server_request(
            "GET",
            f"/api/skill-approval-requests/{request_id}/",
        )
        status_payload = status_response.json()
        decision = status_payload.get("decision")
        if decision:
            consume_response = local_server_request(
                "POST",
                f"/api/skill-approval-requests/{request_id}/consume/",
            )
            return consume_response.json()["decision"]

        if time.monotonic() >= deadline:
            local_server_request(
                "POST",
                f"/api/approval-requests/{request_id}/",
                json={"decision": "cancel"},
            )
            consume_response = local_server_request(
                "POST",
                f"/api/skill-approval-requests/{request_id}/consume/",
            )
            decision = consume_response.json()["decision"]
            return {**decision, "decision": "timeout", "accepted": False}

        time.sleep(interval)


def _skill_approval_params(
    *,
    skill: str,
    action: str,
    description: str,
    details: dict[str, Any] | None,
    command: str | None,
    timeout_seconds: float | None,
) -> dict[str, Any]:
    skill_name = _require_text(skill, "skill")
    action_name = _require_text(action, "action")
    description_text = _require_text(description, "description")
    params: dict[str, Any] = {
        "skill": skill_name,
        "action": action_name,
        "description": description_text,
        "name": f"{skill_name}: {action_name}",
        "source": "skill",
    }
    if command:
        params["command"] = command
    if details:
        params["details"] = details
        params["justification"] = _details_summary(details)
    if timeout_seconds is not None:
        params["timeout_seconds"] = timeout_seconds
    return params


def _request_map(path: Path | str | None = None) -> dict[str, Any]:
    requests = read_permission_store(path).get("requests")
    return requests if isinstance(requests, dict) else {}


def _decision_map(path: Path | str | None = None) -> dict[str, Any]:
    decisions = read_permission_store(path).get("decisions")
    return decisions if isinstance(decisions, dict) else {}


def _decision_record(
    *,
    request_id: str,
    decision: str,
    request: dict[str, Any],
    answered_at: str | None,
) -> dict[str, Any]:
    return {
        "id": str(request_id),
        "decision": decision,
        "accepted": decision == "accept",
        "answered_at": answered_at,
        "request": request,
    }


def _validate_decision(decision: str) -> Literal["accept", "decline", "cancel"]:
    normalized = decision.strip().lower()
    if normalized not in APPROVAL_DECISIONS:
        allowed = ", ".join(sorted(APPROVAL_DECISIONS))
        raise ValueError(f"decision must be one of: {allowed}")
    return cast(Literal["accept", "decline", "cancel"], normalized)


def _details_summary(details: dict[str, Any]) -> str:
    parts = []
    for key, value in details.items():
        if value is None:
            continue
        parts.append(f"{key}: {value}")
    return "; ".join(parts)


def _require_text(value: str, name: str) -> str:
    text = " ".join(str(value).split())
    if not text:
        raise ValueError(f"{name} is required")
    return text


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
