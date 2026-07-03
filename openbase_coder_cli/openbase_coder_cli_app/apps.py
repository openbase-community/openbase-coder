"""
Django app configuration for openbase_coder_cli_app.
"""

from __future__ import annotations

import logging

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class OpenbaseCoderCliAppConfig(AppConfig):
    """Configuration for the openbase_coder_cli_app Django application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "openbase_coder_cli.openbase_coder_cli_app"
    verbose_name = "Openbase Coder Cli"

    def ready(self):
        from openbase_coder_cli import dispatcher_config
        from openbase_coder_cli.openbase_coder_cli_app.skills import (
            _auto_link_normal_codex_skills_sync,
        )

        if not dispatcher_config.auto_link_normal_codex_skills():
            return
        try:
            _auto_link_normal_codex_skills_sync()
        except OSError:
            logger.exception("Unable to auto-link normal Codex skills on startup.")
