#!/usr/bin/env bash
# regen_research_index.sh — regenerate the researcher's prior-report index.
#
# RESEARCHER_TRANCHE2_8_RESEARCH_MEMORY_INDEX (b2, 2026-07-12; dispatch lead #9721
# + #9894 + #9898, Option B design-approved). Item #8: the researcher re-runs findings
# cold because there is no queryable prior-report surface. The only index,
# wiki/research/_index.md, was seed-written once (updated_by: seed_migration, 2026-04-14)
# and covers only the April NVIDIA/Corinthia cluster — 55+ reports since are invisible.
#
# This script scans wiki/research/*.md (excluding _index.*), best-effort-parses the
# heterogeneous frontmatter of each report, and emits:
#   * wiki/research/_index.json — the MACHINE source of truth (one record per report),
#   * wiki/research/_index.md   — a REGENERATED human Obsidian view of the SAME manifest
#     (lead ruling #9898 §2: _index.md is regenerated from the manifest, single SoT —
#     it is NOT hand-maintained).
#
# CAGE POSTURE (Option B, design §4.5; lead ruling #9898 cage note): the write target
# (wiki/research/) is a researcher-writable root and this is a vetted bash script, so the
# in-cage write is legitimate. NO env override, NO arg-driven config path — the scan/write
# dir is HARD-PINNED to $HOME/baker-vault/wiki/research (same hardening as
# check_source_monitors.sh / item #12). The additive IS_VETTED entry in
# researcher_bash_cage.sh is ADDITIVE ONLY — it relaxes no existing deny.
#
# FAIL-LOUD, not silent-drop (design §4.1; mirrors #12): a report with no frontmatter
# (or malformed YAML) is STILL indexed (path + mtime + filename-derived title/date) with
# flags:["no-frontmatter"] and surfaced in the run summary — never dropped.
#
# Usage:
#   regen_research_index.sh            # regenerate _index.json + _index.md, print summary
#   regen_research_index.sh --check    # DRY-RUN: report what WOULD change; write nothing
set -u

VAULT_DIR="$HOME/baker-vault"                       # HARD-PINNED (no env override)
RESEARCH_DIR="$VAULT_DIR/wiki/research"             # scan + write root (in-cage)
REL_PREFIX="wiki/research"                          # path prefix recorded in the manifest

fail() { echo "regen_research_index: $1" >&2; exit "${2:-1}"; }

# --- arg parse: only an optional --check flag; no arg-driven config path ---
MODE="write"
if [ "$#" -gt 1 ]; then fail "at most one flag (--check) accepted" 1; fi
if [ "$#" -eq 1 ]; then
    case "$1" in
        --check) MODE="check" ;;
        *) fail "unknown arg '$1' (only --check)" 1 ;;
    esac
fi

[ -d "$RESEARCH_DIR" ] || fail "research dir missing ($RESEARCH_DIR) — is baker-vault checked out? (fail-loud)" 3

RESEARCH_DIR="$RESEARCH_DIR" REL_PREFIX="$REL_PREFIX" MODE="$MODE" python3 - <<'PYEOF'
import glob, json, os, re, sys
from datetime import datetime, timezone

research_dir = os.environ["RESEARCH_DIR"]
rel_prefix = os.environ["REL_PREFIX"]
mode = os.environ["MODE"]

now = datetime.now(timezone.utc)
SUMMARY_CAP = 240
FN_DATE = re.compile(r"^(\d{4}-\d{2}-\d{2})")


def unquote(v):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
        return v[1:-1].strip()
    return v


def parse_frontmatter(text):
    """Best-effort YAML-frontmatter parse (no pyyaml dep). Returns (dict, had_fm).
    Handles `key: value`, inline `[a, b]` lists, and `key:`/`  - item` block lists.
    Never raises: a malformed line is skipped, not fatal (fail-loud handled by caller)."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, False
    fm = {}
    i = 1
    cur_key = None
    while i < len(lines):
        line = lines[i]
        if line.strip() == "---":
            break
        # block-list continuation: `  - item`
        m = re.match(r"^\s+-\s+(.*)$", line)
        if m and cur_key is not None:
            # an empty `key:` opener leaves cur_key set to "" — promote it to a list
            if not isinstance(fm.get(cur_key), list):
                fm[cur_key] = []
            fm[cur_key].append(unquote(m.group(1)))
            i += 1
            continue
        m = re.match(r"^([A-Za-z0-9_.-]+):\s*(.*)$", line)
        if m:
            key, val = m.group(1), m.group(2)
            cur_key = key
            val_s = val.strip()
            if val_s == "":
                # may be a block list opener; leave unset until we see items
                fm.setdefault(key, "")
            elif val_s.startswith("[") and val_s.endswith("]"):
                inner = val_s[1:-1].strip()
                fm[key] = [unquote(x) for x in inner.split(",") if x.strip()] if inner else []
            else:
                fm[key] = unquote(val_s)
        else:
            cur_key = None
        i += 1
    # drop empty block-list openers that never got items
    fm = {k: v for k, v in fm.items() if v != ""}
    return fm, True


def derive_title(fname):
    stem = re.sub(r"\.md$", "", fname)
    stem = FN_DATE.sub("", stem).lstrip("-")
    stem = stem.replace("-", " ").strip()
    return stem if stem else fname


def extract_summary(text, fm):
    for key in ("summary", "purpose", "deliverable_for"):
        if fm.get(key):
            return str(fm[key]).strip()[:SUMMARY_CAP]
    # else: first non-heading, non-blank paragraph after any frontmatter
    body = text
    if body.split("\n")[:1] == ["---"]:
        parts = body.split("\n---", 1)
        body = parts[1] if len(parts) > 1 else body
    for para in re.split(r"\n\s*\n", body):
        p = para.strip()
        if not p or p.startswith("#") or p.startswith("---") or p.startswith("|"):
            continue
        p = " ".join(p.split())
        return p[:SUMMARY_CAP]
    return ""


def as_list(v):
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x) for x in v]
    return [str(v)]


records = []
no_fm = []
paths = sorted(glob.glob(os.path.join(research_dir, "*.md")))
for path in paths:
    fname = os.path.basename(path)
    if fname.startswith("_index"):
        continue
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except Exception as exc:  # noqa: BLE001 — fail-loud on unreadable, never drop
        print("regen_research_index: unreadable report %s: %s" % (fname, exc), file=sys.stderr)
        sys.exit(3)

    fm, had_fm = parse_frontmatter(text)
    flags = []
    if not had_fm:
        flags.append("no-frontmatter")

    # date: frontmatter → filename prefix → null
    date = fm.get("date") or fm.get("created") or ""
    if not date:
        m = FN_DATE.match(fname)
        date = m.group(1) if m else ""
    if not date:
        flags.append("no-date")

    title = fm.get("title") or derive_title(fname)
    mtime = datetime.fromtimestamp(os.path.getmtime(path), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    rec = {
        "path": "%s/%s" % (rel_prefix, fname),
        "title": str(title).strip(),
        "date": str(date).strip(),
        "author": str(fm.get("author") or fm.get("requested_by") or "").strip(),
        "type": str(fm.get("type") or "research").strip(),
        "tags": as_list(fm.get("tags")),
        "summary": extract_summary(text, fm),
        "mtime": mtime,
        "flags": flags,
    }
    records.append(rec)
    if not had_fm:
        no_fm.append(rec["path"])

# Deterministic ordering: date DESC, then path ASC; undated reports sort last
# (also path ASC). Python's sort is stable, so sort by path ascending first, then
# by date descending — same-date ties retain path-ascending order. No string
# negation needed, and the result is fully deterministic across runs.
dated = [r for r in records if r["date"]]
dated.sort(key=lambda r: r["path"])
dated.sort(key=lambda r: r["date"], reverse=True)
undated = sorted((r for r in records if not r["date"]), key=lambda r: r["path"])
records = dated + undated

manifest = {
    "schema_version": 1,
    "generated": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    "count": len(records),
    "reports": records,
}
json_body = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"


# --- human _index.md, regenerated from the SAME manifest (single SoT) ---
def md_view(recs):
    lines = [
        "---",
        'title: "Research Index"',
        "type: system",
        "confidence: high",
        "updated_by: regen_research_index.sh",
        'note: "GENERATED FILE — do not hand-edit; regenerate via scripts/regen_research_index.sh"',
        "---",
        "",
        "# Research — Index",
        "",
        "_%d reports · regenerated %s · machine source of truth: `_index.json`_"
        % (len(recs), now.strftime("%Y-%m-%d")),
        "",
        "| Date | Report | Summary | Flags |",
        "|------|--------|---------|-------|",
    ]
    for r in recs:
        link = r["path"][:-3] if r["path"].endswith(".md") else r["path"]
        title = r["title"].replace("|", "\\|")
        summ = (r["summary"] or "").replace("|", "\\|").replace("\n", " ")
        flags = ",".join(r["flags"]) if r["flags"] else ""
        lines.append("| %s | [[%s\\|%s]] | %s | %s |"
                     % (r["date"] or "—", link, title, summ, flags))
    lines.append("")
    return "\n".join(lines)


md_body = md_view(records)

json_path = os.path.join(research_dir, "_index.json")
md_path = os.path.join(research_dir, "_index.md")

if mode == "check":
    print("DRY-RUN (--check): %d reports would be indexed." % len(records))
    if no_fm:
        print("no-frontmatter (indexed, flagged, NOT dropped): %d" % len(no_fm))
        for p in no_fm:
            print("  ! %s" % p)
    sys.exit(0)

with open(json_path, "w", encoding="utf-8") as f:
    f.write(json_body)
with open(md_path, "w", encoding="utf-8") as f:
    f.write(md_body)

print("regen_research_index: wrote _index.json + _index.md (%d reports)." % len(records))
if no_fm:
    print("FLAGGED no-frontmatter (indexed, not dropped): %d" % len(no_fm))
    for p in no_fm:
        print("  ! %s" % p)
PYEOF
