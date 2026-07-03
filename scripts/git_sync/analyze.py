"""Branch and working-tree diagnosis for git-sync."""

from __future__ import annotations

import argparse
import json
import sys

from git_utils import (
    ahead_behind,
    changed_files_between,
    merge_base,
    rev_parse,
    run_git,
    run_git_ok,
    tracking_branch,
    branch_pushed_to_origin,
)
from conflicts import predict_conflicts


def _parse_porcelain_v2() -> dict:
    staged: list[str] = []
    unstaged: list[str] = []
    untracked: list[str] = []

    for line in run_git("status", "--porcelain=v2", "-b").splitlines():
        if line.startswith("? "):
            untracked.append(line[2:])
            continue
        if line.startswith("1 ") or line.startswith("2 "):
            parts = line.split()
            xy = parts[1]
            path = parts[-1]
            index_status, worktree_status = xy[0], xy[1]
            if index_status not in (".", "?"):
                staged.append(path)
            if worktree_status not in (".", "?"):
                unstaged.append(path)
        elif line.startswith("u "):
            parts = line.split()
            staged.append(parts[-1])
            unstaged.append(parts[-1])

    staged = sorted(set(staged))
    unstaged = sorted(set(unstaged))
    untracked = sorted(set(untracked))
    return {
        "staged": staged,
        "unstaged": unstaged,
        "untracked": untracked,
    }


def _dirty_level(staged: list[str], unstaged: list[str], untracked: list[str]) -> str:
    has_staged = bool(staged)
    has_unstaged = bool(unstaged)
    has_untracked = bool(untracked)
    if not has_staged and not has_unstaged and not has_untracked:
        return "clean"
    if has_staged and not has_unstaged and not has_untracked:
        return "staged"
    if not has_staged and (has_unstaged or has_untracked):
        return "unstaged"
    return "mixed"


def _local_changed_files(staged: list[str], unstaged: list[str]) -> set[str]:
    return set(staged) | set(unstaged)


def _remote_exists(name: str) -> bool:
    ok, _ = run_git_ok("remote", "get-url", name)
    return ok


def _ref_exists(ref: str) -> bool:
    return rev_parse(ref) is not None


def _overlap(local_files: set[str], base: str, tip: str) -> list[str]:
    if not local_files or not _ref_exists(base) or not _ref_exists(tip):
        return []
    mb = merge_base(base, tip)
    if not mb:
        return []
    incoming = changed_files_between(mb, tip)
    return sorted(local_files & incoming)


def analyze(base_branch: str, deep: bool) -> dict:
    head = rev_parse("HEAD")
    if not head:
        raise RuntimeError("Could not resolve HEAD")

    branch = run_git("rev-parse", "--abbrev-ref", "HEAD").strip()
    upstream_track = tracking_branch()

    origin_ref = f"origin/{base_branch}"
    upstream_ref = f"upstream/{base_branch}"

    origin_sha = rev_parse(origin_ref)
    upstream_sha = rev_parse(upstream_ref)

    wt = _parse_porcelain_v2()
    dirty_level = _dirty_level(wt["staged"], wt["unstaged"], wt["untracked"])
    local_files = _local_changed_files(wt["staged"], wt["unstaged"])

    local_vs_origin = ahead_behind("HEAD", origin_ref) if origin_sha else (0, 0)
    local_vs_upstream = ahead_behind("HEAD", upstream_ref) if upstream_sha else (0, 0)
    origin_vs_upstream = (
        ahead_behind(origin_ref, upstream_ref) if origin_sha and upstream_sha else (0, 0)
    )

    overlap_upstream = _overlap(local_files, "HEAD", upstream_ref) if upstream_sha else []
    overlap_origin = _overlap(local_files, "HEAD", origin_ref) if origin_sha else []

    deep_conflicts: dict = {"merge": [], "rebase": []}
    if upstream_sha and (deep or overlap_upstream):
        deep_conflicts = predict_conflicts("HEAD", upstream_ref)

    pushed = (
        branch_pushed_to_origin(branch)
        if branch not in ("HEAD", base_branch)
        else False
    )

    return {
        "head": head,
        "branch": branch,
        "base_branch": base_branch,
        "tracking": upstream_track,
        "on_main": branch == base_branch,
        "pushed_to_origin": pushed,
        "remotes": {
            "origin": _remote_exists("origin"),
            "upstream": _remote_exists("upstream"),
        },
        "refs": {
            "origin_main": origin_sha,
            "upstream_main": upstream_sha,
        },
        "divergence": {
            "local_vs_origin": {"ahead": local_vs_origin[0], "behind": local_vs_origin[1]},
            "local_vs_upstream": {"ahead": local_vs_upstream[0], "behind": local_vs_upstream[1]},
            "origin_vs_upstream": {
                "ahead": origin_vs_upstream[0],
                "behind": origin_vs_upstream[1],
            },
        },
        "working_tree": {
            **wt,
            "dirty_level": dirty_level,
            "local_changed_files": sorted(local_files),
        },
        "overlap": {
            "upstream": overlap_upstream,
            "origin": overlap_origin,
        },
        "deep_conflicts": deep_conflicts,
    }


def format_human(report: dict) -> str:
    lines = [
        f"Branch: {report['branch']}"
        + (f" (tracking {report['tracking']})" if report.get("tracking") else ""),
    ]
    wt = report["working_tree"]
    lines.append(
        f"Local changes: {len(wt['staged'])} staged, "
        f"{len(wt['unstaged'])} unstaged, {len(wt['untracked'])} untracked"
    )

    div = report["divergence"]
    if report["refs"]["origin_main"] and report["refs"]["upstream_main"]:
        ob = div["origin_vs_upstream"]["behind"]
        if ob:
            lines.append(f"Fork sync: origin/{report['base_branch']} is {ob} commit(s) behind upstream/{report['base_branch']}")
        else:
            lines.append(f"Fork sync: origin/{report['base_branch']} is up to date with upstream/{report['base_branch']}")

    lu = div["local_vs_upstream"]
    lo = div["local_vs_origin"]
    if lu["behind"] or lu["ahead"]:
        lines.append(
            f"Your branch vs upstream/{report['base_branch']}: "
            f"{lu['ahead']} ahead, {lu['behind']} behind"
        )
    if lo["behind"] or lo["ahead"]:
        lines.append(
            f"Your branch vs origin/{report['base_branch']}: "
            f"{lo['ahead']} ahead, {lo['behind']} behind"
        )

    if report["overlap"]["upstream"]:
        files = ", ".join(report["overlap"]["upstream"][:5])
        extra = len(report["overlap"]["upstream"]) - 5
        suffix = f" (+{extra} more)" if extra > 0 else ""
        lines.append(f"Overlap risk (upstream): {len(report['overlap']['upstream'])} file(s) ({files}{suffix})")

    merge_conflicts = report["deep_conflicts"].get("merge", [])
    if merge_conflicts:
        files = ", ".join(merge_conflicts[:5])
        lines.append(f"Predicted conflicts (merge-tree): {len(merge_conflicts)} file(s) ({files})")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze local git state vs origin/upstream")
    parser.add_argument("--json", action="store_true", help="Emit JSON report")
    parser.add_argument("--deep", action="store_true", help="Run merge-tree conflict prediction")
    parser.add_argument("--base-branch", default="main")
    args = parser.parse_args()

    try:
        report = analyze(args.base_branch, args.deep)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(format_human(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
