from __future__ import annotations

import os

os.environ.setdefault("OPENBASE_CODER_CLI_SECRET_KEY", "test-secret")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "openbase_coder_cli.config.settings")

import django  # noqa: E402

django.setup()

import pytest  # noqa: E402
from channels.testing.websocket import WebsocketCommunicator  # noqa: E402
from open_approvals import ApprovalRequest, record_request  # noqa: E402

from openbase_coder_cli.openbase_coder_cli_app import consumers  # noqa: E402


def _communicator() -> WebsocketCommunicator:
    communicator = WebsocketCommunicator(
        consumers.ApprovalRequestsConsumer.as_asgi(), "/ws/approval-requests/"
    )
    communicator.scope["user"] = "authenticated"
    return communicator


@pytest.mark.asyncio
async def test_approvals_socket_pushes_snapshot_on_store_change(monkeypatch, tmp_path):
    store_file = tmp_path / "approval-requests.json"
    monkeypatch.setenv("OPEN_APPROVALS_REQUESTS_FILE", str(store_file))

    snapshots: list[list[dict]] = [[]]

    async def fake_pending_approval_requests() -> list[dict]:
        return snapshots[-1]

    monkeypatch.setattr(
        consumers, "pending_approval_requests", fake_pending_approval_requests
    )
    monkeypatch.setattr(consumers._approval_store_watcher, "poll_seconds", 0.05)

    communicator = _communicator()
    connected, _ = await communicator.connect()
    assert connected

    initial = await communicator.receive_json_from()
    assert initial == {"type": "approval_requests", "data": {"requests": []}}

    pending = {
        "id": "claude-1",
        "method": "claudeCode/requestApproval",
        "params": {"toolName": "Bash", "threadId": "thread-1"},
        "received_at": "2026-01-01T00:00:00Z",
    }
    snapshots.append([pending])
    record_request(
        ApprovalRequest(
            id="claude-1",
            method="claudeCode/requestApproval",
            params={"toolName": "Bash", "threadId": "thread-1"},
            received_at="2026-01-01T00:00:00Z",
        )
    )

    changed = await communicator.receive_json_from(timeout=5)
    assert changed == {"type": "approval_requests", "data": {"requests": [pending]}}

    await communicator.disconnect()


@pytest.mark.asyncio
async def test_approvals_socket_refresh_action_resends_snapshot(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "OPEN_APPROVALS_REQUESTS_FILE", str(tmp_path / "approval-requests.json")
    )

    async def fake_pending_approval_requests() -> list[dict]:
        return []

    monkeypatch.setattr(
        consumers, "pending_approval_requests", fake_pending_approval_requests
    )

    communicator = _communicator()
    connected, _ = await communicator.connect()
    assert connected
    await communicator.receive_json_from()

    await communicator.send_json_to({"action": "refresh"})
    refreshed = await communicator.receive_json_from(timeout=5)
    assert refreshed["type"] == "approval_requests"

    await communicator.disconnect()


@pytest.mark.asyncio
async def test_approvals_socket_rejects_unauthenticated(monkeypatch):
    communicator = WebsocketCommunicator(
        consumers.ApprovalRequestsConsumer.as_asgi(), "/ws/approval-requests/"
    )
    connected, close_code = await communicator.connect()
    assert not connected
    assert close_code == 4001
    await communicator.disconnect()
