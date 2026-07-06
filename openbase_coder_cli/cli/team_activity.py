"""Report agent activity to openbase-cloud for teammates."""

from __future__ import annotations

import time

import click

from openbase_coder_cli.services.team_activity import (
    report_team_activity_once,
    team_activity_disabled,
)

UNSUPPORTED_BACKOFF_SECONDS = 600


@click.group("team-activity")
def team_activity() -> None:
    """Share this machine's agent activity with your team."""


@team_activity.command("once")
def team_activity_once_cmd() -> None:
    """Collect and report a single activity snapshot."""
    result = report_team_activity_once()
    prefix = "OK" if result.ok else "WARN"
    click.echo(f"{prefix}  team activity: {result.detail or 'reported'}")


@team_activity.command("run")
@click.option("--interval", default=45, show_default=True, type=int)
def team_activity_run_cmd(interval: int) -> None:
    """Report activity on an interval (used by the background service)."""
    while True:
        result = report_team_activity_once()
        if team_activity_disabled():
            click.echo("team activity disabled; sleeping")
            time.sleep(max(interval, 60))
            continue
        click.echo(f"{'ok' if result.ok else 'warn'} {result.detail or 'reported'}")
        if not result.supported:
            time.sleep(UNSUPPORTED_BACKOFF_SECONDS)
        else:
            time.sleep(max(interval, 10))
