from __future__ import annotations

import json

import click

from openbase_coder_cli.plugins.manager import (
    add_plugin,
    list_bootstrappers,
    list_plugins,
    remove_plugin,
    show_plugin,
    update_plugin,
)


@click.group()
def plugins() -> None:
    """Manage Openbase plugins."""


@plugins.command("add")
@click.argument("source")
@click.option(
    "--ref",
    default="",
    help="Optional branch/tag/ref for GitHub sources.",
)
def add(source: str, ref: str) -> None:
    """Install a plugin from local path or GitHub URL."""
    plugin = add_plugin(source=source, ref=ref or None)
    click.echo(f"Installed plugin {plugin.plugin_id} ({plugin.version})")


@plugins.command("list")
def list_cmd() -> None:
    """List installed plugins."""
    plugins_list = list_plugins()
    if not plugins_list:
        click.echo("No plugins installed")
        return

    click.echo("Installed plugins:")
    for plugin in sorted(plugins_list, key=lambda item: item.plugin_id):
        click.echo(
            f"  {plugin.plugin_id:<24} {plugin.version:<10} {plugin.source_type}"
        )


@plugins.command("show")
@click.argument("plugin_id")
def show(plugin_id: str) -> None:
    """Show detailed plugin metadata."""
    plugin = show_plugin(plugin_id)

    click.echo(f"Plugin: {plugin.plugin_id}")
    click.echo(f"Display Name: {plugin.display_name}")
    click.echo(f"Version: {plugin.version}")
    click.echo(f"Package: {plugin.package_name}")
    click.echo(f"Source Type: {plugin.source_type}")
    click.echo(f"Source: {plugin.source}")
    if plugin.github_url:
        click.echo(f"Git URL: {plugin.github_url}")
    if plugin.ref:
        click.echo(f"Ref: {plugin.ref}")
    if plugin.commit_sha:
        click.echo(f"Commit: {plugin.commit_sha}")

    caps = {
        "bootstrappers": [item.__dict__ for item in plugin.capabilities.bootstrappers],
        "stacks": [item.__dict__ for item in plugin.capabilities.stacks],
        "console_pages": [item.__dict__ for item in plugin.capabilities.console_pages],
        "skills": [item.__dict__ for item in plugin.capabilities.skills],
        "django_url_modules": list(plugin.capabilities.django_url_modules),
    }
    click.echo()
    click.echo(json.dumps(caps, indent=2))


@plugins.command("remove")
@click.argument("plugin_id")
def remove(plugin_id: str) -> None:
    """Uninstall a plugin."""
    remove_plugin(plugin_id)
    click.echo(f"Removed plugin {plugin_id}")


@plugins.command("update")
@click.argument("plugin_id", required=False)
@click.option(
    "--ref",
    default="",
    help="Override ref used for update (GitHub plugins).",
)
def update(plugin_id: str | None, ref: str) -> None:
    """Update one plugin or all plugins."""
    updated = update_plugin(plugin_id=plugin_id, ref=ref or None)
    if not updated:
        click.echo("No plugins updated")
        return

    click.echo("Updated plugins:")
    for plugin in updated:
        click.echo(f"  {plugin.plugin_id} -> {plugin.version} {plugin.commit_sha}")


@plugins.command("bootstrappers")
def bootstrappers() -> None:
    """List discovered bootstrapper names."""
    rows = list_bootstrappers()
    if not rows:
        click.echo("No bootstrappers found")
        return

    click.echo("Available bootstrappers:")
    for name, plugin_id, description in rows:
        description_suffix = f" - {description}" if description else ""
        click.echo(f"  {name:<24} ({plugin_id}){description_suffix}")
