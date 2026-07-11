"""Local onboarding state for the Openbase onboarding flow.

Computes the CLI-side onboarding facts defined in the workspace
``specs/onboarding/`` spec: whether the CLI is configured, the local
Tailscale identity, Tailscale Serve health, and local auth presence.
"""

from __future__ import annotations

import json
import os
from typing import Any

from openbase_coder_cli.config.token_manager import (
    DEFAULT_WEB_BACKEND_URL,
    TokenManager,
)
from openbase_coder_cli.paths import (
    DEFAULT_ENV_FILE_PATH,
    ONBOARDING_JSON_PATH,
)
from openbase_coder_cli.services.installation import InstallationConfig
from openbase_coder_cli.services.launchd import launchctl_status
from openbase_coder_cli.services.selection import configured_default_services
from openbase_coder_cli.services.tailnet_devices import tailscale_self_identity
from openbase_coder_cli.services.tailscale_serve import tailscale_serve_health


def cli_configured_checks() -> dict[str, bool]:
    """Individual checks behind the ``cli_configured`` onboarding state."""
    installation_config = InstallationConfig.exists()
    env_file = False
    if installation_config:
        try:
            config = InstallationConfig.load()
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            installation_config = False
        else:
            env_path = config.env_file or str(DEFAULT_ENV_FILE_PATH)
            env_file = os.path.isfile(os.path.expanduser(env_path))

    services_installed = installation_config and all(
        launchctl_status(svc).get("installed") for svc in configured_default_services()
    )

    return {
        "installation_config": installation_config,
        "env_file": env_file,
        "services_installed": bool(services_installed),
    }


def compute_cli_configured() -> bool:
    return all(cli_configured_checks().values())


def read_onboarding_cache() -> dict[str, Any]:
    """Last-known cloud registration/report results written by this CLI."""
    try:
        payload = json.loads(ONBOARDING_JSON_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def write_onboarding_cache(updates: dict[str, Any]) -> None:
    payload = {**read_onboarding_cache(), **updates}
    ONBOARDING_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    ONBOARDING_JSON_PATH.write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )


def web_backend_url() -> str:
    return os.environ.get(
        "OPENBASE_CODER_CLI_WEB_BACKEND_URL", DEFAULT_WEB_BACKEND_URL
    ).rstrip("/")


def onboarding_status_payload() -> dict[str, Any]:
    """Local onboarding status consumed by the Mac app, iOS app, and console."""
    checks = cli_configured_checks()
    from openbase_coder_cli.self_update import version_info
    from openbase_coder_cli.services.tunneld import tsnet_enabled, voice_turn_info

    payload = {
        "cli_configured": all(checks.values()),
        "checks": checks,
        "versions": version_info(),
        "authenticated": TokenManager(web_backend_url()).has_refresh_token,
        "tailscale_self": tailscale_self_identity(),
        "tailscale_serve": tailscale_serve_health().to_dict(),
        "cloud": read_onboarding_cache(),
    }
    if tsnet_enabled():
        # Embedded-mode phones route WebRTC media through the tunneld TURN
        # relay; this endpoint is their credential channel (loopback and the
        # user's own tailnet only).
        turn = voice_turn_info()
        if turn:
            payload["voice_turn"] = turn
    return payload
