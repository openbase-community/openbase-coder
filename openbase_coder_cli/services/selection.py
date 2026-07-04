"""Backend-aware service selection for the current installation."""

from __future__ import annotations

import json
from pathlib import Path

from openbase_coder_cli.env_file import selected_backend_from_env_file
from openbase_coder_cli.paths import DEFAULT_ENV_FILE_PATH
from openbase_coder_cli.services.definitions import (
    ServiceDefinition,
    default_services,
)
from openbase_coder_cli.services.installation import InstallationConfig


def configured_env_file_path() -> Path:
    """The env file recorded by the installation, or the default location."""
    if InstallationConfig.exists():
        try:
            config = InstallationConfig.load()
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return DEFAULT_ENV_FILE_PATH
        if config.env_file:
            return Path(config.env_file).expanduser()
    return DEFAULT_ENV_FILE_PATH


def configured_coding_backend() -> str:
    """The coding backend selected by the current installation's env file."""
    return selected_backend_from_env_file(configured_env_file_path())


def configured_default_services() -> list[ServiceDefinition]:
    """Default services applicable to the currently selected coding backend."""
    return default_services(configured_coding_backend())
