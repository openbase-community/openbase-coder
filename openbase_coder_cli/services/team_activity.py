"""Report this machine's agent activity to openbase-cloud for teammates.

Collects active thread names/statuses from the local server and changed file
paths from tracked project repos, then upserts a snapshot at
POST /api/openbase/activity/report/. Privacy: only thread id/name/agent/status,
repo names, and repository-relative file paths ever leave the machine — no
diff contents, prompts, or absolute paths.
"""

from __future__ import annotations

import os
import socket
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from openbase_coder_cli.config.token_manager import get_token_manager
from openbase_coder_cli.mcp.projects import get_recent_projects

DISABLED_ENV = "OPENBASE_TEAM_ACTIVITY_DISABLED"
DEFAULT_WEB_BACKEND_URL = "https://app.openbase.cloud"
REPORT_PATH = "/api/openbase/activity/report/"
MAX_REPOS = 20
MAX_FILES_PER_REPO = 40
GIT_TIMEOUT_SECONDS = 5


@dataclass(frozen=True)
class TeamActivityResult:
    ok: bool
    supported: bool
    detail: str = ""


def team_activity_disabled() -> bool:
    return os.environ.get(DISABLED_ENV, "").strip() not in ("", "0", "false")


def _web_backend_url() -> str:
    return os.environ.get(
        "OPENBASE_CODER_CLI_WEB_BACKEND_URL", DEFAULT_WEB_BACKEND_URL
    ).rstrip("/")


def _device_id() -> str:
    """Stable per-machine identifier (hostname + persisted uuid suffix)."""
    marker = Path.home() / ".openbase" / "device-id"
    try:
        if marker.exists():
            return marker.read_text().strip()
        value = f"desktop-{uuid.uuid4().hex[:12]}"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(value)
        return value
    except OSError:
        return f"desktop-{socket.gethostname()}"


def changed_file_paths(directory: str) -> list[str]:
    """Repository-relative paths with uncommitted changes, capped."""
    try:
        result = subprocess.run(  # noqa: S603
            ["git", "status", "--porcelain"],  # noqa: S607
            cwd=directory,
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    paths: list[str] = []
    for line in result.stdout.splitlines():
        if len(line) < 4:
            continue
        entry = line[3:].strip()
        # Renames come through as "old -> new"; report the new path.
        if " -> " in entry:
            entry = entry.split(" -> ", 1)[1]
        entry = entry.strip().strip('"')
        if entry:
            paths.append(entry)
        if len(paths) >= MAX_FILES_PER_REPO:
            break
    return paths


def _active_threads() -> list[dict[str, Any]]:
    # Imported lazily: cli.local_server pulls in the click command tree,
    # which imports this module (circular at import time).
    import click

    from openbase_coder_cli.cli.local_server import local_server_request

    try:
        response = local_server_request("GET", "/api/threads/")
        payload = response.json()
    except (click.ClickException, ValueError):
        return []
    threads = payload.get("threads", payload) if isinstance(payload, dict) else payload
    if not isinstance(threads, list):
        return []
    collected = []
    for thread in threads:
        if not isinstance(thread, dict):
            continue
        status = str(thread.get("status") or "")
        if status in ("completed", "error"):
            continue
        collected.append(
            {
                "thread_id": str(
                    thread.get("thread_id") or thread.get("session_id") or ""
                ),
                "name": str(thread.get("name") or thread.get("display_name") or ""),
                "agent_name": str(thread.get("agent_name") or ""),
                "status": status,
                "directory": str(thread.get("directory") or ""),
            }
        )
    return collected


def collect_activity_snapshot() -> dict[str, Any]:
    """Assemble the paths-only payload. Absolute paths never leave here."""
    projects = [p["path"] for p in get_recent_projects()][:MAX_REPOS]

    repos = []
    repo_name_by_path: dict[str, str] = {}
    for project_path in projects:
        name = Path(project_path).name
        repo_name_by_path[project_path] = name
        files = changed_file_paths(project_path)
        if files:
            repos.append({"name": name, "changed_files": files})

    threads = []
    for thread in _active_threads():
        directory = thread.pop("directory", "")
        repo = ""
        best = ""
        for project_path, name in repo_name_by_path.items():
            if directory.startswith(project_path) and len(project_path) > len(best):
                best = project_path
                repo = name
        thread["repo"] = repo
        threads.append(thread)

    return {"device_id": _device_id(), "threads": threads, "repos": repos}


def report_team_activity_once() -> TeamActivityResult:
    """Collect and POST one snapshot. Never raises."""
    if team_activity_disabled():
        return TeamActivityResult(
            ok=True,
            supported=True,
            detail="disabled by OPENBASE_TEAM_ACTIVITY_DISABLED",
        )
    try:
        payload = collect_activity_snapshot()
    except Exception as exc:  # noqa: BLE001 - reporter must never crash the loop
        return TeamActivityResult(ok=False, supported=True, detail=f"collect: {exc}")

    try:
        token = get_token_manager().get_access_token()
    except Exception as exc:  # noqa: BLE001
        return TeamActivityResult(ok=False, supported=True, detail=f"auth: {exc}")

    try:
        response = httpx.post(
            f"{_web_backend_url()}{REPORT_PATH}",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
    except httpx.HTTPError as exc:
        return TeamActivityResult(ok=False, supported=True, detail=str(exc))

    if response.status_code in (404, 405) or response.headers.get(
        "content-type", ""
    ).startswith("text/html"):
        return TeamActivityResult(
            ok=False, supported=False, detail="backend does not support team activity"
        )
    if response.status_code >= 400:
        return TeamActivityResult(
            ok=False, supported=True, detail=f"HTTP {response.status_code}"
        )
    return TeamActivityResult(
        ok=True,
        supported=True,
        detail=f"{len(payload['threads'])} threads, {len(payload['repos'])} repos",
    )


def fetch_team_activity() -> dict[str, Any]:
    """GET the merged team feed from the cloud (used by the local proxy)."""
    try:
        token = get_token_manager().get_access_token()
        response = httpx.get(
            f"{_web_backend_url()}/api/openbase/team/activity/",
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
    except Exception as exc:  # noqa: BLE001
        return {"supported": False, "error": str(exc)}
    if response.status_code in (404, 405) or response.headers.get(
        "content-type", ""
    ).startswith("text/html"):
        return {"supported": False, "error": "backend does not support team activity"}
    if response.status_code >= 400:
        return {"supported": False, "error": f"HTTP {response.status_code}"}
    try:
        data = response.json()
    except ValueError:
        return {"supported": False, "error": "invalid response"}
    data["supported"] = True
    return data
