"""Stable plugin site directory for every install mode.

Standalone runtime packages are replaced wholesale on upgrade, so plugin
Python packages must not live inside them. They are installed into
``~/.openbase/plugins/site`` instead, which every Openbase Coder process adds
to ``sys.path`` at import time (see the package ``__init__``).

Dev installs use the same site dir: installing plugins into the workspace
venv would let ``uv sync`` silently wipe them, and would leave the site-dir
import mechanics — the only path production exercises — untested in
development.
"""

from __future__ import annotations

import shutil
import site
import subprocess
import sys

from openbase_coder_cli.paths import PLUGIN_SITE_DIR


def activate_plugin_site() -> None:
    if PLUGIN_SITE_DIR.is_dir():
        site.addsitedir(str(PLUGIN_SITE_DIR))


def use_plugin_site() -> bool:
    """Whether plugin packages should install into the stable site dir.

    Always true: dev and standalone share the site dir so both pathways run
    the same plugin import mechanics and ``uv sync`` cannot wipe plugins.
    """
    return True


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
