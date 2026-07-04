"""Console integration for plugins: iframe pages served at runtime.

Plugin console pages are prebuilt static assets copied into
``~/.openbase/plugins/console-assets`` and served by the Django server; the
console discovers them through ``/api/plugins/console-registry/``. No console
rebuild is involved, so pages work identically in dev and standalone installs
and can be added after installation.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from openbase_coder_cli.paths import PLUGIN_CONSOLE_ASSETS_DIR

from .models import PluginRegistry
from .store import save_console_registry


def sync_console_integration(registry: PluginRegistry) -> None:
    _sync_iframe_assets(registry)
    payload = {
        "pages": [
            {
                "plugin_id": plugin.plugin_id,
                "pages": [
                    _console_page_payload(plugin.plugin_id, page)
                    for page in plugin.capabilities.console_pages
                ],
            }
            for plugin in registry.plugins
        ],
    }
    save_console_registry(payload)


def _console_page_payload(plugin_id: str, page) -> dict:
    payload = page.__dict__.copy()
    payload["iframe_url"] = (
        f"/openbase-plugin-assets/{plugin_id}/{page.key}/{page.entrypoint}"
    )
    return payload


def _sync_iframe_assets(registry: PluginRegistry) -> None:
    PLUGIN_CONSOLE_ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    active_targets: set[Path] = set()

    for plugin in registry.plugins:
        source_root = Path(plugin.source_path)
        for page in plugin.capabilities.console_pages:
            source = (source_root / page.asset_dir).resolve()
            if not source.is_dir():
                raise FileNotFoundError(
                    f"Console page asset_dir not found for {plugin.plugin_id}/{page.key}: {source}"
                )
            target = PLUGIN_CONSOLE_ASSETS_DIR / plugin.plugin_id / page.key
            active_targets.add(target.resolve())
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(source, target)

    for plugin_dir in PLUGIN_CONSOLE_ASSETS_DIR.iterdir():
        if not plugin_dir.is_dir():
            continue
        for page_dir in plugin_dir.iterdir():
            if page_dir.is_dir() and page_dir.resolve() not in active_targets:
                shutil.rmtree(page_dir)
