#!/usr/bin/env bash
# search_research_index.sh — vetted READ-ONLY query over the researcher's prior-report
# index (_index.json). The researcher runs this at Step 0 of a brief to find and reuse
# relevant prior research instead of re-running it cold.
#
# RESEARCHER_TRANCHE2_8_RESEARCH_MEMORY_INDEX (b2, 2026-07-12; dispatch lead #9721 +
# #9894 + #9898, Option B). Companion to regen_research_index.sh, which builds the
# manifest this reads.
#
# CAGE POSTURE (design §4.3): READ-ONLY — no writes, no ack, no arg-driven exec. Reads
# a HARD-PINNED manifest path ($HOME/baker-vault/wiki/research/_index.json); positional
# args are treated ONLY as literal search keywords (never a path, never a command). Same
# read-only posture as check_source_monitors.sh. Additive IS_VETTED entry; relaxes no deny.
#
# Matching: a report matches when EVERY keyword (case-insensitive) appears somewhere in
# its title + summary + tags + author + path. AND semantics narrows; run again with fewer
# keywords to broaden. Fails LOUD if the manifest is missing/stale (never "no results"
# when the index simply hasn't been generated).
#
# Usage:
#   search_research_index.sh <keyword> [keyword ...]   # human list of matching reports
#   search_research_index.sh --json <keyword> [...]    # machine-readable JSON array
set -u

VAULT_DIR="$HOME/baker-vault"                       # HARD-PINNED (no env override)
INDEX_JSON="$VAULT_DIR/wiki/research/_index.json"

fail() { echo "search_research_index: $1" >&2; exit "${2:-1}"; }

OUT="human"
if [ "$#" -ge 1 ] && [ "$1" = "--json" ]; then
    OUT="json"
    shift
fi
[ "$#" -ge 1 ] || fail "no keywords — usage: search_research_index.sh [--json] <keyword> [keyword ...]" 1
for a in "$@"; do
    case "$a" in
        --*) fail "unexpected flag '$a' (only a leading --json is accepted; all other args are literal keywords)" 1 ;;
    esac
done

[ -f "$INDEX_JSON" ] || fail "index missing ($INDEX_JSON) — run regen_research_index.sh first (fail-loud, not 'no results')" 3

INDEX_JSON="$INDEX_JSON" OUT="$OUT" python3 - "$@" <<'PYEOF'
import json, os, sys

index_json = os.environ["INDEX_JSON"]
out = os.environ["OUT"]
keywords = [k.lower() for k in sys.argv[1:]]

try:
    with open(index_json, encoding="utf-8") as f:
        manifest = json.load(f)
except Exception as exc:  # noqa: BLE001 — fail-loud on a corrupt/unreadable index
    print("search_research_index: index unreadable/corrupt: %s" % exc, file=sys.stderr)
    sys.exit(3)

reports = manifest.get("reports") or []


def haystack(r):
    parts = [r.get("title", ""), r.get("summary", ""), r.get("author", ""),
             r.get("path", "")]
    parts.extend(r.get("tags") or [])
    return " ".join(str(p) for p in parts).lower()


matches = [r for r in reports if all(kw in haystack(r) for kw in keywords)]

if out == "json":
    print(json.dumps(matches, indent=2, ensure_ascii=False))
    sys.exit(0)

print("%d match(es) for: %s   (index generated %s, %d reports)"
      % (len(matches), " ".join(keywords), manifest.get("generated", "?"),
         manifest.get("count", len(reports))))
for r in matches:
    print("\n- %s  [%s]" % (r.get("title") or "(untitled)", r.get("date") or "—"))
    print("  %s" % r.get("path", ""))
    if r.get("summary"):
        print("  %s" % r["summary"])
    if r.get("flags"):
        print("  flags: %s" % ",".join(r["flags"]))
if not matches:
    print("\n  (no matching priors — safe to research this cold)")
PYEOF
