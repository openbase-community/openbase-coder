#!/bin/bash
# SessionStart hook for the Openbase-managed Codex and Claude Code homes.
# Reads the session_id from the hook's stdin JSON and injects it into the
# conversation as additionalContext, so the agent knows its own thread/session
# ID and can stamp commits with the Agent-Thread-Id trailer.

set -euo pipefail

INPUT=$(cat)

if command -v jq >/dev/null 2>&1; then
    SESSION_ID=$(printf '%s' "$INPUT" | jq -r '.session_id // empty' 2>/dev/null || true)
elif command -v python3 >/dev/null 2>&1; then
    SESSION_ID=$(printf '%s' "$INPUT" | python3 -c '
import json, sys
try:
    value = json.load(sys.stdin).get("session_id")
except Exception:
    value = None
print(value if isinstance(value, str) else "")
' 2>/dev/null || true)
else
    exit 0
fi

if [ -z "$SESSION_ID" ]; then
    exit 0
fi

CONTEXT="Current agent thread/session ID: ${SESSION_ID}. Use this as the Agent-Thread-Id git commit trailer value when committing."

printf '{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"%s"}}\n' "$CONTEXT"
