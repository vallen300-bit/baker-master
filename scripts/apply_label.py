#!/usr/bin/env python3
"""Apply one label to the in-progress labeled JSONL file.

Usage: apply_label.py <idx> <vedana> <primary> <related_csv> <yn> <notes...>
  idx: 0-based signal index
  related_csv: "-" or "none" or "" treated as empty
  notes: optional (concatenates remaining args with space)

Creates outputs/kbl_eval_set_<DATE>_labeled.jsonl from the template on
first call, then updates row <idx> in place.
"""
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

OUT_DIR = Path("outputs")
DATE = os.environ.get("EVAL_DATE") or datetime.now(timezone.utc).strftime("%Y%m%d")
TEMPLATE = OUT_DIR / f"kbl_eval_set_{DATE}_labeling_template.jsonl"
LABELED = OUT_DIR / f"kbl_eval_set_{DATE}_labeled.jsonl"

VEDANA_ENUM = {"opportunity", "threat", "routine"}
VEDANA_MENU = {"1": "opportunity", "2": "threat", "3": "routine"}
MATTER_MENU = {
    "1": "hagenauer-rg7", "2": "cupial", "3": "mo-vie", "4": "ao",
    "5": "mrci", "6": "lilienmat", "7": "brisen-lp", "8": "aukera",
    "9": "null",
}
# Accept typo variants silently (wertheimer removed — now its own slug)
SLUG_ALIASES = {
    "lilienmatt": "lilienmat",
}


def parse_vedana(s: str) -> str:
    s = s.strip().lower()
    return VEDANA_MENU.get(s, s)


def parse_matter(s: str) -> str:
    s = s.strip()
    v = MATTER_MENU.get(s, s)
    return SLUG_ALIASES.get(v.lower(), v)


def normalize_related(raw: str) -> list[str]:
    r = (raw or "").strip().lower()
    if r in ("", "-", "none", "null"):
        return []
    out: list[str] = []
    for x in raw.split(","):
        x = x.strip()
        if not x:
            continue
        v = MATTER_MENU.get(x, x)
        out.append(SLUG_ALIASES.get(v.lower(), v))
    return out


def main():
    if len(sys.argv) < 6:
        print("usage: apply_label.py <idx> <vedana> <primary> <related_csv> <yn> [notes...]", file=sys.stderr)
        sys.exit(2)

    idx = int(sys.argv[1])
    vedana = parse_vedana(sys.argv[2])
    primary = parse_matter(sys.argv[3])
    related_raw = sys.argv[4]
    yn = sys.argv[5].strip().lower()
    notes = " ".join(sys.argv[6:]).strip() if len(sys.argv) > 6 else ""

    if vedana not in VEDANA_ENUM:
        print(f"ERROR: vedana must be 1/2/3 or opportunity/threat/routine, got {sys.argv[2]!r}", file=sys.stderr)
        sys.exit(2)
    if yn not in ("y", "n"):
        print(f"ERROR: yn must be y or n, got {yn!r}", file=sys.stderr)
        sys.exit(2)
    triage_pass = yn == "y"

    if primary.lower() in ("null", "none", "-", ""):
        primary_val = "null"
    else:
        primary_val = primary

    related_list = normalize_related(related_raw)

    if not LABELED.exists():
        shutil.copy(TEMPLATE, LABELED)

    with open(LABELED) as f:
        rows = [json.loads(l) for l in f]

    if not (0 <= idx < len(rows)):
        print(f"ERROR: idx {idx} out of range [0,{len(rows)})", file=sys.stderr)
        sys.exit(2)

    row = rows[idx]
    row["vedana_expected"] = vedana
    row["primary_matter_expected"] = primary_val
    row["related_matters_expected"] = related_list
    row["triage_threshold_pass_expected"] = triage_pass
    row["notes"] = notes

    tmp = LABELED.with_suffix(".jsonl.tmp")
    with open(tmp, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, LABELED)

    labeled_count = sum(1 for r in rows if r.get("vedana_expected"))
    print(f"OK signal {idx + 1}/{len(rows)} saved | labeled_so_far={labeled_count}/{len(rows)}")


if __name__ == "__main__":
    main()
