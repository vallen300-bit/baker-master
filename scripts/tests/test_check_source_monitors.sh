#!/usr/bin/env bash
# test_check_source_monitors.sh — suite for the researcher standing-monitor cache reader.
#
# RESEARCHER_TRANCHE3_12_STANDING_MONITORS_1 (b2, 2026-07-12; codex design-verify #9394).
# The reader hard-pins its cache/digest dirs off $HOME (no config env var — codex build
# note). The test controls $HOME to point at a seeded fixture tree, so it exercises the
# real read/filter/dedup/staleness logic without any config override in the script.
set -u
SCRIPT="$(cd "$(dirname "$0")/.." && pwd)/check_source_monitors.sh"
[ -x "$SCRIPT" ] || { echo "FAIL [setup]: script missing/not executable at $SCRIPT" >&2; exit 1; }

PASS=0; FAIL=0
TMP="$(mktemp -d -t csm-test.XXXXXX)"; trap 'rm -rf "$TMP"' EXIT
CACHE="$TMP/baker-vault/_ops/research-monitors-cache"
DIGESTS="$TMP/baker-vault/wiki/research"
mkdir -p "$CACHE" "$DIGESTS"

today="$(date -u +%F)"
old="$(date -u -v-30d +%F 2>/dev/null || date -u -d '30 days ago' +%F)"
recent_status="$(date -u +%FT%TZ)"
stale_status="$(date -u -v-20d +%FT%TZ 2>/dev/null || date -u -d '20 days ago' +%FT%TZ)"

# --- fixture: an arXiv-style Atom feed with one FRESH + one OLD + one DEDUP entry ---
cat > "$CACHE/arxiv_cs_AI.xml" <<XML
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Fresh Paper On Agents</title>
    <id>http://arxiv.org/abs/2507.00001</id>
    <link href="http://arxiv.org/abs/2507.00001"/>
    <published>${today}T00:00:00Z</published>
  </entry>
  <entry>
    <title>Old Paper Should Be Filtered</title>
    <id>http://arxiv.org/abs/2506.00002</id>
    <link href="http://arxiv.org/abs/2506.00002"/>
    <published>${old}T00:00:00Z</published>
  </entry>
  <entry>
    <title>Already Reported Last Week</title>
    <id>http://arxiv.org/abs/2507.09999</id>
    <link href="http://arxiv.org/abs/2507.09999"/>
    <published>${today}T00:00:00Z</published>
  </entry>
</feed>
XML

# --- fixture: _status.json — one ok source + one stale source ---
cat > "$CACHE/_status.json" <<JSON
{
  "generated": "${recent_status}",
  "sources": {
    "arxiv_cs_AI": {"status": "ok", "last_success": "${recent_status}", "size_bytes": 1234, "fetch_error": null},
    "anthropic_changelog": {"status": "ok", "last_success": "${stale_status}", "size_bytes": 500, "fetch_error": null}
  }
}
JSON

# --- fixture: a prior weekly digest that already listed the DEDUP entry ---
cat > "$DIGESTS/2026-07-05-research-monitors-weekly.md" <<MD
# Research monitors — weekly
- [${today}] Already Reported Last Week — http://arxiv.org/abs/2507.09999
MD

run() { HOME="$TMP" bash "$SCRIPT" "$@"; }
check() { # <substr> <name> <should-contain 0|1> <output>
    local sub="$1" name="$2" want="$3" outp="$4"
    case "$outp" in *"$sub"*) got=1 ;; *) got=0 ;; esac
    if [ "$got" = "$want" ]; then echo "PASS: $name"; PASS=$((PASS+1))
    else echo "FAIL: $name (want-contains=$want for '$sub')" >&2; FAIL=$((FAIL+1)); fi
}

OUTPUT="$(run 2>&1)"; RC=$?
echo "== human output =="
[ "$RC" = "0" ] && { echo "PASS: exit 0 with healthy cache"; PASS=$((PASS+1)); } || { echo "FAIL: exit $RC" >&2; FAIL=$((FAIL+1)); }
check "Fresh Paper On Agents"       "fresh item surfaced"                1 "$OUTPUT"
check "Old Paper Should Be Filtered" "old item filtered out (>7d)"       0 "$OUTPUT"
check "Already Reported Last Week"  "dedup vs prior digest"              0 "$OUTPUT"
check "anthropic_changelog"         "stale source flagged (fail-loud)"   1 "$OUTPUT"
check "STALE SOURCES"               "stale banner present"               1 "$OUTPUT"

echo "== json output =="
JOUT="$(run --json 2>&1)"
echo "$JOUT" | python3 -c 'import sys,json; d=json.load(sys.stdin); assert d["fresh"]; assert d["stale"]; print("ok")' >/dev/null 2>&1 \
    && { echo "PASS: --json parses with fresh+stale"; PASS=$((PASS+1)); } || { echo "FAIL: --json shape" >&2; FAIL=$((FAIL+1)); }

echo "== fail-loud: missing cache =="
rm -rf "$CACHE"
run >/dev/null 2>&1; [ "$?" = "3" ] && { echo "PASS: missing cache -> exit 3 (fail-loud)"; PASS=$((PASS+1)); } || { echo "FAIL: missing cache exit" >&2; FAIL=$((FAIL+1)); }

echo "---"
echo "check_source_monitors tests: $PASS passed, $FAIL failed"
[ "$FAIL" = "0" ]
