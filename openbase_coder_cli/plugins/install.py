from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from shutil import which

from .site import install_into_plugin_site, use_plugin_site


def _installer_command() -> list[str]:
    uv_bin = which("uv")
    if uv_bin:
        return [uv_bin, "pip", "install", "--python", sys.executable]
    return [sys.executable, "-m", "pip", "install"]


def _uninstaller_command() -> list[str]:
    uv_bin = which("uv")
    if uv_bin:
        return [uv_bin, "pip", "uninstall", "--python", sys.executable]
    return [sys.executable, "-m", "pip", "uninstall"]


def install_local_editable(path: Path) -> str:
    if use_plugin_site():
        # Editable installs cannot target the plugin site dir; install a
        # regular copy so it survives runtime-package upgrades.
        requirement = str(path)
        install_into_plugin_site(requirement)
        return requirement
    subprocess.run(
        [*_installer_command(), "-e", str(path)],
        check=True,
    )
    return f"-e {path}"


def install_github_pinned(url: str, commit_sha: str) -> str:
    requirement = f"git+{url}@{commit_sha}"
    if use_plugin_site():
        install_into_plugin_site(requirement)
        return requirement
    subprocess.run(
        [*_installer_command(), requirement],
        check=True,
    )
    return requirement


def uninstall_package(package_name: str) -> None:
    if use_plugin_site():
        # --target installs cannot be pip-uninstalled; the manager rebuilds
        # the plugin site from the registry's surviving requirements instead.
        return
    subprocess.run(
        [*_uninstaller_command(), "-y", package_name],
        check=False,
    )
