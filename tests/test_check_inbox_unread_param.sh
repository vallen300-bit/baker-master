#!/usr/bin/env bash
# Regression test for check_inbox.sh — codex verdict #8761 (MEDIUM, Lesson #89).
#
# Guards the fix: BOTH curl invocations (the SINCE branch and the no-SINCE
# fallback) MUST pass `--data-urlencode unread=true`. Without it the daemon's
# OLDEST-first + LIMIT window can truncate away the NEWEST unacked rows behind
# already-acked ones → a phantom "no unacked messages".
#
# Method: stub `curl` on PATH so it CAPTURES its argv to a file and returns a
# minimal valid JSON body (never touches the network). Run check_inbox.sh under
# both branches and assert `unread=true` is present in the captured curl args.

set -euo pipefail

SCRIPT="$(cd "$(dirname "$0")/.." && pwd)/scripts/check_inbox.sh"
[[ -f "$SCRIPT" ]] || { echo "Missing: $SCRIPT" >&2; exit 1; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# --- curl stub: append full argv to $CURL_ARGS_FILE, emit empty-messages JSON ---
mkdir -p "$TMP/bin"
cat > "$TMP/bin/curl" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "${CURL_ARGS_FILE:?}"
printf '%s' '{"messages": []}'
exit 0
STUB
chmod +x "$TMP/bin/curl"

run_case() {
  # $1 = label, $2 = extra numeric-limit arg (may be empty)
  local label="$1" arg="${2:-}"
  export CURL_ARGS_FILE="$TMP/args-${label}.txt"
  : > "$CURL_ARGS_FILE"
  PATH="$TMP/bin:$PATH" \
  BAKER_ROLE=researcher \
  BRISEN_LAB_TERMINAL_KEY="dummy-test-key" \
  bash "$SCRIPT" $arg >/dev/null 2>&1 || true
  cat "$CURL_ARGS_FILE"
}

fail() { echo "FAIL: $1" >&2; exit 1; }

# Case 1 — normal run (SINCE branch fires when `date` succeeds, which it does on
# both macOS -v and GNU -d hosts). Assert unread=true present.
ARGS1="$(run_case since)"
[[ -n "$ARGS1" ]]                     || fail "curl was never invoked (case since)"
grep -q -- "unread=true" <<<"$ARGS1"  || fail "SINCE-branch curl missing unread=true. Args: $ARGS1"
grep -q -- "limit="      <<<"$ARGS1"  || fail "SINCE-branch curl missing limit (sanity)"

# Case 2 — force the no-SINCE fallback by stubbing `date` to fail so SINCE="".
mkdir -p "$TMP/bin2"
cat > "$TMP/bin2/date" <<'STUB'
#!/usr/bin/env bash
exit 1
STUB
chmod +x "$TMP/bin2/date"
cp "$TMP/bin/curl" "$TMP/bin2/curl"
export CURL_ARGS_FILE="$TMP/args-nosince.txt"
: > "$CURL_ARGS_FILE"
PATH="$TMP/bin2:$PATH" \
BAKER_ROLE=researcher \
BRISEN_LAB_TERMINAL_KEY="dummy-test-key" \
bash "$SCRIPT" >/dev/null 2>&1 || true
ARGS2="$(cat "$CURL_ARGS_FILE")"
[[ -n "$ARGS2" ]]                     || fail "curl was never invoked (case no-since)"
grep -q -- "unread=true" <<<"$ARGS2"  || fail "no-SINCE-branch curl missing unread=true. Args: $ARGS2"
grep -q -- "since="      <<<"$ARGS2"  && fail "no-SINCE branch unexpectedly sent since= . Args: $ARGS2"

echo "PASS: check_inbox.sh sends unread=true on both curl branches."
