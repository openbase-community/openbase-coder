"""Merge-tree based conflict prediction."""

from __future__ import annotations

import re
import subprocess

from git_utils import merge_base, rev_parse, run_git, run_git_ok


def _merge_tree(base: str, ours: str, theirs: str) -> str:
    ok, out = run_git_ok("merge-tree", base, ours, theirs)
    if not ok:
        return ""
    return out


def _parse_conflict_paths(output: str) -> list[str]:
    paths: set[str] = set()
    for line in output.splitlines():
        if "CONFLICT" in line and " in " in line:
            match = re.search(r" in (.+)$", line.strip())
            if match:
                paths.add(match.group(1).strip())
        if line.startswith("changed in both"):
            continue
        match = re.match(r"^<<<<<<< ", line)
        if match:
            continue
    # merge-tree also emits "CONFLICT (content): Merge conflict in path"
    for match in re.finditer(r"Merge conflict in (.+)$", output, re.MULTILINE):
        paths.add(match.group(1).strip())
    # newer git: "CONFLICT (modify/delete): file deleted in ..."
    for match in re.finditer(r"CONFLICT \([^)]+\): (.+?)(?:\s|$)", output):
        candidate = match.group(1).strip()
        if candidate and not candidate.startswith("Merge conflict"):
            paths.add(candidate.split()[0])
    return sorted(paths)


def _effective_local_ref() -> str:
    """Use a temporary commit when staged changes exist so merge-tree sees the index."""
    ok, _ = run_git_ok("diff", "--cached", "--quiet")
    if ok:
        return "HEAD"
    tree = run_git("write-tree").strip()
    head = rev_parse("HEAD")
    if not head:
        return "HEAD"
    temp_ok, temp = run_git_ok(
        "commit-tree", tree, "-p", head, "-m", "git-sync-analysis-temp"
    )
    return temp if temp_ok else "HEAD"


def predict_conflicts(local_ref: str, upstream_ref: str) -> dict[str, list[str]]:
    effective = _effective_local_ref() if local_ref == "HEAD" else local_ref
    base = merge_base(effective, upstream_ref)
    if not base:
        return {"merge": [], "rebase": []}

    merge_out = _merge_tree(base, effective, upstream_ref)
    merge_conflicts = _parse_conflict_paths(merge_out)

    rebase_out = _merge_tree(base, upstream_ref, effective)
    rebase_conflicts = _parse_conflict_paths(rebase_out)

    return {"merge": merge_conflicts, "rebase": rebase_conflicts}


def main() -> None:
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser()
    parser.add_argument("--local-ref", default="HEAD")
    parser.add_argument("--upstream-ref", default="upstream/main")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if not rev_parse(args.local_ref) or not rev_parse(args.upstream_ref):
        print("Invalid refs", file=sys.stderr)
        sys.exit(1)

    result = predict_conflicts(args.local_ref, args.upstream_ref)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for kind, paths in result.items():
            print(f"{kind}: {', '.join(paths) or '(none)'}")


if __name__ == "__main__":
    main()
