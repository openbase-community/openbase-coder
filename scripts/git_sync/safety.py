"""Safety checks for git-sync workflows."""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys

PROTECTED_BRANCHES = {"main", "master"}

SECRET_PATTERNS = [
    ".env",
    ".env.*",
    "*credentials*",
    "*secret*",
    "*.pem",
    "*.key",
    "id_rsa",
    "id_rsa.*",
    "*.p12",
    "*.pfx",
    "service-account*.json",
]


def matches_secret_pattern(path: str) -> bool:
    basename = path.split("/")[-1]
    for pattern in SECRET_PATTERNS:
        if fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(basename, pattern):
            return True
    return False


def find_secret_paths(paths: list[str]) -> list[str]:
    return sorted(p for p in paths if matches_secret_pattern(p))


def is_protected_branch(branch: str) -> bool:
    return branch in PROTECTED_BRANCHES


def validate_force_push(branch: str, force: bool) -> list[str]:
    errors: list[str] = []
    if force and is_protected_branch(branch):
        errors.append(f"Force push to protected branch '{branch}' is blocked.")
    return errors


def validate_commit_paths(staged: list[str], untracked: list[str], allow_secrets: bool) -> dict:
    secret_staged = find_secret_paths(staged)
    secret_untracked = find_secret_paths(untracked)
    warnings: list[str] = []
    errors: list[str] = []

    if secret_staged and not allow_secrets:
        warnings.append(
            "Staged files match secret-like patterns: " + ", ".join(secret_staged)
        )
    if secret_untracked:
        warnings.append(
            "Untracked files match secret-like patterns (will not commit): "
            + ", ".join(secret_untracked)
        )

    for path in staged:
        if re.search(r"^<<<<<<<|^=======|^>>>>>>>", path):
            errors.append(f"Invalid path: {path}")

    return {
        "warnings": warnings,
        "errors": errors,
        "secret_staged": secret_staged,
        "secret_untracked": secret_untracked,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Safety checks for git-sync")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--staged", nargs="*", default=[])
    parser.add_argument("--untracked", nargs="*", default=[])
    parser.add_argument("--branch", default="")
    parser.add_argument("--force-push", action="store_true")
    parser.add_argument("--allow-secrets", action="store_true")
    args = parser.parse_args()

    result = validate_commit_paths(args.staged, args.untracked, args.allow_secrets)
    result["force_push_errors"] = validate_force_push(args.branch, args.force_push)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for w in result["warnings"]:
            print(f"WARNING: {w}")
        for e in result["errors"] + result["force_push_errors"]:
            print(f"ERROR: {e}")

    has_errors = bool(result["errors"] or result["force_push_errors"])
    return 1 if has_errors else 0


if __name__ == "__main__":
    sys.exit(main())
