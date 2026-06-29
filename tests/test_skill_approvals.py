from __future__ import annotations

from pathlib import Path

from super_agents.app_server_client import read_permission_store

from openbase_coder_cli.skill_approvals import (
    answer_skill_approval_request,
    consume_skill_approval_decision,
    create_skill_approval_request,
    get_skill_approval_decision,
    get_skill_approval_request,
    list_skill_approval_requests,
    wait_for_skill_approval,
)


def test_skill_approval_lifecycle_uses_json_store(tmp_path: Path) -> None:
    path = tmp_path / "skill-approvals.json"

    request = create_skill_approval_request(
        skill="whatsapp-cli",
        action="send-message",
        description="Queue a WhatsApp message",
        command="whatsapp-local send contact hello",
        details={"contact": "contact"},
        path=path,
    )

    assert request["id"].startswith("skill-")
    assert list_skill_approval_requests(path) == [request]
    assert get_skill_approval_request(request["id"], path) == request
    store = read_permission_store(path)
    assert request["id"] in store["requests"]
    assert store["requests"][request["id"]]["method"] == "openbaseSkill/requestApproval"

    decision = answer_skill_approval_request(request["id"], "accept", path)

    assert decision["accepted"] is True
    assert decision["decision"] == "accept"
    assert list_skill_approval_requests(path) == []
    assert get_skill_approval_decision(request["id"], path) == decision
    assert request["id"] in read_permission_store(path)["decisions"]

    consumed = consume_skill_approval_decision(request["id"], path)

    assert consumed == decision
    assert request["id"] not in read_permission_store(path)["requests"]
    assert request["id"] not in read_permission_store(path)["decisions"]


def test_skill_approval_timeout_removes_pending_request(tmp_path: Path) -> None:
    path = tmp_path / "skill-approvals.json"
    request = create_skill_approval_request(
        skill="whatsapp-cli",
        action="approve-contact",
        description="Approve a contact",
        path=path,
    )

    decision = wait_for_skill_approval(
        request["id"],
        timeout_seconds=0,
        poll_interval_seconds=0.1,
        path=path,
    )

    assert decision["accepted"] is False
    assert decision["decision"] == "timeout"
    assert list_skill_approval_requests(path) == []
    assert request["id"] not in read_permission_store(path)["requests"]
