#!/usr/bin/env bash
# Interactive fork-aware git sync: diagnose, recommend, commit, push, PR.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GIT_SYNC_DIR="$ROOT/scripts/git_sync"
STATE_DIR="${TMPDIR:-/tmp}"
BASE_BRANCH="main"
DRY_RUN=0
DEEP=0
CONTINUE=0
ALLOW_SECRETS=0
NO_VERIFY=0

usage() {
  cat <<'EOF'
Usage: ./scripts/git-sync.sh [OPTIONS]

Fork-aware git sync for commit → push → PR workflows.

Options:
  --dry-run          Diagnose and recommend only; no write operations
  --deep             Always run merge-tree conflict prediction
  --continue         Resume after conflict resolution or stash pop
  --base-branch BR   Base branch name (default: main)
  --allow-secrets    Allow committing secret-like paths without override prompt
  --no-verify        Pass --no-verify to git commit (use with caution)
  -h, --help         Show this help

Examples:
  ./scripts/git-sync.sh
  ./scripts/git-sync.sh --dry-run --deep
  ./scripts/git-sync.sh --continue
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --deep) DEEP=1; shift ;;
    --continue) CONTINUE=1; shift ;;
    --allow-secrets) ALLOW_SECRETS=1; shift ;;
    --no-verify) NO_VERIFY=1; shift ;;
    --base-branch)
      BASE_BRANCH="${2:?missing branch name}"
      shift 2
      ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
  esac
done

cd "$ROOT"

REPO_HASH="$(git rev-parse --show-toplevel | shasum | awk '{print $1}')"
CACHE_FILE="$STATE_DIR/git-sync-${REPO_HASH}.json"
SESSION_FILE="$STATE_DIR/git-sync-${REPO_HASH}.session.json"

py() {
  PYTHONPATH="$GIT_SYNC_DIR" uv run python "$@"
}

confirm() {
  local prompt="$1"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "[dry-run] Would confirm: $prompt"
    return 0
  fi
  read -r -p "$prompt [y/N]: " ans
  case "$ans" in y|Y|yes|YES) return 0 ;; *) return 1 ;; esac
}

confirm_destructive() {
  local prompt="$1"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "[dry-run] Would confirm (typed yes): $prompt"
    return 0
  fi
  read -r -p "$prompt Type 'yes' to continue: " ans
  [[ "$ans" == "yes" ]]
}

run_step() {
  local cmd="$1"
  local desc="$2"
  if [[ -z "$cmd" ]]; then
    echo "  → $desc"
    return 0
  fi
  echo "  → $desc"
  echo "    $ $cmd"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    return 0
  fi
  eval "$cmd"
}

preflight() {
  git rev-parse --git-dir >/dev/null 2>&1 || { echo "Not a git repository." >&2; exit 1; }

  if ! git remote get-url origin >/dev/null 2>&1; then
    echo "Missing 'origin' remote. Add your fork:" >&2
    echo "  git remote add origin git@github.com:<you>/openbase-coder.git" >&2
    exit 1
  fi

  if ! git remote get-url upstream >/dev/null 2>&1; then
    echo "Missing 'upstream' remote. Add upstream:" >&2
    echo "  git remote add upstream git@github.com:openbase-community/openbase-coder.git" >&2
    exit 1
  fi

  if ! command -v gh >/dev/null 2>&1; then
    echo "GitHub CLI (gh) is required. Install: https://cli.github.com/" >&2
    exit 1
  fi

  if ! gh auth status >/dev/null 2>&1; then
    echo "gh is not authenticated. Run: gh auth login" >&2
    exit 1
  fi

  if ! git rev-parse --verify "upstream/${BASE_BRANCH}" >/dev/null 2>&1; then
    echo "Warning: upstream/${BASE_BRANCH} not found." >&2
    echo "  Run: git fetch upstream ${BASE_BRANCH}" >&2
  fi
}

fetch_remotes() {
  echo "Fetching origin and upstream..."
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "[dry-run] Would run: git fetch origin ${BASE_BRANCH} && git fetch upstream ${BASE_BRANCH}"
    return 0
  fi
  git fetch origin "${BASE_BRANCH}"
  git fetch upstream "${BASE_BRANCH}"
}

analyze() {
  if [[ "$DEEP" -eq 1 ]]; then
    py "$GIT_SYNC_DIR/analyze.py" --json --base-branch "$BASE_BRANCH" --deep
  else
    py "$GIT_SYNC_DIR/analyze.py" --json --base-branch "$BASE_BRANCH"
  fi
}

print_diagnosis() {
  local report="$1"
  py -c "
import json, sys
from analyze import format_human
print(format_human(json.load(sys.stdin)))
" <<<"$report"
}

recommend_options() {
  local report="$1"
  py "$GIT_SYNC_DIR/recommend.py" --json <<<"$report"
}

check_safety() {
  local report="$1"
  local force="${2:-0}"
  local staged untracked branch
  staged=$(echo "$report" | py -c "import json,sys; r=json.load(sys.stdin); print(' '.join(r['working_tree']['staged']))")
  untracked=$(echo "$report" | py -c "import json,sys; r=json.load(sys.stdin); print(' '.join(r['working_tree']['untracked']))")
  branch=$(echo "$report" | py -c "import json,sys; r=json.load(sys.stdin); print(r['branch'])")

  local args=(--json --branch "$branch")
  [[ -n "$staged" ]] && args+=(--staged $staged)
  [[ -n "$untracked" ]] && args+=(--untracked $untracked)
  [[ "$force" -eq 1 ]] && args+=(--force-push)
  [[ "$ALLOW_SECRETS" -eq 1 ]] && args+=(--allow-secrets)

  py "$GIT_SYNC_DIR/safety.py" "${args[@]}"
}

in_rebase() {
  [[ -d "$(git rev-parse --git-path rebase-merge)" || -d "$(git rev-parse --git-path rebase-apply)" ]]
}

in_merge() {
  [[ -f "$(git rev-parse --git-path MERGE_HEAD)" ]]
}

resolve_continue_state() {
  if in_rebase; then
    echo "Rebase in progress."
    if confirm "Continue rebase (git rebase --continue)?"; then
      run_step "git rebase --continue" "Continue rebase"
    fi
    return
  fi
  if in_merge; then
    echo "Merge in progress."
    if confirm "Complete merge (git commit)?"; then
      run_step "git commit --no-edit" "Complete merge commit"
    fi
    return
  fi
  echo "No rebase/merge in progress. Re-run without --continue for full diagnosis."
}

handle_dirty_before_sync() {
  local dirty_level="$1"
  case "$dirty_level" in
    staged)
      if confirm "Staged changes detected. Create WIP commit before sync?"; then
        run_step 'git commit -m "wip: pre-sync snapshot"' "WIP commit staged changes"
      else
        echo "Aborted." >&2
        exit 1
      fi
      ;;
    unstaged|mixed)
      run_step 'git stash push -u -m "git-sync: pre-sync WIP"' "Stash changes including untracked"
      echo "stash" > "$SESSION_FILE.stash"
      ;;
    clean) ;;
  esac
}

restore_stash_if_needed() {
  if [[ -f "$SESSION_FILE.stash" ]]; then
    if confirm "Restore stashed changes (git stash pop)?"; then
      run_step "git stash pop" "Restore stashed changes"
    fi
    rm -f "$SESSION_FILE.stash"
  fi
}

sync_with_upstream() {
  local strategy="$1"
  if [[ "$strategy" == "rebase" ]]; then
    if ! confirm_destructive "Rebase onto upstream/${BASE_BRANCH}."; then
      echo "Aborted." >&2
      exit 1
    fi
    if ! run_step "git rebase upstream/${BASE_BRANCH}" "Rebase onto upstream/${BASE_BRANCH}"; then
      echo "Rebase conflict. Resolve files, then run: ./scripts/git-sync.sh --continue" >&2
      exit 1
    fi
  else
    if ! confirm "Merge upstream/${BASE_BRANCH} into current branch?"; then
      echo "Aborted." >&2
      exit 1
    fi
    if ! run_step "git merge upstream/${BASE_BRANCH}" "Merge upstream/${BASE_BRANCH}"; then
      echo "Merge conflict. Resolve files, then run: ./scripts/git-sync.sh --continue" >&2
      exit 1
    fi
  fi
}

commit_changes() {
  if git diff --cached --quiet; then
    if [[ -n "$(git status --porcelain)" ]]; then
      if confirm "Stage all changes (git add -A)?"; then
        run_step "git add -A" "Stage all changes"
      else
        echo "Nothing staged; skipping commit." >&2
        return 0
      fi
    else
      echo "Working tree clean; skipping commit."
      return 0
    fi
  fi

  local suggestion message
  suggestion=$(py "$GIT_SYNC_DIR/commit_suggest.py" --json) || {
    echo "No staged changes to commit."
    return 0
  }
  message=$(echo "$suggestion" | py -c "import json,sys; print(json.load(sys.stdin)['message'])")
  echo "Suggested commit message: $message"
  read -r -p "Press Enter to accept, or type a new message: " custom
  if [[ -n "$custom" ]]; then
    message="$custom"
  fi

  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "[dry-run] Would commit: $message"
    return 0
  fi
  if [[ "$NO_VERIFY" -eq 1 ]]; then
    git commit --no-verify -m "$message"
  else
    git commit -m "$message"
  fi
}

push_branch() {
  local force="${1:-0}"
  local branch
  branch="$(git rev-parse --abbrev-ref HEAD)"

  if [[ "$branch" == "$BASE_BRANCH" || "$branch" == "main" || "$branch" == "master" ]]; then
    echo "Refusing to push directly to protected branch '$branch'." >&2
    exit 1
  fi

  if [[ "$force" -eq 1 ]]; then
    if ! confirm_destructive "Force-with-lease push branch '$branch'."; then
      exit 1
    fi
    run_step "git push --force-with-lease -u origin HEAD" "Force-with-lease push"
  else
    run_step "git push -u origin HEAD" "Push branch to origin"
  fi
}

open_pr_pipeline() {
  local title
  title=$(git log -1 --format=%s 2>/dev/null || echo "Update branch")
  read -r -p "PR title [$title]: " custom_title
  [[ -n "$custom_title" ]] && title="$custom_title"

  local pr_json pr_url pr_number pr_repo
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "[dry-run] Would create PR: $title"
    return 0
  fi

  pr_json=$(py "$GIT_SYNC_DIR/gh_pr.py" create --title "$title" --base-branch "$BASE_BRANCH" --json)
  pr_url=$(echo "$pr_json" | py -c "import json,sys; print(json.load(sys.stdin)['url'])")
  pr_number=$(echo "$pr_json" | py -c "import json,sys; print(json.load(sys.stdin)['number'])")
  pr_repo=$(echo "$pr_json" | py -c "import json,sys; print(json.load(sys.stdin)['target']['parent'])")
  echo "PR created: $pr_url"

  if confirm "Watch CI checks (gh pr checks --watch)?"; then
    py "$GIT_SYNC_DIR/gh_pr.py" watch --number "$pr_number" --repo "$pr_repo" || true
  fi

  if confirm "Merge PR when ready?"; then
    echo "Merge strategy: 1=merge 2=squash 3=rebase"
    read -r -p "Choice [1]: " merge_choice
    merge_choice="${merge_choice:-1}"
    local strategy="merge"
    case "$merge_choice" in
      2) strategy="squash" ;;
      3) strategy="rebase" ;;
    esac
    if confirm_destructive "Merge PR #$pr_number ($strategy)."; then
      py "$GIT_SYNC_DIR/gh_pr.py" merge --number "$pr_number" --repo "$pr_repo" --strategy "$strategy"
      echo "PR merged."
    fi
  fi
}

execute_option() {
  local option_id="$1"
  local report="$2"
  local branch dirty_level behind_upstream on_main pushed

  branch=$(echo "$report" | py -c "import json,sys; print(json.load(sys.stdin)['branch'])")
  dirty_level=$(echo "$report" | py -c "import json,sys; print(json.load(sys.stdin)['working_tree']['dirty_level'])")
  behind_upstream=$(echo "$report" | py -c "import json,sys; print(json.load(sys.stdin)['divergence']['local_vs_upstream']['behind'])")
  on_main=$(echo "$report" | py -c "import json,sys; print(json.load(sys.stdin)['on_main'])")
  pushed=$(echo "$report" | py -c "import json,sys; print(json.load(sys.stdin)['pushed_to_origin'])")

  local suggested
  suggested=$(echo "$report" | py -c "
import json, sys
from recommend import _suggest_branch_name
print(_suggest_branch_name(json.load(sys.stdin)))
" 2>/dev/null || echo "sync/$(date +%Y-%m-%d)-changes")

  local safety_json
  safety_json=$(check_safety "$report" 0)
  echo "$safety_json" | py -c "
import json, sys
s = json.load(sys.stdin)
for w in s.get('warnings', []):
    print('WARNING:', w)
for e in s.get('errors', []):
    print('ERROR:', e)
    sys.exit(1)
"

  case "$option_id" in
    abort|noop|manual)
      echo "No automated steps executed."
      return 0
      ;;
    sync_fork)
      fetch_remotes
      if confirm "Merge upstream/${BASE_BRANCH} into ${BASE_BRANCH}?"; then
        run_step "git merge upstream/${BASE_BRANCH}" "Merge upstream"
        run_step "git push origin ${BASE_BRANCH}" "Update origin/${BASE_BRANCH}"
      fi
      return 0
      ;;
    push_pr)
      push_branch 0
      open_pr_pipeline
      return 0
      ;;
    commit_push_pr)
      if [[ "$on_main" == "True" || "$on_main" == "true" ]]; then
        read -r -p "Feature branch name [$suggested]: " new_branch
        new_branch="${new_branch:-$suggested}"
        run_step "git switch -c \"$new_branch\"" "Create feature branch"
      fi
      commit_changes
      push_branch 0
      open_pr_pipeline
      return 0
      ;;
  esac

  # Workflows that need feature branch + optional sync
  if [[ "$on_main" == "True" || "$on_main" == "true" ]]; then
    read -r -p "Feature branch name [$suggested]: " new_branch
    new_branch="${new_branch:-$suggested}"
    run_step "git switch -c \"$new_branch\"" "Create feature branch"
  fi

  fetch_remotes

  local strategy=""
  local force=0
  case "$option_id" in
    rebase_upstream|feature_then_sync)
      strategy="rebase"
      ;;
    rebase_force_upstream)
      strategy="rebase"
      force=1
      ;;
    merge_upstream|merge_upstream_pushed)
      strategy="merge"
      ;;
  esac

  if [[ "$option_id" == "feature_then_sync" && "$behind_upstream" -eq 0 ]]; then
    strategy=""
  fi

  if [[ "$behind_upstream" -gt 0 && -n "$strategy" ]]; then
    handle_dirty_before_sync "$dirty_level"
    sync_with_upstream "$strategy"
    restore_stash_if_needed
  fi

  commit_changes
  push_branch "$force"
  open_pr_pipeline
}

main() {
  preflight

  if [[ "$CONTINUE" -eq 1 ]]; then
    resolve_continue_state
    if confirm "Continue with commit/push/PR steps?"; then
      local report
      report=$(analyze)
      execute_option "commit_push_pr" "$report"
    fi
    exit 0
  fi

  fetch_remotes

  local report rec
  report=$(analyze)
  echo "$report" > "$CACHE_FILE"

  echo ""
  echo "=== Diagnosis ==="
  print_diagnosis "$report"
  echo ""

  rec=$(recommend_options "$report")
  echo "=== Recommended options ==="
  echo "$rec" | py -c "
import json, sys
data = json.load(sys.stdin)
for i, opt in enumerate(data['options'], 1):
    print(f\"{i}. [{opt['risk'].upper()}] {opt['title']}\")
    print(f\"   {opt['rationale']}\")
    for step in opt['steps'][:4]:
        if step['cmd']:
            print(f\"   - {step['description']}: {step['cmd']}\")
        else:
            print(f\"   - {step['description']}\")
    if len(opt['steps']) > 4:
        print(f\"   - ... {len(opt['steps']) - 4} more step(s)\")
print()
print(f\"Suggested branch: {data.get('suggested_branch', '')}\")
"

  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo ""
    echo "[dry-run] No changes made."
    exit 0
  fi

  local count
  count=$(echo "$rec" | py -c "import json,sys; print(len(json.load(sys.stdin)['options']))")
  read -r -p "Select option [1-${count}] (or q to quit): " choice
  case "$choice" in q|Q) exit 0 ;; esac
  if ! [[ "$choice" =~ ^[0-9]+$ ]] || [[ "$choice" -lt 1 || "$choice" -gt "$count" ]]; then
    echo "Invalid choice." >&2
    exit 1
  fi

  local option_id
  option_id=$(echo "$rec" | py -c "
import json, sys
data = json.load(sys.stdin)
print(data['options'][int(sys.argv[1]) - 1]['id'])
" "$choice")

  echo ""
  echo "Executing: $option_id"
  execute_option "$option_id" "$report"
  echo ""
  echo "Done."
}

main "$@"
