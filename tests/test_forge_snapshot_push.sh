#!/usr/bin/env bash
# Smoke test for forge_snapshot_push.sh state collection.
#
# Seven fixtures exercise the daemon end-to-end without POSTing to a real
# endpoint (LAB_URL="http://127.0.0.1:1" → curl exits 000; we only validate
# state-collection, not HTTP transport):
#
#   Case A — heading-style mailbox, single clone (legacy fixture)
#   Case B — YAML frontmatter mailbox; extract_brief_name reads `brief:` field
#   Case C — two-clone alias picks pending-mailbox clone over older single
#   Case D — two-clone alias falls back to recency tiebreaker when neither has mailbox
#   Case E — two non-git candidate paths fall back to first; daemon still POSTs
#   Case F — two-clone alias picks COMPLETE-mailbox clone over empty sibling (+50 > 0)
#   Case G — frontmatter `status: DROPPED` authoritative over filename `_PENDING` suffix
#
# Cases B/C/D/E added in BRISEN_LAB_CARD_STATE_FIX_1 (Fix 4.1).
# Cases F/G added in FORGE_DAEMON_FRONTMATTER_STATUS_AUTHORITATIVE_1.

set -euo pipefail

SCRIPT="$(cd "$(dirname "$0")/.." && pwd)/scripts/forge_snapshot_push.sh"
[[ -f "$SCRIPT" ]] || { echo "Missing: $SCRIPT" >&2; exit 1; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

run_daemon() {
  # Runs the script with a fresh LOCK_DIR per case so prior cases don't block
  # the next. Returns combined stdout+stderr to caller's stdout.
  local case_label="$1"
  local override="$2"
  local lock_dir="$TMP/lock-${case_label}"
  LAB_URL="http://127.0.0.1:1" \
  FORGE_KEY="test-key" \
  PR_LOOKUP_ENABLED=0 \
  DEBUG_DUMP_PAYLOAD=1 \
  LOCK_DIR="$lock_dir" \
  TERMINALS_OVERRIDE="$override" \
  bash "$SCRIPT" 2>&1 || true
}

assert_no_prod_aliases() {
  local output_file="$1"
  for alias in lead deputy b1 b2 b3 b4; do
    if grep -q "\[forge-push\] ${alias}:" "$output_file"; then
      echo "FAIL: production alias '$alias' processed despite TERMINALS_OVERRIDE" >&2
      exit 1
    fi
  done
}

# Extract the JSON payload for a given alias from a PAYLOAD_DUMP line. Uses
# python for JSON-aware field extraction (order-agnostic).
extract_payload_field() {
  local output_file="$1"
  local alias="$2"
  local field="$3"
  grep "^PAYLOAD_DUMP:" "$output_file" \
    | sed 's/^PAYLOAD_DUMP://' \
    | python3 -c "
import json, sys
for line in sys.stdin:
    try:
        d = json.loads(line)
    except Exception:
        continue
    if d.get('terminal_alias') == '$alias':
        v = d.get('$field')
        print('' if v is None else v)
        break
"
}

# ─────────────────────────────────────────────────────────────────────────────
# Case A — heading-style mailbox, single clone (legacy fixture, preserved).
# ─────────────────────────────────────────────────────────────────────────────
CASE_A_REPO="$TMP/case-a-b9"
mkdir -p "$CASE_A_REPO/briefs/_tasks"
(
  cd "$CASE_A_REPO"
  git init -q
  git config user.email "test@example.com"
  git config user.name "Test"
  echo "# CODE_9_PENDING — TEST_BRIEF_FORGE_PUSH_FOLD" > briefs/_tasks/CODE_9_PENDING.md
  git add .
  git commit -q -m "fixture A commit"
)
OUT_A="$TMP/case-a.log"
run_daemon "a" "b9:$CASE_A_REPO" > "$OUT_A"
[[ "$(grep -c '\[forge-push\] b9:' "$OUT_A" || true)" -ge 1 ]] \
  || { echo "FAIL: Case A — no b9 stderr line; coverage gap" >&2; cat "$OUT_A" >&2; exit 1; }
assert_no_prod_aliases "$OUT_A"
brief_a="$(extract_payload_field "$OUT_A" b9 mailbox_brief_name)"
[[ "$brief_a" == "CODE_9_PENDING — TEST_BRIEF_FORGE_PUSH_FOLD" ]] \
  || { echo "FAIL: Case A — mailbox_brief_name='$brief_a' (expected heading extraction)" >&2; exit 1; }
echo "PASS: Case A — heading-style mailbox, single clone."

# ─────────────────────────────────────────────────────────────────────────────
# Case B — YAML frontmatter mailbox; extract_brief_name reads `brief:` field.
# ─────────────────────────────────────────────────────────────────────────────
CASE_B_REPO="$TMP/case-b-b9"
mkdir -p "$CASE_B_REPO/briefs/_tasks"
(
  cd "$CASE_B_REPO"
  git init -q
  git config user.email "test@example.com"
  git config user.name "Test"
  cat > briefs/_tasks/CODE_9_PENDING.md <<'YAML'
---
status: PENDING
brief: ~/baker-vault/_ops/briefs/FAKE_FRONTMATTER_BRIEF_1.md
target: b9
---
# CODE_9_PENDING — should NOT be extracted because frontmatter wins
YAML
  git add .
  git commit -q -m "fixture B commit"
)
OUT_B="$TMP/case-b.log"
run_daemon "b" "b9:$CASE_B_REPO" > "$OUT_B"
brief_b="$(extract_payload_field "$OUT_B" b9 mailbox_brief_name)"
[[ "$brief_b" == "FAKE_FRONTMATTER_BRIEF_1" ]] \
  || { echo "FAIL: Case B — mailbox_brief_name='$brief_b' (expected 'FAKE_FRONTMATTER_BRIEF_1' from frontmatter)" >&2; exit 1; }
assert_no_prod_aliases "$OUT_B"
echo "PASS: Case B — YAML frontmatter mailbox extracts brief: field."

# ─────────────────────────────────────────────────────────────────────────────
# Case C — two-clone alias picks pending-mailbox clone (older) over recent clean.
# ─────────────────────────────────────────────────────────────────────────────
CASE_C_REPO_A="$TMP/case-c-bm-b9"             # No mailbox, RECENT commit.
CASE_C_REPO_B="$TMP/case-c-bm-b9-brisen-lab"  # Pending mailbox, OLDER commit.
mkdir -p "$CASE_C_REPO_A" "$CASE_C_REPO_B/briefs/_tasks"
(
  cd "$CASE_C_REPO_B"
  git init -q
  git config user.email "test@example.com"
  git config user.name "Test"
  cat > briefs/_tasks/CODE_9_PENDING.md <<'YAML'
---
status: PENDING
brief: WORKTREE_AWARE_PICK_BRIEF
---
YAML
  git add .
  # Older commit (yesterday).
  GIT_AUTHOR_DATE="2026-05-11T08:00:00Z" GIT_COMMITTER_DATE="2026-05-11T08:00:00Z" \
    git commit -q -m "fixture C-B commit (older)"
)
(
  cd "$CASE_C_REPO_A"
  git init -q
  git config user.email "test@example.com"
  git config user.name "Test"
  echo "noop" > README.md
  git add .
  # Recent commit (today).
  GIT_AUTHOR_DATE="2026-05-13T08:00:00Z" GIT_COMMITTER_DATE="2026-05-13T08:00:00Z" \
    git commit -q -m "fixture C-A commit (recent, no mailbox)"
)
OUT_C="$TMP/case-c.log"
run_daemon "c" "b9:$CASE_C_REPO_A,$CASE_C_REPO_B" > "$OUT_C"
brief_c="$(extract_payload_field "$OUT_C" b9 mailbox_brief_name)"
status_c="$(extract_payload_field "$OUT_C" b9 mailbox_status)"
[[ "$status_c" == "pending" && "$brief_c" == "WORKTREE_AWARE_PICK_BRIEF" ]] \
  || { echo "FAIL: Case C — picked wrong clone: mailbox_status='$status_c' brief='$brief_c' (expected pending/WORKTREE_AWARE_PICK_BRIEF)" >&2; cat "$OUT_C" >&2; exit 1; }
assert_no_prod_aliases "$OUT_C"
echo "PASS: Case C — two-clone alias picks pending-mailbox clone (overrides recency)."

# ─────────────────────────────────────────────────────────────────────────────
# Case D — two-clone alias falls back to recency tiebreaker (neither has mailbox).
# ─────────────────────────────────────────────────────────────────────────────
CASE_D_REPO_OLD="$TMP/case-d-old"
CASE_D_REPO_NEW="$TMP/case-d-new"
mkdir -p "$CASE_D_REPO_OLD" "$CASE_D_REPO_NEW"
(
  cd "$CASE_D_REPO_OLD"
  git init -q
  git config user.email "test@example.com"
  git config user.name "Test"
  echo "old" > README.md
  git add .
  GIT_AUTHOR_DATE="2026-05-01T08:00:00Z" GIT_COMMITTER_DATE="2026-05-01T08:00:00Z" \
    git commit -q -m "fixture D-old commit"
)
(
  cd "$CASE_D_REPO_NEW"
  git init -q
  git config user.email "test@example.com"
  git config user.name "Test"
  echo "new" > README.md
  git add .
  GIT_AUTHOR_DATE="2026-05-13T08:00:00Z" GIT_COMMITTER_DATE="2026-05-13T08:00:00Z" \
    git commit -q -m "fixture D-new commit"
)
OUT_D="$TMP/case-d.log"
run_daemon "d" "b9:$CASE_D_REPO_OLD,$CASE_D_REPO_NEW" > "$OUT_D"
# Both repos have no mailbox → mailbox_status=empty. The winning clone should
# be the newer one — but mailbox_status alone doesn't tell us which clone won.
# Use git_head_subject (per-clone) as the discriminator.
subject_d="$(extract_payload_field "$OUT_D" b9 git_head_subject)"
[[ "$subject_d" == "fixture D-new commit" ]] \
  || { echo "FAIL: Case D — tiebreaker picked wrong clone: git_head_subject='$subject_d' (expected 'fixture D-new commit')" >&2; cat "$OUT_D" >&2; exit 1; }
assert_no_prod_aliases "$OUT_D"
echo "PASS: Case D — two-clone alias falls back to recency tiebreaker."

# ─────────────────────────────────────────────────────────────────────────────
# Case E — two non-git candidate paths fall back to first; daemon still POSTs.
# Locks down the empty-/no-.git edge case that surfaced the IFS-leak bug
# during reviewer pass (architect-required).
# ─────────────────────────────────────────────────────────────────────────────
CASE_E_DIR_A="$TMP/case-e-empty-a"
CASE_E_DIR_B="$TMP/case-e-empty-b"
mkdir -p "$CASE_E_DIR_A" "$CASE_E_DIR_B"
OUT_E="$TMP/case-e.log"
run_daemon "e" "b9:$CASE_E_DIR_A,$CASE_E_DIR_B" > "$OUT_E"
# Expectation: pick_active_clone returns "$CASE_E_DIR_A" (first candidate);
# snapshot_one then logs the "repo missing at $CASE_E_DIR_A" line because
# neither candidate has a .git, but the daemon does not crash and does emit
# the expected stderr signal. Downstream UI shows grey.
grep -q "\[forge-push\] b9: repo missing at $CASE_E_DIR_A, skipping" "$OUT_E" \
  || { echo "FAIL: Case E — expected 'repo missing at $CASE_E_DIR_A' line; daemon did not fall back to first candidate" >&2; cat "$OUT_E" >&2; exit 1; }
# Daemon should NOT have crashed (script exit 0 baked into run_daemon || true,
# but check that production aliases weren't iterated as fallback).
assert_no_prod_aliases "$OUT_E"
echo "PASS: Case E — two non-git candidate paths fall back to first; daemon still emits stderr without crash."

# ─────────────────────────────────────────────────────────────────────────────
# Case F — two-clone alias picks COMPLETE-mailbox clone over empty sibling.
# Anchor: hotfix f5012a9 (2026-05-12 eve) added COMPLETE → +50 scoring so the
# post-merge clone doesn't tie at 0 with a no-mailbox sibling and oscillate
# off via recency tiebreaker. The fix shipped; this fixture locks it down.
# ─────────────────────────────────────────────────────────────────────────────
CASE_F_REPO_A="$TMP/case-f-clone-a"  # has CODE_9_COMPLETE.md (older commit)
CASE_F_REPO_B="$TMP/case-f-clone-b"  # empty mailbox, newer commit
mkdir -p "$CASE_F_REPO_A/briefs/_tasks" "$CASE_F_REPO_B"
(
  cd "$CASE_F_REPO_A"
  git init -q
  git config user.email "test@example.com"
  git config user.name "Test"
  cat > briefs/_tasks/CODE_9_COMPLETE.md <<'YAML'
---
status: COMPLETE
brief: COMPLETED_BRIEF_1
---
YAML
  git add .
  GIT_AUTHOR_DATE="2026-05-12T08:00:00Z" GIT_COMMITTER_DATE="2026-05-12T08:00:00Z" \
    git commit -q -m "fixture F-A commit (COMPLETE mailbox, older)"
)
(
  cd "$CASE_F_REPO_B"
  git init -q
  git config user.email "test@example.com"
  git config user.name "Test"
  echo "noop" > README.md
  git add .
  GIT_AUTHOR_DATE="2026-05-14T08:00:00Z" GIT_COMMITTER_DATE="2026-05-14T08:00:00Z" \
    git commit -q -m "fixture F-B commit (newer, empty mailbox)"
)
OUT_F="$TMP/case-f.log"
run_daemon "f" "b9:$CASE_F_REPO_A,$CASE_F_REPO_B" > "$OUT_F"
status_f="$(extract_payload_field "$OUT_F" b9 mailbox_status)"
brief_f="$(extract_payload_field "$OUT_F" b9 mailbox_brief_name)"
[[ "$status_f" == "complete" && "$brief_f" == "COMPLETED_BRIEF_1" ]] \
  || { echo "FAIL: Case F — picked wrong clone: mailbox_status='$status_f' brief='$brief_f' (expected complete/COMPLETED_BRIEF_1; COMPLETE +50 must beat empty +0 even with newer recency)" >&2; cat "$OUT_F" >&2; exit 1; }
assert_no_prod_aliases "$OUT_F"
echo "PASS: Case F — two-clone alias picks COMPLETE-mailbox clone over empty sibling."

# ─────────────────────────────────────────────────────────────────────────────
# Case G — frontmatter `status: DROPPED` authoritative over filename `_PENDING`.
# Anchor: b4 CODE_4_PENDING.md carried `status: STAGED` (Director pivot
# 2026-05-11) but filename was still `_PENDING` → daemon's filename-only
# classifier reported pending → red card lied. This fixture asserts the new
# frontmatter-authoritative path (also exercises the dropped classification
# end-to-end, which previously had no representation in the daemon vocabulary).
# ─────────────────────────────────────────────────────────────────────────────
CASE_G_REPO="$TMP/case-g-b9"
mkdir -p "$CASE_G_REPO/briefs/_tasks"
(
  cd "$CASE_G_REPO"
  git init -q
  git config user.email "test@example.com"
  git config user.name "Test"
  cat > briefs/_tasks/CODE_9_PENDING.md <<'YAML'
---
status: DROPPED
brief: DROPPED_VIA_FRONTMATTER_1
target: b9
---
# CODE_9_PENDING — filename says PENDING but frontmatter says DROPPED
YAML
  git add .
  git commit -q -m "fixture G commit (frontmatter drift)"
)
OUT_G="$TMP/case-g.log"
run_daemon "g" "b9:$CASE_G_REPO" > "$OUT_G"
status_g="$(extract_payload_field "$OUT_G" b9 mailbox_status)"
brief_g="$(extract_payload_field "$OUT_G" b9 mailbox_brief_name)"
[[ "$status_g" == "dropped" ]] \
  || { echo "FAIL: Case G — frontmatter status DROPPED not applied: mailbox_status='$status_g' (expected 'dropped'; filename _PENDING suffix must NOT override frontmatter)" >&2; cat "$OUT_G" >&2; exit 1; }
[[ "$brief_g" == "DROPPED_VIA_FRONTMATTER_1" ]] \
  || { echo "FAIL: Case G — brief extraction broken: '$brief_g' (expected 'DROPPED_VIA_FRONTMATTER_1')" >&2; exit 1; }
assert_no_prod_aliases "$OUT_G"
echo "PASS: Case G — frontmatter status: DROPPED authoritative over filename _PENDING suffix."

echo ""
echo "All 7 cases PASS."
