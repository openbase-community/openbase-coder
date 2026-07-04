"""Self-update API views (see the workspace AUTO_UPDATE.md guide)."""

from __future__ import annotations

import subprocess

from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from openbase_coder_cli.paths import DEFAULT_LOG_DIR, STANDALONE_CURRENT_DIR
from openbase_coder_cli.runtime import is_standalone_runtime
from openbase_coder_cli.self_update import (
    SelfUpdateError,
    check_for_update,
    version_info,
)


@api_view(["GET"])
def update_status(request):
    """Version facts plus update flags; ?refresh=1 re-checks the feed."""
    payload = version_info()
    if request.query_params.get("refresh"):
        try:
            check = check_for_update()
        except SelfUpdateError as exc:
            payload["check_error"] = str(exc)
        else:
            payload["update_available"] = check.update_available
            payload["update_required"] = check.update_required
            if check.latest_version:
                payload["latest_version"] = check.latest_version
    return Response(payload, status=status.HTTP_200_OK)


@api_view(["POST"])
def update_apply(request):
    """Kick off a detached self-update of the standalone install.

    Detached because the update restarts the very services serving this
    request; progress lands in the self-update log.
    """
    if not is_standalone_runtime():
        return Response(
            {
                "error": "Development workspace installs are git-managed; no auto-update."
            },
            status=status.HTTP_400_BAD_REQUEST,
        )
    launcher = STANDALONE_CURRENT_DIR / "bin" / "openbase-coder"
    if not launcher.is_file():
        return Response(
            {"error": f"Standalone launcher not found at {launcher}."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    args = [str(launcher), "self-update", "--json"]
    if request.data.get("force"):
        args.append("--force")

    DEFAULT_LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = DEFAULT_LOG_DIR / "self-update.log"
    with log_path.open("ab") as log_handle:
        subprocess.Popen(
            args,
            stdout=log_handle,
            stderr=log_handle,
            start_new_session=True,
        )
    return Response(
        {"started": True, "log": str(log_path)},
        status=status.HTTP_202_ACCEPTED,
    )
