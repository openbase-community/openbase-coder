from __future__ import annotations

import json

from openbase_coder_cli.paths import PLUGIN_CONSOLE_REGISTRY_PATH

from .manager import run_bootstrapper
from .store import load_registry


def plugin_to_payload(plugin) -> dict:
    return {
        "plugin_id": plugin.plugin_id,
        "display_name": plugin.display_name,
        "version": plugin.version,
        "package_name": plugin.package_name,
        "source_type": plugin.source_type,
        "source": plugin.source,
        "github_url": plugin.github_url,
        "ref": plugin.ref,
        "commit_sha": plugin.commit_sha,
        "capabilities": {
            "bootstrappers": [
                item.__dict__ for item in plugin.capabilities.bootstrappers
            ],
            "stacks": [item.__dict__ for item in plugin.capabilities.stacks],
            "console_pages": [
                item.__dict__ for item in plugin.capabilities.console_pages
            ],
            "skills": [item.__dict__ for item in plugin.capabilities.skills],
            "django_url_modules": list(plugin.capabilities.django_url_modules),
        },
    }


def list_plugins_payload() -> list[dict]:
    registry = load_registry()
    return [plugin_to_payload(item) for item in registry.plugins]


def get_plugin_payload(plugin_id: str) -> dict | None:
    registry = load_registry()
    plugin = registry.get(plugin_id)
    if not plugin:
        return None
    return plugin_to_payload(plugin)


def get_console_registry_payload() -> dict:
    if not PLUGIN_CONSOLE_REGISTRY_PATH.is_file():
        return {"pages": []}
    return json.loads(PLUGIN_CONSOLE_REGISTRY_PATH.read_text())


def run_bootstrapper_payload(name: str, params: dict) -> dict:
    return run_bootstrapper(name, params=params)
