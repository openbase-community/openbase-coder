"""Openbase Cloud workspace integration commands.

Currently just the idle heartbeat: a workspace launched by openbase-cloud reports
whether agent runs (Super Agents / Codex / Claude Code threads) are running or
were launched during the beat window, so the cloud API can defer idle auto-stop.
Desktop (DCV) connections and console browsing intentionally do not count as
activity: a workspace with no run activity is stopped for later.
"""

from __future__ import annotations

import time

import click
import httpx

from openbase_coder_cli.cli.backend import read_env_values
from openbase_coder_cli.cli.local_server import local_server_url
from openbase_coder_cli.config.token_manager import (
    DEFAULT_WEB_BACKEND_URL,
    CloudAccessTokenAuth,
    TokenManager,
)
from openbase_coder_cli.paths import DEFAULT_ENV_FILE_PATH

HEARTBEAT_PATH = "/api/openbase/devspaces/heartbeat/"
THREAD_ACTIVITY_PATH = "/api/threads/activity/"

# Runs shorter than one heartbeat interval would be invisible to a single
# per-beat check, so activity is sampled more often and OR-ed into the beat.
RUN_SAMPLE_INTERVAL_SECONDS = 15


def _web_backend_url() -> str:
    if DEFAULT_ENV_FILE_PATH.is_file():
        url = read_env_values(DEFAULT_ENV_FILE_PATH).get(
            "OPENBASE_CODER_CLI_WEB_BACKEND_URL"
        )
        if url:
            return url.rstrip("/")
    return DEFAULT_WEB_BACKEND_URL


def _agent_runs_active(local_url: str, manager: TokenManager) -> bool:
    """True when any coder thread has a running or queued agent run.

    The local coder server is the source of truth for Super Agents / Codex /
    Claude Code runs. Any failure here (server down, auth hiccup) just means
    "no run activity" for this sample; the next sample retries.
    """
    try:
        response = httpx.get(
            f"{local_url}{THREAD_ACTIVITY_PATH}",
            auth=CloudAccessTokenAuth(manager),
            timeout=10,
        )
    except (httpx.HTTPError, RuntimeError):
        return False
    if response.status_code != 200:
        return False
    try:
        data = response.json()
    except ValueError:
        return False
    return int(data.get("active_run_count", 0)) > 0


@click.group()
def cloud() -> None:
    """Openbase Cloud workspace integration."""


@cloud.command()
@click.option(
    "--interval",
    type=int,
    default=60,
    show_default=True,
    help="Seconds between heartbeats. 0 sends a single heartbeat and exits.",
)
def heartbeat(interval: int) -> None:
    """Report agent-run activity to Openbase Cloud so idle auto-stop is deferred."""
    url = _web_backend_url()
    manager = TokenManager(web_backend_url=url)
    manager.load()
    local_url = local_server_url()

    active = _agent_runs_active(local_url, manager)
    while True:
        # A long-running service must survive network blips and token-refresh
        # hiccups: skipping one beat and retrying next interval is the fallback.
        try:
            token = manager.get_access_token()
            httpx.post(
                f"{url}{HEARTBEAT_PATH}",
                json={"active": active},
                headers={"Authorization": f"Bearer {token}"},
                timeout=15,
            )
        except (httpx.HTTPError, RuntimeError) as exc:
            click.echo(f"Heartbeat skipped: {exc}", err=True)
            if interval <= 0:
                raise
        if interval <= 0:
            break

        # Sample run activity through the beat window so short runs launched
        # between beats still mark the workspace active.
        active = False
        deadline = time.monotonic() + interval
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(RUN_SAMPLE_INTERVAL_SECONDS, remaining))
            active = _agent_runs_active(local_url, manager) or active
