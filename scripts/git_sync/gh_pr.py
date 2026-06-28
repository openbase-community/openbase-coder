"""GitHub PR helpers: detect fork parent, create/watch/merge PRs."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys


def _run_gh(*args: str, check: bool = True) -> str:
    result = subprocess.run(["gh", *args], capture_output=True, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "gh failed")
    return result.stdout


def _run_git(*args: str) -> str:
    result = subprocess.run(["git", *args], capture_output=True, text=True)
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _upstream_remote_url() -> str | None:
    out = _run_git("remote", "get-url", "upstream")
    return out or None


def _parse_github_slug(url: str) -> str | None:
    # git@github.com:owner/repo.git or https://github.com/owner/repo
    patterns = [
        r"github\.com[:/]([^/]+)/([^/.]+)",
    ]
    for pat in patterns:
        m = re.search(pat, url)
        if m:
            return f"{m.group(1)}/{m.group(2)}"
    return None


def detect_pr_target(base_branch: str = "main") -> dict:
    origin_url = _run_git("remote", "get-url", "origin")
    fork_slug = _parse_github_slug(origin_url) if origin_url else None
    if not fork_slug:
        fork_slug = _run_gh("repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner").strip()

    parent_slug = None
    parent_default_branch = base_branch
    try:
        parent_raw = _run_gh(
            "repo",
            "view",
            "--json",
            "parent",
            "-q",
            ".parent.nameWithOwner",
        ).strip()
        if parent_raw and parent_raw != "null":
            parent_slug = parent_raw
            parent_default_branch = _run_gh(
                "repo",
                "view",
                parent_slug,
                "--json",
                "defaultBranchRef",
                "-q",
                ".defaultBranchRef.name",
            ).strip() or base_branch
    except RuntimeError:
        pass

    if not parent_slug:
        upstream_url = _upstream_remote_url()
        if upstream_url:
            parent_slug = _parse_github_slug(upstream_url)

    head_branch = _run_git("rev-parse", "--abbrev-ref", "HEAD")
    head = f"{fork_slug}:{head_branch}" if fork_slug and head_branch else head_branch

    return {
        "fork": fork_slug,
        "parent": parent_slug,
        "base_branch": parent_default_branch or base_branch,
        "head_branch": head_branch,
        "head": head,
    }


def _commit_subjects(since_ref: str | None = None) -> list[str]:
    args = ["log", "--format=%s", "-n", "10"]
    if since_ref:
        args.append(f"{since_ref}..HEAD")
    out = _run_git(*args)
    return [line.strip() for line in out.splitlines() if line.strip()]


def build_pr_body(title: str, base_branch: str) -> str:
    subjects = _commit_subjects(f"upstream/{base_branch}")
    if not subjects:
        subjects = _commit_subjects(f"origin/{base_branch}")
    if not subjects:
        subjects = _commit_subjects()

    summary = "\n".join(f"- {s}" for s in subjects[:5]) or f"- {title}"
    return f"""## Summary
{summary}

## Test plan
- [ ] `./scripts/git-sync.sh --dry-run` passes locally
- [ ] Relevant tests pass (`uv run pytest -q` if applicable)
- [ ] Manual smoke test of changed behavior
"""


def create_pr(title: str, body: str, base_branch: str, draft: bool = False) -> dict:
    target = detect_pr_target(base_branch)
    if not target["parent"]:
        raise RuntimeError("Could not detect PR base repo (no gh parent or upstream remote)")

    args = [
        "pr",
        "create",
        "--repo",
        target["parent"],
        "--base",
        target["base_branch"],
        "--head",
        target["head"],
        "--title",
        title,
        "--body",
        body,
    ]
    if draft:
        args.append("--draft")

    url = _run_gh(*args).strip()
    number_match = re.search(r"/pull/(\d+)", url)
    return {
        "url": url,
        "number": int(number_match.group(1)) if number_match else None,
        "target": target,
    }


def watch_checks(pr_number: int, repo: str) -> None:
    _run_gh("pr", "checks", str(pr_number), "--repo", repo, "--watch")


def merge_pr(pr_number: int, repo: str, strategy: str = "merge") -> str:
    args = ["pr", "merge", str(pr_number), "--repo", repo]
    if strategy == "squash":
        args.append("--squash")
    elif strategy == "rebase":
        args.append("--rebase")
    else:
        args.append("--merge")
    return _run_gh(*args).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="GitHub PR helpers for git-sync")
    sub = parser.add_subparsers(dest="command", required=True)

    detect_p = sub.add_parser("detect-target")
    detect_p.add_argument("--base-branch", default="main")
    detect_p.add_argument("--json", action="store_true")

    create_p = sub.add_parser("create")
    create_p.add_argument("--title", required=True)
    create_p.add_argument("--base-branch", default="main")
    create_p.add_argument("--body", default="")
    create_p.add_argument("--draft", action="store_true")
    create_p.add_argument("--json", action="store_true")

    watch_p = sub.add_parser("watch")
    watch_p.add_argument("--number", type=int, required=True)
    watch_p.add_argument("--repo", required=True)

    merge_p = sub.add_parser("merge")
    merge_p.add_argument("--number", type=int, required=True)
    merge_p.add_argument("--repo", required=True)
    merge_p.add_argument("--strategy", choices=["merge", "squash", "rebase"], default="merge")
    merge_p.add_argument("--json", action="store_true")

    args = parser.parse_args()

    try:
        if args.command == "detect-target":
            result = detect_pr_target(args.base_branch)
            if args.json:
                print(json.dumps(result, indent=2))
            else:
                print(json.dumps(result, indent=2))
        elif args.command == "create":
            body = args.body or build_pr_body(args.title, args.base_branch)
            result = create_pr(args.title, body, args.base_branch, draft=args.draft)
            if args.json:
                print(json.dumps(result, indent=2))
            else:
                print(result["url"])
        elif args.command == "watch":
            watch_checks(args.number, args.repo)
        elif args.command == "merge":
            url = merge_pr(args.number, args.repo, args.strategy)
            result = {"merged": url}
            if args.json:
                print(json.dumps(result, indent=2))
            else:
                print(url)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
