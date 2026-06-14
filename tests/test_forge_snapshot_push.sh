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
  for alias in lead deputy deputy-codex b1 b2 b3 b4; do
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

# ─────────────────────────────────────────────────────────────────────────────
# Case H — BRISEN_LAB_CARD_STATE_FIX_2 Fix 2: B-code on feature branch, local
# main lags origin/main, origin/main has COMPLETE mailbox. Classifier MUST
# read from origin/main (not the local file from the feature branch) and
# return "complete".
#
# Anchor: 2026-05-13 — AH1 committed mailbox(b4) → COMPLETE from ~/bm-aihead1;
# ~/bm-b4 was on a feature branch with stale local main, so the daemon
# reported "Working at: hard-deadline-audit-1" for >10h post-ship.
# ─────────────────────────────────────────────────────────────────────────────
CASE_H_ORIGIN="$TMP/case-h-origin.git"
CASE_H_CLONE="$TMP/case-h-clone"
git init -q --bare "$CASE_H_ORIGIN"

# Seed origin/main with a PENDING mailbox, push.
SEED_DIR="$TMP/case-h-seed"
mkdir -p "$SEED_DIR/briefs/_tasks"
(
  cd "$SEED_DIR"
  git init -q -b main
  git config user.email "test@example.com"
  git config user.name "Test"
  cat > briefs/_tasks/CODE_9_PENDING.md <<'YAML'
---
status: PENDING
brief: STILL_RUNNING_BRIEF_1
target: b9
---
YAML
  git add .
  git commit -q -m "seed: PENDING mailbox"
  git remote add origin "$CASE_H_ORIGIN"
  git push -q origin main
)

# Clone into CASE_H_CLONE (pulls origin/main at PENDING).
git clone -q --branch main "$CASE_H_ORIGIN" "$CASE_H_CLONE"
(
  cd "$CASE_H_CLONE"
  git config user.email "test@example.com"
  git config user.name "Test"
  # Move to a feature branch BEFORE origin/main flips.
  git checkout -q -b b9/some-feature
  echo "feature-branch-work" > feature.txt
  git add feature.txt
  git commit -q -m "feature commit"
)

# Now flip origin/main → COMPLETE behind the clone's back.
(
  cd "$SEED_DIR"
  cat > briefs/_tasks/CODE_9_PENDING.md <<'YAML'
---
status: COMPLETE
brief: STILL_RUNNING_BRIEF_1
target: b9
---
YAML
  git add briefs/_tasks/CODE_9_PENDING.md
  git commit -q -m "flip mailbox → COMPLETE"
  git push -q origin main
)

# Crucial: the test must NOT auto-sync the clone (because sync_clone_to_main
# runs origin fetch + ff-pull and would update the clone). We want to verify
# the script ALSO does sync_clone_to_main itself, so let it run normally —
# but verify that EVEN IF FORGE_SYNC_DISABLED=1 short-circuits the sync,
# classify_mailbox still pulls from origin/main using the clone's existing
# remote-tracking ref.
#
# Step 1: pre-fetch the clone so origin/main remote-tracking ref carries
# the COMPLETE flip (mimics what sync_clone_to_main would do at the top of
# the iteration), then run with FORGE_SYNC_DISABLED=1 to prove the
# classify_mailbox branch path reads from origin/main without help.
git -C "$CASE_H_CLONE" fetch -q origin main

OUT_H="$TMP/case-h.log"
LAB_URL="http://127.0.0.1:1" \
FORGE_KEY="test-key" \
PR_LOOKUP_ENABLED=0 \
DEBUG_DUMP_PAYLOAD=1 \
LOCK_DIR="$TMP/lock-h" \
TERMINALS_OVERRIDE="b9:$CASE_H_CLONE" \
FORGE_SYNC_DISABLED=1 \
bash "$SCRIPT" > "$OUT_H" 2>&1 || true

status_h="$(extract_payload_field "$OUT_H" b9 mailbox_status)"
brief_h="$(extract_payload_field "$OUT_H" b9 mailbox_brief_name)"
[[ "$status_h" == "complete" ]] \
  || { echo "FAIL: Case H — feature-branch read from origin/main: mailbox_status='$status_h' (expected 'complete'; classify_mailbox must read upstream)" >&2; cat "$OUT_H" >&2; exit 1; }
[[ "$brief_h" == "STILL_RUNNING_BRIEF_1" ]] \
  || { echo "FAIL: Case H — brief from origin/main: '$brief_h' (expected 'STILL_RUNNING_BRIEF_1')" >&2; exit 1; }
assert_no_prod_aliases "$OUT_H"
echo "PASS: Case H — feature-branch clone reads mailbox state from origin/main."

# ─────────────────────────────────────────────────────────────────────────────
# Case I — Regression check on FIX_1: clone is on main and matches origin/main.
# Classifier MUST still return the frontmatter status from the local file.
# This locks down that the feature-branch path does not corrupt the main-branch
# read.
# ─────────────────────────────────────────────────────────────────────────────
CASE_I_REPO="$TMP/case-i-b9"
mkdir -p "$CASE_I_REPO/briefs/_tasks"
(
  cd "$CASE_I_REPO"
  git init -q -b main
  git config user.email "test@example.com"
  git config user.name "Test"
  cat > briefs/_tasks/CODE_9_PENDING.md <<'YAML'
---
status: PENDING
brief: ON_MAIN_BRIEF_1
target: b9
---
YAML
  git add .
  git commit -q -m "fixture I: on main, PENDING"
)
OUT_I="$TMP/case-i.log"
run_daemon "i" "b9:$CASE_I_REPO" > "$OUT_I"
status_i="$(extract_payload_field "$OUT_I" b9 mailbox_status)"
brief_i="$(extract_payload_field "$OUT_I" b9 mailbox_brief_name)"
[[ "$status_i" == "pending" ]] \
  || { echo "FAIL: Case I — on-main regression: mailbox_status='$status_i' (expected 'pending'; FIX_1 frontmatter-authoritative path must still work)" >&2; cat "$OUT_I" >&2; exit 1; }
[[ "$brief_i" == "ON_MAIN_BRIEF_1" ]] \
  || { echo "FAIL: Case I — on-main brief extraction: '$brief_i' (expected 'ON_MAIN_BRIEF_1')" >&2; exit 1; }
assert_no_prod_aliases "$OUT_I"
echo "PASS: Case I — on-main clone uses local frontmatter (FIX_1 regression check)."

# ─────────────────────────────────────────────────────────────────────────────
# Case H' — BRISEN_LAB_CARD_STATE_FIX_2-v0-2 MEDIUM 1: integration check that
# sync_clone_to_main + classify_mailbox work end-to-end WITHOUT FORGE_SYNC_DISABLED
# and WITHOUT pre-fetching origin/main. The script must do the fetch itself.
#
# Case H pre-fetched + ran with FORGE_SYNC_DISABLED=1 so it only exercised the
# branch-aware read path. This case proves the full pipeline.
# ─────────────────────────────────────────────────────────────────────────────
CASE_HP_ORIGIN="$TMP/case-hp-origin.git"
CASE_HP_CLONE="$TMP/case-hp-clone"
git init -q --bare "$CASE_HP_ORIGIN"

SEED_HP_DIR="$TMP/case-hp-seed"
mkdir -p "$SEED_HP_DIR/briefs/_tasks"
(
  cd "$SEED_HP_DIR"
  git init -q -b main
  git config user.email "test@example.com"
  git config user.name "Test"
  cat > briefs/_tasks/CODE_9_PENDING.md <<'YAML'
---
status: PENDING
brief: INTEGRATION_CHECK_BRIEF_1
target: b9
---
YAML
  git add .
  git commit -q -m "seed: PENDING mailbox"
  git remote add origin "$CASE_HP_ORIGIN"
  git push -q origin main
)

git clone -q --branch main "$CASE_HP_ORIGIN" "$CASE_HP_CLONE"
(
  cd "$CASE_HP_CLONE"
  git config user.email "test@example.com"
  git config user.name "Test"
  git checkout -q -b b9/feature-hp
  echo "feature-work-hp" > feature.txt
  git add feature.txt
  git commit -q -m "feature commit hp"
)

# Flip origin/main → COMPLETE behind the clone's back; clone is NOT pre-fetched.
(
  cd "$SEED_HP_DIR"
  cat > briefs/_tasks/CODE_9_PENDING.md <<'YAML'
---
status: COMPLETE
brief: INTEGRATION_CHECK_BRIEF_1
target: b9
---
YAML
  git add briefs/_tasks/CODE_9_PENDING.md
  git commit -q -m "flip mailbox → COMPLETE"
  git push -q origin main
)

# Run daemon WITH sync enabled (no FORGE_SYNC_DISABLED) — sync_clone_to_main
# must do the fetch itself before classify_mailbox needs origin/main.
OUT_HP="$TMP/case-hp.log"
LAB_URL="http://127.0.0.1:1" \
FORGE_KEY="test-key" \
PR_LOOKUP_ENABLED=0 \
DEBUG_DUMP_PAYLOAD=1 \
LOCK_DIR="$TMP/lock-hp" \
TERMINALS_OVERRIDE="b9:$CASE_HP_CLONE" \
bash "$SCRIPT" > "$OUT_HP" 2>&1 || true

status_hp="$(extract_payload_field "$OUT_HP" b9 mailbox_status)"
brief_hp="$(extract_payload_field "$OUT_HP" b9 mailbox_brief_name)"
[[ "$status_hp" == "complete" ]] \
  || { echo "FAIL: Case H' — sync_clone_to_main+classify_mailbox integration: mailbox_status='$status_hp' (expected 'complete'; daemon must fetch origin/main itself)" >&2; cat "$OUT_HP" >&2; exit 1; }
[[ "$brief_hp" == "INTEGRATION_CHECK_BRIEF_1" ]] \
  || { echo "FAIL: Case H' — brief after sync+classify: '$brief_hp' (expected 'INTEGRATION_CHECK_BRIEF_1')" >&2; cat "$OUT_HP" >&2; exit 1; }
assert_no_prod_aliases "$OUT_HP"
echo "PASS: Case H' — sync_clone_to_main + classify_mailbox integrate end-to-end without pre-fetch."

# ─────────────────────────────────────────────────────────────────────────────
# Case J — BRISEN_LAB_CARD_STATE_FIX_2-v0-2 HIGH: feature-branch clone with
# NO local mailbox file; origin/main has the mailbox with frontmatter `brief:`.
# Classifier must source via origin/main AND extract_brief_name_from_content
# must populate mailbox_brief_name from upstream content.
#
# Anchor (real-world trigger): B-code creates feature branch BEFORE AH1
# dispatches a brief to main. The feature branch's working tree never receives
# the new CODE_N_PENDING.md. Pre-fix: blank card subtitle because
# extract_brief_name short-circuited on the missing local file.
# ─────────────────────────────────────────────────────────────────────────────
CASE_J_ORIGIN="$TMP/case-j-origin.git"
CASE_J_CLONE="$TMP/case-j-clone"
git init -q --bare "$CASE_J_ORIGIN"

# Step 1: seed origin/main WITHOUT any mailbox. Clone, branch off — clone never
# sees a mailbox file in its working tree.
SEED_J_DIR="$TMP/case-j-seed"
mkdir -p "$SEED_J_DIR"
(
  cd "$SEED_J_DIR"
  git init -q -b main
  git config user.email "test@example.com"
  git config user.name "Test"
  echo "initial" > README.md
  git add .
  git commit -q -m "seed: no mailbox yet"
  git remote add origin "$CASE_J_ORIGIN"
  git push -q origin main
)

git clone -q --branch main "$CASE_J_ORIGIN" "$CASE_J_CLONE"
(
  cd "$CASE_J_CLONE"
  git config user.email "test@example.com"
  git config user.name "Test"
  git checkout -q -b b9/feature-j
  echo "feature-pre-dispatch" > feature.txt
  git add feature.txt
  git commit -q -m "feature commit before mailbox exists"
)

# Step 2: seed dir adds the mailbox + pushes. Clone has stale main + feature branch.
(
  cd "$SEED_J_DIR"
  mkdir -p briefs/_tasks
  cat > briefs/_tasks/CODE_9_PENDING.md <<'YAML'
---
status: PENDING
brief: ORIGIN_ONLY_BRIEF_1
target: b9
---
YAML
  git add briefs/_tasks/CODE_9_PENDING.md
  git commit -q -m "add mailbox after feature branch was cut"
  git push -q origin main
)

OUT_J="$TMP/case-j.log"
LAB_URL="http://127.0.0.1:1" \
FORGE_KEY="test-key" \
PR_LOOKUP_ENABLED=0 \
DEBUG_DUMP_PAYLOAD=1 \
LOCK_DIR="$TMP/lock-j" \
TERMINALS_OVERRIDE="b9:$CASE_J_CLONE" \
bash "$SCRIPT" > "$OUT_J" 2>&1 || true

# Sanity: confirm there's no local file (the path classify_mailbox returns
# points at a path that doesn't exist on disk; without the HIGH fix the
# brief-name extraction would return empty).
[[ ! -f "$CASE_J_CLONE/briefs/_tasks/CODE_9_PENDING.md" ]] \
  || { echo "FAIL: Case J fixture broken — local file should not exist" >&2; exit 1; }

status_j="$(extract_payload_field "$OUT_J" b9 mailbox_status)"
brief_j="$(extract_payload_field "$OUT_J" b9 mailbox_brief_name)"
[[ "$status_j" == "pending" ]] \
  || { echo "FAIL: Case J — feature branch with no local mailbox, origin/main has it: status='$status_j' (expected 'pending')" >&2; cat "$OUT_J" >&2; exit 1; }
[[ "$brief_j" == "ORIGIN_ONLY_BRIEF_1" ]] \
  || { echo "FAIL: Case J HIGH — extract_brief_name_from_content not invoked: brief='$brief_j' (expected 'ORIGIN_ONLY_BRIEF_1' streamed from origin/main)" >&2; cat "$OUT_J" >&2; exit 1; }
assert_no_prod_aliases "$OUT_J"
echo "PASS: Case J — feature branch with no local file extracts brief from origin/main."

# ─────────────────────────────────────────────────────────────────────────────
# Case K — BRISEN_LAB_CARD_STATE_FIX_2-v0-2 MEDIUM 2: cold-clone fallback.
# Feature-branch clone with NO origin/main remote-tracking ref (never fetched)
# and a local mailbox file present from the initial clone. classify_mailbox
# must fall through to the local file (lines 291-307 fallback path).
# ─────────────────────────────────────────────────────────────────────────────
CASE_K_ORIGIN="$TMP/case-k-origin.git"
CASE_K_CLONE="$TMP/case-k-clone"
git init -q --bare "$CASE_K_ORIGIN"

SEED_K_DIR="$TMP/case-k-seed"
mkdir -p "$SEED_K_DIR/briefs/_tasks"
(
  cd "$SEED_K_DIR"
  git init -q -b main
  git config user.email "test@example.com"
  git config user.name "Test"
  cat > briefs/_tasks/CODE_9_PENDING.md <<'YAML'
---
status: IN_PROGRESS
brief: COLD_CLONE_LOCAL_FALLBACK_1
target: b9
---
YAML
  git add .
  git commit -q -m "seed K"
  git remote add origin "$CASE_K_ORIGIN"
  git push -q origin main
)

git clone -q --branch main "$CASE_K_ORIGIN" "$CASE_K_CLONE"
(
  cd "$CASE_K_CLONE"
  git config user.email "test@example.com"
  git config user.name "Test"
  git checkout -q -b b9/feature-k
  echo "feature-k" > feature.txt
  git add feature.txt
  git commit -q -m "feature k"
)

# Strip the origin/main remote-tracking ref to simulate a cold clone state.
# Also wipe packed-refs (where the ref may live after gc). After this, no
# `origin/main` reference is reachable — `git cat-file -e origin/main:...`
# will return non-zero for every probe. Re-point origin to a dead URL so
# sync_clone_to_main's fetch can't refresh it during the daemon run.
rm -f "$CASE_K_CLONE/.git/refs/remotes/origin/main"
[[ -f "$CASE_K_CLONE/.git/packed-refs" ]] && \
  grep -v "refs/remotes/origin/main" "$CASE_K_CLONE/.git/packed-refs" \
    > "$CASE_K_CLONE/.git/packed-refs.new" && \
  mv "$CASE_K_CLONE/.git/packed-refs.new" "$CASE_K_CLONE/.git/packed-refs"
git -C "$CASE_K_CLONE" remote set-url origin "file:///dev/null/does-not-exist.git"

OUT_K="$TMP/case-k.log"
LAB_URL="http://127.0.0.1:1" \
FORGE_KEY="test-key" \
PR_LOOKUP_ENABLED=0 \
DEBUG_DUMP_PAYLOAD=1 \
LOCK_DIR="$TMP/lock-k" \
TERMINALS_OVERRIDE="b9:$CASE_K_CLONE" \
bash "$SCRIPT" > "$OUT_K" 2>&1 || true

status_k="$(extract_payload_field "$OUT_K" b9 mailbox_status)"
brief_k="$(extract_payload_field "$OUT_K" b9 mailbox_brief_name)"
[[ "$status_k" == "in_progress" ]] \
  || { echo "FAIL: Case K — cold-clone fallback: status='$status_k' (expected 'in_progress' from local file)" >&2; cat "$OUT_K" >&2; exit 1; }
[[ "$brief_k" == "COLD_CLONE_LOCAL_FALLBACK_1" ]] \
  || { echo "FAIL: Case K — local fallback brief: '$brief_k' (expected 'COLD_CLONE_LOCAL_FALLBACK_1')" >&2; cat "$OUT_K" >&2; exit 1; }
assert_no_prod_aliases "$OUT_K"
echo "PASS: Case K — cold-clone (no origin/main ref) falls back to local mailbox file."

# ─────────────────────────────────────────────────────────────────────────────
# Case L — HAG_DESK_HEARTBEAT_DAEMON_1: non-b-code single-clone slug
# (desk pattern, e.g. hag-desk). Brief's `^b([1-9])$` mailbox-classifier
# regex must skip non-b-code aliases so mailbox_status defaults to "n/a"
# and mailbox_brief_name stays empty. Locks in the contract for future
# desk-on-bus additions (AO Desk / MOVIE Desk / Brisen Desk / Origination
# Desk / Baden-Baden Desk).
#
# Brief authored against a stale snapshot that labelled this "Case H"; the
# letter was reassigned to L to avoid collision with PR #201's H–K fixtures.
# ─────────────────────────────────────────────────────────────────────────────
CASE_L_REPO="$TMP/case-l-desk"
mkdir -p "$CASE_L_REPO"
(
  cd "$CASE_L_REPO"
  git init -q
  git config user.email "test@test"
  git config user.name "test"
  echo "vault-content" > README.md
  git add README.md
  git commit -qm "case-l: desk vault clone init"
)

CASE_L_OUT="$TMP/case-l.out"
run_daemon "case-l" "hag-desk:$CASE_L_REPO" > "$CASE_L_OUT"
assert_no_prod_aliases "$CASE_L_OUT"

CASE_L_ALIAS="$(extract_payload_field "$CASE_L_OUT" "hag-desk" "terminal_alias")"
CASE_L_MSTATUS="$(extract_payload_field "$CASE_L_OUT" "hag-desk" "mailbox_status")"
CASE_L_MBRIEF="$(extract_payload_field "$CASE_L_OUT" "hag-desk" "mailbox_brief_name")"

[[ "$CASE_L_ALIAS" == "hag-desk" ]]    || { echo "FAIL Case L: terminal_alias='$CASE_L_ALIAS'" >&2; exit 1; }
[[ "$CASE_L_MSTATUS" == "n/a" ]]       || { echo "FAIL Case L: mailbox_status='$CASE_L_MSTATUS'" >&2; exit 1; }
[[ -z "$CASE_L_MBRIEF" ]]              || { echo "FAIL Case L: mailbox_brief_name='$CASE_L_MBRIEF' (expected empty)" >&2; exit 1; }
echo "PASS: Case L — non-b-code single-clone slug (desk pattern) — mailbox stays n/a."

# ─────────────────────────────────────────────────────────────────────────────
# Case L2 — AO_DESK_ON_BUS_1: non-b-code single-clone slug, same desk pattern
# as origination-desk. AO Desk's picker is Dropbox-backed and has no .git, so
# production snapshot wiring must point at ~/baker-vault; this fixture uses a
# git tempdir to assert the desk alias itself is accepted and mailbox stays n/a.
# ─────────────────────────────────────────────────────────────────────────────
CASE_L2_REPO="$TMP/case-l2-ao-desk"
mkdir -p "$CASE_L2_REPO"
(
  cd "$CASE_L2_REPO"
  git init -q
  git config user.email "test@test"
  git config user.name "test"
  echo "ao-desk-vault-content" > README.md
  git add README.md
  git commit -qm "case-l2: ao-desk vault clone init"
)

CASE_L2_OUT="$TMP/case-l2.out"
run_daemon "case-l2" "ao-desk:$CASE_L2_REPO" > "$CASE_L2_OUT"
assert_no_prod_aliases "$CASE_L2_OUT"

CASE_L2_ALIAS="$(extract_payload_field "$CASE_L2_OUT" "ao-desk" "terminal_alias")"
CASE_L2_MSTATUS="$(extract_payload_field "$CASE_L2_OUT" "ao-desk" "mailbox_status")"
CASE_L2_MBRIEF="$(extract_payload_field "$CASE_L2_OUT" "ao-desk" "mailbox_brief_name")"

[[ "$CASE_L2_ALIAS" == "ao-desk" ]]    || { echo "FAIL Case L2: terminal_alias='$CASE_L2_ALIAS'" >&2; exit 1; }
[[ "$CASE_L2_MSTATUS" == "n/a" ]]      || { echo "FAIL Case L2: mailbox_status='$CASE_L2_MSTATUS'" >&2; exit 1; }
[[ -z "$CASE_L2_MBRIEF" ]]             || { echo "FAIL Case L2: mailbox_brief_name='$CASE_L2_MBRIEF' (expected empty)" >&2; exit 1; }
echo "PASS: Case L2 — ao-desk non-b-code single-clone slug — mailbox stays n/a."

# ─────────────────────────────────────────────────────────────────────────────
# Case L3 — RUSSO_IT_ON_BUS_1: shared-specialist single-clone slug. Russo IT's
# picker dir is provisioned by lead as Tier-B; production snapshot wiring points
# at ~/baker-vault until that local lane exists. The alias must still be accepted
# and mailbox fields stay n/a, matching non-b-code agents.
# ─────────────────────────────────────────────────────────────────────────────
CASE_L3_REPO="$TMP/case-l3-russo-it"
mkdir -p "$CASE_L3_REPO"
(
  cd "$CASE_L3_REPO"
  git init -q
  git config user.email "test@test"
  git config user.name "test"
  echo "russo-it-vault-content" > README.md
  git add README.md
  git commit -qm "case-l3: russo-it vault clone init"
)

CASE_L3_OUT="$TMP/case-l3.out"
run_daemon "case-l3" "russo-it:$CASE_L3_REPO" > "$CASE_L3_OUT"
assert_no_prod_aliases "$CASE_L3_OUT"

CASE_L3_ALIAS="$(extract_payload_field "$CASE_L3_OUT" "russo-it" "terminal_alias")"
CASE_L3_MSTATUS="$(extract_payload_field "$CASE_L3_OUT" "russo-it" "mailbox_status")"
CASE_L3_MBRIEF="$(extract_payload_field "$CASE_L3_OUT" "russo-it" "mailbox_brief_name")"

[[ "$CASE_L3_ALIAS" == "russo-it" ]]   || { echo "FAIL Case L3: terminal_alias='$CASE_L3_ALIAS'" >&2; exit 1; }
[[ "$CASE_L3_MSTATUS" == "n/a" ]]      || { echo "FAIL Case L3: mailbox_status='$CASE_L3_MSTATUS'" >&2; exit 1; }
[[ -z "$CASE_L3_MBRIEF" ]]             || { echo "FAIL Case L3: mailbox_brief_name='$CASE_L3_MBRIEF' (expected empty)" >&2; exit 1; }
echo "PASS: Case L3 — russo-it non-b-code single-clone slug — mailbox stays n/a."

# ─────────────────────────────────────────────────────────────────────────────
# Case M — RESEARCHER_ON_BUS_1: non-b-code single-clone slug, Cowork-App-only
# variant (researcher). Same contract as Case L (mailbox stays n/a, brief
# stays empty), but home-repo is the picker dir itself (~/bm-researcher),
# not a vault clone. Locks in the Cowork-App-only single-clone slug pattern
# alongside the desk pattern for future agents installed via Cowork picker
# (no Terminal sibling, no zsh function).
# ─────────────────────────────────────────────────────────────────────────────
CASE_M_REPO="$TMP/case-m-researcher"
mkdir -p "$CASE_M_REPO"
(
  cd "$CASE_M_REPO"
  git init -q
  git config user.email "test@test"
  git config user.name "test"
  echo "researcher-picker-content" > README.md
  git add README.md
  git commit -qm "case-m: researcher picker init"
)

CASE_M_OUT="$TMP/case-m.out"
run_daemon "case-m" "researcher:$CASE_M_REPO" > "$CASE_M_OUT"
assert_no_prod_aliases "$CASE_M_OUT"

CASE_M_ALIAS="$(extract_payload_field "$CASE_M_OUT" "researcher" "terminal_alias")"
CASE_M_MSTATUS="$(extract_payload_field "$CASE_M_OUT" "researcher" "mailbox_status")"
CASE_M_MBRIEF="$(extract_payload_field "$CASE_M_OUT" "researcher" "mailbox_brief_name")"

[[ "$CASE_M_ALIAS" == "researcher" ]]  || { echo "FAIL Case M: terminal_alias='$CASE_M_ALIAS'" >&2; exit 1; }
[[ "$CASE_M_MSTATUS" == "n/a" ]]       || { echo "FAIL Case M: mailbox_status='$CASE_M_MSTATUS'" >&2; exit 1; }
[[ -z "$CASE_M_MBRIEF" ]]              || { echo "FAIL Case M: mailbox_brief_name='$CASE_M_MBRIEF' (expected empty)" >&2; exit 1; }
echo "PASS: Case M — non-b-code single-clone slug (Cowork-App-only) — mailbox stays n/a."

# ─────────────────────────────────────────────────────────────────────────────
# Cases N-R — HAG_WORKERS_PHASE_1: 5 new non-b-code single-clone slugs (CM-1
# through CM-4 fleet ClaimsMax workers + hag-filer Hagenauer-matter filer).
# Same contract as Case L (mailbox stays n/a, brief stays empty). Each gets
# its own tempdir to keep isolation tight. Locks in the worker-pool slug
# pattern alongside hag-desk + researcher.
# ─────────────────────────────────────────────────────────────────────────────
for spec in "n:CM-1" "o:CM-2" "p:CM-3" "q:CM-4" "r:hag-filer" "s:codex" "t:clerk" "u:codex-arch" "v:clerk-haiku"; do
  CASE_LABEL="${spec%%:*}"
  CASE_SLUG="${spec##*:}"
  CASE_REPO="$TMP/case-${CASE_LABEL}-${CASE_SLUG}"
  mkdir -p "$CASE_REPO"
  (
    cd "$CASE_REPO"
    git init -q
    git config user.email "test@test"
    git config user.name "test"
    echo "${CASE_SLUG}-worker-content" > README.md
    git add README.md
    git commit -qm "case-${CASE_LABEL}: ${CASE_SLUG} worker init"
  )

  CASE_OUT="$TMP/case-${CASE_LABEL}.out"
  run_daemon "case-${CASE_LABEL}" "${CASE_SLUG}:$CASE_REPO" > "$CASE_OUT"
  assert_no_prod_aliases "$CASE_OUT"

  CASE_ALIAS="$(extract_payload_field "$CASE_OUT" "${CASE_SLUG}" "terminal_alias")"
  CASE_MSTATUS="$(extract_payload_field "$CASE_OUT" "${CASE_SLUG}" "mailbox_status")"
  CASE_MBRIEF="$(extract_payload_field "$CASE_OUT" "${CASE_SLUG}" "mailbox_brief_name")"

  [[ "$CASE_ALIAS" == "${CASE_SLUG}" ]]  || { echo "FAIL Case $(echo "$CASE_LABEL" | tr '[:lower:]' '[:upper:]') (${CASE_SLUG}): terminal_alias='$CASE_ALIAS'" >&2; exit 1; }
  [[ "$CASE_MSTATUS" == "n/a" ]]         || { echo "FAIL Case $(echo "$CASE_LABEL" | tr '[:lower:]' '[:upper:]') (${CASE_SLUG}): mailbox_status='$CASE_MSTATUS'" >&2; exit 1; }
  [[ -z "$CASE_MBRIEF" ]]                || { echo "FAIL Case $(echo "$CASE_LABEL" | tr '[:lower:]' '[:upper:]') (${CASE_SLUG}): mailbox_brief_name='$CASE_MBRIEF' (expected empty)" >&2; exit 1; }
  echo "PASS: Case $(echo "$CASE_LABEL" | tr '[:lower:]' '[:upper:]') — non-b-code single-clone slug (${CASE_SLUG}) — mailbox stays n/a."
done

echo ""
echo "All 22 cases PASS."
