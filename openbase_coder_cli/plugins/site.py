"""Stable plugin site directory for standalone installs.

Standalone runtime packages are replaced wholesale on upgrade, so plugin
Python packages must not live inside them. They are installed into
``~/.openbase/plugins/site`` instead, which every Openbase process adds
to ``sys.path`` at import time (see the package ``__init__``).

Dev installs keep using the workspace venv directly; it persists on its own.
"""

from __future__ import annotations

import shutil
import site
import subprocess
import sys

from openbase_coder_cli.paths import PLUGIN_SITE_DIR
from openbase_coder_cli.runtime import is_standalone_runtime


def activate_plugin_site() -> None:
    if PLUGIN_SITE_DIR.is_dir():
        site.addsitedir(str(PLUGIN_SITE_DIR))


def use_plugin_site() -> bool:
    """Whether plugin packages should install into the stable site dir."""
    return is_standalone_runtime()


def install_into_plugin_site(requirement: str) -> None:
    PLUGIN_SITE_DIR.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--upgrade",
            "--target",
            str(PLUGIN_SITE_DIR),
            requirement,
        ],
        check=True,
    )
    activate_plugin_site()


def rebuild_plugin_site(requirements: list[str]) -> None:
    """Reinstall the site dir from scratch to match the plugin registry.

    ``pip uninstall`` cannot remove ``--target`` installs, so removal and
    rollback are handled by rebuilding from the surviving requirements. Also
    the recovery path after a runtime-package upgrade with a new Python.
    """
    if PLUGIN_SITE_DIR.exists():
        shutil.rmtree(PLUGIN_SITE_DIR)
    for requirement in requirements:
        install_into_plugin_site(requirement)
