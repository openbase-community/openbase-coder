from __future__ import annotations

import importlib
import json

import click

from openbase_coder_cli.services.installation import InstallationConfig
from openbase_coder_cli.services.restart import (
    API_RESTART_DELAY_SECONDS,
    RestartRequest,
    schedule_restart,
)

from .console import sync_console_integration
from .install import install_github_pinned, install_local_editable, uninstall_package
from .models import PluginRecord, PluginRegistry
from .site import rebuild_plugin_site, use_plugin_site
from .skills import remove_plugin_skills, sync_plugin_skills
from .sources import inspect_source, resolve_source
from .spec import load_plugin_spec, normalize_capabilities, normalize_plugin_header
from .store import (
    load_registry,
    remove_plugin_source,
    save_registry,
    write_requirements_file,
)

_BUILTIN_CONSOLE_ROUTES = {
    "/dashboard",
    "/dashboard/projects",
    "/dashboard/threads",
    "/dashboard/threads/:threadId",
    "/dashboard/project-view",
    "/dashboard/diff",
    "/dashboard/skills",
    "/dashboard/status",
    "/dashboard/settings",
}


def _restart_services_if_installed() -> None:
    if not InstallationConfig.exists():
        return

    schedule_restart(
        RestartRequest(delay_seconds=API_RESTART_DELAY_SECONDS),
        emit_cli_warning=False,
    )


def _workspace_path_or_none() -> str | None:
    if not InstallationConfig.exists():
        return None
    return InstallationConfig.load().workspace_path


def _find_bootstrapper_collisions(
    registry: PluginRegistry,
    candidate: PluginRecord,
    *,
    ignore_plugin_id: str | None = None,
) -> list[str]:
    collisions: list[str] = []

    existing_bootstrapper_names: dict[str, str] = {}
    existing_console_keys: dict[str, str] = {}
    existing_console_routes: dict[str, str] = {}

    for plugin in registry.plugins:
        if ignore_plugin_id and plugin.plugin_id == ignore_plugin_id:
            continue
        for bootstrapper in plugin.capabilities.bootstrappers:
            existing_bootstrapper_names[bootstrapper.name] = plugin.plugin_id
        for page in plugin.capabilities.console_pages:
            existing_console_keys[page.key] = plugin.plugin_id
            existing_console_routes[page.route] = plugin.plugin_id

    for bootstrapper in candidate.capabilities.bootstrappers:
        owner = existing_bootstrapper_names.get(bootstrapper.name)
        if owner:
            collisions.append(
                f"bootstrapper name '{bootstrapper.name}' already provided by {owner}"
            )

    for page in candidate.capabilities.console_pages:
        owner = existing_console_keys.get(page.key)
        if owner:
            collisions.append(
                f"console page key '{page.key}' already provided by {owner}"
            )
        route_owner = existing_console_routes.get(page.route)
        if route_owner:
            collisions.append(
                f"console page route '{page.route}' already provided by {route_owner}"
            )
        if page.route in _BUILTIN_CONSOLE_ROUTES:
            collisions.append(
                f"console page route '{page.route}' conflicts with built-in console route"
            )

    return collisions


def _build_record(
    *,
    source: str,
    ref: str | None,
) -> PluginRecord:
    resolved = resolve_source(source, ref)
    package_name, entrypoint_name, expected_entrypoint_value = inspect_source(
        resolved.local_path
    )

    if resolved.source_type == "local":
        requirement = install_local_editable(resolved.local_path)
    else:
        requirement = install_github_pinned(resolved.github_url, resolved.commit_sha)

    raw_spec, installed_entrypoint_value = load_plugin_spec(
        package_name, entrypoint_name
    )
    plugin_id, display_name, version = normalize_plugin_header(raw_spec)
    capabilities = normalize_capabilities(raw_spec, plugin_id)

    entrypoint_value = installed_entrypoint_value or expected_entrypoint_value

    return PluginRecord(
        plugin_id=plugin_id,
        display_name=display_name,
        version=version,
        package_name=package_name,
        source_type=resolved.source_type,
        source=source,
        source_path=str(resolved.local_path),
        entrypoint_name=entrypoint_name,
        entrypoint_value=entrypoint_value,
        requirement=requirement,
        github_url=resolved.github_url,
        ref=resolved.ref,
        commit_sha=resolved.commit_sha,
        capabilities=capabilities,
    )


def list_plugins() -> list[PluginRecord]:
    return load_registry().plugins


def show_plugin(plugin_id: str) -> PluginRecord:
    registry = load_registry()
    plugin = registry.get(plugin_id)
    if not plugin:
        raise click.ClickException(f"Plugin '{plugin_id}' is not installed")
    return plugin


def add_plugin(source: str, ref: str | None) -> PluginRecord:
    registry = load_registry()
    record = _build_record(source=source, ref=ref)

    if registry.get(record.plugin_id):
        uninstall_package(record.package_name)
        raise click.ClickException(f"Plugin '{record.plugin_id}' is already installed")

    collisions = _find_bootstrapper_collisions(registry, record)
    if collisions:
        uninstall_package(record.package_name)
        joined = "\n".join(f"- {item}" for item in collisions)
        raise click.ClickException(f"Plugin install blocked by collisions:\n{joined}")

    registry.plugins.append(record)
    save_registry(registry)
    write_requirements_file(registry)

    sync_plugin_skills(record)
    sync_console_integration(registry)
    _restart_services_if_installed()

    return record


def remove_plugin(plugin_id: str) -> None:
    registry = load_registry()
    plugin = registry.get(plugin_id)
    if not plugin:
        raise click.ClickException(f"Plugin '{plugin_id}' is not installed")

    registry.plugins = [
        item for item in registry.plugins if item.plugin_id != plugin_id
    ]
    save_registry(registry)
    write_requirements_file(registry)

    uninstall_package(plugin.package_name)
    if use_plugin_site():
        rebuild_plugin_site(
            [item.requirement for item in registry.plugins]
        )
    remove_plugin_skills(plugin_id)
    remove_plugin_source(plugin)

    sync_console_integration(registry)
    _restart_services_if_installed()


def update_plugin(plugin_id: str | None, ref: str | None) -> list[PluginRecord]:
    registry = load_registry()

    targets = registry.plugins
    if plugin_id:
        plugin = registry.get(plugin_id)
        if not plugin:
            raise click.ClickException(f"Plugin '{plugin_id}' is not installed")
        targets = [plugin]

    updated: list[PluginRecord] = []
    next_plugins = [item for item in registry.plugins if item not in targets]

    for current in targets:
        source_ref = ref if ref is not None else (current.ref or None)
        record = _build_record(source=current.source, ref=source_ref)

        if record.plugin_id != current.plugin_id:
            uninstall_package(record.package_name)
            raise click.ClickException(
                f"Plugin ID mismatch during update: expected {current.plugin_id}, got {record.plugin_id}"
            )

        collisions = _find_bootstrapper_collisions(
            PluginRegistry(plugins=next_plugins),
            record,
        )
        if collisions:
            uninstall_package(record.package_name)
            joined = "\n".join(f"- {item}" for item in collisions)
            raise click.ClickException(
                f"Plugin update blocked by collisions:\n{joined}"
            )

        if current.package_name != record.package_name:
            uninstall_package(current.package_name)
            if use_plugin_site():
                rebuild_plugin_site(
                    [item.requirement for item in [*next_plugins, record]]
                )
        next_plugins.append(record)
        updated.append(record)

    new_registry = PluginRegistry(
        plugins=sorted(next_plugins, key=lambda item: item.plugin_id)
    )
    save_registry(new_registry)
    write_requirements_file(new_registry)

    for plugin in updated:
        sync_plugin_skills(plugin)

    sync_console_integration(new_registry)
    _restart_services_if_installed()

    return updated


def list_bootstrappers() -> list[tuple[str, str, str]]:
    registry = load_registry()
    rows: list[tuple[str, str, str]] = []
    for plugin in registry.plugins:
        for bootstrapper in plugin.capabilities.bootstrappers:
            rows.append((bootstrapper.name, plugin.plugin_id, bootstrapper.description))
    return sorted(rows, key=lambda item: item[0])


def run_bootstrapper(
    bootstrapper_name: str,
    *,
    params: dict,
) -> dict:
    registry = load_registry()

    matches: list[tuple[PluginRecord, str]] = []
    for plugin in registry.plugins:
        for bootstrapper in plugin.capabilities.bootstrappers:
            if bootstrapper.name == bootstrapper_name:
                matches.append((plugin, bootstrapper.handler))

    if not matches:
        raise click.ClickException(f"Unknown bootstrapper '{bootstrapper_name}'")

    if len(matches) > 1:
        owners = ", ".join(item[0].plugin_id for item in matches)
        raise click.ClickException(
            f"Bootstrapper '{bootstrapper_name}' is ambiguous across plugins: {owners}"
        )

    plugin, handler_ref = matches[0]

    if ":" not in handler_ref:
        raise click.ClickException(
            f"Invalid handler reference for bootstrapper '{bootstrapper_name}': {handler_ref}"
        )

    module_name, function_name = handler_ref.split(":", 1)
    module = importlib.import_module(module_name)
    handler = getattr(module, function_name)
    if not callable(handler):
        raise click.ClickException(
            f"Bootstrap handler is not callable: {module_name}:{function_name}"
        )

    context = {
        "workspace_path": _workspace_path_or_none() or "",
        "plugin_id": plugin.plugin_id,
        "plugin_source_path": plugin.source_path,
    }
    result = handler(params=params, context=context)

    if result is None:
        return {"status": "ok"}

    if isinstance(result, dict):
        return result

    try:
        return json.loads(json.dumps(result))
    except TypeError as exc:
        raise click.ClickException(
            "Bootstrap handler must return JSON-serializable data"
        ) from exc
