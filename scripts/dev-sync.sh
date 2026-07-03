#!/usr/bin/env bash
# Bootstrap local dev: ensure super-agents sibling exists, sync deps with Python 3.13.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SUPER_AGENTS_DIR="$(dirname "$ROOT")/super-agents"
SUPER_AGENTS_REPO="https://github.com/montaguegabe/super-agents.git"
PYTHON_VERSION="3.13"

cd "$ROOT"

if [[ ! -f "$SUPER_AGENTS_DIR/pyproject.toml" ]]; then
  echo "Cloning super-agents into $SUPER_AGENTS_DIR ..."
  git clone "$SUPER_AGENTS_REPO" "$SUPER_AGENTS_DIR"
fi

echo "Syncing openbase-coder with Python $PYTHON_VERSION ..."
uv sync --extra dev --python "$PYTHON_VERSION"

echo "Done. Try: uv run pytest -q"
