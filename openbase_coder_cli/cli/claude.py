from __future__ import annotations

import click

from openbase_coder_cli.claude_auth import (
    copy_normal_claude_keychain,
    run_claude_login,
    sync_normal_claude_state,
    verified_claude_auth_status,
)
from openbase_coder_cli.paths import OPENBASE_CLAUDE_CONFIG_DIR


@click.group()
def claude() -> None:
    """Manage Openbase's Claude Code auth and config."""


@claude.command()
def status() -> None:
    """Show Claude Code auth status for Openbase's CLAUDE_CONFIG_DIR."""
    result = verified_claude_auth_status()
    click.echo(result.raw_output)
    if not result.logged_in:
        raise click.ClickException(
            "Openbase Claude Code is not logged in. Run `openbase-coder claude "
            "sync-state` to re-bridge your normal Claude login, or "
            "`openbase-coder claude login`."
        )


@claude.command("sync-state")
def sync_state() -> None:
    """Copy normal Claude Code state into Openbase's managed Claude config."""
    result = sync_normal_claude_state()
    if result.state_updated:
        click.echo("Updated Openbase Claude Code state.")
    click.echo(result.message)
    status_result = verified_claude_auth_status()
    if not status_result.logged_in and copy_normal_claude_keychain():
        click.echo("Copied normal Claude Code login into Openbase's keychain entry.")
        status_result = verified_claude_auth_status()
    if status_result.logged_in:
        click.echo("Openbase Claude Code auth is ready.")
        return
    raise click.ClickException(
        "Openbase Claude Code still needs its own scoped login. "
        "Run `openbase-coder claude login`."
    )


@claude.command()
@click.option("--sso", is_flag=True, help="Force Claude SSO login flow.")
@click.option("--email", default=None, help="Pre-populate the Claude login email.")
def login(sso: bool, email: str | None) -> None:
    """Run Claude Code login for Openbase's CLAUDE_CONFIG_DIR."""
    click.echo(f"Using CLAUDE_CONFIG_DIR={OPENBASE_CLAUDE_CONFIG_DIR}")
    raise SystemExit(run_claude_login(sso=sso, email=email))


@claude.command("computer-use-mcp", hidden=True)
def computer_use_mcp() -> None:
    """Run the Openbase computer-use MCP server on stdio (desktop-app proxy)."""
    from openbase_coder_cli.claude_computer_use_mcp import main as mcp_main

    mcp_main()
