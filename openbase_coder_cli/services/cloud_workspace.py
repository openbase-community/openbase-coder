"""Identity helpers for Openbase Cloud-provisioned workspaces."""

from __future__ import annotations

import re
from pathlib import Path

DEVSPACE_PUBLIC_ID_PATH = Path("/etc/openbase/devspace-public-id")
DEVSPACE_TAILSCALE_HOSTNAME_PATH = Path("/etc/openbase/devspace-tailscale-hostname")
_PUBLIC_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,19}$")
_LEGACY_HOSTNAME_PATTERN = re.compile(r"^devspace-([a-z0-9][a-z0-9-]{0,19})$")


def _read_marker(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8").strip().lower()
    except (OSError, UnicodeError):
        return None


def cloud_workspace_id(
    *,
    public_id_path: Path = DEVSPACE_PUBLIC_ID_PATH,
    tailscale_hostname_path: Path = DEVSPACE_TAILSCALE_HOSTNAME_PATH,
) -> str | None:
    public_id = _read_marker(public_id_path)
    if public_id and _PUBLIC_ID_PATTERN.fullmatch(public_id):
        return public_id

    hostname = _read_marker(tailscale_hostname_path)
    if hostname:
        match = _LEGACY_HOSTNAME_PATTERN.fullmatch(hostname)
        if match:
            return match.group(1)

    return None
