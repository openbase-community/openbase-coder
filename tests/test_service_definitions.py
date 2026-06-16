from openbase_coder_cli.services.definitions import SERVICES


def test_livekit_server_service_supports_tailscale_and_local_modes():
    service = next(svc for svc in SERVICES if svc.name == "livekit-server")
    command = service.command_template.format(
        livekit="/usr/local/bin/livekit-server",
        data_dir="/tmp/openbase",
        workspace="/tmp/workspace",
    )

    assert 'LIVEKIT_NETWORK_MODE="${LIVEKIT_NETWORK_MODE:-tailscale}"' in command
    assert 'case "$LIVEKIT_NETWORK_MODE" in' in command
    assert "    local)" in command
    assert "    tailscale)" in command
    assert 'LIVEKIT_TCP_PORT="${LIVEKIT_TCP_PORT:-7881}"' in command
    assert 'LIVEKIT_NODE_IP_V6="$(tailscale ip -6 2>/dev/null | head -n 1)"' in command
    assert "Ignoring invalid Tailscale IPv4 value: $LIVEKIT_NODE_IP" in command
    assert "Ignoring invalid Tailscale IPv6 value: $LIVEKIT_NODE_IP_V6" in command
    assert 'ifconfig 2>/dev/null | awk -v ip="$LIVEKIT_NODE_IP"' in command
    assert 'route -n get "$LIVEKIT_NODE_IP"' in command
    assert "%s\\n      - %s/128\\n" in command
    assert "tcp_port: %s" in command
    assert 'LIVEKIT_BIND_IP="${LIVEKIT_BIND_IP:-127.0.0.1}"' in command
    assert "enable_loopback_candidate: true" in command
    assert 'LIVEKIT_LOOPBACK_IFACE="lo0"' in command
    assert 'LIVEKIT_LOOPBACK_IFACE="lo"' in command
    assert 'ip -o -4 addr show 2>/dev/null | awk -v ip="$LIVEKIT_NODE_IP"' in command
    assert '"$LIVEKIT_LOOPBACK_IFACE"' in command
    assert '--bind "$LIVEKIT_BIND_IP"' in command
    assert service.cleanup_ports == (7880, 7881)


def test_codex_claude_proxy_service_runs_packaged_proxy():
    service = next(svc for svc in SERVICES if svc.name == "codex-claude-proxy")
    command = service.command_template.format(
        data_dir="/tmp/openbase",
        super_agents_claude_proxy="/tmp/workspace/cli/.venv/bin/super-agents-claude-proxy",
        workspace="/tmp/workspace",
    )

    assert (
        'CODEX_CLAUDE_PROXY_COMMAND="${CODEX_CLAUDE_PROXY_COMMAND:-/tmp/workspace/cli/.venv/bin/super-agents-claude-proxy}"'
        in command
    )
    assert 'CODEX_CLAUDE_PROXY_PORT="${CODEX_CLAUDE_PROXY_PORT:-6066}"' in command
    assert 'if [ -x "$CODEX_CLAUDE_PROXY_COMMAND" ]; then' in command
    assert 'elif ! CODEX_CLAUDE_PROXY_RESOLVED="$(command -v "$CODEX_CLAUDE_PROXY_COMMAND")' in command
    assert 'exec "$CODEX_CLAUDE_PROXY_RESOLVED" --port "$CODEX_CLAUDE_PROXY_PORT" --debug' in command
    assert service.port == 6066
    assert service.cleanup_ports == (6066,)
    assert service.cleanup_command_substrings == ("super-agents-claude-proxy",)


def test_codex_app_server_service_sets_model_defaults():
    service = next(svc for svc in SERVICES if svc.name == "codex-app-server")
    command = service.command_template.format(
        codex="/usr/local/bin/codex",
        data_dir="/tmp/openbase",
        super_agents_claude_proxy="/tmp/workspace/cli/.venv/bin/super-agents-claude-proxy",
        workspace="/tmp/workspace",
    )

    assert 'OPENBASE_CODEX_BACKEND="${OPENBASE_CODEX_BACKEND:-codex}"' in command
    assert "claude|claude-code|claude-code-proxy|claude-proxy)" in command
    assert 'CODEX_CLAUDE_MODEL="${CODEX_CLAUDE_MODEL:-claude-code}"' in command
    assert (
        'CODEX_CLAUDE_PROXY_COMMAND="${CODEX_CLAUDE_PROXY_COMMAND:-/tmp/workspace/cli/.venv/bin/super-agents-claude-proxy}"'
        in command
    )
    assert 'if [ -x "$CODEX_CLAUDE_PROXY_COMMAND" ]; then' in command
    assert 'elif ! CODEX_CLAUDE_PROXY_RESOLVED="$(command -v "$CODEX_CLAUDE_PROXY_COMMAND")' in command
    assert 'CODEX_CLAUDE_MODEL_CATALOG_JSON="$("$CODEX_CLAUDE_PROXY_RESOLVED" --print-model-catalog-path)"' in command
    assert '"$CODEX_CLAUDE_PROXY_RESOLVED" --port "$CODEX_CLAUDE_PROXY_PORT" --debug &' not in command
    assert (
        "Claude Code proxy did not become ready at $CODEX_CLAUDE_PROXY_HEALTH_URL"
        in command
    )
    assert "model_providers.claude-code-proxy=" in command
    assert '-c "model_provider=\\"claude-code-proxy\\""' in command
    assert '-c "model=\\"$CODEX_CLAUDE_MODEL\\""' in command
    assert 'CODEX_MODEL="${CODEX_MODEL:-gpt-5.5}"' in command
    assert "claude-tui|claude-code-tui)" in command
    assert "bypasses codex-app-server" in command
    assert (
        'CODEX_MODEL_REASONING_EFFORT="${CODEX_MODEL_REASONING_EFFORT:-high}"'
        in command
    )
    assert 'CODEX_SERVICE_TIER="${CODEX_SERVICE_TIER:-fast}"' in command
    assert '-c "model=\\"$CODEX_MODEL\\""' in command
    assert '-c "model_reasoning_effort=\\"$CODEX_MODEL_REASONING_EFFORT\\""' in command
    assert '-c "service_tier=\\"$CODEX_SERVICE_TIER\\""' in command


def test_livekit_agent_service_does_not_export_dispatcher_instructions_path():
    service = next(svc for svc in SERVICES if svc.name == "livekit-agent")
    command = service.command_template.format(
        data_dir="/tmp/openbase",
        uv="/usr/local/bin/uv",
        workspace="/tmp/workspace",
    )

    assert 'LIVEKIT_NETWORK_MODE="${LIVEKIT_NETWORK_MODE:-tailscale}"' in command
    assert 'export LIVEKIT_URL="${LIVEKIT_AGENT_URL:-ws://localhost:7880}"' in command
    assert 'export LIVEKIT_URL="${LIVEKIT_URL:-ws://localhost:7880}"' in command
    assert "LIVEKIT_DISPATCHER_INSTRUCTIONS_PATH" not in command
    assert (
        "exec /usr/local/bin/uv run python -m openbase_coder_cli.livekit_agent.livekit start"
        in command
    )


def test_django_service_uses_livekit_network_mode_for_room_url():
    service = next(svc for svc in SERVICES if svc.name == "django-cli")
    command = service.command_template.format(
        openbase_coder="/usr/local/bin/openbase-coder",
        data_dir="/tmp/openbase",
        workspace="/tmp/workspace",
    )

    assert 'LIVEKIT_NETWORK_MODE="${LIVEKIT_NETWORK_MODE:-tailscale}"' in command
    assert "Ignoring invalid Tailscale IPv4 value: $LIVEKIT_NODE_IP" in command
    assert (
        "LIVEKIT_NODE_IP is required to derive LIVEKIT_URL in Tailscale mode."
        in command
    )
    assert 'export LIVEKIT_URL="ws://${LIVEKIT_NODE_IP}:7880"' in command
    assert 'export LIVEKIT_URL="${LIVEKIT_URL:-ws://localhost:7880}"' in command


def test_codex_thread_sync_service_is_auto_installed_service():
    service = next(svc for svc in SERVICES if svc.name == "codex-thread-sync")
    command = service.command_template.format(
        openbase_coder="/usr/local/bin/openbase-coder",
        data_dir="/tmp/openbase",
        workspace="/tmp/workspace",
    )

    assert service.workdir_template == "{data_dir}"
    assert 'CODEX_THREAD_SYNC_INTERVAL="${CODEX_THREAD_SYNC_INTERVAL:-60}"' in command
    assert (
        'CODEX_THREAD_SYNC_MAX_AGE_DAYS="${CODEX_THREAD_SYNC_MAX_AGE_DAYS:-15}"'
        in command
    )
    assert (
        'exec /usr/local/bin/openbase-coder codex-sync run --interval "$CODEX_THREAD_SYNC_INTERVAL" --max-age-days "$CODEX_THREAD_SYNC_MAX_AGE_DAYS"'
        in command
    )


def test_codex_thread_device_sync_service_is_auto_installed_service():
    service = next(svc for svc in SERVICES if svc.name == "codex-thread-device-sync")
    command = service.command_template.format(
        openbase_coder="/usr/local/bin/openbase-coder",
        data_dir="/tmp/openbase",
        workspace="/tmp/workspace",
    )

    assert service.workdir_template == "{data_dir}"
    assert (
        'CODEX_THREAD_DEVICE_SYNC_INTERVAL="${CODEX_THREAD_DEVICE_SYNC_INTERVAL:-60}"'
        in command
    )
    assert (
        'CODEX_THREAD_DEVICE_SYNC_MAX_AGE_DAYS="${CODEX_THREAD_DEVICE_SYNC_MAX_AGE_DAYS:-15}"'
        in command
    )
    assert (
        'CODEX_THREAD_DEVICE_SYNC_EXCHANGE_DIR="${CODEX_THREAD_DEVICE_SYNC_EXCHANGE_DIR:-/tmp/openbase/thread-sync}"'
        in command
    )
    assert (
        'exec /usr/local/bin/openbase-coder codex-sync devices run --interval "$CODEX_THREAD_DEVICE_SYNC_INTERVAL" --max-age-days "$CODEX_THREAD_DEVICE_SYNC_MAX_AGE_DAYS" --exchange-dir "$CODEX_THREAD_DEVICE_SYNC_EXCHANGE_DIR"'
        in command
    )


def test_openbase_routines_service_is_auto_installed_service():
    service = next(svc for svc in SERVICES if svc.name == "openbase-routines")
    command = service.command_template.format(
        openbase_coder="/usr/local/bin/openbase-coder",
        data_dir="/tmp/openbase",
        workspace="/tmp/workspace",
    )

    assert service.workdir_template == "{data_dir}"
    assert (
        'OPENBASE_CODER_ROUTINES_INTERVAL="${OPENBASE_CODER_ROUTINES_INTERVAL:-60}"'
        in command
    )
    assert (
        'exec /usr/local/bin/openbase-coder routines run-loop --interval "$OPENBASE_CODER_ROUTINES_INTERVAL"'
        in command
    )
