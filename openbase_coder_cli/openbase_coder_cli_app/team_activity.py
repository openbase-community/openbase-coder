"""Local proxy so on-machine agents can read the team activity feed.

Keeps cloud tokens inside the CLI: super-agents (MCP) calls this endpoint on
localhost, and the CLI forwards to openbase-cloud with its own credentials.
Failures return 200 with {"supported": false} so agents degrade gracefully.
"""

from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from openbase_coder_cli.services.team_activity import fetch_team_activity


@api_view(["GET"])
def team_activity_feed(request):
    return Response(fetch_team_activity(), status=status.HTTP_200_OK)
