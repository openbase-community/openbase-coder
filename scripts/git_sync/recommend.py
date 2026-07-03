"""Rank sync workflow options based on analysis report."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date


def _step(cmd: str, description: str) -> dict:
    return {"cmd": cmd, "description": description}


def _option(
    option_id: str,
    title: str,
    rationale: str,
    risk: str,
    steps: list[dict],
) -> dict:
    return {
        "id": option_id,
        "title": title,
        "rationale": rationale,
        "risk": risk,
        "steps": steps,
    }


def _suggest_branch_name(report: dict) -> str:
    files = report["working_tree"]["staged"] or report["working_tree"]["local_changed_files"]
    slug = "changes"
    if files:
        first = files[0].split("/")[-1]
        slug = first.replace(".", "-").replace("_", "-")[:24]
    return f"sync/{date.today().isoformat()}-{slug}"


def recommend(report: dict) -> list[dict]:
    base = report["base_branch"]
    branch = report["branch"]
    on_main = report["on_main"]
    dirty = report["working_tree"]["dirty_level"]
    behind_upstream = report["divergence"]["local_vs_upstream"]["behind"]
    fork_behind = report["divergence"]["origin_vs_upstream"]["behind"]
    pushed = report["pushed_to_origin"]
    overlap = report["overlap"]["upstream"]
    merge_conflicts = report["deep_conflicts"].get("merge", [])
    suggested_branch = _suggest_branch_name(report)

    options: list[dict] = []

    # Option: diagnose-only abort
    if merge_conflicts:
        options.append(
            _option(
                "abort",
                "Review conflicts before syncing",
                f"merge-tree predicts conflicts in: {', '.join(merge_conflicts[:3])}",
                "safe",
                [
                    _step("", "Resolve overlapping edits locally before sync"),
                    _step(f"git diff upstream/{base_branch}...HEAD", "Inspect divergence"),
                ],
            )
        )

    needs_sync = behind_upstream > 0 or fork_behind > 0

    if on_main and dirty != "clean":
        options.append(
            _option(
                "feature_then_sync",
                "Create feature branch, sync with upstream, then commit",
                "Work should not land directly on main; sync before opening a PR",
                "safe",
                _feature_sync_steps(base, suggested_branch, dirty, needs_sync, pushed=False, prefer="rebase"),
            )
        )

    if not on_main and needs_sync and not pushed:
        options.append(
            _option(
                "rebase_upstream",
                f"Rebase onto upstream/{base} (unpushed branch)",
                "Linear history; best when branch has not been pushed yet",
                "caution" if overlap else "safe",
                _sync_steps(base, dirty, strategy="rebase", force_push=False),
            )
        )
        options.append(
            _option(
                "merge_upstream",
                f"Merge upstream/{base} into current branch",
                "Safer when you want to preserve branch history without rewriting",
                "safe",
                _sync_steps(base, dirty, strategy="merge", force_push=False),
            )
        )

    if not on_main and needs_sync and pushed:
        options.append(
            _option(
                "merge_upstream_pushed",
                f"Merge upstream/{base} (branch already on origin)",
                "Avoids force-push on a published branch",
                "safe",
                _sync_steps(base, dirty, strategy="merge", force_push=False),
            )
        )
        options.append(
            _option(
                "rebase_force_upstream",
                f"Rebase onto upstream/{base} and force-with-lease push",
                "Rewrites published branch; requires explicit confirmation",
                "destructive",
                _sync_steps(base, dirty, strategy="rebase", force_push=True),
            )
        )

    if dirty != "clean" and not needs_sync:
        options.append(
            _option(
                "commit_push_pr",
                "Commit, push, and open PR (already up to date with upstream)",
                "No sync needed; proceed with commit workflow",
                "safe",
                _commit_push_pr_steps(base, dirty, on_main, suggested_branch),
            )
        )

    if dirty == "clean" and not needs_sync and not on_main:
        options.append(
            _option(
                "push_pr",
                "Push and open PR (no local changes)",
                "Branch is synced; publish and open PR",
                "safe",
                [
                    _step("git push -u origin HEAD", "Push branch to origin"),
                    _step("gh pr create ...", "Create pull request against upstream parent"),
                ],
            )
        )

    if on_main and dirty == "clean" and not needs_sync:
        options.append(
            _option(
                "noop",
                "Nothing to do — main is clean and synced",
                "Make changes or switch to a feature branch to start work",
                "safe",
                [_step("", "No action required")],
            )
        )

    if fork_behind > 0 and on_main and dirty == "clean":
        options.append(
            _option(
                "sync_fork",
                f"Update local main from upstream/{base} (no local changes)",
                f"origin/{base} is {fork_behind} commit(s) behind upstream",
                "safe",
                [
                    _step(f"git fetch origin {base} && git fetch upstream {base}", "Fetch latest remotes"),
                    _step(f"git merge upstream/{base}", f"Merge upstream into current branch"),
                    _step(f"git push origin {base}", f"Update origin/{base}"),
                ],
            )
        )

    if not options:
        options.append(
            _option(
                "manual",
                "Manual review recommended",
                "State does not match a known safe template",
                "caution",
                [_step("./scripts/git-sync.sh --dry-run --deep", "Re-run with deep analysis")],
            )
        )

    return options


def _dirty_prep_steps(dirty: str) -> list[dict]:
    if dirty == "staged":
        return [
            _step(
                'git commit -m "wip: pre-sync snapshot"',
                "WIP commit staged changes before sync",
            ),
        ]
    if dirty in ("unstaged", "mixed"):
        return [
            _step(
                'git stash push -u -m "git-sync: pre-sync WIP"',
                "Stash local changes (including untracked) before sync",
            ),
        ]
    return []


def _sync_steps(base: str, dirty: str, strategy: str, force_push: bool) -> list[dict]:
    steps = [_step(f"git fetch origin {base} && git fetch upstream {base}", "Fetch latest remotes")]
    steps.extend(_dirty_prep_steps(dirty))
    if strategy == "rebase":
        steps.append(_step(f"git rebase upstream/{base}", f"Rebase onto upstream/{base}"))
    else:
        steps.append(_step(f"git merge upstream/{base}", f"Merge upstream/{base}"))
    if dirty in ("unstaged", "mixed"):
        steps.append(_step("git stash pop", "Restore stashed changes"))
    steps.extend(
        [
            _step("git add -A && git commit ...", "Commit changes with suggested message"),
            _step(
                "git push -u origin HEAD" + (" --force-with-lease" if force_push else ""),
                "Push branch to origin",
            ),
            _step("gh pr create ...", "Create pull request"),
            _step("gh pr checks --watch", "Wait for CI checks"),
        ]
    )
    return steps


def _feature_sync_steps(
    base: str,
    suggested_branch: str,
    dirty: str,
    needs_sync: bool,
    pushed: bool,
    prefer: str,
) -> list[dict]:
    steps = [
        _step(f"git switch -c {suggested_branch}", f"Create feature branch {suggested_branch}"),
        _step(f"git fetch origin {base} && git fetch upstream {base}", "Fetch latest remotes"),
    ]
    steps.extend(_dirty_prep_steps(dirty))
    if needs_sync:
        if prefer == "rebase" and not pushed:
            steps.append(_step(f"git rebase upstream/{base}", f"Rebase onto upstream/{base}"))
        else:
            steps.append(_step(f"git merge upstream/{base}", f"Merge upstream/{base}"))
    if dirty in ("unstaged", "mixed"):
        steps.append(_step("git stash pop", "Restore stashed changes"))
    steps.extend(
        [
            _step("git add -A && git commit ...", "Commit with suggested message"),
            _step("git push -u origin HEAD", "Push branch to origin"),
            _step("gh pr create ...", "Create pull request against upstream parent"),
            _step("gh pr checks --watch", "Wait for CI checks"),
        ]
    )
    return steps


def _commit_push_pr_steps(base: str, dirty: str, on_main: bool, suggested_branch: str) -> list[dict]:
    steps: list[dict] = []
    if on_main:
        steps.append(_step(f"git switch -c {suggested_branch}", "Create feature branch"))
    steps.extend(
        [
            _step("git add -A && git commit ...", "Commit with suggested message"),
            _step("git push -u origin HEAD", "Push branch to origin"),
            _step("gh pr create ...", "Create pull request"),
            _step("gh pr checks --watch", "Wait for CI checks"),
        ]
    )
    return steps


def format_options(options: list[dict]) -> str:
    lines: list[str] = []
    for i, opt in enumerate(options, 1):
        lines.append(f"{i}. [{opt['risk'].upper()}] {opt['title']}")
        lines.append(f"   {opt['rationale']}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Recommend git-sync workflow options")
    parser.add_argument("--report", help="Path to analyze JSON report")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.report:
        with open(args.report) as f:
            report = json.load(f)
    else:
        report = json.load(sys.stdin)

    options = recommend(report)
    payload = {"options": options, "suggested_branch": _suggest_branch_name(report)}

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(format_options(options))
    return 0


if __name__ == "__main__":
    sys.exit(main())
