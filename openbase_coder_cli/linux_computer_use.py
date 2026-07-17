from __future__ import annotations

import asyncio
import base64
import json
import os
import shlex
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

import httpx

DEFAULT_DISPLAY = ":0"
DEFAULT_STATE = "off"
REMOTE_CONTROL_PREFIX = "openbase.remote_control."
X11_SOCKET_DIR = Path("/tmp/.X11-unix")
DCV_XAUTH_DIR_TEMPLATE = "/run/user/{uid}/dcv"


def detect_display() -> str:
    for name in ("OPENBASE_COMPUTER_USE_DISPLAY", "DISPLAY"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return _user_owned_display() or DEFAULT_DISPLAY


def _user_owned_display() -> str | None:
    # Boot-started services have no DISPLAY, and :0 may belong to another
    # user's X server (on DevSpaces GDM's greeter can hold :0 while the DCV
    # virtual session lands on :1). The user's desktop is the X socket owned
    # by the current uid.
    numbers: list[int] = []
    try:
        sockets = list(X11_SOCKET_DIR.iterdir())
    except OSError:
        return None
    for socket_path in sockets:
        suffix = socket_path.name.removeprefix("X")
        if socket_path.name == suffix or not suffix.isdigit():
            continue
        try:
            if socket_path.stat().st_uid == os.getuid():
                numbers.append(int(suffix))
        except OSError:
            continue
    return f":{min(numbers)}" if numbers else None


def detect_xauthority() -> str | None:
    value = os.environ.get("XAUTHORITY", "").strip()
    if value:
        return value
    # DCV virtual sessions keep their cookie under /run/user/<uid>/dcv/.
    dcv_dir = Path(DCV_XAUTH_DIR_TEMPLATE.format(uid=os.getuid()))
    try:
        candidates = sorted(dcv_dir.glob("*.xauth"))
    except OSError:
        return None
    return str(candidates[0]) if candidates else None


class LinuxComputerUseError(RuntimeError):
    pass


def load_env_value(name: str, env_path: Path | None = None) -> str | None:
    value = os.environ.get(name, "").strip()
    if value:
        return value

    path = env_path or (Path.home() / ".openbase" / ".env")
    if not path.is_file():
        return None

    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").strip()
        key, sep, raw_value = line.partition("=")
        if sep and key.strip() == name:
            return _unquote_env(raw_value.strip()) or None
    return None


def _unquote_env(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return value.replace("\\n", "\n").replace('\\"', '"').replace("\\\\", "\\")


@dataclass
class Screenshot:
    png: bytes
    width: int
    height: int

    @property
    def base64_png(self) -> str:
        return base64.b64encode(self.png).decode("ascii")


@dataclass
class LinuxDesktop:
    display: str = field(default_factory=detect_display)
    xauthority: str | None = field(default_factory=detect_xauthority)
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run

    def readiness(self) -> dict[str, Any]:
        return {
            "display": self.display,
            "xauthority": self.xauthority,
            "x11": bool(self.display),
            "xdotool": bool(shutil.which("xdotool")),
            "screenshot": self._screenshot_tool() is not None,
            "imagemagick": bool(shutil.which("identify") and shutil.which("convert")),
        }

    def require_ready(self) -> None:
        missing: list[str] = []
        if not self.display:
            missing.append("DISPLAY")
        for command in ("xdotool", "identify", "convert"):
            if not shutil.which(command):
                missing.append(command)
        if self._screenshot_tool() is None:
            missing.append("scrot or gnome-screenshot")
        if missing:
            raise LinuxComputerUseError(
                "Linux computer use requires X11 tooling: " + ", ".join(missing)
            )

    def screenshot(self) -> Screenshot:
        self.require_ready()
        with tempfile.TemporaryDirectory(prefix="openbase-computer-use-") as temp_dir:
            png_path = Path(temp_dir) / "screen.png"
            tool = self._screenshot_tool()
            if tool == "scrot":
                self._run(["scrot", str(png_path)])
            elif tool == "gnome-screenshot":
                self._run(["gnome-screenshot", "-f", str(png_path)])
            else:
                raise LinuxComputerUseError("No screenshot command found.")

            dimensions = self._run(
                ["identify", "-format", "%w %h", str(png_path)],
                capture_output=True,
            ).stdout.strip()
            width_text, height_text = dimensions.split(maxsplit=1)
            return Screenshot(
                png=png_path.read_bytes(),
                width=int(width_text),
                height=int(height_text),
            )

    def screenshot_rgba(self) -> tuple[bytes, int, int]:
        screenshot = self.screenshot()
        with tempfile.NamedTemporaryFile(suffix=".png") as handle:
            handle.write(screenshot.png)
            handle.flush()
            raw = self._run(
                ["convert", handle.name, "rgba:-"],
                capture_output=True,
                text=False,
            ).stdout
        return raw, screenshot.width, screenshot.height

    def execute_openai_action(self, action: dict[str, Any]) -> None:
        action_type = str(action.get("type") or "")
        keys = _string_list(action.get("keys"))
        if action_type == "click":
            self.click(
                _number(action.get("x")),
                _number(action.get("y")),
                action.get("button"),
                keys,
            )
        elif action_type == "double_click":
            self.click(
                _number(action.get("x")),
                _number(action.get("y")),
                action.get("button"),
                keys,
                click_count=2,
            )
        elif action_type == "move":
            self.move_to(_number(action.get("x")), _number(action.get("y")), keys)
        elif action_type == "drag":
            self.drag(_drag_path(action.get("path")), keys)
        elif action_type == "scroll":
            self.move_to(_number(action.get("x")), _number(action.get("y")), keys)
            self.scroll(
                _number(action.get("scrollX")), _number(action.get("scrollY")), keys
            )
        elif action_type == "type":
            self.type_text(str(action.get("text") or ""))
        elif action_type == "keypress":
            values = _string_list(action.get("keys")) or _string_list(action.get("key"))
            self.keypress(values)
        elif action_type == "wait":
            time.sleep(2)
        elif action_type == "screenshot":
            return
        else:
            raise LinuxComputerUseError(f"Unsupported computer action: {action_type}")

    def handle_remote_control_message(self, message: dict[str, Any]) -> None:
        action = str(message.get("action") or "")
        if action == "move":
            self.move_relative(
                _number(message.get("deltaX")) * 1.35,
                _number(message.get("deltaY")) * 1.35,
            )
        elif action == "click":
            self.click_current(message.get("button"))
        elif action == "scroll":
            self.scroll(
                _number(message.get("deltaX")), _number(message.get("deltaY")), []
            )
        elif action == "type":
            self.type_text(str(message.get("text") or "")[:1000])
        elif action == "keypress":
            self.keypress(_string_list(message.get("keys"))[:8])
        else:
            raise LinuxComputerUseError(f"Unsupported remote-control action: {action}")

    def click(
        self,
        x: float,
        y: float,
        button: Any = None,
        keys: list[str] | None = None,
        *,
        click_count: int = 1,
    ) -> None:
        self.move_to(x, y, keys or [])
        self._with_keys(
            keys or [],
            [
                "xdotool",
                "click",
                "--repeat",
                str(max(1, click_count)),
                _mouse_button(button),
            ],
        )

    def click_current(self, button: Any = None) -> None:
        self._run(["xdotool", "click", _mouse_button(button)])

    def move_to(self, x: float, y: float, keys: list[str] | None = None) -> None:
        self._with_keys(
            keys or [], ["xdotool", "mousemove", str(round(x)), str(round(y))]
        )

    def move_relative(self, dx: float, dy: float) -> None:
        self._run(
            ["xdotool", "mousemove_relative", "--", str(round(dx)), str(round(dy))]
        )

    def drag(
        self, points: list[tuple[float, float]], keys: list[str] | None = None
    ) -> None:
        if not points:
            return
        self.move_to(points[0][0], points[0][1], keys or [])
        self._run(["xdotool", "mousedown", "1"])
        for x, y in points[1:]:
            self._run(["xdotool", "mousemove", str(round(x)), str(round(y))])
        self._run(["xdotool", "mouseup", "1"])

    def scroll(self, dx: float, dy: float, keys: list[str] | None = None) -> None:
        clicks = max(1, min(10, int(abs(dy) / 40) or 1))
        button = "4" if dy < 0 else "5"
        if abs(dx) > abs(dy):
            button = "6" if dx < 0 else "7"
        self._with_keys(
            keys or [], ["xdotool", "click", "--repeat", str(clicks), button]
        )

    def type_text(self, text: str) -> None:
        if text:
            self._run(["xdotool", "type", "--clearmodifiers", "--delay", "0", text])

    def keypress(self, keys: list[str]) -> None:
        combo = "+".join(_normalize_key(key) for key in keys if key)
        if combo:
            self._run(["xdotool", "key", "--clearmodifiers", combo])

    def _with_keys(self, keys: list[str], command: list[str]) -> None:
        modifiers = [_normalize_key(key) for key in keys if _is_modifier(key)]
        for key in modifiers:
            self._run(["xdotool", "keydown", key])
        try:
            self._run(command)
        finally:
            for key in reversed(modifiers):
                self._run(["xdotool", "keyup", key])

    def _screenshot_tool(self) -> str | None:
        if shutil.which("scrot"):
            return "scrot"
        if shutil.which("gnome-screenshot"):
            return "gnome-screenshot"
        return None

    def _run(
        self,
        command: list[str],
        *,
        capture_output: bool = False,
        text: bool = True,
    ) -> subprocess.CompletedProcess:
        env = {**os.environ, "DISPLAY": self.display}
        if self.xauthority:
            env["XAUTHORITY"] = self.xauthority
        result = self.runner(
            command,
            env=env,
            check=False,
            capture_output=capture_output,
            text=text,
        )
        if result.returncode != 0:
            detail = ""
            stderr = getattr(result, "stderr", None)
            if isinstance(stderr, bytes):
                detail = stderr.decode(errors="replace").strip()
            elif stderr:
                detail = str(stderr).strip()
            raise LinuxComputerUseError(
                f"Command failed: {shlex.join(command)}"
                + (f": {detail}" if detail else "")
            )
        return result


class OpenAIComputerUseRunner:
    def __init__(
        self,
        desktop: LinuxDesktop,
        *,
        model: str = "gpt-5.5",
        max_steps: int = 30,
        api_key: str | None = None,
    ) -> None:
        self.desktop = desktop
        self.model = model
        self.max_steps = max(1, max_steps)
        self.api_key = api_key or load_env_value("OPENAI_API_KEY")
        self._latest_steering: str | None = None
        self._queued: list[str] = []
        self._cancelled = threading.Event()
        if not self.api_key:
            raise LinuxComputerUseError(
                "OPENAI_API_KEY was not found in the environment or ~/.openbase/.env."
            )

    def steer(self, instructions: str) -> None:
        self._latest_steering = instructions

    def queue(self, instructions: str) -> None:
        self._queued.append(instructions)

    def interrupt(self) -> None:
        self._cancelled.set()

    def run(self, instructions: str) -> None:
        active: str | None = instructions
        while active:
            if self._cancelled.is_set():
                raise LinuxComputerUseError("Computer use interrupted.")
            response = self._create_initial_response(active)
            active = None
            completed = False
            for _step in range(self.max_steps):
                if self._cancelled.is_set():
                    raise LinuxComputerUseError("Computer use interrupted.")
                call = _computer_call(response)
                if call is None:
                    completed = True
                    if self._queued:
                        active = self._queued.pop(0)
                    break
                for action in call["actions"]:
                    self.desktop.execute_openai_action(action)
                screenshot = self.desktop.screenshot()
                steering = self._latest_steering
                self._latest_steering = None
                response = self._send_screenshot(
                    previous_response_id=response["id"],
                    call_id=call["call_id"],
                    screenshot=screenshot,
                    steering=steering,
                )
            if not completed:
                return

    def _create_initial_response(self, instructions: str) -> dict[str, Any]:
        return self._create_response(
            {
                "model": self.model,
                "tools": [{"type": "computer"}],
                "input": (
                    f"{instructions}\n\nUse the computer tool for UI interaction "
                    "on the visible Linux X11 desktop. Do not use browser automation "
                    "or shell commands."
                ),
            }
        )

    def _send_screenshot(
        self,
        *,
        previous_response_id: str,
        call_id: str,
        screenshot: Screenshot,
        steering: str | None,
    ) -> dict[str, Any]:
        input_items: list[dict[str, Any]] = [
            {
                "type": "computer_call_output",
                "call_id": call_id,
                "output": {
                    "type": "computer_screenshot",
                    "image_url": f"data:image/png;base64,{screenshot.base64_png}",
                    "detail": "original",
                },
            }
        ]
        if steering and steering.strip():
            input_items.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "Steering update for the active computer-use run:\n"
                            + steering,
                        }
                    ],
                }
            )
        return self._create_response(
            {
                "model": self.model,
                "tools": [{"type": "computer"}],
                "previous_response_id": previous_response_id,
                "input": input_items,
            }
        )

    def _create_response(self, body: dict[str, Any]) -> dict[str, Any]:
        response = httpx.post(
            "https://api.openai.com/v1/responses",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=60,
        )
        if response.status_code >= 400:
            raise LinuxComputerUseError(
                f"OpenAI API error {response.status_code}: {response.text}"
            )
        payload = response.json()
        if not isinstance(payload, dict) or not payload.get("id"):
            raise LinuxComputerUseError(
                "OpenAI returned an invalid computer-use response."
            )
        return payload


class LinuxCompanion:
    def __init__(self, desktop: LinuxDesktop | None = None) -> None:
        self.desktop = desktop or LinuxDesktop()
        self.state = DEFAULT_STATE
        self.error: str | None = None
        self._room: Any = None
        self._screen_task: asyncio.Task | None = None
        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(target=self._run_loop, daemon=True)
        self._loop_thread.start()
        self._runner: OpenAIComputerUseRunner | None = None
        self._runner_thread: threading.Thread | None = None
        self._remote_control_enabled = False
        self._authorized_identity: str | None = None

    def status(self) -> dict[str, Any]:
        return {
            "ok": self.error is None,
            "state": self.state,
            "error": self.error,
            "linux": self.desktop.readiness(),
        }

    def start_screen_share(self, payload: dict[str, Any]) -> dict[str, Any]:
        room_url = str(payload.get("roomUrl") or "")
        token = str(payload.get("token") or payload.get("companionToken") or "")
        if not room_url or not token:
            raise LinuxComputerUseError("Missing LiveKit room URL or companion token.")
        self.desktop.require_ready()
        self.state = "starting"
        self.error = None
        self._await(self._start_livekit(room_url, token))
        self.state = "sharing"
        return self.status()

    def stop_screen_share(self) -> dict[str, Any]:
        self.state = "stopping"
        self.interrupt_computer_use()
        self._await(self._stop_livekit())
        self._remote_control_enabled = False
        self._authorized_identity = None
        self.state = "off"
        return self.status()

    def start_computer_use(self, payload: dict[str, Any]) -> dict[str, Any]:
        instructions = str(payload.get("instructions") or "").strip()
        if not instructions:
            raise LinuxComputerUseError("Computer-use instructions are required.")
        if self._runner_thread and self._runner_thread.is_alive():
            raise LinuxComputerUseError("Computer use is already running.")
        if self.state not in {"sharing", "controlling"}:
            raise LinuxComputerUseError(
                "Screen sharing must be active before computer use starts."
            )

        self.state = "starting-control"
        self._runner = OpenAIComputerUseRunner(
            self.desktop,
            model=str(payload.get("model") or "gpt-5.5"),
            max_steps=int(payload.get("maxSteps") or 30),
        )
        self._runner_thread = threading.Thread(
            target=self._run_computer_use,
            args=(self._runner, instructions),
            daemon=True,
        )
        self._runner_thread.start()
        self.state = "controlling"
        return self.status()

    def steer_computer_use(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self._runner:
            raise LinuxComputerUseError(
                "No active computer-use run is available to steer."
            )
        self._runner.steer(str(payload.get("instructions") or ""))
        return self.status()

    def queue_computer_use(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self._runner:
            raise LinuxComputerUseError(
                "No active computer-use run is available to queue."
            )
        self._runner.queue(str(payload.get("instructions") or ""))
        return self.status()

    def interrupt_computer_use(self) -> dict[str, Any]:
        if self._runner:
            self._runner.interrupt()
        if self.state in {"starting-control", "controlling"}:
            self.state = "sharing" if self._room else "off"
        return self.status()

    async def _start_livekit(self, room_url: str, token: str) -> None:
        from livekit import rtc

        if self._room:
            await self._stop_livekit()

        room = rtc.Room()

        @room.on("data_received")
        def on_data_received(packet: Any) -> None:
            self._handle_data_packet(packet)

        await room.connect(room_url, token)
        raw, width, height = await asyncio.to_thread(self.desktop.screenshot_rgba)
        source = rtc.VideoSource(width, height, is_screencast=True)
        track = rtc.LocalVideoTrack.create_video_track("openbase-screen-share", source)
        options = rtc.TrackPublishOptions()
        options.source = rtc.TrackSource.Value("SOURCE_SCREENSHARE")
        await room.local_participant.publish_track(track, options)
        source.capture_frame(
            rtc.VideoFrame(width, height, rtc.VideoBufferType.Value("RGBA"), raw)
        )
        self._room = room
        self._screen_task = asyncio.create_task(self._capture_loop(source))

    async def _stop_livekit(self) -> None:
        if self._screen_task:
            self._screen_task.cancel()
            try:
                await self._screen_task
            except asyncio.CancelledError:
                pass
            self._screen_task = None
        if self._room:
            await self._room.disconnect()
            self._room = None

    async def _capture_loop(self, source: Any) -> None:
        from livekit import rtc

        while True:
            raw, width, height = await asyncio.to_thread(self.desktop.screenshot_rgba)
            frame = rtc.VideoFrame(
                width, height, rtc.VideoBufferType.Value("RGBA"), raw
            )
            source.capture_frame(frame)
            await asyncio.sleep(0.5)

    def _handle_data_packet(self, packet: Any) -> None:
        try:
            message = json.loads(packet.data.decode("utf-8"))
        except Exception:
            return
        if not isinstance(message, dict):
            return
        message_type = str(message.get("type") or "")
        if not message_type.startswith(REMOTE_CONTROL_PREFIX):
            return
        sender = getattr(getattr(packet, "participant", None), "identity", None)
        sender_identity = getattr(sender, "string_value", None) or str(sender or "")
        try:
            if message_type == "openbase.remote_control.set_enabled":
                self._set_remote_control_enabled(
                    message.get("enabled") is True, sender_identity
                )
            elif message_type == "openbase.remote_control.input":
                self._handle_remote_control_input(message, sender_identity)
        except Exception as exc:
            self.error = str(exc)

    def _set_remote_control_enabled(self, enabled: bool, sender_identity: str) -> None:
        if not enabled:
            if self._authorized_identity in {None, sender_identity}:
                self._remote_control_enabled = False
                self._authorized_identity = None
            return
        if self.state not in {"sharing", "controlling"}:
            self._remote_control_enabled = False
            self._authorized_identity = None
            return
        if sender_identity:
            self._authorized_identity = sender_identity
            self._remote_control_enabled = True

    def _handle_remote_control_input(
        self, message: dict[str, Any], sender_identity: str
    ) -> None:
        if (
            not self._remote_control_enabled
            or sender_identity != self._authorized_identity
        ):
            return
        if self.state not in {"sharing", "controlling"}:
            self._remote_control_enabled = False
            self._authorized_identity = None
            return
        self.desktop.handle_remote_control_message(message)

    def _run_computer_use(
        self, runner: OpenAIComputerUseRunner, instructions: str
    ) -> None:
        try:
            runner.run(instructions)
        except Exception as exc:
            self.error = str(exc)
            self.state = "error"
            return
        finally:
            if self._runner is runner:
                self._runner = None
        if self.state == "controlling":
            self._await(self._stop_livekit())
            self.state = "off"

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _await(self, coroutine: Any) -> Any:
        future = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
        return future.result(timeout=30)


def serve_linux_companion(
    *,
    host: str = "127.0.0.1",
    port: int = 39281,
    secret: str = "openbase-livekit-companion-local",
    companion: LinuxCompanion | None = None,
) -> None:
    active_companion = companion or LinuxCompanion()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self._route()

        def do_POST(self) -> None:  # noqa: N802
            self._route()

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _route(self) -> None:
            if self.headers.get("X-Openbase-Companion-Secret") != secret:
                self._send(
                    401,
                    {
                        "ok": False,
                        "state": active_companion.state,
                        "error": "Unauthorized",
                    },
                )
                return
            try:
                payload = self._read_json()
                if self.command == "GET" and self.path == "/status":
                    self._send(200, active_companion.status())
                elif self.command == "POST" and self.path == "/screen-share/start":
                    self._send(200, active_companion.start_screen_share(payload))
                elif self.command == "POST" and self.path == "/screen-share/stop":
                    self._send(200, active_companion.stop_screen_share())
                elif self.command == "POST" and self.path == "/computer-use/start":
                    self._send(200, active_companion.start_computer_use(payload))
                elif self.command == "POST" and self.path == "/computer-use/steer":
                    self._send(200, active_companion.steer_computer_use(payload))
                elif self.command == "POST" and self.path == "/computer-use/queue":
                    self._send(200, active_companion.queue_computer_use(payload))
                elif self.command == "POST" and self.path == "/computer-use/interrupt":
                    self._send(200, active_companion.interrupt_computer_use())
                else:
                    self._send(
                        404,
                        {
                            "ok": False,
                            "state": active_companion.state,
                            "error": "Unknown route",
                        },
                    )
            except Exception as exc:
                active_companion.error = str(exc)
                self._send(
                    500,
                    {"ok": False, "state": active_companion.state, "error": str(exc)},
                )

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length") or "0")
            if length <= 0:
                return {}
            data = self.rfile.read(length)
            parsed = json.loads(data.decode("utf-8"))
            return parsed if isinstance(parsed, dict) else {}

        def _send(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer((host, port), Handler)
    server.serve_forever()


def _computer_call(response: dict[str, Any]) -> dict[str, Any] | None:
    for item in response.get("output") or []:
        if not isinstance(item, dict) or item.get("type") != "computer_call":
            continue
        call_id = item.get("call_id") or item.get("callId")
        actions = item.get("actions")
        if call_id and isinstance(actions, list):
            return {
                "call_id": call_id,
                "actions": [a for a in actions if isinstance(a, dict)],
            }
    return None


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


def _drag_path(value: Any) -> list[tuple[float, float]]:
    if not isinstance(value, list):
        return []
    points: list[tuple[float, float]] = []
    for item in value:
        if isinstance(item, dict):
            points.append((_number(item.get("x")), _number(item.get("y"))))
        elif isinstance(item, list) and len(item) >= 2:
            points.append((_number(item[0]), _number(item[1])))
    return points


def _mouse_button(value: Any) -> str:
    normalized = str(value or "").lower()
    if normalized == "right":
        return "3"
    if normalized in {"middle", "center"}:
        return "2"
    return "1"


def _normalize_key(key: str) -> str:
    normalized = key.upper().replace("ARROW", "")
    mapping = {
        "CTRL": "ctrl",
        "CONTROL": "ctrl",
        "SHIFT": "shift",
        "ALT": "alt",
        "OPTION": "alt",
        "META": "super",
        "CMD": "ctrl",
        "COMMAND": "ctrl",
        "SUPER": "super",
        "ENTER": "Return",
        "RETURN": "Return",
        "ESC": "Escape",
        "ESCAPE": "Escape",
        "BACKSPACE": "BackSpace",
        "DELETE": "BackSpace",
        "LEFT": "Left",
        "RIGHT": "Right",
        "UP": "Up",
        "DOWN": "Down",
        "PAGEUP": "Prior",
        "PAGEDOWN": "Next",
        "SPACE": "space",
    }
    return mapping.get(
        normalized, normalized.lower() if len(normalized) == 1 else normalized
    )


def _is_modifier(key: str) -> bool:
    return key.upper() in {
        "CTRL",
        "CONTROL",
        "SHIFT",
        "ALT",
        "OPTION",
        "META",
        "CMD",
        "COMMAND",
        "SUPER",
    }
