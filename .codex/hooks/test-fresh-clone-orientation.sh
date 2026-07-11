#!/usr/bin/env bash
# Smoke test: fresh-clone picker → SessionStart hook fires → emits AH1/AH2 role context.
#
# Validates 4 paths through session-start-role.sh:
#   1. BAKER_ROLE=aihead1 env  → AH1 context injected
#   2. BAKER_ROLE=aihead2 env  → AH2 context injected
#   3. cwd ending in /bm-aihead1 (no env) → AH1 context injected (cwd fallback)
#   4. cwd ending in /bm-aihead2 (no env) → AH2 context injected (cwd fallback)
#
# Negative checks per case: output MUST NOT contain "no context file" or "lead.md"
# (the original-bug signatures).
#
# Source repo: clones from $LOCAL_REPO via file:// so feature-branch HEAD is testable
# without needing to push first.
#
# Run: bash .claude/hooks/test-fresh-clone-orientation.sh
# Exit 0 on all-pass; non-zero on first failure.

set -euo pipefail

LOCAL_REPO=$(git rev-parse --show-toplevel)
TMP=$(mktemp -d -t picker-smoke.XXXXXX)
trap "rm -rf $TMP" EXIT

fail() { echo "FAIL: $*" >&2; exit 1; }
pass() { echo "PASS: $*"; }

run_hook() {
  # $1 = role-or-empty (set BAKER_ROLE if non-empty), $2 = cwd
  local role="$1" cwd="$2"
  cd "$cwd"
  if [ -n "$role" ]; then
    BAKER_ROLE="$role" bash .claude/hooks/session-start-role.sh </dev/null 2>&1
  else
    env -u BAKER_ROLE bash .claude/hooks/session-start-role.sh </dev/null 2>&1
  fi
}

assert_ok() {
  # $1 = label, $2 = output, $3 = required marker (e.g. "AH1")
  local label="$1" out="$2" marker="$3"
  echo "$out" | grep -q '"additionalContext"' \
    || fail "$label: no additionalContext in JSON envelope"
  echo "$out" | grep -q "$marker" \
    || fail "$label: marker '$marker' missing from injected context"
  ! echo "$out" | grep -q "no context file" \
    || fail "$label: 'no context file' fallback fired (role→file lookup broken)"
  ! echo "$out" | grep -q "lead.md" \
    || fail "$label: 'lead.md' signature still present (pre-fix regression)"
}

echo "Smoke test: fresh clone of $LOCAL_REPO"
echo "Tmp: $TMP"
echo ""

# --- Test 1 + 2: BAKER_ROLE env path ---
git clone -q "file://$LOCAL_REPO" "$TMP/env-test" || fail "clone for env test"

out=$(run_hook "aihead1" "$TMP/env-test")
assert_ok "T1 BAKER_ROLE=aihead1" "$out" "AH1"
pass "T1: BAKER_ROLE=aihead1 → AH1 context injected"

out=$(run_hook "aihead2" "$TMP/env-test")
assert_ok "T2 BAKER_ROLE=aihead2" "$out" "AH2"
pass "T2: BAKER_ROLE=aihead2 → AH2 context injected"

# --- Test 3: cwd-fallback for AH1 ---
git clone -q "file://$LOCAL_REPO" "$TMP/bm-aihead1" || fail "clone for cwd AH1 test"
out=$(run_hook "" "$TMP/bm-aihead1")
assert_ok "T3 cwd=bm-aihead1" "$out" "AH1"
pass "T3: cwd ends in /bm-aihead1 (no env) → AH1 context injected"

# --- Test 4: cwd-fallback for AH2 ---
git clone -q "file://$LOCAL_REPO" "$TMP/bm-aihead2" || fail "clone for cwd AH2 test"
out=$(run_hook "" "$TMP/bm-aihead2")
assert_ok "T4 cwd=bm-aihead2" "$out" "AH2"
pass "T4: cwd ends in /bm-aihead2 (no env) → AH2 context injected"

echo ""
echo "All 4 paths PASS. SessionStart orientation works on a fresh clone."
