from __future__ import annotations

import json
from pathlib import Path

import click

from openbase_coder_cli.paths import (
    PLUGIN_CONSOLE_REGISTRY_PATH,
    PLUGIN_REGISTRY_PATH,
    PLUGIN_REQUIREMENTS_PATH,
    PLUGIN_SKILLS_OWNERSHIP_PATH,
    PLUGIN_SOURCES_DIR,
)

from .models import PluginRecord, PluginRegistry


def ensure_plugin_dirs() -> None:
    try:
        PLUGIN_REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
        PLUGIN_SOURCES_DIR.mkdir(parents=True, exist_ok=True)
        PLUGIN_CONSOLE_REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise click.ClickException(
            f"Could not create plugin data directories under {PLUGIN_REGISTRY_PATH.parent}: {exc}"
        ) from exc


# Bump alongside a forward-only migration; see the workspace AUTO_UPDATE.md.
PLUGIN_REGISTRY_SCHEMA_VERSION = 1


def load_registry() -> PluginRegistry:
    if not PLUGIN_REGISTRY_PATH.is_file():
        return PluginRegistry()
    data = json.loads(PLUGIN_REGISTRY_PATH.read_text())
    found_version = int(data.get("schema_version", 1))
    if found_version > PLUGIN_REGISTRY_SCHEMA_VERSION:
        raise click.ClickException(
            f"plugins.json schema {found_version} was written by a newer "
            "Openbase Coder; update the CLI."
        )
    return PluginRegistry.from_dict(data)


def save_registry(registry: PluginRegistry) -> None:
    ensure_plugin_dirs()
    payload = {"schema_version": PLUGIN_REGISTRY_SCHEMA_VERSION, **registry.to_dict()}
    PLUGIN_REGISTRY_PATH.write_text(json.dumps(payload, indent=2) + "\n")


def write_requirements_file(registry: PluginRegistry) -> None:
    ensure_plugin_dirs()
    lines: list[str] = ["# Managed by openbase-coder plugins"]
    for plugin in sorted(registry.plugins, key=lambda item: item.plugin_id):
        lines.append(f"# {plugin.plugin_id}")
        lines.append(plugin.requirement)
    PLUGIN_REQUIREMENTS_PATH.write_text("\n".join(lines) + "\n")


def load_skills_ownership() -> dict[str, str]:
    if not PLUGIN_SKILLS_OWNERSHIP_PATH.is_file():
        return {}
    data = json.loads(PLUGIN_SKILLS_OWNERSHIP_PATH.read_text())
    return dict(data.get("targets", {}))


def save_skills_ownership(ownership: dict[str, str]) -> None:
    ensure_plugin_dirs()
    payload = {"targets": ownership}
    PLUGIN_SKILLS_OWNERSHIP_PATH.write_text(json.dumps(payload, indent=2) + "\n")


def save_console_registry(payload: dict) -> None:
    ensure_plugin_dirs()
    PLUGIN_CONSOLE_REGISTRY_PATH.write_text(json.dumps(payload, indent=2) + "\n")


def remove_plugin_source(plugin: PluginRecord) -> None:
    if plugin.source_type != "github":
        return
    source_path = Path(plugin.source_path)
    if source_path.is_dir() and source_path.parent == PLUGIN_SOURCES_DIR:
        import shutil

        shutil.rmtree(source_path)
