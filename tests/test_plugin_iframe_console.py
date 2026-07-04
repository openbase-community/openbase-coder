from __future__ import annotations

import json
from pathlib import Path

import pytest

from openbase_coder_cli.plugins.console import sync_console_integration
from openbase_coder_cli.plugins.models import (
    ConsolePageSpec,
    PluginCapabilities,
    PluginRecord,
    PluginRegistry,
)
from openbase_coder_cli.plugins.spec import normalize_capabilities


def test_normalize_capabilities_accepts_iframe_console_page():
    capabilities = normalize_capabilities(
        {
            "console_pages": [
                {
                    "key": "dashboard",
                    "title": "Dashboard",
                    "asset_dir": "web",
                    "entrypoint": "index.html",
                }
            ]
        },
        "example",
    )

    page = capabilities.console_pages[0]
    assert page.asset_dir == "web"
    assert page.route == "/dashboard/plugins/example/dashboard"


def test_normalize_capabilities_rejects_component_console_pages():
    with pytest.raises(Exception, match="only iframe console pages"):
        normalize_capabilities(
            {
                "console_pages": [
                    {
                        "key": "page",
                        "render": "component",
                        "import_module": "legacy/Page",
                    }
                ]
            },
            "legacy",
        )


def test_normalize_capabilities_requires_asset_dir():
    with pytest.raises(Exception, match="asset_dir"):
        normalize_capabilities(
            {"console_pages": [{"key": "page"}]},
            "example",
        )


def test_normalize_capabilities_rejects_project_views():
    with pytest.raises(Exception, match="project_views are no longer supported"):
        normalize_capabilities(
            {"project_views": [{"stack": "nextjs", "import_module": "legacy/View"}]},
            "legacy",
        )


def test_registry_load_tolerates_legacy_component_fields(tmp_path: Path):
    legacy_payload = {
        "plugins": [
            {
                "plugin_id": "legacy",
                "display_name": "Legacy",
                "version": "0.1.0",
                "package_name": "legacy",
                "source_type": "local",
                "source": "/tmp/legacy",
                "source_path": "/tmp/legacy",
                "entrypoint_name": "legacy",
                "entrypoint_value": "legacy.spec:get_plugin_spec",
                "requirement": "-e /tmp/legacy",
                "capabilities": {
                    "console_pages": [
                        {
                            "key": "page",
                            "title": "Page",
                            "route": "/dashboard/plugins/legacy/page",
                            "render": "component",
                            "import_module": "legacy/Page",
                            "export": "default",
                            "sidebar": True,
                            "asset_dir": "",
                            "entrypoint": "index.html",
                        }
                    ],
                    "project_views": [
                        {"stack": "nextjs", "import_module": "legacy/View"}
                    ],
                    "console_npm_packages": ["some-pkg"],
                },
            }
        ]
    }

    registry = PluginRegistry.from_dict(legacy_payload)

    page = registry.plugins[0].capabilities.console_pages[0]
    assert page.key == "page"
    assert not hasattr(page, "import_module")


def test_sync_console_integration_copies_iframe_assets(monkeypatch, tmp_path: Path):
    source = tmp_path / "plugin"
    assets = source / "web"
    assets.mkdir(parents=True)
    (assets / "index.html").write_text("<h1>Plugin</h1>", encoding="utf-8")
    registry_path = tmp_path / "registry.json"
    assets_root = tmp_path / "assets"
    monkeypatch.setattr(
        "openbase_coder_cli.plugins.store.PLUGIN_CONSOLE_REGISTRY_PATH",
        registry_path,
    )
    monkeypatch.setattr(
        "openbase_coder_cli.plugins.console.PLUGIN_CONSOLE_ASSETS_DIR",
        assets_root,
    )

    registry = PluginRegistry(
        plugins=[
            PluginRecord(
                plugin_id="example",
                display_name="Example",
                version="0.1.0",
                package_name="example",
                source_type="local",
                source=str(source),
                source_path=str(source),
                entrypoint_name="example",
                entrypoint_value="example.spec:get_plugin_spec",
                requirement=f"-e {source}",
                capabilities=PluginCapabilities(
                    console_pages=[
                        ConsolePageSpec(
                            key="dashboard",
                            title="Dashboard",
                            route="/dashboard/plugins/example/dashboard",
                            asset_dir="web",
                        )
                    ]
                ),
            )
        ]
    )

    sync_console_integration(registry)

    copied = assets_root / "example" / "dashboard" / "index.html"
    assert copied.read_text(encoding="utf-8") == "<h1>Plugin</h1>"
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    page = payload["pages"][0]["pages"][0]
    assert page["iframe_url"] == (
        "/openbase-plugin-assets/example/dashboard/index.html"
    )
