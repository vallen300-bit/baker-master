#!/usr/bin/env bash
# forge_snapshot_push.sh — Mac Mini → brisen-lab snapshot pusher.
# Iterates known terminals, gathers state, POSTs to /api/snapshot.
# Designed to run from launchd (com.baker.forge-snapshot-push) every 30s.
# Tolerant: any single-terminal failure logs + continues; never exits non-zero
# unless config is invalid (so launchd does not back off).

set -u
set -o pipefail

LAB_URL="${LAB_URL:-https://brisen-lab.onrender.com}"
FORGE_KEY="${FORGE_KEY:-}"

if [[ -z "$FORGE_KEY" ]]; then
  echo "[forge-push] FATAL: FORGE_KEY env var unset" >&2
  exit 2
fi

# Map: alias -> repo path. Edit here if a terminal's primary clone moves.
declare -a TERMINALS=(
  "lead:/Users/dimitry/Desktop/baker-code"
  "deputy:/Users/dimitry/bm-aihead2"
  "b1:/Users/dimitry/bm-b1"
  "b2:/Users/dimitry/bm-b2"
  "b3:/Users/dimitry/bm-b3"
  "b4:/Users/dimitry/bm-b4"
)

# PR lookup toggle (disabled in tests to avoid gh dependency / network).
PR_LOOKUP_ENABLED="${PR_LOOKUP_ENABLED:-1}"

snapshot_one() {
  local alias="$1"
  local repo="$2"

  if [[ ! -d "$repo/.git" ]]; then
    echo "[forge-push] $alias: repo missing at $repo, skipping" >&2
    return 0
  fi

  local branch sha subject
  branch="$(git -C "$repo" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '')"
  sha="$(git -C "$repo" log -1 --format='%H' 2>/dev/null | cut -c1-12 || echo '')"
  subject="$(git -C "$repo" log -1 --format='%s' 2>/dev/null || echo '')"

  # Mailbox state. b-codes have CODE_N_PENDING / CODE_N_COMPLETE; lead/deputy
  # do not have mailbox slots. Derive N from alias suffix for b-codes; else n/a.
  local mailbox_status="n/a"
  local mailbox_brief_name=""
  local mailbox_path=""
  if [[ "$alias" =~ ^b([1-9])$ ]]; then
    local n="${BASH_REMATCH[1]}"
    local pending="$repo/briefs/_tasks/CODE_${n}_PENDING.md"
    local complete="$repo/briefs/_tasks/CODE_${n}_COMPLETE.md"
    if [[ -f "$pending" ]]; then
      mailbox_status="pending"
      mailbox_path="$pending"
      mailbox_brief_name="$(head -1 "$pending" | sed 's/^# *//' | head -c 200)"
    elif [[ -f "$complete" ]]; then
      mailbox_status="complete"
      mailbox_path="$complete"
      mailbox_brief_name="$(head -1 "$complete" | sed 's/^# *//' | head -c 200)"
    else
      mailbox_status="empty"
    fi
  fi

  # Open PR lookup (best-effort, errors swallowed).
  local pr_number="null"
  local pr_title=""
  if [[ "$PR_LOOKUP_ENABLED" == "1" && -n "$branch" && "$branch" != "main" && "$branch" != "master" ]]; then
    local remote_url repo_slug
    remote_url="$(git -C "$repo" remote get-url origin 2>/dev/null || echo '')"
    repo_slug="$(echo "$remote_url" | sed -E 's#.*github\.com[:/]##; s#\.git$##')"
    if [[ -n "$repo_slug" ]]; then
      local pr_json
      pr_json="$(gh pr list --repo "$repo_slug" --head "$branch" --state open --json number,title --limit 1 2>/dev/null || echo '[]')"
      if [[ "$pr_json" != "[]" && -n "$pr_json" ]]; then
        pr_number="$(echo "$pr_json" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d[0]["number"] if d else "null")')"
        pr_title="$(echo "$pr_json" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d[0]["title"] if d else "")')"
      fi
    fi
  fi

  # Build payload via python (safe JSON escaping). Variables are passed via env,
  # not string-interpolated into the source, to keep apostrophes / backslashes safe.
  local payload
  payload="$(
    F_ALIAS="$alias" \
    F_BRANCH="$branch" \
    F_SHA="$sha" \
    F_SUBJECT="$subject" \
    F_MBOX_PATH="$mailbox_path" \
    F_MBOX_STATUS="$mailbox_status" \
    F_MBOX_BRIEF="$mailbox_brief_name" \
    F_PR_NUMBER="$pr_number" \
    F_PR_TITLE="$pr_title" \
    python3 -c "
import json, os
def s(v):
    return v if v else None
pr_n = os.environ.get('F_PR_NUMBER', 'null')
pr_n_val = None if pr_n == 'null' or pr_n == '' else int(pr_n)
print(json.dumps({
    'terminal_alias': os.environ['F_ALIAS'],
    'git_branch': s(os.environ.get('F_BRANCH', '')),
    'git_head_sha': s(os.environ.get('F_SHA', '')),
    'git_head_subject': s(os.environ.get('F_SUBJECT', '').strip()),
    'mailbox_path': s(os.environ.get('F_MBOX_PATH', '')),
    'mailbox_status': os.environ.get('F_MBOX_STATUS', 'n/a'),
    'mailbox_brief_name': s(os.environ.get('F_MBOX_BRIEF', '')),
    'open_pr_number': pr_n_val,
    'open_pr_title': s(os.environ.get('F_PR_TITLE', '')),
}))
" 2>/dev/null)"

  if [[ -z "$payload" ]]; then
    echo "[forge-push] $alias: payload build failed, skipping" >&2
    return 0
  fi

  local http_status
  http_status="$(curl -s -o /dev/null -w '%{http_code}' \
    -X POST "${LAB_URL}/api/snapshot" \
    -H "X-Forge-Key: ${FORGE_KEY}" \
    -H "Content-Type: application/json" \
    --max-time 10 \
    -d "$payload" || echo '000')"

  if [[ "$http_status" != "200" ]]; then
    echo "[forge-push] $alias: HTTP $http_status (payload sha $(echo "$payload" | shasum | cut -c1-8))" >&2
  fi
}

# Iterate. Per-terminal failures are isolated.
for entry in "${TERMINALS[@]}"; do
  alias="${entry%%:*}"
  repo="${entry#*:}"
  snapshot_one "$alias" "$repo" || true
done

exit 0
