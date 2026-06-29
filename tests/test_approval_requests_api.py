from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("OPENBASE_CODER_CLI_SECRET_KEY", "test-secret")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "openbase_coder_cli.config.settings")

import django  # noqa: E402
from rest_framework.test import APIRequestFactory, force_authenticate  # noqa: E402

django.setup()

from openbase_coder_cli.openbase_coder_cli_app import approvals  # noqa: E402
from openbase_coder_cli.skill_approvals import APPROVAL_METHOD  # noqa: E402


class FakeApprovalManager:
    def __init__(self, requests: list[dict]) -> None:
        self.requests = requests
        self.answered: list[tuple[str, str]] = []

    async def list_approval_requests(self) -> list[dict]:
        return self.requests

    async def answer_approval_request(self, request_id: str, decision: str) -> dict:
        self.answered.append((request_id, decision))
        return {"requestId": request_id, "result": {"decision": decision}}


def _factory_get():
    request = APIRequestFactory().get("/api/approval-requests/")
    force_authenticate(request, user=SimpleNamespace(is_authenticated=True))
    return request


def test_approval_requests_keeps_codex_and_pending_skill_requests(monkeypatch):
    codex_request = {
        "id": "codex-1",
        "method": "mcpServer/elicitation/request",
        "params": {"serverName": "filesystem", "description": "Codex needs input"},
        "received_at": "2026-01-01T00:00:00Z",
    }
    pending_skill_request = {
        "id": "skill-1",
        "method": APPROVAL_METHOD,
        "params": {"source": "skill", "description": "Skill needs approval"},
        "received_at": "2026-01-01T00:00:01Z",
    }
    answered_skill_request = {
        "id": "skill-2",
        "method": APPROVAL_METHOD,
        "params": {"source": "skill", "description": "Already answered"},
        "received_at": "2026-01-01T00:00:02Z",
    }

    monkeypatch.setattr(
        approvals,
        "get_session_manager",
        lambda: FakeApprovalManager(
            [codex_request, pending_skill_request, answered_skill_request]
        ),
    )
    monkeypatch.setattr(
        approvals,
        "is_pending_skill_approval_request",
        lambda request: request["id"] == "skill-1",
    )

    response = approvals.approval_requests(_factory_get())

    assert response.status_code == 200
    assert response.data["requests"] == [codex_request, pending_skill_request]


def test_answer_request_falls_back_to_codex_manager(monkeypatch):
    manager = FakeApprovalManager([])
    monkeypatch.setattr(approvals, "get_session_manager", lambda: manager)
    monkeypatch.setattr(
        approvals,
        "answer_skill_approval_request",
        lambda request_id, decision: (_ for _ in ()).throw(ValueError("not skill")),
    )

    request = APIRequestFactory().post(
        "/api/approval-requests/codex-1/",
        {"decision": "accept"},
        format="json",
    )
    force_authenticate(request, user=SimpleNamespace(is_authenticated=True))
    response = approvals.approval_request_detail(request, "codex-1")

    assert response.status_code == 200
    assert manager.answered == [("codex-1", "accept")]
