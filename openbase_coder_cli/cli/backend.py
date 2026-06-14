from __future__ import annotations

from pathlib import Path

import click

from openbase_coder_cli.backend_config import (
    CODING_BACKEND_ENV_KEY,
    DEFAULT_CODING_BACKEND,
    LEGACY_CODEX_BACKEND_ENV_KEY,
    SUPPORTED_BACKENDS,
    normalize_backend,
)
from openbase_coder_cli.cli.setup import (
    _active_env_key,
    _format_env_value,
    _upsert_env_file_values,
)
from openbase_coder_cli.paths import DEFAULT_ENV_FILE_PATH

BACKEND_ENV_KEY = CODING_BACKEND_ENV_KEY


@click.group()
def backend() -> None:
    """View or switch the selected coding backend."""


@backend.command("list")
def list_backends() -> None:
    """List supported coding backends."""
    for backend_name in SUPPORTED_BACKENDS:
        marker = " (default)" if backend_name == DEFAULT_CODING_BACKEND else ""
        click.echo(f"{backend_name}{marker}")


@backend.command()
@click.option(
    "--env-file",
    type=click.Path(path_type=Path),
    default=DEFAULT_ENV_FILE_PATH,
    show_default=True,
    help="Openbase .env file to inspect.",
)
def status(env_file: Path) -> None:
    """Show the currently selected coding backend."""
    value = read_backend(env_file)
    exists = "exists" if env_file.is_file() else "missing"
    click.echo(f"Backend: {value}")
    click.echo(f"Env file: {env_file} ({exists})")


@backend.command("use")
@click.argument("backend_name")
@click.option(
    "--env-file",
    type=click.Path(path_type=Path),
    default=DEFAULT_ENV_FILE_PATH,
    show_default=True,
    help="Openbase .env file to update.",
)
def use_backend(backend_name: str, env_file: Path) -> None:
    """Persist the selected coding backend."""
    try:
        normalized = normalize_backend(backend_name)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    write_backend(env_file, normalized)
    click.echo(f"Backend set to {normalized} in {env_file}.")
    if normalized == "codex":
        click.echo(
            "Restart or recreate the dispatcher/MCP host for Super Agents to pick up the change."
        )
    else:
        click.echo(
            "Restart or recreate the dispatcher/MCP host for the Claude backend to pick up the change; keep Openbase services running."
        )


def read_backend(env_file: Path) -> str:
    if not env_file.is_file():
        return DEFAULT_CODING_BACKEND
    values = read_env_values(env_file)
    raw_value = values.get(BACKEND_ENV_KEY)
    if raw_value is None:
        raw_value = values.get(LEGACY_CODEX_BACKEND_ENV_KEY)
    try:
        return normalize_backend(raw_value)
    except ValueError:
        return f"unsupported:{raw_value}"


def write_backend(env_file: Path, backend_name: str) -> None:
    normalized = normalize_backend(backend_name)
    env_file.parent.mkdir(parents=True, exist_ok=True)
    if env_file.is_file():
        _upsert_env_file_values(env_file, {BACKEND_ENV_KEY: normalized})
        return
    env_file.write_text(
        f"{BACKEND_ENV_KEY}={_format_env_value(normalized)}\n", encoding="utf-8"
    )


def read_env_values(env_file: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in env_file.read_text(encoding="utf-8").splitlines():
        key = _active_env_key(line)
        if key is None:
            continue
        _raw_key, raw_value = line.split("=", 1)
        values[key] = _unquote_env_value(raw_value.strip())
    return values


def _unquote_env_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value
