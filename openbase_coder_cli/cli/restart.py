from __future__ import annotations

import click

from openbase_coder_cli.services.restart import (
    DEFAULT_RESTART_DELAY_SECONDS,
    RestartRequest,
    restart_target_names,
    schedule_restart,
)


@click.command("restart")
@click.option(
    "--service",
    type=click.Choice(restart_target_names()),
    help="Restart one Openbase-managed service and required dependents.",
)
@click.option(
    "--delay",
    type=float,
    default=DEFAULT_RESTART_DELAY_SECONDS,
    show_default=True,
    help="Seconds to wait before restarting.",
)
@click.option(
    "--recreate-dispatcher",
    is_flag=True,
    help="Recreate the dispatcher thread during restart.",
)
def restart(service: str | None, delay: float, recreate_dispatcher: bool) -> None:
    """Restart Openbase-managed services."""
    request = RestartRequest(
        services=(service,) if service else (),
        recreate_dispatcher=recreate_dispatcher,
        delay_seconds=delay,
    )
    plan = schedule_restart(request)

    if service:
        service_list = ", ".join(plan.services)
        click.echo(f"Scheduled restart for {service_list} in {plan.delay_seconds:g}s.")
    else:
        click.echo(
            f"Scheduled restart for all Openbase-managed services in {plan.delay_seconds:g}s."
        )
    if plan.recreate_dispatcher:
        click.echo("Dispatcher thread will be recreated.")
    else:
        click.echo(
            "Dispatcher context is preserved; use --recreate-dispatcher for a "
            "fresh dispatcher thread."
        )


@click.command("self-restart")
@click.option(
    "--delay",
    type=float,
    default=DEFAULT_RESTART_DELAY_SECONDS,
    show_default=True,
    help="Seconds to wait before restarting.",
)
@click.option(
    "--recreate-dispatcher",
    is_flag=True,
    help="Recreate the dispatcher thread during restart.",
)
def self_restart(delay: float, recreate_dispatcher: bool) -> None:
    """Restart the full Openbase service stack."""
    request = RestartRequest(
        recreate_dispatcher=recreate_dispatcher,
        delay_seconds=delay,
    )
    plan = schedule_restart(request)
    click.echo(
        f"Scheduled self-restart for all Openbase-managed services in {plan.delay_seconds:g}s."
    )
    if plan.recreate_dispatcher:
        click.echo("Dispatcher thread will be recreated.")
    else:
        click.echo(
            "Dispatcher context is preserved; use --recreate-dispatcher for a "
            "fresh dispatcher thread."
        )
