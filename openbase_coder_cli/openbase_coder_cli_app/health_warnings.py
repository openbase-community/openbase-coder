"""Aggregated health warnings for the console banner.

The console shows a top-of-page banner when something the current
configuration *expects* is not actually healthy. Expectations follow
configuration, not a fixed list: services installed by default are always
expected; conditional services (code-sync) are expected exactly when their
feature is enabled — and conversely are flagged when running without their
feature enabled.
"""

from __future__ import annotations

import time
from typing import Callable

from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

RECONCILE_STALE_SECONDS = 10 * 60

# Conditional services: expected exactly when the callable returns True.
# Services not listed here are expected iff install_by_default.
_CONDITIONAL_SERVICES: dict[str, Callable[[], bool]] = {}


def _code_sync_expected() -> bool:
    from openbase_coder_cli.sync_config import code_sync_enabled

    try:
        return code_sync_enabled()
    except ValueError:
        return False


_CONDITIONAL_SERVICES["code-sync"] = _code_sync_expected
# Cross-device thread sync rides the code-sync transport; when devices are
# mirrored, both backends' device-sync services are expected too.
_CONDITIONAL_SERVICES["codex-thread-device-sync"] = _code_sync_expected
_CONDITIONAL_SERVICES["claude-thread-device-sync"] = _code_sync_expected


def _warning(
    warning_id: str, severity: str, message: str, action: str = ""
) -> dict[str, str]:
    return {
        "id": warning_id,
        "severity": severity,  # "warning" | "critical"
        "message": message,
        "action": action,
    }


def _service_warnings() -> list[dict[str, str]]:
    from openbase_coder_cli.services.definitions import SERVICES
    from openbase_coder_cli.services.launchd import launchctl_status

    warnings: list[dict[str, str]] = []
    for service in SERVICES:
        conditional = _CONDITIONAL_SERVICES.get(service.name)
        expected = conditional() if conditional else service.install_by_default
        try:
            info = launchctl_status(service)
        except Exception:  # noqa: BLE001 - status probe must never break health
            continue
        installed = bool(info.get("installed"))
        running = bool(info.get("pid"))
        if expected and not installed:
            warnings.append(
                _warning(
                    f"service-missing:{service.name}",
                    "critical",
                    f"Expected service '{service.name}' is not installed.",
                    "Run 'openbase-coder services install'.",
                )
            )
        elif expected and not running:
            warnings.append(
                _warning(
                    f"service-stopped:{service.name}",
                    "critical",
                    f"Expected service '{service.name}' is not running "
                    f"(last exit: {info.get('last_exit_code', 'unknown')}).",
                    "Run 'openbase-coder restart'.",
                )
            )
        elif not expected and conditional is not None and installed:
            warnings.append(
                _warning(
                    f"service-unexpected:{service.name}",
                    "warning",
                    f"Service '{service.name}' is installed but its feature "
                    "is disabled.",
                    "Disable removed the feature; uninstall the service or "
                    "re-enable the feature.",
                )
            )
    return warnings


def _sync_warnings() -> list[dict[str, str]]:
    from openbase_coder_cli.code_sync import CodeSyncError
    from openbase_coder_cli.code_sync import manager as sync_manager
    from openbase_coder_cli.code_sync.ignores import STIGNORE_FILENAME
    from openbase_coder_cli.code_sync.reconciler import read_reconcile_state
    from openbase_coder_cli.code_sync.syncthing import SyncthingClient
    from openbase_coder_cli.services.tailnet_devices import tailscale_self_identity
    from openbase_coder_cli.sync_config import sync_folders

    warnings: list[dict[str, str]] = []

    # Engine reachable + peers connected.
    try:
        client = SyncthingClient()
        for device_id, conn in client.connections().items():
            if not conn.get("connected") and not conn.get("paused"):
                warnings.append(
                    _warning(
                        f"sync-peer-disconnected:{device_id[:7]}",
                        "critical",
                        f"Sync peer {device_id[:7]}… is not connected; file "
                        "sync between your machines is stopped.",
                        "Check the peer machine is on and on the tailnet; "
                        "see the file-sync skill for half-open connections.",
                    )
                )
    except CodeSyncError as exc:
        warnings.append(
            _warning(
                "sync-engine-unreachable",
                "critical",
                f"Code sync is enabled but its engine is unreachable: {exc}",
                "Run 'openbase-coder restart' or 'openbase-coder sync enable'.",
            )
        )

    # This device must advertise a tailscale identity or peers will drop it.
    identity = tailscale_self_identity()
    if not identity.get("available"):
        warnings.append(
            _warning(
                "sync-no-tailscale-identity",
                "critical",
                "This device's registration has no Tailscale identity; "
                "peers will drop it from their sync configuration.",
                identity.get("error") or "Check Tailscale is installed and up.",
            )
        )

    # A second, user-managed Syncthing syncing the same folders echoes
    # writes into conflict storms.
    try:
        sync_manager.ensure_no_user_managed_overlap(sync_folders())
    except CodeSyncError as exc:
        warnings.append(_warning("sync-user-managed-overlap", "critical", str(exc), ""))

    # Reconciler heartbeat: git branch pointers stop propagating silently.
    state = read_reconcile_state()
    last = state.get("last_reconcile_at")
    if last:
        try:
            last_epoch = time.mktime(time.strptime(last, "%Y-%m-%dT%H:%M:%SZ"))
            stale = (time.time() - time.timezone) - last_epoch
        except ValueError:
            stale = None
        if stale is not None and stale > RECONCILE_STALE_SECONDS:
            warnings.append(
                _warning(
                    "sync-reconcile-stale",
                    "warning",
                    f"Git-state reconciliation last ran {int(stale // 60)} "
                    "minutes ago; commits are not propagating.",
                    "Check the openbase-routines service.",
                )
            )

    # Managed ignore integrity: losing the VCS block silently syncs .git.
    for folder in sync_folders():
        stignore = folder.absolute_path() / STIGNORE_FILENAME
        try:
            content = stignore.read_text(encoding="utf-8", errors="replace")
        except OSError:
            content = ""
        if "(?d).git" not in content:
            warnings.append(
                _warning(
                    f"sync-stignore-broken:{folder.folder_id}",
                    "critical",
                    f"Sync folder '{folder.relpath}' is missing its .git "
                    "ignore; syncing .git corrupts repositories.",
                    "Run 'openbase-coder sync enable' to regenerate it.",
                )
            )
    return warnings


def _installation_warnings() -> list[dict[str, str]]:
    """Warn when a dev workspace exists but a packaged install serves it.

    The two sanctioned installs (see the workspace glossary's Installation
    pathways) are mutually exclusive on one machine in practice: if the
    Projects list tracks an ``openbase-coder-workspace`` checkout, the
    developer expects localhost:7999 to serve that code — a standalone
    (app-installed) runtime silently serves something older instead.
    """
    from openbase_coder_cli.mcp.projects import get_recent_projects
    from openbase_coder_cli.services.installation import InstallationConfig

    try:
        if not InstallationConfig.exists():
            return []
        config = InstallationConfig.load()
    except Exception:  # noqa: BLE001 - health must never break on bad state
        return []
    if not config.standalone:
        return []

    for project in get_recent_projects():
        path = project.get("path", "")
        if path.rstrip("/").split("/")[-1] == "openbase-coder-workspace":
            return [
                _warning(
                    "installation-not-dev",
                    "warning",
                    "An openbase-coder-workspace checkout is in your "
                    "projects, but this machine runs a packaged install — "
                    "the code on disk is not what localhost:7999 serves.",
                    "For development, archive ~/.openbase and run the "
                    "workspace's ./scripts/setup (dev pathway).",
                )
            ]
    return []


def _livekit_skew_warnings() -> list[dict[str, str]]:
    """Warn dev installs whose livekit-server differs from the release pin.

    Dev resolves livekit-server from Homebrew/PATH while releases bundle
    the pinned version; a divergence means development tests a different
    voice engine than users run.
    """
    import re
    import subprocess

    from openbase_coder_cli.livekit_version import LIVEKIT_SERVER_PINNED_VERSION
    from openbase_coder_cli.services.installation import InstallationConfig

    try:
        if not InstallationConfig.exists() or InstallationConfig.load().standalone:
            return []  # Standalone installs run the bundled pin by construction.
    except Exception:  # noqa: BLE001
        return []

    binary = _resolve_livekit_binary()
    if binary is None:
        return []  # Missing binary surfaces through service checks instead.
    try:
        result = subprocess.run(
            [binary, "--version"], capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    match = re.search(r"(\d+\.\d+\.\d+)", result.stdout + result.stderr)
    if not match or match.group(1) == LIVEKIT_SERVER_PINNED_VERSION:
        return []
    return [
        _warning(
            "livekit-version-skew",
            "warning",
            f"This dev install runs livekit-server {match.group(1)}, but "
            f"releases ship {LIVEKIT_SERVER_PINNED_VERSION} — voice testing "
            "here exercises a different engine than users run.",
            "Align your local livekit-server with the pin in "
            "livekit_version.py (or bump the pin deliberately).",
        )
    ]


def _resolve_livekit_binary() -> str | None:
    import shutil

    found = shutil.which("livekit-server")
    if found:
        return found
    fallback = "/opt/homebrew/bin/livekit-server"
    import os

    return fallback if os.access(fallback, os.X_OK) else None


def collect_warnings() -> list[dict[str, str]]:
    warnings = _service_warnings()
    warnings.extend(_installation_warnings())
    warnings.extend(_livekit_skew_warnings())
    if _code_sync_expected():
        warnings.extend(_sync_warnings())
    return warnings


@api_view(["GET"])
def health_warnings(request):
    """Warnings the console surfaces in its top banner."""
    return Response({"warnings": collect_warnings()}, status=status.HTTP_200_OK)
