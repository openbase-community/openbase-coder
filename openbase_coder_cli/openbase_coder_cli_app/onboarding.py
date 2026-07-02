"""Onboarding status API view."""

from __future__ import annotations

from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from openbase_coder_cli.services.onboarding import onboarding_status_payload


@api_view(["GET"])
def onboarding_status(request):
    """Report local onboarding state (CLI configured, Tailscale, auth)."""
    return Response(onboarding_status_payload(), status=status.HTTP_200_OK)
