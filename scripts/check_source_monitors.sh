#!/usr/bin/env bash
# check_source_monitors.sh — vetted READ-ONLY standing-monitor cache reader for the
# researcher.
#
# RESEARCHER_TRANCHE3_12_STANDING_MONITORS_1 (b2, 2026-07-12; dispatch deputy #9337,
# Director order via lead #9334; codex design-verify #9394). Recency is otherwise rebuilt
# cold every brief. A trusted actor (Mac Mini launchd, mirroring edge-scout) pre-fetches
# the standing sources into $BAKER_VAULT/_ops/research-monitors-cache/; THIS script is the
# researcher's read-only view of that cache: it surfaces items from the last 7 days,
# dedups against recent weekly digests, and FAILS LOUD on a missing/stale cache (never
# silently reports "nothing new" when the fetch is actually broken).
#
# CAGE POSTURE (codex #9394): read-only. NO env override, NO arg-driven config path
# (pinned cache dir + digest dir constants). The researcher never fetches — fetching is
# the trusted-actor launchd job (research-monitors-prefetch.sh). This is an additive
# read-only entry in the researcher_bash_cage IS_VETTED allow-list; no deny relaxed.
#
# Usage:
#   check_source_monitors.sh            # human summary of fresh (<=7d) undated items
#   check_source_monitors.sh --json     # machine-readable JSON (same data)
set -u

VAULT_DIR="$HOME/baker-vault"                                  # HARD-PINNED (no env override)
CACHE_DIR="$VAULT_DIR/_ops/research-monitors-cache"           # trusted-actor-populated
DIGEST_DIR="$VAULT_DIR/wiki/research"                         # researcher weekly digests
FRESH_DAYS=7                                                  # item recency window
STALE_DAYS=8                                                  # a source not refreshed within => stale (missed a weekly cycle)
DIGEST_GLOB="*research-monitors-weekly.md"                    # prior digests for dedup

fail() { echo "check_source_monitors: $1" >&2; exit "${2:-1}"; }

# --- arg parse: only an optional --json flag; no arg-driven config path ---
OUT="human"
if [ "$#" -gt 1 ]; then fail "at most one flag (--json) accepted" 1; fi
if [ "$#" -eq 1 ]; then
    case "$1" in
        --json) OUT="json" ;;
        *) fail "unknown arg '$1' (only --json)" 1 ;;
    esac
fi

[ -d "$CACHE_DIR" ] || fail "cache dir missing ($CACHE_DIR) — has the prefetch launchd job run? (fail-loud, not 'nothing new')" 3
[ -f "$CACHE_DIR/_status.json" ] || fail "cache _status.json missing — prefetch never completed (fail-loud)" 3

CACHE_DIR="$CACHE_DIR" DIGEST_DIR="$DIGEST_DIR" DIGEST_GLOB="$DIGEST_GLOB" \
FRESH_DAYS="$FRESH_DAYS" STALE_DAYS="$STALE_DAYS" OUT="$OUT" python3 - <<'PYEOF'
import glob, json, os, sys
from datetime import datetime, timezone, timedelta
import xml.etree.ElementTree as ET

cache_dir = os.environ["CACHE_DIR"]
digest_dir = os.environ["DIGEST_DIR"]
digest_glob = os.environ["DIGEST_GLOB"]
fresh_days = int(os.environ["FRESH_DAYS"])
stale_days = int(os.environ["STALE_DAYS"])
out = os.environ["OUT"]

now = datetime.now(timezone.utc)
fresh_cutoff = now - timedelta(days=fresh_days)


def parse_dt(s):
    """Parse RFC3339 / RSS date variants; return aware UTC datetime or None."""
    if not s:
        return None
    s = s.strip()
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z",
                "%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z",
                "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
        except ValueError:
            continue
    # arXiv atom uses ...Z already handled; last resort: fromisoformat
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    except Exception:
        return None


# --- 1. staleness from _status.json (FAIL LOUD, never drop) ---
stale = []
try:
    with open(os.path.join(cache_dir, "_status.json")) as f:
        status = json.load(f)
except Exception as exc:  # noqa: BLE001
    print("check_source_monitors: _status.json unreadable: %s" % exc, file=sys.stderr)
    sys.exit(3)

for name, meta in (status.get("sources") or {}).items():
    st = meta.get("status")
    last = parse_dt(meta.get("last_success"))
    if st != "ok":
        stale.append({"source": name, "why": "status=%s" % st,
                      "fetch_error": meta.get("fetch_error")})
    elif last is None or (now - last).days >= stale_days:
        stale.append({"source": name,
                      "why": "no refresh in >=%sd (last_success=%s)" % (stale_days, meta.get("last_success"))})

# --- 2. dedup keys from the last 4 weekly digests (links/ids already reported) ---
seen = set()
digests = sorted(glob.glob(os.path.join(digest_dir, digest_glob)))[-4:]
for d in digests:
    try:
        with open(d, errors="ignore") as f:
            txt = f.read()
    except Exception:  # noqa: BLE001
        continue
    # crude but effective: any arxiv id or http link token already present is "seen"
    for tok in txt.replace("(", " ").replace(")", " ").split():
        if tok.startswith("http") or "arxiv.org/abs/" in tok:
            seen.add(tok.rstrip(".,);"))


# --- 3. parse each cached feed, keep fresh (<=FRESH_DAYS) + not-seen items ---
def strip_ns(tag):
    return tag.rsplit("}", 1)[-1]


fresh = {}
for path in sorted(glob.glob(os.path.join(cache_dir, "*"))):
    base = os.path.basename(path)
    if base.startswith("_") or base.lower() in ("readme.md",):
        continue
    try:
        root = ET.parse(path).getroot()
    except Exception:
        continue
    src = os.path.splitext(base)[0]
    items = []
    # Atom <entry> or RSS <item>
    for el in root.iter():
        if strip_ns(el.tag) not in ("entry", "item"):
            continue
        title = link = date = None
        for child in el:
            t = strip_ns(child.tag)
            if t == "title" and child.text:
                title = " ".join(child.text.split())
            elif t == "link":
                link = child.get("href") or (child.text or "").strip() or link
            elif t == "id" and not link:
                link = (child.text or "").strip()
            elif t in ("published", "updated", "pubDate", "date") and not date:
                date = parse_dt(child.text)
        if date is None or date < fresh_cutoff:
            continue
        key = (link or title or "").rstrip(".,);")
        if key and key in seen:
            continue
        items.append({"title": title, "link": link,
                      "date": date.strftime("%Y-%m-%d")})
    if items:
        fresh[src] = items

# --- 4. emit ---
if out == "json":
    print(json.dumps({"generated": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                      "fresh": fresh, "stale": stale}, indent=2))
else:
    if stale:
        print("STALE SOURCES (fail-loud — prefetch broken or behind):")
        for s in stale:
            print("  ! %s — %s%s" % (s["source"], s["why"],
                                     (" [%s]" % s["fetch_error"]) if s.get("fetch_error") else ""))
        print()
    total = sum(len(v) for v in fresh.values())
    print("FRESH ITEMS (<=%sd, deduped vs last 4 digests): %d" % (fresh_days, total))
    for src, items in fresh.items():
        print("\n## %s (%d)" % (src, len(items)))
        for it in items:
            print("  - [%s] %s — %s" % (it["date"], it["title"] or "(untitled)", it["link"] or ""))
    if total == 0 and not stale:
        print("  (no fresh items this window — cache is healthy)")
PYEOF
