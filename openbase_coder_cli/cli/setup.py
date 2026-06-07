from __future__ import annotations

import json
import platform
import secrets
import shlex
import subprocess
from pathlib import Path
from shutil import which

import click
from multi.api import sync_workspace

from openbase_coder_cli.cli.node import run_workspace_package_command
from openbase_coder_cli.paths import (
    CODEX_AGENTS_MD_PATH,
    CODEX_DIRECT_LIVEKIT_INSTRUCTIONS_PATH,
    CODEX_DISPATCHER_CONFIG_PATH,
    CODEX_DISPATCHER_INSTRUCTIONS_PATH,
    CODEX_HOME_DIR,
    CODEX_SUPER_AGENT_INSTRUCTIONS_PATH,
    DEFAULT_ENV_FILE_PATH,
    DEFAULT_WORKSPACE_DIR,
    OPENBASE_BASE_DIR,
)
from openbase_coder_cli.services.installation import InstallationConfig
from openbase_coder_cli.services.launchd import install_all_services

WORKSPACE_REPO = "https://github.com/openbase-community/openbase-coder-workspace.git"
WORKSPACE_INSTALL_SET = "default"
CODEX_HOME_DEFAULT_SOURCE_DIR = "instructions"
CODEX_HOME_SKILLS_SOURCE_DIR = "skills"
CODEX_HOME_DEFAULT_FILES = (
    ("AGENTS.md", CODEX_AGENTS_MD_PATH),
    ("VOICE_INSTRUCTIONS.md", CODEX_DIRECT_LIVEKIT_INSTRUCTIONS_PATH),
    ("DISPATCHER_INSTRUCTIONS.md", CODEX_DISPATCHER_INSTRUCTIONS_PATH),
    ("SUPER_AGENT_INSTRUCTIONS.md", CODEX_SUPER_AGENT_INSTRUCTIONS_PATH),
)
SUPER_AGENTS_MCP_TABLE = "mcp_servers.super-agents"
SUPER_AGENTS_MCP_COMMAND = "super-agents-mcp"
CODEX_HOME_PERMISSION_VALUES = (
    ("sandbox_mode", json.dumps("danger-full-access")),
    (
        "approval_policy",
        "{ granular = { sandbox_approval = false, rules = false, "
        "mcp_elicitations = false, request_permissions = false, "
        "skill_approval = false } }",
    ),
)
CODEX_HOME_DEFAULT_DISPATCHER_CONFIG = {
    "dispatcher_reasoning_effort": "low",
    "super_agents_reasoning_effort": "high",
}


@click.command()
@click.option(
    "--workspace-dir",
    type=click.Path(),
    default=str(DEFAULT_WORKSPACE_DIR),
    show_default=True,
    help="Override clone location for the workspace.",
)
@click.option(
    "--env-file",
    type=click.Path(),
    default=str(DEFAULT_ENV_FILE_PATH),
    show_default=True,
    help="Override .env file location.",
)
@click.option(
    "--assembly-ai-api-key",
    envvar="ASSEMBLY_AI_API_KEY",
    default="",
    help="AssemblyAI API key for speech-to-text.",
)
@click.option(
    "--cartesia-api-key",
    envvar="CARTESIA_API_KEY",
    default="",
    help="Cartesia API key for text-to-speech.",
)
@click.option(
    "--skip-clone",
    is_flag=True,
    help="Skip git clone step.",
)
@click.option(
    "--skip-services",
    is_flag=True,
    help="Skip launchd service installation.",
)
def setup(
    workspace_dir: str,
    env_file: str,
    assembly_ai_api_key: str,
    cartesia_api_key: str,
    skip_clone: bool,
    skip_services: bool,
) -> None:
    """Full install flow for Openbase Coder."""
    if platform.system() != "Darwin":
        raise click.ClickException("Setup is only supported on macOS.")

    OPENBASE_BASE_DIR.mkdir(parents=True, exist_ok=True)

    # --- Clone workspace ---
    if not skip_clone:
        _clone_workspace(workspace_dir)

    # --- Write installation.json ---
    config = InstallationConfig(
        workspace_path=workspace_dir,
        env_file=env_file,
    )
    config.save()
    click.echo("Wrote installation.json")

    # --- Generate .env ---
    _ensure_env_file(
        env_file,
        assembly_ai_api_key=assembly_ai_api_key,
        cartesia_api_key=cartesia_api_key,
    )

    # --- Symlink Codex auth into the service CODEX_HOME ---
    _symlink_codex_auth()
    _ensure_codex_home_default_files(workspace_dir)
    _ensure_codex_home_dispatcher_config()
    _symlink_codex_home_skills(workspace_dir)

    # --- Initialize CLI workspace ---
    _init_cli_workspace(workspace_dir)

    # --- Configure the service CODEX_HOME ---
    _ensure_codex_home_config(workspace_dir)

    # --- Install/update user-facing CLI shim ---
    _install_cli_shim(workspace_dir)

    # --- Build console ---
    _build_console(workspace_dir)

    # --- Install services ---
    if not skip_services:
        click.echo()
        click.echo("Installing launchd services...")
        install_all_services(config)
    else:
        click.echo("Skipped service installation (--skip-services).")

    click.echo()
    click.echo("Setup complete.")
    click.echo()
    click.echo(
        "To enable remote authentication, run 'openbase-coder login' "
        "and ensure OPENBASE_CODER_CLI_WEB_BACKEND_URL is set in your .env."
    )


def _clone_workspace(workspace_dir: str) -> None:
    ws = Path(workspace_dir)
    if ws.exists() and (ws / ".git").is_dir():
        click.echo(f"Workspace already exists at {ws}, pulling latest...")
        _update_existing_workspace(ws)
        _remove_managed_repo_symlinks(ws)
        _multi_sync(ws)
        _update_install_set_repos(ws)
        return

    click.echo(f"Cloning workspace to {ws}...")
    subprocess.run(
        ["git", "clone", WORKSPACE_REPO, str(ws)],
        check=True,
    )
    _multi_sync(ws)
    _update_install_set_repos(ws)


def _update_existing_workspace(ws: Path) -> None:
    if ws.resolve() == DEFAULT_WORKSPACE_DIR.resolve():
        dirty = subprocess.run(
            ["git", "-C", str(ws), "status", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if dirty:
            click.echo(
                "Resetting managed install workspace before update; "
                "local generated changes are discarded."
            )
            subprocess.run(["git", "-C", str(ws), "fetch", "origin", "main"], check=True)
            subprocess.run(
                ["git", "-C", str(ws), "reset", "--hard", "origin/main"],
                check=True,
            )
            return

    subprocess.run(["git", "-C", str(ws), "pull", "--ff-only"], check=True)


def _remove_managed_repo_symlinks(ws: Path) -> None:
    if ws.resolve() != DEFAULT_WORKSPACE_DIR.resolve():
        return

    for repo_name in _install_set_repo_names(ws):
        repo_path = ws / repo_name
        if repo_path.is_symlink():
            click.echo(f"Removing symlinked install repo at {repo_path}")
            repo_path.unlink()


def _update_install_set_repos(ws: Path) -> None:
    for repo_name in _install_set_repo_names(ws):
        repo_path = ws / repo_name
        if not (repo_path / ".git").exists():
            continue

        if ws.resolve() == DEFAULT_WORKSPACE_DIR.resolve():
            click.echo(f"Updating managed install repo {repo_name}...")
            subprocess.run(
                ["git", "-C", str(repo_path), "fetch", "origin", "main"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(repo_path), "reset", "--hard", "origin/main"],
                check=True,
            )
        else:
            subprocess.run(["git", "-C", str(repo_path), "pull", "--ff-only"], check=True)


def _install_set_repo_names(ws: Path) -> list[str]:
    multi_json_path = ws / "multi.json"
    if not multi_json_path.is_file():
        return []

    try:
        multi_json = json.loads(multi_json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    names = []
    for repo in multi_json.get("repos", []):
        install_sets = repo.get("installSets")
        if install_sets is not None and WORKSPACE_INSTALL_SET not in install_sets:
            continue
        if name := repo.get("name"):
            names.append(name)
    return names


def _multi_sync(ws_path: Path) -> None:
    click.echo(f"Running multi sync --install-set {WORKSPACE_INSTALL_SET}...")
    sync_workspace(ws_path, install_set=WORKSPACE_INSTALL_SET)


def _build_console(workspace_dir: str) -> None:
    console_dir = Path(workspace_dir) / "console"
    if not console_dir.is_dir():
        click.echo(f"Console directory not found at {console_dir}, skipping build.")
        return

    click.echo("Building console...")
    workspace_path = Path(workspace_dir)
    if not run_workspace_package_command(workspace_path, console_dir, "install"):
        return

    run_workspace_package_command(workspace_path, console_dir, "run", "build")
    click.echo("Console build complete.")


def _symlink_codex_auth() -> None:
    """Point the service CODEX_HOME at the user's normal Codex login."""
    codex_auth = Path.home() / ".codex" / "auth.json"
    service_auth = CODEX_HOME_DIR / "auth.json"

    CODEX_HOME_DIR.mkdir(parents=True, exist_ok=True)

    if not codex_auth.is_file():
        click.echo(
            f"Codex auth not found at {codex_auth}; run 'codex login' before "
            "using voice Codex services."
        )
        return

    if service_auth.is_symlink():
        if service_auth.resolve() == codex_auth.resolve():
            click.echo(f"Codex service auth already linked to {codex_auth}")
            return
        service_auth.unlink()
    elif service_auth.exists():
        try:
            auth_matches = service_auth.read_bytes() == codex_auth.read_bytes()
        except OSError:
            auth_matches = False
        if not auth_matches:
            click.echo(
                f"Codex service auth already exists at {service_auth} and differs "
                f"from {codex_auth}; leaving it unchanged."
            )
            return
        service_auth.unlink()

    service_auth.symlink_to(codex_auth)
    click.echo(f"Symlinked Codex service auth → {codex_auth}")


def _ensure_codex_home_default_files(workspace_dir: str) -> None:
    """Create missing Openbase Codex home instruction files."""
    CODEX_HOME_DIR.mkdir(parents=True, exist_ok=True)
    defaults_dir = Path(workspace_dir) / CODEX_HOME_DEFAULT_SOURCE_DIR

    for resource_name, target_path in CODEX_HOME_DEFAULT_FILES:
        if target_path.exists():
            click.echo(f"Codex home default already exists at {target_path}")
            continue

        source_path = defaults_dir / resource_name
        if not source_path.is_file():
            click.echo(f"Codex home default source not found at {source_path}")
            continue

        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(
            source_path.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        click.echo(f"Created Codex home default at {target_path}")


def _ensure_codex_home_dispatcher_config() -> None:
    """Create the missing Openbase dispatcher config."""
    if CODEX_DISPATCHER_CONFIG_PATH.exists():
        click.echo(
            f"Codex home dispatcher config already exists at "
            f"{CODEX_DISPATCHER_CONFIG_PATH}"
        )
        return

    CODEX_DISPATCHER_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CODEX_DISPATCHER_CONFIG_PATH.write_text(
        json.dumps(CODEX_HOME_DEFAULT_DISPATCHER_CONFIG, indent=2) + "\n",
        encoding="utf-8",
    )
    click.echo(f"Created Codex home dispatcher config at {CODEX_DISPATCHER_CONFIG_PATH}")


def _symlink_codex_home_skills(workspace_dir: str) -> None:
    """Symlink workspace-owned skills into the Openbase Codex home."""
    source_root = Path(workspace_dir) / CODEX_HOME_SKILLS_SOURCE_DIR
    skill_sources = _workspace_skill_sources(source_root)
    if not skill_sources:
        click.echo(f"No workspace skills found at {source_root}")
        return

    target_root = CODEX_HOME_DIR / "skills"
    target_root.mkdir(parents=True, exist_ok=True)

    for source_path in skill_sources:
        target_path = target_root / source_path.name
        if target_path.is_symlink():
            if target_path.resolve() == source_path.resolve():
                click.echo(f"Codex home skill already linked at {target_path}")
                continue
            target_path.unlink()
        elif target_path.exists():
            click.echo(
                f"Codex home skill already exists at {target_path}; "
                "leaving it unchanged."
            )
            continue

        target_path.symlink_to(source_path)
        click.echo(f"Linked Codex home skill {target_path} → {source_path}")


def _ensure_codex_home_config(workspace_dir: str) -> None:
    """Configure Openbase's service Codex home."""
    CODEX_HOME_DIR.mkdir(parents=True, exist_ok=True)
    config_path = CODEX_HOME_DIR / "config.toml"
    command_path, args = _super_agents_mcp_command(Path(workspace_dir))
    block = (
        f"[{SUPER_AGENTS_MCP_TABLE}]\n"
        f"command = {json.dumps(str(command_path))}\n"
        f"{_toml_args_line(args)}"
    )

    if not command_path.is_file():
        click.echo(
            f"Super Agents MCP command not found at {command_path}; "
            "writing the expected config path anyway."
        )

    existing = ""
    if config_path.is_file():
        existing = config_path.read_text(encoding="utf-8")

    updated = _ensure_toml_root_values(existing, CODEX_HOME_PERMISSION_VALUES)
    updated = _replace_toml_table(updated, SUPER_AGENTS_MCP_TABLE, block)
    if updated == existing:
        click.echo(f"Codex home config already configured at {config_path}")
        return

    config_path.write_text(updated, encoding="utf-8")
    click.echo(f"Configured Codex home config at {config_path}")


def _super_agents_mcp_command(workspace_dir: Path) -> tuple[Path, list[str]]:
    candidates = (
        workspace_dir / ".venv" / "bin" / SUPER_AGENTS_MCP_COMMAND,
        workspace_dir / "cli" / ".venv" / "bin" / SUPER_AGENTS_MCP_COMMAND,
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate, []

    if command := which(SUPER_AGENTS_MCP_COMMAND):
        return Path(command), []

    if uv_bin := which("uv"):
        run_dir = workspace_dir / "cli"
        if not run_dir.is_dir():
            run_dir = workspace_dir
        return Path(uv_bin), [
            "--directory",
            str(run_dir),
            "run",
            SUPER_AGENTS_MCP_COMMAND,
        ]

    return candidates[0], []


def _toml_args_line(args: list[str]) -> str:
    if not args:
        return ""
    return f"args = {json.dumps(args)}\n"


def _ensure_toml_root_values(
    text: str,
    values: tuple[tuple[str, str], ...],
) -> str:
    lines = text.splitlines()
    first_table_index = next(
        (
            index
            for index, line in enumerate(lines)
            if line.strip().startswith("[") and line.strip().endswith("]")
        ),
        len(lines),
    )
    root_lines = lines[:first_table_index]
    table_lines = lines[first_table_index:]
    keys = {key for key, _value in values}
    updated_root = [
        line
        for line in root_lines
        if _toml_root_key(line) not in keys
    ]

    while updated_root and not updated_root[-1].strip():
        updated_root.pop()

    for key, value in values:
        updated_root.append(f"{key} = {value}")

    while table_lines and not table_lines[0].strip():
        table_lines.pop(0)

    if table_lines:
        return "\n".join(updated_root) + "\n\n" + "\n".join(table_lines) + "\n"
    return "\n".join(updated_root) + "\n"


def _toml_root_key(line: str) -> str | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None
    return stripped.split("=", 1)[0].strip()


def _replace_toml_table(text: str, table_name: str, block: str) -> str:
    target_header = f"[{table_name}]"
    lines = text.splitlines()
    output: list[str] = []
    index = 0

    while index < len(lines):
        if lines[index].strip() == target_header:
            index += 1
            while index < len(lines):
                stripped = lines[index].strip()
                if stripped.startswith("[") and stripped.endswith("]"):
                    break
                index += 1
            while output and not output[-1].strip():
                output.pop()
            continue

        output.append(lines[index])
        index += 1

    while output and not output[-1].strip():
        output.pop()

    if output:
        return "\n".join(output) + "\n\n" + block
    return block


def _workspace_skill_sources(source_root: Path) -> list[Path]:
    candidate_roots = [source_root / "skills", source_root]
    seen: set[Path] = set()
    sources: list[Path] = []

    for candidate_root in candidate_roots:
        if not candidate_root.is_dir():
            continue
        for child in sorted(candidate_root.iterdir(), key=lambda path: path.name):
            if not child.is_dir() or child.name.startswith("."):
                continue
            if (child / "SKILL.md").is_file():
                resolved = child.resolve()
                if resolved not in seen:
                    seen.add(resolved)
                    sources.append(child)

    return sources


def _init_cli_workspace(workspace_dir: str) -> None:
    """Initialize the CLI checkout that now hosts the LiveKit worker."""
    cli_dir = Path(workspace_dir) / "cli"
    if not cli_dir.is_dir():
        click.echo("CLI directory not found, skipping worker init.")
        return

    uv_bin = which("uv")
    if not uv_bin:
        click.echo("'uv' not found on PATH, skipping CLI workspace init.")
        return

    click.echo("Initializing CLI workspace...")

    # Create venv and install dependencies
    click.echo("  Running uv sync...")
    subprocess.run([uv_bin, "sync"], cwd=str(cli_dir), check=True)

    # Download LiveKit model files (STT, VAD, etc.)
    click.echo("  Downloading LiveKit model files...")
    subprocess.run(
        [
            uv_bin,
            "run",
            "python",
            "-m",
            "openbase_coder_cli.livekit_agent.livekit",
            "download-files",
        ],
        cwd=str(cli_dir),
        check=True,
    )

    click.echo("CLI workspace initialization complete.")


def _install_cli_shim(workspace_dir: str) -> None:
    """Install a stable user command that runs the workspace checkout."""
    uv_bin = which("uv")
    if not uv_bin:
        click.echo("'uv' not found on PATH, skipping CLI shim install.")
        return

    cli_dir = Path(workspace_dir) / "cli"
    if not cli_dir.is_dir():
        click.echo(f"CLI directory not found at {cli_dir}, skipping CLI shim install.")
        return

    user_bin = Path.home() / ".local" / "bin"
    user_bin.mkdir(parents=True, exist_ok=True)
    shim_path = user_bin / "openbase-coder"
    if shim_path.is_symlink():
        shim_path.unlink()
    shim = (
        "#!/bin/sh\n"
        f"cd {shlex.quote(str(cli_dir))} || exit 1\n"
        f"exec {shlex.quote(uv_bin)} run openbase-coder \"$@\"\n"
    )
    shim_path.write_text(shim)
    shim_path.chmod(0o755)
    click.echo(f"Installed openbase-coder shim at {shim_path}")


def _ensure_env_file(
    env_file: str,
    *,
    assembly_ai_api_key: str,
    cartesia_api_key: str,
) -> None:
    path = Path(env_file)
    if path.is_file():
        click.echo(f".env already exists at {path}, leaving unchanged.")
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    secret_key = secrets.token_urlsafe(50)
    livekit_api_key = "APIkey" + secrets.token_urlsafe(12)
    livekit_api_secret = secrets.token_urlsafe(32)

    lines = [
        f"OPENBASE_CODER_CLI_SECRET_KEY={secret_key}",
        f"LIVEKIT_API_KEY={livekit_api_key}",
        f"LIVEKIT_API_SECRET={livekit_api_secret}",
        "# Use tailscale for phone-to-computer voice calls; use local for loopback-only testing.",
        "LIVEKIT_NETWORK_MODE=tailscale",
        "LIVEKIT_URL=ws://localhost:7880",
        "# In tailscale mode, launchd rewrites localhost LIVEKIT_URL to the Tailscale IPv4 address.",
        "# The local Python agent still registers over localhost unless LIVEKIT_AGENT_URL is set.",
        "# LIVEKIT_AGENT_URL=ws://localhost:7880",
        "# Override the Tailscale IP LiveKit advertises in ICE candidates.",
        "# If unset in tailscale mode, the launchd service uses the first `tailscale ip -4` value.",
        "# LIVEKIT_NODE_IP=100.x.y.z",
        "# Override the Tailscale interface used for LiveKit media.",
        "# If unset, the launchd service derives it from LIVEKIT_NODE_IP.",
        "# LIVEKIT_INTERFACE=utun4",
        "# Override the address LiveKit binds locally. Keep this on localhost when using Tailscale Serve.",
        "# LIVEKIT_BIND_IP=127.0.0.1",
        "# Override the LiveKit agent health/control listener. Keep this on localhost.",
        "# LIVEKIT_AGENT_HOST=127.0.0.1",
        "# Override the LiveKit TCP media fallback port.",
        "# LIVEKIT_TCP_PORT=7881",
        "# Override the LiveKit UDP media port.",
        "# LIVEKIT_UDP_PORT=7882",
        "# Override the CLI API listener. Keep this on localhost when using Tailscale Serve.",
        "# OPENBASE_CODER_CLI_HOST=127.0.0.1",
        "# Allow localhost and Tailscale Serve hostnames.",
        "OPENBASE_CODER_CLI_ALLOWED_HOSTS=localhost,127.0.0.1,.ts.net",
        "# Codex app-server defaults used by the launchd service.",
        "CODEX_MODEL=gpt-5.5",
        "CODEX_MODEL_REASONING_EFFORT=high",
        "CODEX_SERVICE_TIER=fast",
        "CODEX_APP_SERVER_URL=ws://127.0.0.1:4500",
        "LIVEKIT_CODEX_THREAD_CWD=~",
        "# Cartesia voice used by the LiveKit agent TTS.",
        "CARTESIA_VOICE_ID=9626c31c-bec5-4cca-baa8-f8ba9e84c8bc",
        "OPENBASE_CODER_CLI_OAUTH_CLIENT_ID=openbase-coder-cli",
    ]

    if assembly_ai_api_key:
        lines.append(f"ASSEMBLY_AI_API_KEY={assembly_ai_api_key}")
    if cartesia_api_key:
        lines.append(f"CARTESIA_API_KEY={cartesia_api_key}")

    lines.extend(
        [
            "# Override the web backend URL (defaults to https://app.openbase.cloud):",
            "# OPENBASE_CODER_CLI_WEB_BACKEND_URL=https://app.openbase.cloud",
            "# Override JWT key/session endpoints if your backend routes differ:",
            "# OPENBASE_CODER_CLI_JWT_JWKS_URL=https://app.openbase.cloud/.well-known/jwks.json",
            "# OPENBASE_CODER_CLI_JWT_AUTH_SESSION_URL=https://app.openbase.cloud/_allauth/app/v1/auth/session",
        ]
    )

    path.write_text("\n".join(lines) + "\n")
    click.echo(f"Generated .env at {path}")
