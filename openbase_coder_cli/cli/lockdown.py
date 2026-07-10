"""Locked-down mode commands.

Locked-down mode keeps Super Agents launches gated (no approvalPolicy
"never", no danger-full-access sandboxes, no Claude bypassPermissions)
unless the configured safe phrase is heard in the direct voice transcript
of the live session.
"""

from __future__ import annotations

import json

import click

from openbase_coder_cli.services.console_settings import (
    get_lockdown_safe_phrase,
    get_locked_down_mode,
    set_lockdown_safe_phrase,
    set_locked_down_mode,
)
from openbase_coder_cli.services.lockdown import (
    lockdown_restricted,
    sync_lockdown_guard,
)


@click.group()
def lockdown() -> None:
    """Manage locked-down mode for Super Agents launches."""


@lockdown.command()
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
def status(as_json: bool) -> None:
    """Show locked-down mode, the safe phrase, and the current guard state."""
    payload = {
        "locked_down_mode": get_locked_down_mode(),
        "lockdown_safe_phrase_set": bool(get_lockdown_safe_phrase()),
        "restricted": lockdown_restricted(),
    }
    if as_json:
        click.echo(json.dumps(payload, indent=2))
        return
    click.echo(f"Locked-down mode: {'on' if payload['locked_down_mode'] else 'off'}")
    click.echo(
        f"Safe phrase set: {'yes' if payload['lockdown_safe_phrase_set'] else 'no'}"
    )
    click.echo(
        f"Launches restricted right now: {'yes' if payload['restricted'] else 'no'}"
    )


@lockdown.command()
@click.option(
    "--safe-phrase",
    default=None,
    help="Voice safe phrase that unlocks permission bypasses for a session.",
)
def enable(safe_phrase: str | None) -> None:
    """Enable locked-down mode (requires a safe phrase to be set)."""
    if safe_phrase:
        set_lockdown_safe_phrase(safe_phrase)
    if not get_lockdown_safe_phrase():
        raise click.ClickException(
            "Set a safe phrase first: openbase-coder lockdown enable --safe-phrase '...'"
        )
    set_locked_down_mode(True)
    sync_lockdown_guard(relock=True)
    click.echo("Locked-down mode enabled; Super Agents launches are gated.")


@lockdown.command()
def disable() -> None:
    """Disable locked-down mode and lift the launch restriction."""
    set_locked_down_mode(False)
    sync_lockdown_guard()
    click.echo("Locked-down mode disabled.")


@lockdown.command()
def relock() -> None:
    """Re-arm the restriction after a safe-phrase unlock."""
    if not get_locked_down_mode():
        raise click.ClickException("Locked-down mode is off; nothing to relock.")
    sync_lockdown_guard(relock=True)
    click.echo("Launch restriction re-armed.")
