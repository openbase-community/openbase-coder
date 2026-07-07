"""CLI commands for onboarding state and cloud device registration."""

from __future__ import annotations

import json

import click

from openbase_coder_cli.services.cloud_registration import (
    deregister_device_with_cloud,
    register_and_report,
    register_device_with_cloud,
)
from openbase_coder_cli.services.onboarding import onboarding_status_payload
from openbase_coder_cli.services.tailscale_serve import tailscale_up


@click.group()
def onboarding() -> None:
    """Onboarding state and openbase-cloud device registration."""


@onboarding.command("status")
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Print machine-readable JSON instead of a summary.",
)
def onboarding_status_cmd(as_json: bool) -> None:
    """Show local onboarding state (CLI configured, Tailscale, auth)."""
    payload = onboarding_status_payload()
    if as_json:
        click.echo(json.dumps(payload, indent=2))
        return

    def line(value: bool, label: str, *, indent: str = "") -> None:
        mark = (
            click.style("  OK  ", fg="green")
            if value
            else click.style("  --  ", fg="yellow")
        )
        click.echo(indent + mark + label)

    line(payload["cli_configured"], "cli_configured")
    for name, value in payload["checks"].items():
        line(value, name, indent="    ")
    line(payload["authenticated"], "authenticated")

    tailscale_self = payload["tailscale_self"]
    dns_name = tailscale_self["dns_name"]
    line(
        tailscale_self["available"],
        "tailscale identity" + (f" ({dns_name})" if dns_name else ""),
    )
    if tailscale_self["error"]:
        click.echo(f"        {tailscale_self['error']}")

    serve = payload["tailscale_serve"]
    line(
        serve["healthy"],
        "tailscale serve"
        + (f" ({serve['openbase_url']})" if serve["openbase_url"] else ""),
    )
    if serve["error"]:
        click.echo(f"        {serve['error']}")


@onboarding.command("report")
def onboarding_report_cmd() -> None:
    """Register this device and report CLI state to openbase-cloud."""
    result = register_and_report()
    if result.ok:
        if not result.tailscale_advertised:
            # Registered, but Tailscale is not connected so no address was
            # shared — pairing cannot complete. Signal a non-zero exit so the
            # desktop app shows guidance instead of a false "done".
            click.echo(
                click.style(
                    "Registered, but Tailscale isn't connected — no address was "
                    "shared, so pairing can't complete. Open Tailscale and sign "
                    "in, then run this again.",
                    fg="yellow",
                )
            )
            raise SystemExit(2)
        click.echo("Registered device and reported CLI state to openbase-cloud.")
        return
    if not result.supported:
        click.echo(
            click.style(
                f"Skipped: {result.error}",
                fg="yellow",
            )
        )
        return
    raise click.ClickException(result.error or "Cloud report failed.")


@onboarding.command("heartbeat")
def onboarding_heartbeat_cmd() -> None:
    """Re-register this device so it stays "present" in the rendezvous registry.

    Best-effort and quiet: intended to run on a timer while an onboarding page
    is open. Never fails the caller.
    """
    result = register_device_with_cloud()
    if result.ok:
        click.echo("heartbeat ok")
    else:
        click.echo(click.style(f"heartbeat skipped: {result.error}", fg="yellow"))


@onboarding.command("deregister")
@click.option(
    "--device-id",
    "device_id",
    default=None,
    help="Device id to forget. Defaults to this machine's own device id.",
)
def onboarding_deregister_cmd(device_id: str | None) -> None:
    """Remove a device from openbase-cloud's rendezvous registry."""
    result = deregister_device_with_cloud(device_id)
    if result.ok:
        click.echo("Deregistered device from openbase-cloud.")
        return
    if not result.supported:
        click.echo(click.style(f"Skipped: {result.error}", fg="yellow"))
        return
    raise click.ClickException(result.error or "Cloud deregister failed.")


@onboarding.command("tailscale-up")
def onboarding_tailscale_up_cmd() -> None:
    """Bring Tailscale online on this Mac, opening browser SSO if needed."""
    tailscale_up()
    click.echo("Tailscale is connected.")
