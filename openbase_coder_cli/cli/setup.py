from __future__ import annotations

import importlib.resources as importlib_resources
import json
import platform
import secrets
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from shutil import which

import click
from multi.api import sync_workspace

from openbase_coder_cli.backend_config import (
    CODING_BACKEND_ENV_KEY,
    DEFAULT_CODING_BACKEND,
    LEGACY_CODEX_BACKEND_ENV_KEY,
    OPENBASE_CLOUD_BACKEND,
    SUPPORTED_BACKENDS,
    normalize_backend,
)
from openbase_coder_cli.claude_auth import (
    claude_auth_status,
    run_claude_login,
    sync_normal_claude_state,
)
from openbase_coder_cli.cli.node import run_workspace_package_command
from openbase_coder_cli.codex_backend_config import apply_backend_to_codex_config
from openbase_coder_cli.codex_home_instructions import (
    ensure_openbase_agents_md,
    ensure_openbase_instruction_md,
)
from openbase_coder_cli.config.machine_token_manager import (
    MachineTokenError,
    MachineTokenManager,
)
from openbase_coder_cli.config.token_manager import (
    DEFAULT_WEB_BACKEND_URL,
    AuthLoginRequiredError,
    AuthTransientError,
    TokenManager,
)
from openbase_coder_cli.dispatcher_config import (
    DISPATCHER_VOICE_ID_KEY,
    DISPATCHER_VOICE_NAME_KEY,
    STT_PROVIDER_KEY,
    TTS_PROVIDER_KEY,
)
from openbase_coder_cli.paths import (
    CODEX_DIRECT_LIVEKIT_INSTRUCTIONS_PATH,
    CODEX_DISPATCHER_CONFIG_PATH,
    CODEX_DISPATCHER_INSTRUCTIONS_PATH,
    CODEX_HOME_DIR,
    CODEX_SUPER_AGENT_INSTRUCTIONS_PATH,
    DEFAULT_ENV_FILE_PATH,
    DEFAULT_WORKSPACE_DIR,
    LEGACY_CODEX_DIRECT_LIVEKIT_INSTRUCTIONS_PATH,
    LEGACY_CODEX_DISPATCHER_CONFIG_PATH,
    LEGACY_CODEX_DISPATCHER_INSTRUCTIONS_PATH,
    LEGACY_CODEX_SUPER_AGENT_INSTRUCTIONS_PATH,
    NORMAL_CLAUDE_CONFIG_DIR,
    NORMAL_CLAUDE_SETTINGS_PATH,
    NORMAL_CODEX_CONFIG_PATH,
    OPENBASE_BASE_DIR,
    OPENBASE_CLAUDE_CONFIG_DIR,
    OPENBASE_CLAUDE_JSON_PATH,
    OPENBASE_CLAUDE_MD_PATH,
    OPENBASE_CLAUDE_SETTINGS_PATH,
    OPENBASE_SOUNDS_DIR,
)
from openbase_coder_cli.runtime import (
    current_runtime_package,
    packaged_instructions_dir,
    packaged_skills_dir,
)
from openbase_coder_cli.services.installation import InstallationConfig
from openbase_coder_cli.services.launchd import install_all_services
from openbase_coder_cli.services.tailscale_serve import (
    configure_tailscale_serve,
    tailscale_serve_health,
)
from openbase_coder_cli.stt_providers import (
    ASSEMBLYAI_STT_PROVIDER_ID,
    LOCAL_MLX_WHISPER_STT_PROVIDER_ID,
    OPENBASE_CLOUD_STT_PROVIDER_ID,
    download_local_mlx_whisper,
)
from openbase_coder_cli.tts_providers import (
    CARTESIA_PROVIDER_ID,
    KOKORO_PROVIDER_ID,
    OPENBASE_CLOUD_TTS_PROVIDER_ID,
    get_tts_provider,
)

WORKSPACE_REPO = "https://github.com/openbase-community/openbase-coder-workspace.git"
WORKSPACE_INSTALL_SET = "default"
CODEX_HOME_DEFAULT_SOURCE_DIR = "instructions"
CODEX_HOME_SKILLS_SOURCE_DIR = "skills"
BUNDLED_SOUNDS_PACKAGE = "openbase_coder_cli.resources.sounds"
BUNDLED_SOUND_FILES = ("wilhelm.wav",)
CODEX_HOME_DEFAULT_FILES = (
    ("VOICE_INSTRUCTIONS.md", CODEX_DIRECT_LIVEKIT_INSTRUCTIONS_PATH),
    ("DISPATCHER_INSTRUCTIONS.md", CODEX_DISPATCHER_INSTRUCTIONS_PATH),
    ("SUPER_AGENT_INSTRUCTIONS.md", CODEX_SUPER_AGENT_INSTRUCTIONS_PATH),
)
LEGACY_CODEX_HOME_DEFAULT_FILES = (
    (
        CODEX_DIRECT_LIVEKIT_INSTRUCTIONS_PATH,
        LEGACY_CODEX_DIRECT_LIVEKIT_INSTRUCTIONS_PATH,
    ),
    (CODEX_DISPATCHER_INSTRUCTIONS_PATH, LEGACY_CODEX_DISPATCHER_INSTRUCTIONS_PATH),
    (CODEX_SUPER_AGENT_INSTRUCTIONS_PATH, LEGACY_CODEX_SUPER_AGENT_INSTRUCTIONS_PATH),
)
THREAD_SYNC_EXCHANGE_DIR_NAME = "thread-sync"
THREAD_SYNC_MARKER_FILE_NAME = "syncthing-folder-openbase-thread-sync.txt"
THREAD_SYNC_STIGNORE_CONTENT = "#include .stglobalignore\n"
DEFAULT_SYNCTHING_GLOBAL_STIGNORE_CONTENT = "(?d).DS_Store\n"
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
CLAUDE_CODE_PERMISSION_MODE = "bypassPermissions"
OPENBASE_CLAUDE_SETTINGS_DEFAULTS = {
    "env": {"CLAUDE_CODE_ENABLE_TELEMETRY": "0"},
    "permissions": {
        "allow": [],
        "deny": [],
        "defaultMode": CLAUDE_CODE_PERMISSION_MODE,
    },
    "skipDangerousModePermissionPrompt": True,
    "skipAutoPermissionPrompt": True,
}
CODEX_HOME_DEFAULT_DISPATCHER_CONFIG = {
    "dispatcher_reasoning_effort": "low",
    "super_agents_reasoning_effort": "high",
    "backend_models": {
        "codex": {"dispatcher": "gpt-5.5", "super_agents": "gpt-5.5"},
        "claude_code": {"dispatcher": "opus", "super_agents": "opus"},
    },
}
CODING_BACKEND_OPTIONS = SUPPORTED_BACKENDS
AUDIO_PROVIDER_OPENBASE_CLOUD = "openbase-cloud"
AUDIO_PROVIDER_CARTESIA = "cartesia"
AUDIO_PROVIDER_LOCAL = "local"
AUDIO_PROVIDER_OPTIONS = (
    AUDIO_PROVIDER_OPENBASE_CLOUD,
    AUDIO_PROVIDER_CARTESIA,
    AUDIO_PROVIDER_LOCAL,
)
DEFAULT_AUDIO_PROVIDER = AUDIO_PROVIDER_OPENBASE_CLOUD
LOCAL_AUDIO_REQUIREMENTS = (
    "huggingface-hub>=0.36.0",
    "kokoro>=0.9.4",
    "mlx-whisper>=0.4.3",
)
LOCAL_AUDIO_PYTHON_MAX = (3, 13)


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
    "--dev-workspace",
    is_flag=True,
    help="Clone/sync the Openbase Coder workspace for development-mode runtime assets.",
)
@click.option(
    "--skip-services",
    is_flag=True,
    help="Skip background service installation.",
)
@click.option(
    "--link-codex-config",
    is_flag=True,
    help=(
        "Symlink Openbase's service Codex config to the normal ~/.codex/config.toml."
    ),
)
@click.option(
    "--backend",
    "coding_backend",
    type=str,
    default=None,
    help=(
        "Default coding backend: codex, openbase-cloud, or claude-code. "
        "New env files use codex when omitted; "
        "existing env files are only changed when this option is provided."
    ),
)
@click.option(
    "--audio-provider",
    type=click.Choice(AUDIO_PROVIDER_OPTIONS),
    default=None,
    help=(
        "Voice audio provider. New dispatcher configs use openbase-cloud when "
        "omitted; existing configs are only changed when this option is provided."
    ),
)
def setup(
    workspace_dir: str,
    env_file: str,
    assembly_ai_api_key: str,
    cartesia_api_key: str,
    skip_clone: bool,
    dev_workspace: bool,
    skip_services: bool,
    link_codex_config: bool,
    coding_backend: str | None,
    audio_provider: str | None,
) -> None:
    """Full install flow for Openbase Coder."""
    if platform.system() not in ("Darwin", "Linux"):
        raise click.ClickException("Setup is only supported on macOS and Linux.")
    if coding_backend is not None:
        try:
            coding_backend = normalize_backend(coding_backend)
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc

    OPENBASE_BASE_DIR.mkdir(parents=True, exist_ok=True)
    _ensure_thread_sync_exchange_dir()
    _ensure_bundled_sounds()
    runtime_package = current_runtime_package()
    use_dev_workspace = dev_workspace or runtime_package is None

    # --- Clone workspace ---
    if use_dev_workspace and not skip_clone:
        _clone_workspace(workspace_dir)
    elif runtime_package is not None:
        click.echo(f"Using bundled runtime assets from {runtime_package.root}")
    else:
        click.echo("Skipping workspace clone; no bundled runtime package detected.")

    # --- Write installation.json ---
    config = InstallationConfig(
        workspace_path=workspace_dir if use_dev_workspace else "",
        env_file=env_file,
        package_path=str(runtime_package.root) if runtime_package else "",
        console_build_dir=(
            str(runtime_package.console_build_dir)
            if runtime_package and runtime_package.console_build_dir.is_dir()
            else ""
        ),
        python_path=(
            str(runtime_package.python_path)
            if runtime_package and runtime_package.python_path.is_file()
            else ""
        ),
        livekit_server_path=(
            str(runtime_package.livekit_server_path)
            if runtime_package and runtime_package.livekit_server_path.is_file()
            else ""
        ),
        standalone=runtime_package is not None,
    )
    config.save()
    click.echo("Wrote installation.json")

    # --- Generate .env ---
    _ensure_env_file(
        env_file,
        assembly_ai_api_key=assembly_ai_api_key,
        cartesia_api_key=cartesia_api_key,
        coding_backend=coding_backend,
    )
    selected_coding_backend = _selected_coding_backend(Path(env_file), coding_backend)
    if selected_coding_backend == OPENBASE_CLOUD_BACKEND:
        _ensure_openbase_cloud_machine_token(Path(env_file))

    # --- Symlink Codex auth into the service CODEX_HOME ---
    _symlink_codex_auth()
    _ensure_codex_home_default_files(workspace_dir if use_dev_workspace else "")
    _ensure_codex_home_dispatcher_config(audio_provider=audio_provider)
    if audio_provider == AUDIO_PROVIDER_LOCAL:
        _ensure_local_audio_dependencies(runtime_package)
        _download_local_audio_models()
    _symlink_codex_home_skills(workspace_dir if use_dev_workspace else "")

    # --- Initialize CLI workspace ---
    if use_dev_workspace:
        _init_cli_workspace(workspace_dir)

    # --- Configure the service CODEX_HOME ---
    if link_codex_config:
        _ensure_codex_home_config(
            workspace_dir if use_dev_workspace else "",
            coding_backend=selected_coding_backend,
            link_codex_config=True,
        )
    else:
        _ensure_codex_home_config(
            workspace_dir if use_dev_workspace else "",
            coding_backend=selected_coding_backend,
        )
    _ensure_claude_config(workspace_dir if use_dev_workspace else "")
    _ensure_claude_auth_bridge(login_if_needed=selected_coding_backend == "claude_code")

    # --- Install/update user-facing CLI shim ---
    _install_cli_shim(workspace_dir if use_dev_workspace else "")

    # --- Build console ---
    if use_dev_workspace:
        _build_console(workspace_dir)
    elif config.console_build_dir:
        click.echo(f"Using bundled console build at {config.console_build_dir}")
    else:
        click.echo(
            "No bundled console build found; server will require a console build."
        )

    # --- Install services ---
    if not skip_services:
        click.echo()
        service_manager = "launchd" if platform.system() == "Darwin" else "systemd"
        click.echo(f"Installing {service_manager} services...")
        install_all_services(config)
    else:
        click.echo("Skipped service installation (--skip-services).")

    click.echo()
    click.echo("Configuring Tailscale Serve routes...")
    try:
        configure_tailscale_serve()
    except Exception as exc:
        click.echo(click.style(f"  WARN  {exc}", fg="yellow"))
        click.echo(
            "  Run these manually after Tailscale is installed and connected:\n"
            "    tailscale serve --bg --http=18080 http://127.0.0.1:7999\n"
            "    tailscale serve --bg --tcp=7880 tcp://127.0.0.1:7880"
        )
    else:
        health = tailscale_serve_health()
        if health.healthy:
            click.echo(f"  OK    Openbase is reachable at {health.openbase_url}")
        else:
            click.echo(
                click.style(
                    "  WARN  Tailscale Serve was configured, but the external "
                    "Openbase health check is not passing.",
                    fg="yellow",
                )
            )
            if health.error:
                click.echo(f"        {health.error}")

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
            subprocess.run(
                ["git", "-C", str(ws), "fetch", "origin", "main"], check=True
            )
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
            subprocess.run(
                ["git", "-C", str(repo_path), "pull", "--ff-only"], check=True
            )


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


def _ensure_thread_sync_exchange_dir() -> None:
    """Create the Syncthing-backed cross-device Codex thread exchange folder."""
    exchange_dir = OPENBASE_BASE_DIR / THREAD_SYNC_EXCHANGE_DIR_NAME
    exchange_dir.mkdir(parents=True, exist_ok=True)

    marker_dir = exchange_dir / ".stfolder"
    marker_dir.mkdir(exist_ok=True)
    marker_path = marker_dir / THREAD_SYNC_MARKER_FILE_NAME
    if not marker_path.exists():
        marker_path.write_text(
            "Openbase Coder cross-device Codex thread snapshot exchange.\n",
            encoding="utf-8",
        )

    stignore_path = exchange_dir / ".stignore"
    if not stignore_path.exists():
        stignore_path.write_text(THREAD_SYNC_STIGNORE_CONTENT, encoding="utf-8")

    global_ignore_path = _syncthing_global_ignore_path()
    if not global_ignore_path.exists():
        global_ignore_path.parent.mkdir(parents=True, exist_ok=True)
        global_ignore_path.write_text(
            DEFAULT_SYNCTHING_GLOBAL_STIGNORE_CONTENT,
            encoding="utf-8",
        )

    stglobal_path = exchange_dir / ".stglobalignore"
    if stglobal_path.is_symlink():
        if stglobal_path.resolve() != global_ignore_path.resolve():
            stglobal_path.unlink()
            stglobal_path.symlink_to(global_ignore_path)
    elif not stglobal_path.exists():
        stglobal_path.symlink_to(global_ignore_path)

    click.echo(f"Prepared Codex thread sync exchange folder at {exchange_dir}")


def _ensure_bundled_sounds() -> None:
    """Install package-bundled sounds into Openbase's user sounds directory."""
    OPENBASE_SOUNDS_DIR.mkdir(parents=True, exist_ok=True)
    resources = importlib_resources.files(BUNDLED_SOUNDS_PACKAGE)
    for sound_name in BUNDLED_SOUND_FILES:
        resource = resources.joinpath(sound_name)
        with importlib_resources.as_file(resource) as source_path:
            if not source_path.is_file():
                raise click.ClickException(
                    f"Bundled sound resource not found: {sound_name}"
                )
            _copy_bundled_sound(
                source_path=source_path, target_path=OPENBASE_SOUNDS_DIR / sound_name
            )


def _copy_bundled_sound(*, source_path: Path, target_path: Path) -> None:
    if target_path.exists():
        if not target_path.is_file():
            click.echo(
                f"Bundled sound target already exists at {target_path}; "
                "leaving it unchanged."
            )
            return
        try:
            sound_matches = target_path.read_bytes() == source_path.read_bytes()
        except OSError:
            sound_matches = False
        if sound_matches:
            click.echo(f"Bundled sound already installed at {target_path}")
            return
        click.echo(
            f"Bundled sound already exists at {target_path} and differs from "
            "the package default; leaving it unchanged."
        )
        return

    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_path, target_path)
    click.echo(f"Installed bundled sound at {target_path}")


def _syncthing_global_ignore_path() -> Path:
    return Path.home() / ".config" / "syncthing" / "global.stignore"


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
    """Create Openbase-managed agent instruction files."""
    CODEX_HOME_DIR.mkdir(parents=True, exist_ok=True)
    OPENBASE_CLAUDE_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    defaults_dir = _default_instructions_dir(workspace_dir)

    ensure_openbase_agents_md(
        defaults_dir.parent,
        codex_home_dir=CODEX_HOME_DIR,
        report=click.echo,
    )
    ensure_openbase_instruction_md(
        defaults_dir.parent,
        target_path=OPENBASE_CLAUDE_MD_PATH,
        document_label="Claude config CLAUDE.md",
        report=click.echo,
    )

    for resource_name, target_path in CODEX_HOME_DEFAULT_FILES:
        source_path = defaults_dir / resource_name
        if not source_path.is_file():
            click.echo(f"Openbase instruction source not found at {source_path}")
            continue

        _ensure_matching_symlink_or_file(
            target_path=target_path,
            source_path=source_path,
            label="Openbase instruction",
        )

    for canonical_path, legacy_path in LEGACY_CODEX_HOME_DEFAULT_FILES:
        _ensure_legacy_symlink(
            legacy_path=legacy_path,
            canonical_path=canonical_path,
            label="legacy Codex home instruction",
        )


def _ensure_matching_symlink_or_file(
    *,
    target_path: Path,
    source_path: Path,
    label: str,
) -> bool:
    if target_path.is_symlink():
        if target_path.resolve() == source_path.resolve():
            click.echo(f"{label} already linked at {target_path}")
            return False
        target_path.unlink()
    elif target_path.exists():
        if not target_path.is_file():
            click.echo(
                f"{label} already exists at {target_path}; leaving it unchanged."
            )
            return False

        try:
            default_matches = target_path.read_bytes() == source_path.read_bytes()
        except OSError:
            default_matches = False
        if not default_matches:
            click.echo(
                f"{label} already exists at {target_path} and differs from "
                "the workspace default; leaving it unchanged."
            )
            return False
        target_path.unlink()

    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.symlink_to(source_path)
    click.echo(f"Linked {label} {target_path} -> {source_path}")
    return True


def _ensure_legacy_symlink(
    *,
    legacy_path: Path,
    canonical_path: Path,
    label: str,
) -> None:
    if legacy_path == canonical_path:
        return
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    if legacy_path.is_symlink():
        if legacy_path.readlink() == canonical_path:
            return
        legacy_path.unlink()
    elif legacy_path.exists():
        return
    legacy_path.symlink_to(canonical_path)
    click.echo(f"Linked {label} {legacy_path} -> {canonical_path}")


def _ensure_codex_home_dispatcher_config(audio_provider: str | None = None) -> None:
    """Create the missing Openbase dispatcher config."""
    _migrate_legacy_codex_home_dispatcher_config()
    if CODEX_DISPATCHER_CONFIG_PATH.exists():
        if audio_provider:
            _update_dispatcher_audio_provider(
                CODEX_DISPATCHER_CONFIG_PATH,
                audio_provider,
            )
        click.echo(
            f"Openbase dispatcher config already exists at "
            f"{CODEX_DISPATCHER_CONFIG_PATH}"
        )
        _ensure_legacy_dispatcher_config_link()
        return

    CODEX_DISPATCHER_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CODEX_DISPATCHER_CONFIG_PATH.write_text(
        json.dumps(
            _default_dispatcher_config(audio_provider or DEFAULT_AUDIO_PROVIDER),
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    click.echo(f"Created Openbase dispatcher config at {CODEX_DISPATCHER_CONFIG_PATH}")
    _ensure_legacy_dispatcher_config_link()


def _default_dispatcher_config(audio_provider: str) -> dict[str, object]:
    return {
        **CODEX_HOME_DEFAULT_DISPATCHER_CONFIG,
        **_audio_provider_config(audio_provider),
    }


def _update_dispatcher_audio_provider(path: Path, audio_provider: str) -> None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload.update(_audio_provider_config(audio_provider))
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    click.echo(f"Updated voice audio provider in {path}.")


def _audio_provider_config(audio_provider: str) -> dict[str, str]:
    if audio_provider == AUDIO_PROVIDER_OPENBASE_CLOUD:
        tts_provider = OPENBASE_CLOUD_TTS_PROVIDER_ID
        stt_provider = OPENBASE_CLOUD_STT_PROVIDER_ID
    elif audio_provider == AUDIO_PROVIDER_CARTESIA:
        tts_provider = CARTESIA_PROVIDER_ID
        stt_provider = ASSEMBLYAI_STT_PROVIDER_ID
    elif audio_provider == AUDIO_PROVIDER_LOCAL:
        tts_provider = KOKORO_PROVIDER_ID
        stt_provider = LOCAL_MLX_WHISPER_STT_PROVIDER_ID
    else:
        raise click.ClickException(f"Unsupported audio provider: {audio_provider}")

    voice = get_tts_provider(tts_provider).default_dispatcher_voice()
    return {
        TTS_PROVIDER_KEY: tts_provider,
        STT_PROVIDER_KEY: stt_provider,
        DISPATCHER_VOICE_ID_KEY: voice.id,
        DISPATCHER_VOICE_NAME_KEY: voice.name,
    }


def _download_local_audio_models() -> None:
    click.echo("Downloading local TTS voices...")
    tts_status = get_tts_provider(KOKORO_PROVIDER_ID).download_all_voices()
    if not tts_status.ready:
        raise click.ClickException(
            tts_status.detail or "Unable to download local TTS voices."
        )
    click.echo("Downloading local STT model...")
    stt_status = download_local_mlx_whisper()
    if not stt_status.ready:
        raise click.ClickException(
            stt_status.detail or "Unable to download local STT model."
        )
    click.echo("Downloaded local voice audio models.")


def _ensure_local_audio_dependencies(runtime_package) -> None:
    python_path = (
        runtime_package.python_path if runtime_package else Path(sys.executable)
    )
    version = _python_version(python_path)
    if version >= LOCAL_AUDIO_PYTHON_MAX:
        raise click.ClickException(
            "Local audio currently requires a Python 3.12 Openbase Coder runtime "
            "because Kokoro declares Python <3.13. Reinstall Openbase Coder with "
            "a Python 3.12 standalone package, or use --audio-provider openbase-cloud."
        )
    if _local_audio_dependencies_available(python_path):
        return

    click.echo("Installing local audio Python dependencies...")
    try:
        subprocess.run(
            [
                str(python_path),
                "-m",
                "pip",
                "install",
                "--upgrade",
                *LOCAL_AUDIO_REQUIREMENTS,
            ],
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise click.ClickException(
            "Failed to install local audio dependencies. "
            "Use --audio-provider openbase-cloud or retry after checking network access."
        ) from exc


def _local_audio_dependencies_available(python_path: Path) -> bool:
    result = subprocess.run(
        [
            str(python_path),
            "-c",
            "import huggingface_hub, kokoro, mlx_whisper",
        ],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def _python_version(python_path: Path) -> tuple[int, int]:
    result = subprocess.run(
        [
            str(python_path),
            "-c",
            "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    major, minor = result.stdout.strip().split(".", 1)
    return int(major), int(minor)


def _migrate_legacy_codex_home_dispatcher_config() -> None:
    legacy_path = LEGACY_CODEX_DISPATCHER_CONFIG_PATH
    canonical_path = CODEX_DISPATCHER_CONFIG_PATH
    if canonical_path.exists() or not legacy_path.exists() or legacy_path.is_symlink():
        return
    if not legacy_path.is_file():
        click.echo(
            f"Legacy dispatcher config path exists but is not a file at {legacy_path}; "
            "leaving it unchanged."
        )
        return
    canonical_path.parent.mkdir(parents=True, exist_ok=True)
    canonical_path.write_text(legacy_path.read_text(encoding="utf-8"), encoding="utf-8")
    legacy_path.unlink()
    click.echo(f"Migrated dispatcher config {legacy_path} -> {canonical_path}")


def _ensure_legacy_dispatcher_config_link() -> None:
    legacy_path = LEGACY_CODEX_DISPATCHER_CONFIG_PATH
    canonical_path = CODEX_DISPATCHER_CONFIG_PATH
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    if legacy_path.is_symlink():
        if legacy_path.resolve() == canonical_path.resolve():
            return
        legacy_path.unlink()
    elif legacy_path.exists():
        return
    legacy_path.symlink_to(canonical_path)
    click.echo(f"Linked legacy dispatcher config {legacy_path} -> {canonical_path}")


def _symlink_codex_home_skills(workspace_dir: str) -> None:
    """Symlink workspace-owned skills into Openbase-managed agent homes."""
    source_root = _default_skills_dir(workspace_dir)
    skill_sources = _workspace_skill_sources(source_root)
    if not skill_sources:
        click.echo(f"No workspace skills found at {source_root}")
        return

    _symlink_skills_to_root(
        skill_sources,
        target_root=CODEX_HOME_DIR / "skills",
        label="Codex home",
    )
    _symlink_skills_to_root(
        skill_sources,
        target_root=OPENBASE_CLAUDE_CONFIG_DIR / "skills",
        label="Claude config",
    )


def _symlink_skills_to_root(
    skill_sources: list[Path],
    *,
    target_root: Path,
    label: str,
) -> None:
    target_root.mkdir(parents=True, exist_ok=True)

    for source_path in skill_sources:
        target_path = target_root / source_path.name
        if target_path.is_symlink():
            if target_path.resolve() == source_path.resolve():
                click.echo(f"{label} skill already linked at {target_path}")
                continue
            target_path.unlink()
        elif target_path.exists():
            click.echo(
                f"{label} skill already exists at {target_path}; leaving it unchanged."
            )
            continue

        target_path.symlink_to(source_path)
        click.echo(f"Linked {label} skill {target_path} -> {source_path}")


def _ensure_codex_home_config(
    workspace_dir: str,
    *,
    coding_backend: str = DEFAULT_CODING_BACKEND,
    link_codex_config: bool = False,
) -> None:
    """Configure Openbase's service Codex home."""
    CODEX_HOME_DIR.mkdir(parents=True, exist_ok=True)
    config_path = CODEX_HOME_DIR / "config.toml"
    if link_codex_config:
        _symlink_codex_home_config()

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
    else:
        config_path.write_text(updated, encoding="utf-8")
        click.echo(f"Configured Codex home config at {config_path}")

    result = apply_backend_to_codex_config(coding_backend, config_path=config_path)
    if result.changed:
        click.echo(f"Configured Codex backend in {result.path}")


def _ensure_claude_config(workspace_dir: str) -> None:
    """Configure Openbase's Claude Code config dir."""
    OPENBASE_CLAUDE_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _ensure_claude_settings()
    command_path, args = _super_agents_mcp_command(Path(workspace_dir))
    if not command_path.is_file():
        click.echo(
            f"Super Agents MCP command not found at {command_path}; "
            "writing the expected Claude MCP config path anyway."
        )

    existing = _read_json_object(OPENBASE_CLAUDE_JSON_PATH)
    mcp_servers = existing.get("mcpServers")
    if not isinstance(mcp_servers, dict):
        mcp_servers = {}
    updated = {
        **existing,
        "mcpServers": {
            **mcp_servers,
            "super-agents": {
                "type": "stdio",
                "command": str(command_path),
                **({"args": args} if args else {}),
                "env": {
                    "CLAUDE_CONFIG_DIR": str(OPENBASE_CLAUDE_CONFIG_DIR),
                    "SUPER_AGENTS_DEFAULT_CONFIG_PATH": str(
                        CODEX_DISPATCHER_CONFIG_PATH
                    ),
                    "CODEX_SUPER_AGENT_INSTRUCTIONS_PATH": str(
                        CODEX_SUPER_AGENT_INSTRUCTIONS_PATH
                    ),
                },
            },
        },
    }
    if updated == existing:
        click.echo(f"Claude config already configured at {OPENBASE_CLAUDE_JSON_PATH}")
        return

    OPENBASE_CLAUDE_JSON_PATH.write_text(
        json.dumps(updated, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    click.echo(f"Configured Claude MCP config at {OPENBASE_CLAUDE_JSON_PATH}")


def _ensure_claude_settings() -> None:
    """Configure Claude Code settings for Openbase-managed SDK sessions."""
    existing = _read_json_object(OPENBASE_CLAUDE_SETTINGS_PATH)
    seed = existing or _read_json_object(NORMAL_CLAUDE_SETTINGS_PATH)
    updated = _merge_claude_settings(seed)
    if updated == existing:
        click.echo(
            f"Claude settings already configured at {OPENBASE_CLAUDE_SETTINGS_PATH}"
        )
        return

    OPENBASE_CLAUDE_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    OPENBASE_CLAUDE_SETTINGS_PATH.write_text(
        json.dumps(updated, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    click.echo(f"Configured Claude settings at {OPENBASE_CLAUDE_SETTINGS_PATH}")


def _merge_claude_settings(settings: dict[str, object]) -> dict[str, object]:
    updated = dict(settings)
    env = updated.get("env")
    if not isinstance(env, dict):
        env = {}
    updated["env"] = {
        **OPENBASE_CLAUDE_SETTINGS_DEFAULTS["env"],
        **env,
    }

    permissions = updated.get("permissions")
    if not isinstance(permissions, dict):
        permissions = {}
    updated["permissions"] = {
        "allow": permissions.get("allow", []),
        "deny": permissions.get("deny", []),
        **{
            key: value
            for key, value in permissions.items()
            if key not in {"allow", "deny", "defaultMode"}
        },
        "defaultMode": CLAUDE_CODE_PERMISSION_MODE,
    }
    updated["skipDangerousModePermissionPrompt"] = True
    updated["skipAutoPermissionPrompt"] = True
    updated["claudeMdExcludes"] = _merge_claude_md_excludes(
        updated.get("claudeMdExcludes")
    )
    return updated


def _merge_claude_md_excludes(value: object) -> list[str]:
    excludes = (
        [item for item in value if isinstance(item, str)]
        if isinstance(value, list)
        else []
    )
    normal_claude_md_path = str((NORMAL_CLAUDE_CONFIG_DIR / "CLAUDE.md").expanduser())
    if normal_claude_md_path not in excludes:
        excludes.append(normal_claude_md_path)
    return excludes


def _ensure_claude_auth_bridge(*, login_if_needed: bool = False) -> None:
    """Prepare Openbase's managed Claude Code auth state."""
    status = claude_auth_status()
    if status.logged_in:
        click.echo("Openbase Claude Code auth already configured.")
        return

    result = sync_normal_claude_state()
    if result.state_updated:
        click.echo("Updated Openbase Claude Code state.")
    click.echo(result.message)

    status = claude_auth_status()
    if status.logged_in:
        click.echo("Openbase Claude Code auth configured.")
        return

    if login_if_needed:
        click.echo("Running Claude Code login for Openbase's CLAUDE_CONFIG_DIR...")
        exit_code = run_claude_login()
        if exit_code != 0:
            raise click.ClickException(
                "Claude Code login failed. Run `openbase-coder claude login` and then "
                "`openbase-coder restart --recreate-dispatcher`."
            )
        status = claude_auth_status()
        if status.logged_in:
            click.echo("Openbase Claude Code auth configured.")
            return
        raise click.ClickException(
            "Claude Code login completed but Openbase Claude Code auth is still not "
            "available. Run `openbase-coder claude status` for details."
        )

    click.echo(
        "Openbase Claude Code auth is not configured yet. "
        "Run `openbase-coder claude login` before using the Claude Code backend."
    )


def _read_json_object(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _symlink_codex_home_config() -> None:
    """Point the service CODEX_HOME config at the user's normal Codex config."""
    service_config = CODEX_HOME_DIR / "config.toml"
    normal_config = NORMAL_CODEX_CONFIG_PATH

    CODEX_HOME_DIR.mkdir(parents=True, exist_ok=True)
    normal_config.parent.mkdir(parents=True, exist_ok=True)

    if normal_config.exists() and not normal_config.is_file():
        raise click.ClickException(
            f"Normal Codex config exists but is not a file: {normal_config}"
        )

    if service_config.is_symlink():
        if service_config.resolve() == normal_config.resolve():
            click.echo(f"Codex home config already linked to {normal_config}")
            return
        service_config.unlink()
    elif service_config.exists():
        if not service_config.is_file():
            raise click.ClickException(
                f"Codex home config exists but is not a file: {service_config}"
            )
        if not normal_config.exists():
            normal_config.write_text(
                service_config.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
        service_config.unlink()

    if not normal_config.exists():
        normal_config.write_text("", encoding="utf-8")

    service_config.symlink_to(normal_config)
    click.echo(f"Symlinked Codex home config -> {normal_config}")


def _super_agents_mcp_command(workspace_dir: Path) -> tuple[Path, list[str]]:
    candidates = (
        workspace_dir / ".venv" / "bin" / SUPER_AGENTS_MCP_COMMAND,
        workspace_dir / "cli" / ".venv" / "bin" / SUPER_AGENTS_MCP_COMMAND,
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate, []

    runtime_package = current_runtime_package()
    if runtime_package is not None:
        bundled_command = runtime_package.python_path.parent / SUPER_AGENTS_MCP_COMMAND
        if bundled_command.is_file():
            return bundled_command, []

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


def _default_instructions_dir(workspace_dir: str) -> Path:
    if workspace_dir:
        workspace_source = Path(workspace_dir) / CODEX_HOME_DEFAULT_SOURCE_DIR
        if workspace_source.is_dir():
            return workspace_source
    packaged = packaged_instructions_dir()
    if packaged is not None:
        return packaged
    return Path(workspace_dir or DEFAULT_WORKSPACE_DIR) / CODEX_HOME_DEFAULT_SOURCE_DIR


def _default_skills_dir(workspace_dir: str) -> Path:
    if workspace_dir:
        workspace_source = Path(workspace_dir) / CODEX_HOME_SKILLS_SOURCE_DIR
        if workspace_source.is_dir():
            return workspace_source
    packaged = packaged_skills_dir()
    if packaged is not None:
        return packaged
    return Path(workspace_dir or DEFAULT_WORKSPACE_DIR) / CODEX_HOME_SKILLS_SOURCE_DIR


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
    updated_root = [line for line in root_lines if _toml_root_key(line) not in keys]

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
    subprocess.run(
        [uv_bin, "sync", "--python", "3.13"], cwd=str(cli_dir), check=True
    )

    # Download LiveKit model files (STT, VAD, etc.)
    click.echo("  Downloading LiveKit model files...")
    subprocess.run(
        [
            uv_bin,
            "run",
            "--python",
            "3.13",
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
    runtime_package = current_runtime_package()
    uv_bin = which("uv")
    if runtime_package is None and not uv_bin:
        click.echo("'uv' not found on PATH, skipping CLI shim install.")
        return

    user_bin = Path.home() / ".local" / "bin"
    user_bin.mkdir(parents=True, exist_ok=True)
    shim_path = user_bin / "openbase-coder"
    if shim_path.is_symlink():
        shim_path.unlink()

    if runtime_package is not None and runtime_package.openbase_coder_path.is_file():
        shim = (
            "#!/bin/sh\n"
            f"export OPENBASE_CODER_PACKAGE_DIR={shlex.quote(str(runtime_package.root))}\n"
            f'exec {shlex.quote(str(runtime_package.openbase_coder_path))} "$@"\n'
        )
    else:
        cli_dir = Path(workspace_dir) / "cli"
        if not cli_dir.is_dir():
            click.echo(
                f"CLI directory not found at {cli_dir}, skipping CLI shim install."
            )
            return
        shim = (
            "#!/bin/sh\n"
            f"cd {shlex.quote(str(cli_dir))} || exit 1\n"
            f'exec {shlex.quote(uv_bin)} run openbase-coder "$@"\n'
        )

    shim_path.write_text(shim)
    shim_path.chmod(0o755)
    click.echo(f"Installed openbase-coder shim at {shim_path}")


def _ensure_env_file(
    env_file: str,
    *,
    assembly_ai_api_key: str,
    cartesia_api_key: str,
    coding_backend: str | None = None,
) -> None:
    path = Path(env_file)
    if coding_backend:
        coding_backend = normalize_backend(coding_backend)
    if path.is_file():
        updates = _missing_livekit_client_credential_values(path)
        if coding_backend:
            updates[CODING_BACKEND_ENV_KEY] = coding_backend
        if updates:
            _upsert_env_file_values(path, updates)
            if coding_backend:
                click.echo(f"Updated {CODING_BACKEND_ENV_KEY} in {path}.")
            if any(key.startswith("LIVEKIT_CLIENT_") for key in updates):
                click.echo(
                    f"Updated client-facing LiveKit token credentials in {path}."
                )
            return
        click.echo(f".env already exists at {path}, leaving unchanged.")
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    secret_key = secrets.token_urlsafe(50)
    livekit_api_key = "APIkey" + secrets.token_urlsafe(12)
    livekit_api_secret = secrets.token_urlsafe(32)
    livekit_client_api_key = "APIkey" + secrets.token_urlsafe(12)
    livekit_client_api_secret = secrets.token_urlsafe(32)

    lines = [
        f"OPENBASE_CODER_CLI_SECRET_KEY={secret_key}",
        "# Local server/admin credentials. Do not return these in client API responses.",
        f"LIVEKIT_API_KEY={livekit_api_key}",
        f"LIVEKIT_API_SECRET={livekit_api_secret}",
        "# Client-facing token issuer. LiveKit JWTs expose this key in the issuer claim.",
        f"LIVEKIT_CLIENT_API_KEY={livekit_client_api_key}",
        f"LIVEKIT_CLIENT_API_SECRET={livekit_client_api_secret}",
        "# Use tailscale for phone-to-computer voice calls; use local for loopback-only testing.",
        "LIVEKIT_NETWORK_MODE=tailscale",
        "LIVEKIT_URL=ws://localhost:7880",
        "# In tailscale mode, the managed service rewrites localhost LIVEKIT_URL to the Tailscale IPv4 address.",
        "# The local Python agent still registers over localhost unless LIVEKIT_AGENT_URL is set.",
        "# LIVEKIT_AGENT_URL=ws://localhost:7880",
        "# Override the Tailscale IP LiveKit advertises in ICE candidates.",
        "# If unset in tailscale mode, the managed service uses the first `tailscale ip -4` value.",
        "# LIVEKIT_NODE_IP=100.x.y.z",
        "# Override the Tailscale interface used for LiveKit media.",
        "# If unset, the managed service derives it from LIVEKIT_NODE_IP.",
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
        "# Coding backend used by Super Agents and the managed service.",
        f"# Set {CODING_BACKEND_ENV_KEY} to codex, openbase_cloud, or claude_code.",
        f"# {LEGACY_CODEX_BACKEND_ENV_KEY} is still read as a fallback for older installs.",
        f"{CODING_BACKEND_ENV_KEY}={coding_backend or DEFAULT_CODING_BACKEND}",
        "# Claude Code applies to Super Agents UI-driver sessions; Codex-compatible backends use codex-app-server.",
        f"CLAUDE_CONFIG_DIR={OPENBASE_CLAUDE_CONFIG_DIR}",
        f"SUPER_AGENTS_DEFAULT_CONFIG_PATH={CODEX_DISPATCHER_CONFIG_PATH}",
        "CODEX_MODEL_REASONING_EFFORT=high",
        "CODEX_SERVICE_TIER=standard",
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


def _selected_coding_backend(env_file: Path, requested_backend: str | None) -> str:
    if requested_backend:
        return normalize_backend(requested_backend)

    values = _env_file_values(env_file)
    raw_value = values.get(CODING_BACKEND_ENV_KEY)
    if raw_value is None:
        raw_value = values.get(LEGACY_CODEX_BACKEND_ENV_KEY)
    try:
        return normalize_backend(raw_value)
    except ValueError:
        return DEFAULT_CODING_BACKEND


def _ensure_openbase_cloud_machine_token(env_file: Path) -> None:
    web_backend_url = _env_file_values(env_file).get(
        "OPENBASE_CODER_CLI_WEB_BACKEND_URL",
        DEFAULT_WEB_BACKEND_URL,
    )
    token_manager = TokenManager(web_backend_url)
    if not token_manager.has_refresh_token:
        click.echo(
            "Openbase Cloud backend selected. Run `openbase-coder login` before "
            "starting services so setup can create the cloud proxy machine token."
        )
        return
    try:
        MachineTokenManager(web_backend_url, token_manager).get_machine_token()
    except AuthLoginRequiredError:
        click.echo(
            "Openbase Cloud backend selected, but your Openbase login needs to be "
            "refreshed. Run `openbase-coder login` before starting services."
        )
    except (AuthTransientError, MachineTokenError) as exc:
        click.echo(
            click.style(
                f"Warning: could not create Openbase Cloud machine token: {exc}",
                fg="yellow",
            )
        )
    else:
        click.echo("Openbase Cloud machine token is configured.")


def _upsert_env_file_values(path: Path, values: dict[str, str]) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    remaining = dict(values)
    updated: list[str] = []
    for line in lines:
        key = _active_env_key(line)
        if key in remaining:
            updated.append(f"{key}={_format_env_value(remaining.pop(key))}")
        else:
            updated.append(line)
    if updated and updated[-1].strip():
        updated.append("")
    for key, value in remaining.items():
        updated.append(f"{key}={_format_env_value(value)}")
    path.write_text("\n".join(updated).rstrip() + "\n", encoding="utf-8")


def _missing_livekit_client_credential_values(path: Path) -> dict[str, str]:
    existing = _env_file_values(path)
    updates: dict[str, str] = {}
    if not existing.get("CLAUDE_CONFIG_DIR"):
        updates["CLAUDE_CONFIG_DIR"] = str(OPENBASE_CLAUDE_CONFIG_DIR)
    if not existing.get("SUPER_AGENTS_DEFAULT_CONFIG_PATH"):
        updates["SUPER_AGENTS_DEFAULT_CONFIG_PATH"] = str(CODEX_DISPATCHER_CONFIG_PATH)
    if not existing.get("LIVEKIT_CLIENT_API_KEY") or existing.get(
        "LIVEKIT_CLIENT_API_KEY"
    ) == existing.get("LIVEKIT_API_KEY"):
        updates["LIVEKIT_CLIENT_API_KEY"] = "APIkey" + secrets.token_urlsafe(12)
    if not existing.get("LIVEKIT_CLIENT_API_SECRET") or existing.get(
        "LIVEKIT_CLIENT_API_SECRET"
    ) == existing.get("LIVEKIT_API_SECRET"):
        updates["LIVEKIT_CLIENT_API_SECRET"] = secrets.token_urlsafe(32)
    return updates


def _env_file_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        key = _active_env_key(line)
        if key is None:
            continue
        _raw_key, raw_value = line.split("=", 1)
        values[key] = _parse_env_value(raw_value.strip())
    return values


def _parse_env_value(value: str) -> str:
    try:
        parts = shlex.split(value, comments=False, posix=True)
    except ValueError:
        return value
    return parts[0] if len(parts) == 1 else value


def _active_env_key(line: str) -> str | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None
    key, _value = stripped.split("=", 1)
    key = key.strip()
    return key if key else None


def _format_env_value(value: str) -> str:
    if (
        not value
        or any(char.isspace() for char in value)
        or any(char in value for char in ['"', "'", "#"])
    ):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return value
