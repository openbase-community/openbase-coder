from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ServiceDefinition:
    name: str
    description: str
    command_template: str
    workdir_template: str
    port: int | None = None
    cleanup_ports: tuple[int, ...] = ()
    cleanup_command_substrings: tuple[str, ...] = ()


SERVICES: list[ServiceDefinition] = [
    ServiceDefinition(
        name="livekit-server",
        description="LiveKit Server",
        command_template=(
            'LIVEKIT_NETWORK_MODE="${{LIVEKIT_NETWORK_MODE:-tailscale}}"\n'
            'LIVEKIT_TCP_PORT="${{LIVEKIT_TCP_PORT:-7881}}"\n'
            'LIVEKIT_UDP_PORT="${{LIVEKIT_UDP_PORT:-7882}}"\n'
            'LIVEKIT_LOOPBACK_IFACE="lo0"\n'
            'if [ "$(uname)" != "Darwin" ]; then\n'
            '    LIVEKIT_LOOPBACK_IFACE="lo"\n'
            "fi\n"
            'case "$LIVEKIT_NETWORK_MODE" in\n'
            "    local)\n"
            '        LIVEKIT_BIND_IP="${{LIVEKIT_BIND_IP:-127.0.0.1}}"\n'
            '        NODE_IP_ARGS=(--node-ip "$LIVEKIT_BIND_IP")\n'
            '        LIVEKIT_CONFIG_BODY="$(printf \'rtc:\\n  tcp_port: %s\\n  udp_port: %s\\n  enable_loopback_candidate: true\\n  interfaces:\\n    includes:\\n      - %s\\n  ips:\\n    includes:\\n      - 127.0.0.1/32\\n\' "$LIVEKIT_TCP_PORT" "$LIVEKIT_UDP_PORT" "$LIVEKIT_LOOPBACK_IFACE")"\n'
            "        ;;\n"
            "    tailscale)\n"
            '        if [ -z "${{LIVEKIT_NODE_IP:-}}" ] && command -v tailscale >/dev/null 2>&1; then\n'
            '            LIVEKIT_NODE_IP="$(tailscale ip -4 2>/dev/null | head -n 1)"\n'
            "        fi\n"
            '        if [ -z "${{LIVEKIT_NODE_IP_V6:-}}" ] && command -v tailscale >/dev/null 2>&1; then\n'
            '            LIVEKIT_NODE_IP_V6="$(tailscale ip -6 2>/dev/null | head -n 1)"\n'
            "        fi\n"
            '        if [ -n "${{LIVEKIT_NODE_IP:-}}" ] && ! [[ "$LIVEKIT_NODE_IP" =~ ^([0-9]{{1,3}}\\.){{3}}[0-9]{{1,3}}$ ]]; then\n'
            '            echo "Ignoring invalid Tailscale IPv4 value: $LIVEKIT_NODE_IP" >&2\n'
            "            LIVEKIT_NODE_IP=\n"
            "        fi\n"
            '        if [ -n "${{LIVEKIT_NODE_IP_V6:-}}" ] && ! [[ "$LIVEKIT_NODE_IP_V6" =~ ^[0-9A-Fa-f:]+$ ]]; then\n'
            '            echo "Ignoring invalid Tailscale IPv6 value: $LIVEKIT_NODE_IP_V6" >&2\n'
            "            LIVEKIT_NODE_IP_V6=\n"
            "        fi\n"
            '        if [ -z "${{LIVEKIT_NODE_IP:-}}" ]; then\n'
            '            echo "LIVEKIT_NODE_IP is required for Tailscale LiveKit signaling and media." >&2\n'
            "            exit 1\n"
            "        fi\n"
            '        if [ "$(uname)" = "Darwin" ]; then\n'
            '            if [ -z "${{LIVEKIT_INTERFACE:-}}" ]; then\n'
            '                LIVEKIT_INTERFACE="$(ifconfig 2>/dev/null | awk -v ip="$LIVEKIT_NODE_IP" \'BEGIN {{ iface = "" }} /^[a-z0-9]+:/ {{ iface = substr($1, 1, length($1) - 1) }} index($0, "inet " ip " ") {{ print iface; exit }}\')"\n'
            "            fi\n"
            '            if [ -z "$LIVEKIT_INTERFACE" ]; then\n'
            '                LIVEKIT_INTERFACE="$(route -n get "$LIVEKIT_NODE_IP" 2>/dev/null | sed -n \'s/.*interface: //p\' | head -n 1)"\n'
            "            fi\n"
            "        else\n"
            '            if [ -z "${{LIVEKIT_INTERFACE:-}}" ]; then\n'
            '                LIVEKIT_INTERFACE="$(ip -o -4 addr show 2>/dev/null | awk -v ip="$LIVEKIT_NODE_IP" \'index($4, ip "/") == 1 {{ print $2; exit }}\')"\n'
            "            fi\n"
            '            if [ -z "$LIVEKIT_INTERFACE" ]; then\n'
            '                LIVEKIT_INTERFACE="$(ip -4 route get "$LIVEKIT_NODE_IP" 2>/dev/null | sed -n \'s/.* dev \\([^ ]*\\).*/\\1/p\' | head -n 1)"\n'
            "            fi\n"
            "        fi\n"
            '        if [ -z "$LIVEKIT_INTERFACE" ]; then\n'
            '            echo "LIVEKIT_INTERFACE is required for Tailscale LiveKit media." >&2\n'
            "            exit 1\n"
            "        fi\n"
            '        LIVEKIT_BIND_IP="${{LIVEKIT_BIND_IP:-127.0.0.1}}"\n'
            '        NODE_IP_ARGS=(--node-ip "$LIVEKIT_NODE_IP")\n'
            '        LIVEKIT_CONFIG_BODY="$(printf \'rtc:\\n  tcp_port: %s\\n  udp_port: %s\\n  enable_loopback_candidate: true\\n  interfaces:\\n    includes:\\n      - %s\\n      - %s\\n  ips:\\n    includes:\\n      - 127.0.0.1/32\\n      - %s/32\\n\' "$LIVEKIT_TCP_PORT" "$LIVEKIT_UDP_PORT" "$LIVEKIT_LOOPBACK_IFACE" "$LIVEKIT_INTERFACE" "$LIVEKIT_NODE_IP")"\n'
            '        if [ -n "${{LIVEKIT_NODE_IP_V6:-}}" ]; then\n'
            '            LIVEKIT_CONFIG_BODY="$(printf \'%s\\n      - %s/128\\n\' "$LIVEKIT_CONFIG_BODY" "$LIVEKIT_NODE_IP_V6")"\n'
            "        fi\n"
            "        ;;\n"
            "    *)\n"
            '        echo "Unsupported LIVEKIT_NETWORK_MODE: $LIVEKIT_NETWORK_MODE" >&2\n'
            "        exit 1\n"
            "        ;;\n"
            "esac\n"
            'exec {livekit} --dev --bind "$LIVEKIT_BIND_IP" --config-body "$LIVEKIT_CONFIG_BODY" "${{NODE_IP_ARGS[@]}}" --keys "$LIVEKIT_API_KEY: $LIVEKIT_API_SECRET"'
        ),
        workdir_template="{workspace}",
        port=7880,
        cleanup_ports=(7880, 7881),
        cleanup_command_substrings=("livekit-server",),
    ),
    ServiceDefinition(
        name="codex-claude-proxy",
        description="Codex Claude Proxy",
        command_template=(
            'CODEX_CLAUDE_PROXY_COMMAND="${{CODEX_CLAUDE_PROXY_COMMAND:-{super_agents_claude_proxy}}}"\n'
            'CODEX_CLAUDE_PROXY_PORT="${{CODEX_CLAUDE_PROXY_PORT:-6066}}"\n'
            'if [ -x "$CODEX_CLAUDE_PROXY_COMMAND" ]; then\n'
            '    CODEX_CLAUDE_PROXY_RESOLVED="$CODEX_CLAUDE_PROXY_COMMAND"\n'
            'elif ! CODEX_CLAUDE_PROXY_RESOLVED="$(command -v "$CODEX_CLAUDE_PROXY_COMMAND")"; then\n'
            '    echo "Claude Code proxy command not found on PATH: $CODEX_CLAUDE_PROXY_COMMAND" >&2\n'
            "    exit 1\n"
            "fi\n"
            'exec "$CODEX_CLAUDE_PROXY_RESOLVED" --port "$CODEX_CLAUDE_PROXY_PORT" --debug'
        ),
        workdir_template="{workspace}",
        port=6066,
        cleanup_ports=(6066,),
        cleanup_command_substrings=("super-agents-claude-proxy",),
    ),
    ServiceDefinition(
        name="codex-app-server",
        description="Codex App Server",
        command_template=(
            'export CODEX_HOME="{data_dir}/codex_home"\n'
            'mkdir -p "$CODEX_HOME"\n'
            'CODEX_MODEL_REASONING_EFFORT="${{CODEX_MODEL_REASONING_EFFORT:-high}}"\n'
            'CODEX_SERVICE_TIER="${{CODEX_SERVICE_TIER:-fast}}"\n'
            'OPENBASE_CODEX_BACKEND="${{OPENBASE_CODEX_BACKEND:-codex}}"\n'
            'case "$OPENBASE_CODEX_BACKEND" in\n'
            "    claude|claude-code|claude-code-proxy|claude-proxy)\n"
            '        CODEX_CLAUDE_MODEL="${{CODEX_CLAUDE_MODEL:-claude-code}}"\n'
            '        CODEX_CLAUDE_PROXY_PORT="${{CODEX_CLAUDE_PROXY_PORT:-6066}}"\n'
            '        CODEX_CLAUDE_PROXY_BASE_URL="${{CODEX_CLAUDE_PROXY_BASE_URL:-http://127.0.0.1:$CODEX_CLAUDE_PROXY_PORT/v1}}"\n'
            '        CODEX_CLAUDE_PROXY_HEALTH_URL="${{CODEX_CLAUDE_PROXY_HEALTH_URL:-http://127.0.0.1:$CODEX_CLAUDE_PROXY_PORT/health}}"\n'
            '        CODEX_CLAUDE_PROXY_COMMAND="${{CODEX_CLAUDE_PROXY_COMMAND:-{super_agents_claude_proxy}}}"\n'
            '        if [ -x "$CODEX_CLAUDE_PROXY_COMMAND" ]; then\n'
            '            CODEX_CLAUDE_PROXY_RESOLVED="$CODEX_CLAUDE_PROXY_COMMAND"\n'
            '        elif ! CODEX_CLAUDE_PROXY_RESOLVED="$(command -v "$CODEX_CLAUDE_PROXY_COMMAND")"; then\n'
            '            echo "Claude Code proxy command not found on PATH: $CODEX_CLAUDE_PROXY_COMMAND" >&2\n'
            "            exit 1\n"
            "        fi\n"
            '        if [ -z "${{CODEX_CLAUDE_MODEL_CATALOG_JSON:-}}" ]; then\n'
            '            CODEX_CLAUDE_MODEL_CATALOG_JSON="$("$CODEX_CLAUDE_PROXY_RESOLVED" --print-model-catalog-path)"\n'
            "        fi\n"
            '        CODEX_MODEL_REASONING_SUMMARY="${{CODEX_MODEL_REASONING_SUMMARY:-concise}}"\n'
            '        CODEX_WEB_SEARCH="${{CODEX_WEB_SEARCH:-live}}"\n'
            '        if [ ! -f "$CODEX_CLAUDE_MODEL_CATALOG_JSON" ]; then\n'
            '            echo "Claude Code model catalog not found at $CODEX_CLAUDE_MODEL_CATALOG_JSON" >&2\n'
            "            exit 1\n"
            "        fi\n"
            "        for _openbase_codex_proxy_wait in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do\n"
            '            if curl -fsS "$CODEX_CLAUDE_PROXY_HEALTH_URL" >/dev/null 2>&1; then\n'
            "                break\n"
            "            fi\n"
            "            sleep 0.25\n"
            "        done\n"
            '        if ! curl -fsS "$CODEX_CLAUDE_PROXY_HEALTH_URL" >/dev/null 2>&1; then\n'
            '            echo "Claude Code proxy did not become ready at $CODEX_CLAUDE_PROXY_HEALTH_URL" >&2\n'
            "            exit 1\n"
            "        fi\n"
            "        {codex} app-server "
            "-c \"model_providers.claude-code-proxy={{ name = 'Claude Proxy', base_url = '$CODEX_CLAUDE_PROXY_BASE_URL', wire_api = 'responses', requires_openai_auth = false }}\" "
            '-c "model_provider=\\"claude-code-proxy\\"" '
            '-c "model=\\"$CODEX_CLAUDE_MODEL\\"" '
            '-c "model_catalog_json=\\"$CODEX_CLAUDE_MODEL_CATALOG_JSON\\"" '
            '-c "model_reasoning_summary=\\"$CODEX_MODEL_REASONING_SUMMARY\\"" '
            '-c "web_search=\\"$CODEX_WEB_SEARCH\\"" '
            "--listen ws://127.0.0.1:4500\n"
            "        ;;\n"
            "    claude-tui|claude-code-tui)\n"
            '        echo "OPENBASE_CODEX_BACKEND=$OPENBASE_CODEX_BACKEND bypasses codex-app-server; Super Agents uses the Claude TUI backend directly."\n'
            "        exec sleep 86400\n"
            "        ;;\n"
            '    codex|openai|"")\n'
            '        CODEX_MODEL="${{CODEX_MODEL:-gpt-5.5}}"\n'
            "        exec {codex} app-server "
            '-c "model=\\"$CODEX_MODEL\\"" '
            '-c "model_reasoning_effort=\\"$CODEX_MODEL_REASONING_EFFORT\\"" '
            '-c "service_tier=\\"$CODEX_SERVICE_TIER\\"" '
            "--listen ws://127.0.0.1:4500\n"
            "        ;;\n"
            "    *)\n"
            '        echo "Unsupported OPENBASE_CODEX_BACKEND: $OPENBASE_CODEX_BACKEND" >&2\n'
            "        exit 1\n"
            "        ;;\n"
            "esac"
        ),
        workdir_template="{workspace}",
        port=4500,
    ),
    ServiceDefinition(
        name="codex-thread-sync",
        description="Codex Thread Sync",
        command_template=(
            'CODEX_THREAD_SYNC_INTERVAL="${{CODEX_THREAD_SYNC_INTERVAL:-60}}"\n'
            'CODEX_THREAD_SYNC_MAX_AGE_DAYS="${{CODEX_THREAD_SYNC_MAX_AGE_DAYS:-15}}"\n'
            'exec {openbase_coder} codex-sync run --interval "$CODEX_THREAD_SYNC_INTERVAL" --max-age-days "$CODEX_THREAD_SYNC_MAX_AGE_DAYS"'
        ),
        workdir_template="{data_dir}",
    ),
    ServiceDefinition(
        name="codex-thread-device-sync",
        description="Codex Thread Device Sync",
        command_template=(
            'CODEX_THREAD_DEVICE_SYNC_INTERVAL="${{CODEX_THREAD_DEVICE_SYNC_INTERVAL:-60}}"\n'
            'CODEX_THREAD_DEVICE_SYNC_MAX_AGE_DAYS="${{CODEX_THREAD_DEVICE_SYNC_MAX_AGE_DAYS:-15}}"\n'
            'CODEX_THREAD_DEVICE_SYNC_EXCHANGE_DIR="${{CODEX_THREAD_DEVICE_SYNC_EXCHANGE_DIR:-{data_dir}/thread-sync}}"\n'
            'exec {openbase_coder} codex-sync devices run --interval "$CODEX_THREAD_DEVICE_SYNC_INTERVAL" --max-age-days "$CODEX_THREAD_DEVICE_SYNC_MAX_AGE_DAYS" --exchange-dir "$CODEX_THREAD_DEVICE_SYNC_EXCHANGE_DIR"'
        ),
        workdir_template="{data_dir}",
    ),
    ServiceDefinition(
        name="openbase-routines",
        description="Openbase Routines",
        command_template=(
            'OPENBASE_CODER_ROUTINES_INTERVAL="${{OPENBASE_CODER_ROUTINES_INTERVAL:-60}}"\n'
            'exec {openbase_coder} routines run-loop --interval "$OPENBASE_CODER_ROUTINES_INTERVAL"'
        ),
        workdir_template="{data_dir}",
    ),
    ServiceDefinition(
        name="livekit-agent",
        description="LiveKit Agent Worker",
        command_template=(
            'LIVEKIT_NETWORK_MODE="${{LIVEKIT_NETWORK_MODE:-tailscale}}"\n'
            'if [ -z "${{LIVEKIT_NODE_IP:-}}" ] && command -v tailscale >/dev/null 2>&1; then\n'
            '    LIVEKIT_NODE_IP="$(tailscale ip -4 2>/dev/null | head -n 1)"\n'
            "fi\n"
            'if [ "$LIVEKIT_NETWORK_MODE" = "tailscale" ]; then\n'
            '    export LIVEKIT_URL="${{LIVEKIT_AGENT_URL:-ws://localhost:7880}}"\n'
            'elif [ "$LIVEKIT_NETWORK_MODE" = "local" ]; then\n'
            '    export LIVEKIT_URL="${{LIVEKIT_URL:-ws://localhost:7880}}"\n'
            "else\n"
            '    echo "Unsupported LIVEKIT_NETWORK_MODE: $LIVEKIT_NETWORK_MODE" >&2\n'
            "    exit 1\n"
            "fi\n"
            "exec {uv} run python -m openbase_coder_cli.livekit_agent.livekit start"
        ),
        workdir_template="{workspace}/cli",
        cleanup_ports=(8081,),
        cleanup_command_substrings=("openbase_coder_cli.livekit_agent.livekit",),
    ),
    ServiceDefinition(
        name="django-cli",
        description="Django CLI Server",
        command_template=(
            'LIVEKIT_NETWORK_MODE="${{LIVEKIT_NETWORK_MODE:-tailscale}}"\n'
            'if [ -z "${{LIVEKIT_NODE_IP:-}}" ] && command -v tailscale >/dev/null 2>&1; then\n'
            '    LIVEKIT_NODE_IP="$(tailscale ip -4 2>/dev/null | head -n 1)"\n'
            "fi\n"
            'if [ -n "${{LIVEKIT_NODE_IP:-}}" ] && ! [[ "$LIVEKIT_NODE_IP" =~ ^([0-9]{{1,3}}\\.){{3}}[0-9]{{1,3}}$ ]]; then\n'
            '    echo "Ignoring invalid Tailscale IPv4 value: $LIVEKIT_NODE_IP" >&2\n'
            "    LIVEKIT_NODE_IP=\n"
            "fi\n"
            'if [ "$LIVEKIT_NETWORK_MODE" = "tailscale" ]; then\n'
            '    case "${{LIVEKIT_URL:-}}" in\n'
            '        ""|ws://localhost:*|ws://127.0.0.1:*|http://localhost:*|http://127.0.0.1:*)\n'
            '            if [ -z "${{LIVEKIT_NODE_IP:-}}" ]; then\n'
            '                echo "LIVEKIT_NODE_IP is required to derive LIVEKIT_URL in Tailscale mode." >&2\n'
            "                exit 1\n"
            "            fi\n"
            '            export LIVEKIT_URL="ws://${{LIVEKIT_NODE_IP}}:7880"\n'
            "            ;;\n"
            "    esac\n"
            'elif [ "$LIVEKIT_NETWORK_MODE" = "local" ]; then\n'
            '    export LIVEKIT_URL="${{LIVEKIT_URL:-ws://localhost:7880}}"\n'
            "else\n"
            '    echo "Unsupported LIVEKIT_NETWORK_MODE: $LIVEKIT_NETWORK_MODE" >&2\n'
            "    exit 1\n"
            "fi\n"
            'OPENBASE_CODER_CLI_HOST="${{OPENBASE_CODER_CLI_HOST:-127.0.0.1}}"\n'
            'exec {openbase_coder} server --host "$OPENBASE_CODER_CLI_HOST" --port 7999'
        ),
        workdir_template="{data_dir}",
        port=7999,
    ),
]
