"""Openbase Cloud workspace integration commands.

Currently just the idle heartbeat: a workspace launched by openbase-cloud reports
whether a DCV client is currently connected so the cloud API can defer idle
auto-stop for full/GUI workspaces. Headless workspaces have no desktop and their
activity is observed from proxy traffic instead, so they report inactive here.
"""

from __future__ import annotations

import json
import os
import subprocess
import time

import click
import httpx

from openbase_coder_cli.cli.backend import read_env_values
from openbase_coder_cli.config.token_manager import (
    DEFAULT_WEB_BACKEND_URL,
    TokenManager,
)
from openbase_coder_cli.paths import DEFAULT_ENV_FILE_PATH

HEARTBEAT_PATH = "/api/openbase/devspaces/heartbeat/"


def _web_backend_url() -> str:
    if DEFAULT_ENV_FILE_PATH.is_file():
        url = read_env_values(DEFAULT_ENV_FILE_PATH).get(
            "OPENBASE_CODER_CLI_WEB_BACKEND_URL"
        )
        if url:
            return url.rstrip("/")
    return DEFAULT_WEB_BACKEND_URL


def _dcv_connection_active(session_name: str) -> bool:
    """True when the DCV session has at least one connected client."""
    result = subprocess.run(
        ["dcv", "describe-session", session_name, "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return False
    data = json.loads(result.stdout)
    return int(data.get("num-of-connections", 0)) > 0


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
@click.option(
    "--session-name",
    default=None,
    help="DCV session name to inspect (defaults to $DCV_SESSION_NAME or 'openbase').",
)
def heartbeat(interval: int, session_name: str | None) -> None:
    """Report workspace activity to Openbase Cloud so idle auto-stop is deferred."""
    url = _web_backend_url()
    manager = TokenManager(web_backend_url=url)
    manager.load()
    session = session_name or os.environ.get("DCV_SESSION_NAME", "openbase")

    while True:
        active = _dcv_connection_active(session)
        token = manager.get_access_token()
        httpx.post(
            f"{url}{HEARTBEAT_PATH}",
            json={"active": active},
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        if interval <= 0:
            break
        time.sleep(interval)
