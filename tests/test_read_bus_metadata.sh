#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; SCRIPT="$ROOT/scripts/read_bus_metadata.sh"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
fail() { echo "FAIL: $1" >&2; exit 1; }
mkdir -p "$TMP/bin"
cat > "$TMP/bin/curl" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$*" > "${CURL_ARGS_FILE:?}"
printf '%s' '{"ok":true}'
STUB
chmod +x "$TMP/bin/curl"; export CURL_ARGS_FILE="$TMP/curl.args"
PATH="$TMP/bin:$PATH" BRISEN_LAB_TERMINAL_KEY=dummy bash "$SCRIPT" schema >/dev/null
grep -q 'https://brisen-lab.onrender.com/research/bus/schema' "$CURL_ARGS_FILE" || fail "schema URL"
PATH="$TMP/bin:$PATH" BRISEN_LAB_TERMINAL_KEY=dummy bash "$SCRIPT" events 2026-07-12T10:00:00Z 25 >/dev/null
grep -q 'https://brisen-lab.onrender.com/research/bus/events' "$CURL_ARGS_FILE" || fail "events URL"
grep -q 'since=2026-07-12T10:00:00Z' "$CURL_ARGS_FILE" || fail "since"
grep -q 'limit=25' "$CURL_ARGS_FILE" || fail "limit"
for bad in '../events' '2026-07-12' 'x&limit=200'; do
  ! PATH="$TMP/bin:$PATH" BRISEN_LAB_TERMINAL_KEY=dummy bash "$SCRIPT" events "$bad" 25 >/dev/null 2>&1 || fail "bad since"
done
for lim in 0 201 nope; do
  ! PATH="$TMP/bin:$PATH" BRISEN_LAB_TERMINAL_KEY=dummy bash "$SCRIPT" events 2026-07-12T10:00:00Z "$lim" >/dev/null 2>&1 || fail "bad limit"
done
grep -q 'SLUG="researcher"' "$SCRIPT" || fail "slug not pinned"
! grep -Eq '(/msg/.*/ack|curl.*-X|curl.*--request|body_preview)' "$SCRIPT" || fail "forbidden surface"
echo "PASS: read_bus_metadata wrapper contract"
