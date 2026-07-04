from __future__ import annotations

import click

from openbase_coder_cli.paths import LAUNCHD_DOMAIN
from openbase_coder_cli.services.definitions import (
    SERVICES,
    ServiceDefinition,
)
from openbase_coder_cli.services.installation import InstallationConfig
from openbase_coder_cli.services.selection import configured_default_services


def require_installation() -> InstallationConfig:
    if not InstallationConfig.exists():
        raise click.ClickException(
            "installation.json not found. Run 'openbase-coder setup' first."
        )
    return InstallationConfig.load()


def find_service(service_name: str) -> ServiceDefinition:
    for service in SERVICES:
        if service.name == service_name:
            return service
    valid = ", ".join(service.name for service in SERVICES)
    raise click.ClickException(f"Unknown service '{service_name}'. Valid: {valid}")


def target_services(service_name: str | None) -> list[ServiceDefinition]:
    if service_name:
        return [find_service(service_name)]
    return configured_default_services()


def service_label(service: ServiceDefinition) -> str:
    return f"{LAUNCHD_DOMAIN}.{service.name}"
