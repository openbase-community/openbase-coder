"""Local onboarding state for the Openbase onboarding flow.

Computes the CLI-side onboarding facts defined in the workspace
``specs/onboarding/`` spec: whether the CLI is configured, the local
Tailscale identity, Tailscale Serve health, and local auth presence.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from openbase_coder_cli.backend_config import (
    CLAUDE_CODE_BACKEND,
    OPENBASE_CLOUD_BACKEND,
)
from openbase_coder_cli.claude_auth import claude_auth_status
from openbase_coder_cli.config.token_manager import (
    DEFAULT_WEB_BACKEND_URL,
    TokenManager,
)
from openbase_coder_cli.env_file import selected_backend_from_env_file
from openbase_coder_cli.paths import (
    CODEX_HOME_DIR,
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


def selected_coding_backend() -> str:
    """The coding backend configured for this install (env file wins)."""
    env_path = DEFAULT_ENV_FILE_PATH
    if InstallationConfig.exists():
        try:
            config = InstallationConfig.load()
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass
        else:
            if config.env_file:
                env_path = os.path.expanduser(config.env_file)
    return selected_backend_from_env_file(Path(env_path))


def codex_auth_present() -> bool:
    """Whether the service Codex home has a usable auth.json."""
    auth_path = CODEX_HOME_DIR / "auth.json"
    try:
        payload = json.loads(auth_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return False
    return isinstance(payload, dict) and bool(payload)


def backend_auth_status(*, authenticated: bool | None = None) -> dict[str, Any]:
    """Auth readiness for the selected coding backend.

    ``ready`` means the backend can start coding sessions without an
    interactive login. Openbase Cloud rides on the CLI's own cloud login,
    so its readiness equals ``authenticated``.
    """
    backend = selected_coding_backend()
    if backend == CLAUDE_CODE_BACKEND:
        ready = claude_auth_status().logged_in
    elif backend == OPENBASE_CLOUD_BACKEND:
        if authenticated is None:
            authenticated = TokenManager(web_backend_url()).has_refresh_token
        ready = authenticated
    else:
        ready = codex_auth_present()
    return {"backend": backend, "ready": ready}


def web_backend_url() -> str:
    return os.environ.get(
        "OPENBASE_CODER_CLI_WEB_BACKEND_URL", DEFAULT_WEB_BACKEND_URL
    ).rstrip("/")


def onboarding_status_payload() -> dict[str, Any]:
    """Local onboarding status consumed by the Mac app and console."""
    checks = cli_configured_checks()
    from openbase_coder_cli.self_update import version_info

    authenticated = TokenManager(web_backend_url()).has_refresh_token
    return {
        "cli_configured": all(checks.values()),
        "checks": checks,
        "versions": version_info(),
        "authenticated": authenticated,
        "backend_auth": backend_auth_status(authenticated=authenticated),
        "tailscale_self": tailscale_self_identity(),
        "tailscale_serve": tailscale_serve_health().to_dict(),
        "cloud": read_onboarding_cache(),
    }
