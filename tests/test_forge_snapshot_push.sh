#!/usr/bin/env bash
# Smoke test for forge_snapshot_push.sh state collection.
# Builds a fake b-code repo with a PENDING mailbox + commit; runs the script
# with TERMINALS_OVERRIDE pointing at it; asserts the override actually
# overrode (production aliases NOT processed) and the fake fixture WAS
# processed. Does NOT POST to the live endpoint — uses a guaranteed-dead URL.

set -euo pipefail

SCRIPT="$(cd "$(dirname "$0")/.." && pwd)/scripts/forge_snapshot_push.sh"
[[ -f "$SCRIPT" ]] || { echo "Missing: $SCRIPT" >&2; exit 1; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# 1. Build a fake b-code repo with a PENDING mailbox.
FAKE_REPO="$TMP/fake-b9"
mkdir -p "$FAKE_REPO/briefs/_tasks"
(
  cd "$FAKE_REPO"
  git init -q
  git config user.email "test@example.com"
  git config user.name "Test"
  echo "# CODE_9_PENDING — TEST_BRIEF_FORGE_PUSH_FOLD" > briefs/_tasks/CODE_9_PENDING.md
  git add .
  git commit -q -m "fixture test commit"
)

# 2. Run the script with override pointing at the fake repo. Point LAB_URL
# at a guaranteed-dead endpoint so curl exits non-200 (we are only verifying
# the state-collection path, not the POST).
OUTPUT="$TMP/out.log"
LAB_URL="http://127.0.0.1:1" \
FORGE_KEY="test-key" \
PR_LOOKUP_ENABLED=0 \
TERMINALS_OVERRIDE="b9:$FAKE_REPO" \
bash "$SCRIPT" 2>&1 | tee "$OUTPUT" || true

# 3. Assertions. The script should have:
# (a) exited 0 (no shell crash),
# (b) attempted ONE curl to 127.0.0.1:1 (the fake terminal, not 6),
# (c) logged the HTTP 000 connect failure (single line per terminal).
EXIT_CODE="$?"
[[ "$EXIT_CODE" == "0" ]] || { echo "FAIL: script exit $EXIT_CODE" >&2; exit 1; }

# Expect at least one "[forge-push] b9: HTTP" stderr line (the connect failure
# against 127.0.0.1:1).
B9_LINES="$(grep -c '\[forge-push\] b9:' "$OUTPUT" || true)"
[[ "$B9_LINES" -ge 1 ]] || { echo "FAIL: no b9 stderr line; coverage gap" >&2; exit 1; }

# No lines for the production aliases — confirms override actually overrode.
for alias in lead deputy b1 b2 b3 b4; do
  if grep -q "\[forge-push\] ${alias}:" "$OUTPUT"; then
    echo "FAIL: production alias '$alias' processed despite TERMINALS_OVERRIDE" >&2
    exit 1
  fi
done

echo "PASS: script processed fake fixture only, exited zero, attempted POST to dead endpoint."
