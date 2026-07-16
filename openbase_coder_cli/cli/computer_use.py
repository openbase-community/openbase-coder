from __future__ import annotations

import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import click
import httpx

from openbase_coder_cli.cli.local_server import local_server_request, response_error
from openbase_coder_cli.linux_computer_use import serve_linux_companion

DEFAULT_COMPANION_PORT = 39281
DEFAULT_COMPANION_SECRET = "openbase-livekit-companion-local"
COMPANION_IDENTITY = "openbase-screen-share-companion"
COMPANION_NAME = "Openbase Screen Share"


@click.group("computer-use")
def computer_use() -> None:
    """Use the Linux desktop screen-share companion for OpenAI Computer Use."""
    if platform.system() == "Darwin":
        raise click.ClickException(
            "The openbase-coder computer-use CLI is Linux-only. On macOS, use "
            "the openbase-computer-use skill's native Computer Use tool path."
        )
    if platform.system() != "Linux":
        raise click.ClickException(
            "The openbase-coder computer-use CLI is only supported on Linux "
            "Openbase DevSpace desktops."
        )


@computer_use.command("start")
@click.argument("instructions", nargs=-1, required=True)
@click.option("--room", "room_name", default="", help="Explicit LiveKit room name.")
@click.option("--model", default="", help="OpenAI computer-use model override.")
@click.option("--max-steps", default=30, show_default=True, type=int)
@click.option(
    "--no-launch",
    is_flag=True,
    help="Do not launch the companion app if its IPC server is not reachable.",
)
def start(
    instructions: tuple[str, ...],
    room_name: str,
    model: str,
    max_steps: int,
    no_launch: bool,
) -> None:
    """Start screen sharing, then start one computer-use run."""
    text = " ".join(instructions).strip()
    if not text:
        raise click.ClickException("Computer-use instructions are required.")
    if max_steps < 1:
        raise click.ClickException("--max-steps must be at least 1.")

    client = CompanionClient()
    if not no_launch:
        client.ensure_running()

    status_payload = client.status()
    if status_payload.get("state") in {"controlling", "starting-control"}:
        raise click.ClickException("Computer use is already running.")

    session = _load_companion_session(room_name)
    try:
        client.start_screen_share(session)
    except click.ClickException:
        raise
    except Exception as exc:
        raise click.ClickException(f"Unable to start screen sharing: {exc}") from None

    try:
        response = client.start_computer_use(
            instructions=text,
            model=model.strip() or None,
            max_steps=max_steps,
        )
    except Exception as exc:
        try:
            client.stop_screen_share()
        finally:
            raise click.ClickException(f"Unable to start computer use: {exc}") from None

    click.echo(
        f"Computer use started ({response.get('state') or 'controlling'}). "
        "Screen sharing will stop when it completes."
    )


@computer_use.command("steer")
@click.argument("instructions", nargs=-1, required=True)
def steer(instructions: tuple[str, ...]) -> None:
    """Replace the latest steering instruction for the active computer-use run."""
    text = " ".join(instructions).strip()
    if not text:
        raise click.ClickException("Steering instructions are required.")

    response = CompanionClient().steer_computer_use(text)
    click.echo(
        f"Computer-use steering updated ({response.get('state') or 'controlling'})."
    )


@computer_use.command("queue")
@click.argument("instructions", nargs=-1, required=True)
def queue(instructions: tuple[str, ...]) -> None:
    """Queue a follow-up instruction after the active computer-use task."""
    text = " ".join(instructions).strip()
    if not text:
        raise click.ClickException("Queued instructions are required.")

    response = CompanionClient().queue_computer_use(text)
    click.echo(
        f"Computer-use instruction queued ({response.get('state') or 'controlling'})."
    )


@computer_use.command("interrupt")
def interrupt() -> None:
    """Interrupt the active computer-use run and stop screen sharing."""
    response = CompanionClient().interrupt_computer_use()
    click.echo(f"Computer use interrupted ({response.get('state') or 'off'}).")


@computer_use.command("status")
def status() -> None:
    """Show the companion computer-use status."""
    response = CompanionClient().status()
    state = response.get("state") or "unknown"
    click.echo(f"Companion state: {state}")
    if error := response.get("error"):
        click.echo(f"Error: {error}")
    linux = response.get("linux")
    if isinstance(linux, dict):
        click.echo(f"Display: {linux.get('display') or 'unknown'}")
        click.echo(
            "Linux tools: "
            f"xdotool={'yes' if linux.get('xdotool') else 'no'}, "
            f"screenshot={'yes' if linux.get('screenshot') else 'no'}, "
            f"imagemagick={'yes' if linux.get('imagemagick') else 'no'}"
        )


@computer_use.command("companion", hidden=True)
def companion() -> None:
    """Run the Linux computer-use companion IPC server in the foreground."""
    port = int(os.environ.get("OPENBASE_LIVEKIT_COMPANION_IPC_PORT", DEFAULT_COMPANION_PORT))
    secret = os.environ.get(
        "OPENBASE_LIVEKIT_COMPANION_IPC_SECRET",
        DEFAULT_COMPANION_SECRET,
    )
    serve_linux_companion(port=port, secret=secret)


def _load_companion_session(room_name: str) -> dict[str, Any]:
    params = {"room_name": room_name.strip()} if room_name.strip() else None
    response = local_server_request(
        "GET",
        "/api/livekit-companion-session/",
        params=params,
    )

    payload = response.json()
    room_url = payload.get("roomUrl")
    token = payload.get("companionToken")
    if not room_url or not token:
        raise click.ClickException(
            "Companion session response is missing roomUrl or companionToken."
        )

    return {
        "roomUrl": room_url,
        "token": token,
        "identity": COMPANION_IDENTITY,
        "name": COMPANION_NAME,
        "companionTokenExpiresAt": payload.get("companionTokenExpiresAt"),
    }


class CompanionClient:
    def __init__(self) -> None:
        self.port = int(
            os.environ.get(
                "OPENBASE_LIVEKIT_COMPANION_IPC_PORT", DEFAULT_COMPANION_PORT
            )
        )
        self.secret = os.environ.get(
            "OPENBASE_LIVEKIT_COMPANION_IPC_SECRET",
            DEFAULT_COMPANION_SECRET,
        )

    def ensure_running(self) -> None:
        if self._status_or_none() is not None:
            return

        log_path = os.environ.get(
            "OPENBASE_LIVEKIT_COMPANION_LOG_PATH",
            str(Path.home() / ".openbase" / "logs" / "livekit-companion.log"),
        )
        Path(log_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        log_handle = Path(log_path).expanduser().open("a", encoding="utf-8")
        env = {
            **os.environ,
            "OPENBASE_LIVEKIT_COMPANION_IPC_PORT": str(self.port),
            "OPENBASE_LIVEKIT_COMPANION_IPC_SECRET": self.secret,
        }
        try:
            subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "openbase_coder_cli.cli",
                    "computer-use",
                    "companion",
                ],
                stdout=log_handle,
                stderr=log_handle,
                start_new_session=True,
                env=env,
            )
        finally:
            log_handle.close()

        deadline = time.monotonic() + 10
        last_error = "unknown error"
        while time.monotonic() < deadline:
            time.sleep(0.35)
            response = self._status_or_none()
            if response is not None:
                return
            last_error = "companion IPC did not respond"

        raise click.ClickException(
            f"LiveKit companion did not become ready: {last_error}"
        )

    def status(self) -> dict[str, Any]:
        return self._request("GET", "/status")

    def start_screen_share(self, session: dict[str, Any]) -> dict[str, Any]:
        payload = {
            **session,
            "sourceType": "display",
        }
        return self._request("POST", "/screen-share/start", payload)

    def stop_screen_share(self) -> dict[str, Any]:
        return self._request("POST", "/screen-share/stop", {})

    def start_computer_use(
        self,
        *,
        instructions: str,
        model: str | None,
        max_steps: int,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "instructions": instructions,
            "maxSteps": max_steps,
        }
        if model:
            payload["model"] = model
        return self._request("POST", "/computer-use/start", payload)

    def steer_computer_use(self, instructions: str) -> dict[str, Any]:
        return self._request(
            "POST", "/computer-use/steer", {"instructions": instructions}
        )

    def queue_computer_use(self, instructions: str) -> dict[str, Any]:
        return self._request(
            "POST", "/computer-use/queue", {"instructions": instructions}
        )

    def interrupt_computer_use(self) -> dict[str, Any]:
        return self._request("POST", "/computer-use/interrupt", {})

    def start_claude_chrome(
        self,
        *,
        session: dict[str, Any],
        instructions: str,
        target_url: str,
        command: str | None,
        cwd: str | None,
        max_turns: int | None,
        permission_mode: str | None,
        allowed_tools: list[str],
        chrome_profile_directory: str | None,
        chrome_use_default_profile: bool,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            **session,
            "instructions": instructions,
            "targetURL": target_url,
            "allowedTools": allowed_tools,
            "chromeUseDefaultProfile": chrome_use_default_profile,
        }
        if command:
            payload["command"] = command
        if cwd:
            payload["cwd"] = cwd
        if max_turns is not None:
            payload["maxTurns"] = max_turns
        if permission_mode:
            payload["permissionMode"] = permission_mode
        if chrome_profile_directory:
            payload["chromeProfileDirectory"] = chrome_profile_directory
        return self._request("POST", "/claude-chrome/start", payload)

    def steer_claude_chrome(self, instructions: str) -> dict[str, Any]:
        return self._request(
            "POST", "/claude-chrome/steer", {"instructions": instructions}
        )

    def queue_claude_chrome(self, instructions: str) -> dict[str, Any]:
        return self._request(
            "POST", "/claude-chrome/queue", {"instructions": instructions}
        )

    def abort_claude_chrome(self) -> dict[str, Any]:
        return self._request("POST", "/claude-chrome/abort", {})

    def _status_or_none(self) -> dict[str, Any] | None:
        try:
            return self.status()
        except click.ClickException:
            return None

    def _request(
        self, method: str, path: str, json: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        url = f"http://127.0.0.1:{self.port}{path}"
        headers = {"X-Openbase-Companion-Secret": self.secret}
        try:
            response = httpx.request(method, url, headers=headers, json=json, timeout=5)
        except httpx.HTTPError as exc:
            raise click.ClickException(
                f"Unable to reach LiveKit companion: {exc}"
            ) from None

        if response.status_code >= 400:
            raise click.ClickException(response_error(response))

        if not response.content:
            return {}
        return response.json()


def _find_companion_app() -> Path | None:
    candidates = [
        os.environ.get("OPENBASE_LIVEKIT_COMPANION_APP_PATH"),
        str(
            Path(__file__).resolve().parents[3]
            / "desktop"
            / "companion"
            / "livekit-swift-example"
            / ".derivedData"
            / "Build"
            / "Products"
            / "Debug"
            / "OpenbaseScreenShareCompanion.app"
        ),
        str(
            Path(__file__).resolve().parents[3]
            / "desktop"
            / "companion"
            / "livekit-swift-example"
            / ".derivedData"
            / "Build"
            / "Products"
            / "Debug"
            / "LiveKitExample.app"
        ),
        "/Applications/Openbase Coder.app/Contents/Resources/app/companion/livekit-swift-example/.derivedData/Build/Products/Debug/OpenbaseScreenShareCompanion.app",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate).expanduser()
        if path.exists():
            return path
    return None
