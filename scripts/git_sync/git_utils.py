"""Shared git/gh subprocess helpers."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


class GitError(RuntimeError):
    pass


def repo_root() -> Path:
    return Path(run_git("rev-parse", "--show-toplevel").strip())


def run_git(*args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        raise GitError(result.stderr.strip() or result.stdout.strip() or "git failed")
    return result.stdout


def run_git_ok(*args: str) -> tuple[bool, str]:
    result = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
    )
    output = (result.stdout or result.stderr).strip()
    return result.returncode == 0, output


def rev_parse(ref: str) -> str | None:
    ok, out = run_git_ok("rev-parse", "--verify", ref)
    return out if ok else None


def ahead_behind(local_ref: str, upstream_ref: str) -> tuple[int, int]:
    ok, out = run_git_ok("rev-list", "--left-right", "--count", f"{upstream_ref}...{local_ref}")
    if not ok:
        return 0, 0
    parts = out.split()
    if len(parts) != 2:
        return 0, 0
    behind, ahead = int(parts[0]), int(parts[1])
    return ahead, behind


def changed_files_between(base: str, tip: str) -> set[str]:
    ok, out = run_git_ok("diff", "--name-only", f"{base}..{tip}")
    if not ok:
        return set()
    return {line.strip() for line in out.splitlines() if line.strip()}


def merge_base(a: str, b: str) -> str | None:
    ok, out = run_git_ok("merge-base", a, b)
    return out if ok else None


def tracking_branch() -> str | None:
    ok, out = run_git_ok("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    return out if ok else None


def branch_pushed_to_origin(branch: str) -> bool:
    ok, _ = run_git_ok("rev-parse", "--verify", f"origin/{branch}")
    return ok


def run_gh(*args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        raise GitError(result.stderr.strip() or result.stdout.strip() or "gh failed")
    return result.stdout


def gh_json(*args: str) -> dict:
    out = run_gh(*args, "--json", "parent,defaultBranchRef,nameWithOwner")
    data = json.loads(out)
    if isinstance(data, list):
        return data[0] if data else {}
    return data
