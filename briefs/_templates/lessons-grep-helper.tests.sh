#!/usr/bin/env bash
# lessons-grep-helper.tests.sh — synthetic tests for lessons-grep-helper.sh v2.
#
# Not pytest; plain bash asserts. Run from repo root:
#   bash briefs/_templates/lessons-grep-helper.tests.sh
#
# Exits 0 on all pass, 1 on any fail. Tests use a synthetic lessons file +
# branch-mode target (git diff against a sibling branch) so they don't need
# `gh auth` or internet. Each test creates/deletes a tmp branch.
set -euo pipefail

HELPER="$(cd "$(dirname "$0")" && pwd)/lessons-grep-helper.sh"
[ -x "$HELPER" ] || chmod +x "$HELPER"

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
cd "$TMP"
git init -q .
git config user.email t@t; git config user.name t
cat > tasks_lessons.md <<'EOF'
# Lessons
### 1. Column name drift
Mistake: table column renamed; code still referenced old name; try/except swallowed.
Rule: verify column_name from information_schema before shipping.
### 2. Queue advisory lock
Mistake: race on two replicas; pg_try_advisory_lock with 30s timeout saved us.
Rule: always use pg_try_advisory_lock when two hosts may run the same DDL.
### 3. Wrong import path
Mistake: feature silently dead since day one because module import path typo.
Rule: grep for the expected symbol; never trust "it's deployed" without a probe.
EOF
mkdir -p tasks && cp tasks_lessons.md tasks/lessons.md
git add -A; git commit -q -m "seed"
git checkout -q -b feat

run_helper() {  # args: branch_name → prints helper output
  LESSONS_FILE="$TMP/tasks/lessons.md" bash "$HELPER" "$1" 2>&1
}
pass=0; fail=0
check() {  # args: description, expected_grep_pattern, actual_text
  if echo "$3" | grep -qE "$2"; then
    echo "  PASS  $1"; pass=$((pass+1))
  else
    echo "  FAIL  $1 — pattern /$2/ not found in:"; echo "$3" | sed 's/^/    | /'; fail=$((fail+1))
  fi
}

# Test 1 — strong-signal diff (distinctive "pg_try_advisory_lock" token → ranks #2 top).
echo "TEST 1: distinctive-token diff ranks the matching lesson first"
echo "added: we now call pg_try_advisory_lock on every migration" > notes.md
git add -A; git commit -q -m "t1"
out="$(run_helper feat)"
check "lesson #2 ranked first" "^  #2 \(score" "$out"
check "fallback did NOT fire"   "Top 5 lessons for branch feat"  "$out"
git reset --hard -q HEAD~1 > /dev/null

# Test 2 — scaffold-style diff (every lesson has incidental 6+ char overlap → fallback).
echo "TEST 2: scaffold diff (hits every lesson) fires low-signal fallback"
cat > docs.md <<'EOF'
column mistake table replicas advisory timeout feature import path rename
Mistake Mistake Mistake rule information_schema replicas pg_try deployed symbol
EOF
git add -A; git commit -q -m "t2"
out="$(run_helper feat)"
check "fallback fired" "No strongly-ranked lessons" "$out"
git reset --hard -q HEAD~1 > /dev/null

# Test 3 — empty diff / no 6+ char tokens → fallback path (empty RANKED branch).
echo "TEST 3: empty-content diff fires fallback (no positive scores)"
echo "a b c" > tiny.txt   # no 6+ char tokens at all
git add -A; git commit -q -m "t3"
out="$(run_helper feat)"
check "fallback fired on empty tokens" "No strongly-ranked lessons" "$out"

echo
echo "Result: $pass passed, $fail failed"
exit $(( fail > 0 ? 1 : 0 ))
