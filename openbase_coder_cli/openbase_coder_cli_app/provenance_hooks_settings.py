"""Openbase git provenance hooks settings API views.

Reports whether the inject-session-id SessionStart hooks are installed in the
Openbase-managed Claude Code and Codex homes, and installs them on demand.
"""

from __future__ import annotations

from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from openbase_coder_cli.provenance_hooks import (
    install_provenance_hooks,
    provenance_hooks_status,
)


@api_view(["GET", "POST"])
def openbase_hooks_settings(request):
    """Read the provenance hooks install state, or install the hooks."""
    if request.method == "GET":
        return Response(provenance_hooks_status(), status=status.HTTP_200_OK)

    payload = install_provenance_hooks()
    payload["changed"] = True
    return Response(payload, status=status.HTTP_200_OK)
