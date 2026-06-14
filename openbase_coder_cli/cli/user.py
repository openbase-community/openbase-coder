from __future__ import annotations

from pathlib import Path

import click

from openbase_coder_cli.cli.local_server import local_server_request
from openbase_coder_cli.dispatcher_config import (
    REASONING_EFFORTS,
    dispatcher_reasoning_effort,
    set_dispatcher_reasoning_effort,
    set_super_agents_model,
    set_super_agents_reasoning_effort,
    super_agents_model,
    super_agents_reasoning_effort,
)
from openbase_coder_cli.livekit_announcer import (
    MAX_ANNOUNCER_TEXT_LENGTH,
    SUPPORTED_AUDIO_EXTENSIONS,
)
from openbase_coder_cli.paths import OPENBASE_SOUNDS_DIR


@click.group()
def user() -> None:
    """Commands for the active Openbase Coder user session."""


@user.command()
@click.argument("words", nargs=-1, metavar="AGENT_NAME MESSAGE")
@click.option(
    "--room",
    "room_name",
    default="",
    help="Explicit LiveKit room name. Defaults to the latest active voice room.",
)
def say(
    words: tuple[str, ...],
    room_name: str,
) -> None:
    """Speak an announcer message in the active voice session."""
    if len(words) < 2:
        raise click.ClickException(
            "Agent name is required. Usage: openbase-coder user say AGENT_NAME MESSAGE"
        )
    agent_name, *message = words
    normalized_agent_name = " ".join(agent_name.split())
    if not normalized_agent_name:
        raise click.ClickException("Agent name is required and cannot be blank.")
    text = " ".join(message).strip()
    if not text:
        raise click.ClickException("Message text is required.")
    if len(text) > MAX_ANNOUNCER_TEXT_LENGTH:
        raise click.ClickException(
            f"Message text must be {MAX_ANNOUNCER_TEXT_LENGTH} characters or fewer."
        )

    payload: dict[str, str] = {"agent_name": normalized_agent_name, "text": text}
    if room_name.strip():
        payload["room_name"] = room_name.strip()

    response = local_server_request("POST", "/api/user/say/", json=payload)

    data = response.json()
    target_room = data.get("room_name") or "active room"
    click.echo(f"Announcer message sent to {target_room}.")


@user.command()
@click.argument("sound_or_path")
@click.option(
    "--room",
    "room_name",
    default="",
    help="Explicit LiveKit room name. Defaults to the latest active voice room.",
)
def play(sound_or_path: str, room_name: str) -> None:
    """Play a local audio file in the active voice session."""
    try:
        audio_path = resolve_sound_path(sound_or_path)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from None

    payload: dict[str, str] = {"audio_path": str(audio_path)}
    if room_name.strip():
        payload["room_name"] = room_name.strip()

    response = local_server_request("POST", "/api/user/play/", json=payload)

    data = response.json()
    target_room = data.get("room_name") or "active room"
    click.echo(f"Audio playback sent to {target_room}.")


def resolve_sound_path(sound_or_path: str) -> Path:
    value = sound_or_path.strip()
    if not value:
        raise ValueError("Sound name or path is required.")

    candidate = Path(value).expanduser()
    if candidate.is_file():
        return _validate_audio_file(candidate.resolve())

    if candidate.is_absolute() or _looks_like_path(value):
        raise ValueError(f"Audio file not found: {value}")

    if not _is_safe_sound_name(value):
        raise ValueError(
            "Named sounds must be simple file names without path separators."
        )

    sounds_dir = OPENBASE_SOUNDS_DIR.expanduser()
    name_path = Path(value)
    candidates = (
        [sounds_dir / name_path.name]
        if name_path.suffix
        else [
            sounds_dir / f"{name_path.name}{extension}"
            for extension in SUPPORTED_AUDIO_EXTENSIONS
        ]
    )
    for sound_path in candidates:
        if sound_path.is_file():
            return _validate_audio_file(sound_path.resolve())

    tried = ", ".join(path.name for path in candidates)
    raise ValueError(f"Named sound not found in {sounds_dir}: {value}. Tried: {tried}")


def _validate_audio_file(path: Path) -> Path:
    if path.suffix.lower() not in SUPPORTED_AUDIO_EXTENSIONS:
        supported = ", ".join(SUPPORTED_AUDIO_EXTENSIONS)
        raise ValueError(
            f"Unsupported audio file extension {path.suffix!r}. Supported: {supported}."
        )
    return path


def _looks_like_path(value: str) -> bool:
    return "/" in value or "\\" in value or value.startswith(".")


def _is_safe_sound_name(value: str) -> bool:
    path = Path(value)
    return path.name == value and value not in {".", ".."} and ".." not in path.parts


@user.command("voice-route")
def voice_route() -> None:
    """Show the active LiveKit voice route."""
    response = local_server_request("GET", "/api/livekit-voice-route/")
    data = response.json()
    click.echo(f"Active route: {data.get('active_route') or 'dispatcher'}")
    dispatcher_thread_id = data.get("dispatcher_thread_id")
    if dispatcher_thread_id:
        click.echo(f"Dispatcher thread: {dispatcher_thread_id}")
    active_target_thread_id = data.get("active_target_thread_id")
    if active_target_thread_id:
        click.echo(f"Active target thread: {active_target_thread_id}")
    if not data.get("instruction_override_supported"):
        click.echo(f"Target transfer blocked: {data.get('blocked_reason')}")


@user.command("exit-to-dispatch")
@click.option(
    "--room",
    "room_name",
    default="",
    help="Explicit LiveKit room name. Defaults to the latest active voice room.",
)
def exit_to_dispatch(room_name: str) -> None:
    """Route the active voice session back to the dispatcher."""
    payload: dict[str, str] = {}
    if room_name.strip():
        payload["room_name"] = room_name.strip()
    response = local_server_request(
        "POST", "/api/livekit-voice-route/exit/", json=payload
    )
    data = response.json()
    target_room = data.get("room_name") or "active room"
    click.echo(f"Voice route returned to dispatcher in {target_room}.")


@user.command("dispatcher-reasoning")
@click.argument("level", required=False)
def dispatcher_reasoning(level: str | None) -> None:
    """Show or set the dispatcher default reasoning effort."""
    if level is None:
        current = dispatcher_reasoning_effort() or "app-server default"
        click.echo(f"Dispatcher reasoning effort: {current}")
        return

    normalized = level.strip().lower()
    if normalized not in REASONING_EFFORTS:
        allowed = ", ".join(sorted(REASONING_EFFORTS))
        raise click.ClickException(f"Reasoning effort must be one of: {allowed}.")

    set_dispatcher_reasoning_effort(normalized)
    click.echo(f"Dispatcher reasoning effort set to {normalized}.")


@user.command("super-agents-reasoning")
@click.argument("level", required=False)
def super_agents_reasoning(level: str | None) -> None:
    """Show or set the Super Agents default reasoning effort."""
    if level is None:
        current = super_agents_reasoning_effort() or "high"
        click.echo(f"Super Agents reasoning effort: {current}")
        return

    normalized = level.strip().lower()
    if normalized not in REASONING_EFFORTS:
        allowed = ", ".join(sorted(REASONING_EFFORTS))
        raise click.ClickException(f"Reasoning effort must be one of: {allowed}.")

    set_super_agents_reasoning_effort(normalized)
    click.echo(f"Super Agents reasoning effort set to {normalized}.")


@user.command("super-agents-model")
@click.argument("model", required=False)
def super_agents_model_command(model: str | None) -> None:
    """Show or set the Super Agents default model."""
    if model is None:
        current = super_agents_model() or "backend default"
        click.echo(f"Super Agents model: {current}")
        return

    try:
        set_super_agents_model(model)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Super Agents model set to {' '.join(model.split())}.")


@user.command("transfer-to-thread")
@click.argument("thread_id")
@click.option(
    "--room",
    "room_name",
    default="",
    help="Explicit LiveKit room name. Defaults to the latest active voice room.",
)
@click.option("--label", default="", help="Optional display label for the target.")
@click.option(
    "--agent-name",
    default="",
    help="Optional agent name used to choose the target voice.",
)
def transfer_to_thread(
    thread_id: str, room_name: str, label: str, agent_name: str
) -> None:
    """Route the active voice session to a Codex thread if instruction-safe."""
    payload: dict[str, str] = {"thread_id": thread_id}
    if room_name.strip():
        payload["room_name"] = room_name.strip()
    if label.strip():
        payload["label"] = label.strip()
    if agent_name.strip():
        payload["agent_name"] = agent_name.strip()
    response = local_server_request(
        "POST", "/api/livekit-voice-route/transfer/", json=payload
    )
    data = response.json()
    target_room = data.get("room_name") or "active room"
    click.echo(f"Voice route transferred to {thread_id} in {target_room}.")


@user.command("transfer-to-agent")
@click.argument("agent_name")
@click.option(
    "--room",
    "room_name",
    default="",
    help="Explicit LiveKit room name. Defaults to the latest active voice room.",
)
def transfer_to_agent(agent_name: str, room_name: str) -> None:
    """Route the active voice session to a named Super Agent."""
    payload: dict[str, str] = {"agent_name": agent_name}
    if room_name.strip():
        payload["room_name"] = room_name.strip()
    response = local_server_request(
        "POST", "/api/livekit-voice-route/transfer/", json=payload
    )
    data = response.json()
    target_room = data.get("room_name") or "active room"
    active_target = data.get("state", {}).get("active_target_thread_id") or agent_name
    click.echo(f"Voice route transferred to {active_target} in {target_room}.")


user.add_command(dispatcher_reasoning, "operator-reasoning")
user.add_command(super_agents_reasoning, "super-agent-reasoning")
user.add_command(super_agents_model_command, "super-agent-model")
