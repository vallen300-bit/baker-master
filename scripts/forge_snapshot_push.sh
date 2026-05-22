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

# Single-instance guard (Fix 3b, BRISEN_LAB_CARD_STATE_FIX_1). Architect-flagged
# 2026-05-13: per-cycle gh pr list count grew with multi-clone snapshots
# (Fix 1); launchd respawns at StartInterval even if previous instance hasn't
# finished, so without this guard two daemons can run concurrently and double
# the API rate. Uses mkdir-mutex (POSIX-atomic) instead of flock (not present
# on default macOS, no Homebrew formula installed on Mac Mini per b3 probe
# 2026-05-13). Stale-lock reclaim: if owning PID is dead, take over.
LOCK_DIR="${LOCK_DIR:-/tmp/forge_snapshot_push.lock}"
acquire_lock() {
  if mkdir "$LOCK_DIR" 2>/dev/null; then
    echo "$$" > "$LOCK_DIR/pid"
    return 0
  fi
  # Lock dir exists. Check if owning PID is alive.
  local owner=""
  if [[ -f "$LOCK_DIR/pid" ]]; then
    owner="$(cat "$LOCK_DIR/pid" 2>/dev/null || echo '')"
  fi
  if [[ -n "$owner" ]] && kill -0 "$owner" 2>/dev/null; then
    # Active owner — bail out cleanly.
    return 1
  fi
  # Stale lock (process gone, possibly SIGKILLed). Reclaim.
  rm -rf "$LOCK_DIR" 2>/dev/null
  if mkdir "$LOCK_DIR" 2>/dev/null; then
    echo "$$" > "$LOCK_DIR/pid"
    return 0
  fi
  # Race lost — another instance reclaimed first. Bail out.
  return 1
}
if ! acquire_lock; then
  # Exit 0 (not non-zero): launchd interprets non-zero as crash and backs off.
  echo "[forge-push] another instance is running; exiting" >&2
  exit 0
fi
trap 'rm -rf "$LOCK_DIR" 2>/dev/null' EXIT

# Map: alias -> comma-separated candidate repo paths. b-codes work in two
# clones (baker-master + brisen-lab); the daemon picks the active one per
# pick_active_clone() scoring. lead/deputy stay single-path. Edit here if
# a terminal's primary clone moves.
declare -a TERMINALS=(
  "lead:/Users/dimitry/bm-aihead1"
  "cowork-ah1:/Users/dimitry/bm-aihead1"
  "deputy:/Users/dimitry/bm-aihead2"
  "b1:/Users/dimitry/bm-b1,/Users/dimitry/bm-b1-brisen-lab"
  "b2:/Users/dimitry/bm-b2,/Users/dimitry/bm-b2-brisen-lab"
  "b3:/Users/dimitry/bm-b3,/Users/dimitry/bm-b3-brisen-lab"
  "b4:/Users/dimitry/bm-b4,/Users/dimitry/bm-b4-brisen-lab"
  "hag-desk:/Users/dimitry/baker-vault"
)

# Test-only override: if TERMINALS_OVERRIDE is set, replace the array. Format:
# "alias1:/path/to/repo1 alias2:/path/to/repoA,/path/to/repoB" (space-separated
# entries; each entry's path-tail may be comma-separated candidates).
if [[ -n "${TERMINALS_OVERRIDE:-}" ]]; then
  TERMINALS=($TERMINALS_OVERRIDE)
fi

# PR lookup toggle (disabled in tests to avoid gh dependency / network).
PR_LOOKUP_ENABLED="${PR_LOOKUP_ENABLED:-1}"

# pick_active_clone — given an alias and comma-separated candidate paths,
# return the single best repo path. Scoring (highest wins):
#   open PR on current branch of that clone : +1000
#   pending mailbox file (b-codes only)     : +100
#   tiebreaker: most-recent commit timestamp (integer unix epoch)
# Missing or non-git clones get score 0 and are skipped from selection;
# if no clone has .git, fall back to first candidate path so the daemon still
# emits a snapshot row (downstream UI then surfaces grey).
pick_active_clone() {
  # ALL state vars are declared local — bash function scope. Reviewer-flagged
  # 2026-05-13: without `local`, best_ts/best_score persist across alias calls
  # and corrupt tiebreaker logic on aliases 2+.
  local alias="$1"
  local paths_csv="$2"
  local n=""
  local best_path=""

  if [[ "$alias" =~ ^b([1-9])$ ]]; then
    n="${BASH_REMATCH[1]}"
  fi

  # Run the split + scoring inside a subshell so IFS mutation cannot leak into
  # the caller. Subshell echoes the winning path on stdout. Reviewer-flagged
  # 2026-05-13: empty paths_csv would skip the unset IFS at loop end, leaking
  # IFS=',' to the rest of the script.
  best_path="$(
    IFS=','
    set -- $paths_csv  # word-split paths_csv into positional args using ',' as IFS
    local inner_best_path=""
    local inner_best_score=-1
    local inner_best_ts=0
    local repo score branch remote_url repo_slug pr_count last_commit_ts
    for repo in "$@"; do
      [[ -d "$repo/.git" ]] || continue
      score=0

      # Mailbox presence + classification (b-codes only). pending/in_progress
      # score +100 (active dispatch); staged/complete score +50 (active clone in
      # holding or post-merge state); dropped scores +25 (drained but still the
      # working clone — better than an empty sibling). Frontmatter `status:` is
      # authoritative via classify_mailbox, so a filename `_PENDING` carrying
      # `status: STAGED` is scored as staged (not pending) — fixing the b4
      # 2026-05-12 drift. Bug seen 2026-05-12 evening: after mailbox flip to
      # COMPLETE, both candidates tied at 0 → picker oscillated to the sibling
      # clone (no briefs dir) → reported mailbox=empty, cards flipped grey.
      # Anchor: Director-observed b1/b2/b3 going empty ~30s post-rename. Fix:
      # any-mailbox is a positive signal of "this is the working clone for this
      # b-code"; pending outranks complete; dropped still outranks empty.
      # Note: avoiding `case ... in a|b)` syntax inside this $(...) — bash 3.2
      # (macOS default; Mac Mini runs this) has a known parser bug rejecting
      # alternation patterns in case statements when they sit inside command
      # substitution. if/elif chain is functionally identical and parses clean.
      if [[ -n "$n" ]]; then
        local mbox_class mbox_status
        mbox_class="$(classify_mailbox "$repo" "$n")"
        mbox_status="${mbox_class%%|*}"
        if [[ "$mbox_status" == "pending" || "$mbox_status" == "in_progress" ]]; then
          score=$((score + 100))
        elif [[ "$mbox_status" == "staged" || "$mbox_status" == "complete" ]]; then
          score=$((score + 50))
        elif [[ "$mbox_status" == "dropped" ]]; then
          score=$((score + 25))
        fi
      fi

      # Open PR on current branch (skip in test mode)
      if [[ "$PR_LOOKUP_ENABLED" == "1" ]]; then
        branch="$(git -C "$repo" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '')"
        if [[ -n "$branch" && "$branch" != "main" && "$branch" != "master" ]]; then
          remote_url="$(git -C "$repo" remote get-url origin 2>/dev/null || echo '')"
          repo_slug="$(echo "$remote_url" | sed -E 's#.*github\.com[:/]##; s#\.git$##')"
          if [[ -n "$repo_slug" ]]; then
            pr_count="$(gh pr list --repo "$repo_slug" --head "$branch" --state open --json number --limit 1 2>/dev/null \
              | python3 -c 'import json,sys; d=json.load(sys.stdin); print(len(d))' 2>/dev/null || echo '0')"
            if [[ "$pr_count" -ge 1 ]]; then
              score=$((score + 1000))
            fi
          fi
        fi
      fi

      # Tiebreaker: most-recent commit timestamp (unix epoch — integer only).
      last_commit_ts="$(git -C "$repo" log -1 --format='%ct' 2>/dev/null || echo '0')"

      if [[ "$score" -gt "$inner_best_score" ]] \
         || { [[ "$score" -eq "$inner_best_score" ]] && [[ "$last_commit_ts" -gt "$inner_best_ts" ]]; }; then
        inner_best_score="$score"
        inner_best_ts="$last_commit_ts"
        inner_best_path="$repo"
      fi
    done
    echo "$inner_best_path"
  )"

  # If subshell returned empty (no clones with .git, or empty paths_csv), fall
  # back to first candidate so the daemon still produces a snapshot row.
  if [[ -z "$best_path" ]]; then
    best_path="${paths_csv%%,*}"
  fi
  echo "$best_path"
}

# sync_clone_to_main — ensure the chosen clone has a fresh `origin/main` ref
# so classify_mailbox can read mailbox state from upstream even when the
# clone is mid-feature-branch (BRISEN_LAB_CARD_STATE_FIX_2 Fix 2).
#
# Anchor: 2026-05-13 — AH1 committed `36708ff` (mailbox(b4) → COMPLETE) from
# ~/bm-aihead1; ~/bm-b4 lagged 3 commits, so the daemon classified b4 as
# pending → "Working at: hard-deadline-audit-1" stayed for >10h after ship.
#
# Behaviour:
#   - On main / master: `fetch` + `merge --ff-only` so the local working copy
#     mirrors origin/main and `cat` reads see fresh frontmatter.
#   - On a feature branch: `fetch origin main` ONLY — mailbox reads use
#     `git show origin/main:...` (classify_mailbox branch-aware path).
#   - Quiet on every output stream; never raises a failure. A failed fetch /
#     non-fast-forward merge leaves origin/main at last-known state, which is
#     still better than the local-feature-branch read.
sync_clone_to_main() {
  local repo="$1"
  [[ -d "$repo/.git" ]] || return 0
  local current_branch
  current_branch="$(git -C "$repo" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')"

  # Quiet fetch in every case — feeds both classify_mailbox's `git show
  # origin/main:` path AND the optional ff-pull below.
  git -C "$repo" fetch origin main --quiet 2>/dev/null || true

  if [[ "$current_branch" == "main" || "$current_branch" == "master" ]]; then
    # ff-only — never touch local work. Falls through silently if not fast-
    # forwardable (e.g. local has unpushed commits).
    git -C "$repo" merge --ff-only origin/main --quiet 2>/dev/null || true
  fi
}

# extract_frontmatter_status — read YAML frontmatter `status:` field.
# Returns the value uppercased + trimmed, or empty if no frontmatter / no
# status field. Authoritative over filename suffix in classify_mailbox per
# FORGE_DAEMON_FRONTMATTER_STATUS_AUTHORITATIVE_1 — anchor: b4 CODE_4_PENDING.md
# carried `status: STAGED` (Director pivot 2026-05-11) but filename was still
# `_PENDING`, so the prior filename-only classifier reported pending → red
# card lied. Reusing the same awk frontmatter-block walker as extract_brief_name.
extract_frontmatter_status() {
  local f="$1"
  [[ -f "$f" ]] || { echo ""; return; }
  awk 'BEGIN{c=0} /^---$/{c++; if(c==2) exit; next} c==1 && /^status:[[:space:]]*/{print; exit}' "$f" 2>/dev/null \
    | sed -E 's/^status:[[:space:]]*//; s/[[:space:]]*$//' \
    | tr '[:lower:]' '[:upper:]' \
    | head -1
}

# extract_frontmatter_status_from_content — same as extract_frontmatter_status
# but reads from a content string passed via stdin (not a file). Used by
# classify_mailbox when reading mailbox state via `git show origin/main:...`
# on a feature-branch clone, where there's no local file to point awk at.
extract_frontmatter_status_from_content() {
  awk 'BEGIN{c=0} /^---$/{c++; if(c==2) exit; next} c==1 && /^status:[[:space:]]*/{print; exit}' 2>/dev/null \
    | sed -E 's/^status:[[:space:]]*//; s/[[:space:]]*$//' \
    | tr '[:lower:]' '[:upper:]' \
    | head -1
}

# classify_mailbox — find the b-code's mailbox file (if any) and return final
# classification. Frontmatter `status:` is authoritative; filename suffix is
# fallback when frontmatter is absent or carries an unknown value. Echoes
# "<status>|<path>": status in lowercase ({pending,in_progress,staged,
# complete,dropped,empty}); path is absolute (empty when no mailbox file).
#
# Filename-suffix priority when multiple files coexist mid-transition:
#   PENDING > IN_PROGRESS > STAGED > COMPLETE > DROPPED
# (Active states outrank terminal states; matches the prior PENDING-then-COMPLETE
# behaviour.)
classify_mailbox() {
  local repo="$1"
  local n="$2"
  local f="" filename_status="" fm_status="" final_status=""
  local suffix candidate

  # BRISEN_LAB_CARD_STATE_FIX_2 Fix 2: when the clone is on a feature branch,
  # local main is frequently stale (B-codes don't auto-pull). Read mailbox
  # state from origin/main instead. sync_clone_to_main() runs before this
  # call to keep the cached origin/main ref fresh.
  local current_branch
  current_branch="$(git -C "$repo" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')"
  local read_from_origin_main=0
  if [[ "$current_branch" != "main" && "$current_branch" != "master" && "$current_branch" != "?" ]]; then
    read_from_origin_main=1
  fi

  # First pass: find the active suffix using the local working copy. Same
  # suffix priority order on both branches — `_PENDING.md` wins over
  # `_COMPLETE.md` etc. when both files coexist mid-transition.
  for suffix in PENDING IN_PROGRESS STAGED COMPLETE DROPPED; do
    candidate="$repo/briefs/_tasks/CODE_${n}_${suffix}.md"
    if [[ "$read_from_origin_main" == "1" ]]; then
      # Probe origin/main for the same filename; if any of the 5 candidates
      # exists in origin/main, pick the highest-priority one.
      if git -C "$repo" cat-file -e "origin/main:briefs/_tasks/CODE_${n}_${suffix}.md" 2>/dev/null; then
        f="$candidate"
        filename_status="$(echo "$suffix" | tr '[:upper:]' '[:lower:]')"
        break
      fi
    else
      if [[ -f "$candidate" ]]; then
        f="$candidate"
        filename_status="$(echo "$suffix" | tr '[:upper:]' '[:lower:]')"
        break
      fi
    fi
  done

  if [[ -z "$f" ]]; then
    # Feature-branch fallback: if origin/main lookup found nothing (e.g.
    # origin/main never fetched, or no mailbox file at all upstream), try
    # the local file once more so a freshly-cloned worktree still classifies
    # correctly before its first fetch.
    if [[ "$read_from_origin_main" == "1" ]]; then
      for suffix in PENDING IN_PROGRESS STAGED COMPLETE DROPPED; do
        candidate="$repo/briefs/_tasks/CODE_${n}_${suffix}.md"
        if [[ -f "$candidate" ]]; then
          f="$candidate"
          filename_status="$(echo "$suffix" | tr '[:upper:]' '[:lower:]')"
          read_from_origin_main=0  # local fallback won — read content from disk
          break
        fi
      done
    fi
  fi

  if [[ -z "$f" ]]; then
    # Three-field output for parser consistency with snapshot_one's IFS='|' read.
    echo "empty||"
    return
  fi

  if [[ "$read_from_origin_main" == "1" ]]; then
    # Stream the file content out of origin/main and pipe through the
    # content-mode frontmatter parser. Path is repo-relative. Re-uppercase
    # filename_status via `tr` (avoid bash-4 `${var^^}` — macOS ships 3.2).
    local rel_path="briefs/_tasks/CODE_${n}_$(echo "$filename_status" | tr '[:lower:]' '[:upper:]').md"
    fm_status="$(git -C "$repo" show "origin/main:${rel_path}" 2>/dev/null \
      | extract_frontmatter_status_from_content)"
  else
    fm_status="$(extract_frontmatter_status "$f")"
  fi

  if [[ -n "$fm_status" ]]; then
    case "$fm_status" in
      PENDING)     final_status="pending" ;;
      IN_PROGRESS) final_status="in_progress" ;;
      STAGED)      final_status="staged" ;;
      COMPLETE)    final_status="complete" ;;
      DROPPED)     final_status="dropped" ;;
      *)           final_status="$filename_status" ;;
    esac
  else
    final_status="$filename_status"
  fi
  # Third field communicates source-of-truth to snapshot_one so extract_brief_name
  # uses the matching reader (file-mode vs content-from-origin-main mode).
  # BRISEN_LAB_CARD_STATE_FIX_2-v0-2 HIGH: prior 2-field output left snapshot_one
  # blind to feature-branch-without-local-file case → blank card subtitle.
  local source="local"
  if [[ "$read_from_origin_main" == "1" ]]; then
    source="origin_main"
  fi
  echo "${final_status}|${f}|${source}"
}

# extract_brief_name — three-step fallback parser. Returns up to 200 chars.
#   1. YAML frontmatter `brief:` field (between first `---` and second `---`)
#   2. First `# heading` anywhere in the file
#   3. Explicit `(unparseable)` marker — architect-folded 2026-05-13: filename
#      slug fallback (e.g. CODE_4_PENDING) was useless noise; explicit marker
#      surfaces the failure mode to a card reader.
extract_brief_name() {
  local f="$1"
  [[ -f "$f" ]] || { echo ""; return; }

  # Step 1: YAML frontmatter `brief:` field (between first --- and second ---).
  # awk: count '---' lines; while in block (c==1), match brief: lines.
  # Reviewer-folded 2026-05-13: regex is `[[:space:]]*` (zero-or-more) so we
  # accept `brief:value` (no space, valid minimal YAML) as well as `brief: value`
  # and `brief:\tvalue`. The brief's edge-case note claimed this; the original
  # `[[:space:]]` (exactly one) contradicted it.
  local brief_line
  brief_line="$(awk 'BEGIN{c=0} /^---$/{c++; if(c==2) exit; next} c==1 && /^brief:[[:space:]]*/{print; exit}' "$f" 2>/dev/null \
    | sed -E 's/^brief:[[:space:]]*//; s/[[:space:]]*$//' \
    | head -1)"
  if [[ -n "$brief_line" ]]; then
    # Strip directory prefix + .md suffix, take basename.
    local base
    base="$(basename "${brief_line%.md}")"
    echo "$base" | head -c 200
    return
  fi

  # Step 2: first '# ' heading anywhere in file.
  local heading
  heading="$(grep -m1 '^# ' "$f" 2>/dev/null | sed 's/^# *//' | head -c 200)"
  if [[ -n "$heading" ]]; then
    echo "$heading"
    return
  fi

  # Step 3: explicit failure marker.
  echo "(unparseable)"
}

# extract_brief_name_from_content — same fallback chain as extract_brief_name
# but reads from stdin. Used by snapshot_one when classify_mailbox sourced the
# mailbox from origin/main (feature-branch clone, no local file present yet).
# BRISEN_LAB_CARD_STATE_FIX_2-v0-2 HIGH: previously extract_brief_name was
# called on the local path and silently returned empty when the file didn't
# exist locally → blank card subtitle even though origin/main had a brief.
extract_brief_name_from_content() {
  local content
  content="$(cat)"
  [[ -z "$content" ]] && { echo ""; return; }

  # Step 1: YAML frontmatter `brief:` field.
  local brief_line
  brief_line="$(printf '%s\n' "$content" \
    | awk 'BEGIN{c=0} /^---$/{c++; if(c==2) exit; next} c==1 && /^brief:[[:space:]]*/{print; exit}' \
    | sed -E 's/^brief:[[:space:]]*//; s/[[:space:]]*$//' \
    | head -1)"
  if [[ -n "$brief_line" ]]; then
    local base
    base="$(basename "${brief_line%.md}")"
    echo "$base" | head -c 200
    return
  fi

  # Step 2: first '# ' heading.
  local heading
  heading="$(printf '%s\n' "$content" | grep -m1 '^# ' | sed 's/^# *//' | head -c 200)"
  if [[ -n "$heading" ]]; then
    echo "$heading"
    return
  fi

  # Step 3: explicit failure marker.
  echo "(unparseable)"
}

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

  # Mailbox state. b-codes have CODE_N_{PENDING,IN_PROGRESS,STAGED,COMPLETE,
  # DROPPED}.md slots; lead/deputy do not. classify_mailbox finds the active
  # file (filename priority order) and applies frontmatter `status:` as the
  # authoritative classification — so a `_PENDING` filename carrying
  # `status: DROPPED` reports as dropped (the b4 drift this brief fixes).
  local mailbox_status="n/a"
  local mailbox_brief_name=""
  local mailbox_path=""
  local mailbox_source=""
  if [[ "$alias" =~ ^b([1-9])$ ]]; then
    local n="${BASH_REMATCH[1]}"
    local mbox_class
    mbox_class="$(classify_mailbox "$repo" "$n")"
    # classify_mailbox now emits 3 fields: status|path|source. source ∈ {local,origin_main}.
    # BRISEN_LAB_CARD_STATE_FIX_2-v0-2 HIGH: route brief-name extraction to the
    # matching reader so feature-branch clones without the local file still
    # surface the brief.
    IFS='|' read -r mailbox_status mailbox_path mailbox_source <<< "$mbox_class"
    if [[ -n "$mailbox_path" ]]; then
      if [[ "$mailbox_source" == "origin_main" ]]; then
        local rel_path="${mailbox_path#${repo}/}"
        mailbox_brief_name="$(git -C "$repo" show "origin/main:${rel_path}" 2>/dev/null \
          | extract_brief_name_from_content)"
      else
        mailbox_brief_name="$(extract_brief_name "$mailbox_path")"
      fi
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

  # Test-only payload dump hook (Fix 4.2). Lets the harness assert on JSON
  # fields without standing up an HTTP receiver. Empty / "0" / unset disables.
  if [[ "${DEBUG_DUMP_PAYLOAD:-0}" == "1" ]]; then
    echo "PAYLOAD_DUMP:$payload" >&2
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

# Iterate. Per-terminal failures are isolated. pick_active_clone() chooses the
# right clone per alias; sync_clone_to_main() then refreshes origin/main so
# classify_mailbox can read upstream state even when the clone is on a
# feature branch (BRISEN_LAB_CARD_STATE_FIX_2 Fix 2).
#
# Disable per-cycle sync via FORGE_SYNC_DISABLED=1 in test fixtures.
for entry in "${TERMINALS[@]}"; do
  alias="${entry%%:*}"
  paths_csv="${entry#*:}"
  repo="$(pick_active_clone "$alias" "$paths_csv")"
  if [[ "${FORGE_SYNC_DISABLED:-0}" != "1" ]]; then
    sync_clone_to_main "$repo" || true
  fi
  snapshot_one "$alias" "$repo" || true
done

exit 0
