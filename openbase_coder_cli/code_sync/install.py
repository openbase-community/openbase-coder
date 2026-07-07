"""On-demand Syncthing installation.

Syncthing is not bundled in the standalone package: most installs never
enable code-sync, and the binary adds ~25 MB. Instead, enabling sync
downloads a pinned upstream release, verifies its sha256 against checksums
recorded here (cross-checked against Syncthing's signed sha256sum.txt.asc),
and installs it at ``~/.openbase/bin/syncthing`` — outside the versioned
package tree so it survives CLI self-updates.
"""

from __future__ import annotations

import hashlib
import platform
import shutil
import tarfile
import tempfile
import zipfile
from pathlib import Path

import click
import httpx

from openbase_coder_cli.paths import OPENBASE_BASE_DIR

SYNCTHING_VERSION = "v2.1.1"
_DOWNLOAD_BASE = (
    "https://github.com/syncthing/syncthing/releases/download/" + SYNCTHING_VERSION
)
# (system, machine) -> (asset name, sha256). Update alongside SYNCTHING_VERSION;
# values must match the release's signed sha256sum.txt.asc.
_ASSETS: dict[tuple[str, str], tuple[str, str]] = {
    ("Darwin", "arm64"): (
        f"syncthing-macos-arm64-{SYNCTHING_VERSION}.zip",
        "0484ec8508ae49a45f3a23b8b5d652e03e2dcdb8492911244f805e13f61bd6c1",
    ),
    ("Darwin", "x86_64"): (
        f"syncthing-macos-amd64-{SYNCTHING_VERSION}.zip",
        "d96b74c61908e3dfc75c57d40b7489ca0d9cff2e9bc82c383e1b537a84b6d16d",
    ),
    ("Linux", "aarch64"): (
        f"syncthing-linux-arm64-{SYNCTHING_VERSION}.tar.gz",
        "2c831e27c73a5c9217bdbbfcdb695d41b027f9d8bf8303f55590881e7b907f7f",
    ),
    ("Linux", "arm64"): (
        f"syncthing-linux-arm64-{SYNCTHING_VERSION}.tar.gz",
        "2c831e27c73a5c9217bdbbfcdb695d41b027f9d8bf8303f55590881e7b907f7f",
    ),
    ("Linux", "x86_64"): (
        f"syncthing-linux-amd64-{SYNCTHING_VERSION}.tar.gz",
        "0b960a67a0391156c2ca45943ed1ceaad9ae1fc3772d967e6aafc5a7c662565d",
    ),
}

MANAGED_SYNCTHING_PATH = OPENBASE_BASE_DIR / "bin" / "syncthing"


def managed_syncthing_path() -> Path:
    return MANAGED_SYNCTHING_PATH


def syncthing_installed() -> bool:
    return MANAGED_SYNCTHING_PATH.is_file()


def ensure_syncthing_installed(*, echo=click.echo) -> Path:
    """Ensure syncthing is available; download the pinned release if not.

    Honors an existing syncthing on PATH (e.g. an apt/homebrew install or a
    DevSpace AMI that pre-baked it) — only downloads when nothing is
    resolvable, so enabling sync never re-fetches a binary the host already
    has.
    """
    if syncthing_installed():
        return MANAGED_SYNCTHING_PATH

    existing = shutil.which("syncthing")
    if existing:
        return Path(existing)

    key = (platform.system(), platform.machine())
    asset = _ASSETS.get(key)
    if asset is None:
        raise click.ClickException(
            f"No pinned Syncthing build for {key[0]}/{key[1]}. "
            "Install syncthing manually and re-run."
        )
    asset_name, expected_sha = asset
    url = f"{_DOWNLOAD_BASE}/{asset_name}"

    echo(f"Downloading Syncthing {SYNCTHING_VERSION} ({asset_name})...")
    with tempfile.TemporaryDirectory() as tmp:
        archive_path = Path(tmp) / asset_name
        digest = hashlib.sha256()
        with httpx.stream("GET", url, follow_redirects=True, timeout=120) as response:
            response.raise_for_status()
            with archive_path.open("wb") as handle:
                for chunk in response.iter_bytes():
                    handle.write(chunk)
                    digest.update(chunk)
        actual_sha = digest.hexdigest()
        if actual_sha != expected_sha:
            raise click.ClickException(
                f"Syncthing download checksum mismatch for {asset_name}: "
                f"expected {expected_sha}, got {actual_sha}. Aborting install."
            )
        binary = _extract_binary(archive_path, Path(tmp))
        MANAGED_SYNCTHING_PATH.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(binary), MANAGED_SYNCTHING_PATH)
        MANAGED_SYNCTHING_PATH.chmod(0o755)

    echo(f"Installed syncthing at {MANAGED_SYNCTHING_PATH}")
    return MANAGED_SYNCTHING_PATH


def _extract_binary(archive_path: Path, work_dir: Path) -> Path:
    extract_dir = work_dir / "extracted"
    extract_dir.mkdir()
    if archive_path.name.endswith(".zip"):
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(extract_dir)
    else:
        with tarfile.open(archive_path, "r:gz") as archive:
            archive.extractall(extract_dir, filter="data")
    matches = sorted(extract_dir.glob("*/syncthing"))
    if not matches:
        raise click.ClickException(
            f"Syncthing archive {archive_path.name} did not contain the "
            "expected binary."
        )
    return matches[0]
