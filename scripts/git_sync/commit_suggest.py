"""Suggest conventional commit messages from staged diff."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter


DOC_EXTENSIONS = {".md", ".rst", ".txt"}
TEST_HINTS = ("test", "tests", "spec", "conftest")


def _run_git(*args: str) -> str:
    result = subprocess.run(["git", *args], capture_output=True, text=True)
    if result.returncode != 0:
        return ""
    return result.stdout


def staged_files() -> list[str]:
    out = _run_git("diff", "--cached", "--name-only")
    return [line.strip() for line in out.splitlines() if line.strip()]


def staged_stat() -> str:
    return _run_git("diff", "--cached", "--stat")


def _primary_type(files: list[str]) -> str:
    if not files:
        return "chore"
    if all(f.endswith(tuple(DOC_EXTENSIONS)) or f.startswith("docs/") for f in files):
        return "docs"
    if any("test" in f.lower() or f.startswith(TEST_HINTS) for f in files):
        return "test"
    if any(f.endswith(".py") for f in files):
        return "fix" if any(k in " ".join(files).lower() for k in ("fix", "bug", "error")) else "feat"
    if any(f.endswith((".sh", ".yml", ".yaml")) or f.startswith(".github/") for f in files):
        return "ci" if ".github" in " ".join(files) else "chore"
    return "chore"


def _scope(files: list[str]) -> str | None:
    top_levels = Counter()
    for f in files:
        parts = f.split("/")
        if len(parts) > 1:
            top_levels[parts[0]] += 1
        else:
            top_levels["root"] += 1
    if not top_levels:
        return None
    scope, _ = top_levels.most_common(1)[0]
    if scope == "root":
        return None
    if scope == "openbase_coder_cli":
        return "cli"
    if scope == "docs":
        return "docs"
    if scope == "scripts":
        return "scripts"
    return scope


def _subject(files: list[str]) -> str:
    if len(files) == 1:
        name = files[0].split("/")[-1]
        stem = re.sub(r"\.[^.]+$", "", name)
        return f"update {stem.replace('_', ' ').replace('-', ' ')}"
    names = [f.split("/")[-1] for f in files[:3]]
    summary = ", ".join(names)
    if len(files) > 3:
        summary += f" and {len(files) - 3} more"
    return f"update {summary}"


def suggest_message(files: list[str] | None = None) -> dict:
    files = files or staged_files()
    commit_type = _primary_type(files)
    scope = _scope(files)
    subject = _subject(files)

    prefix = f"{commit_type}({scope})" if scope else commit_type
    message = f"{prefix}: {subject}"

    body_lines = [f"- {f}" for f in files[:8]]
    if len(files) > 8:
        body_lines.append(f"- ... and {len(files) - 8} more file(s)")

    return {
        "message": message,
        "subject": subject,
        "type": commit_type,
        "scope": scope,
        "files": files,
        "stat": staged_stat().strip(),
        "body_lines": body_lines,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Suggest commit message from staged diff")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    suggestion = suggest_message()
    if not suggestion["files"]:
        print("No staged changes.", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(suggestion, indent=2))
    else:
        print(suggestion["message"])
        if suggestion["body_lines"]:
            print()
            print("\n".join(suggestion["body_lines"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
