#!/usr/bin/env python3
"""Present one signal from the unlabeled JSONL in menu-style for Director labeling.

Usage: present_signal.py <idx>
  idx: 0-based signal index
"""
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

OUT_DIR = Path("outputs")
DATE = os.environ.get("EVAL_DATE") or datetime.now(timezone.utc).strftime("%Y%m%d")
UNLABELED = OUT_DIR / f"kbl_eval_set_{DATE}.jsonl"

MATTERS = [
    ("1", "hagenauer-rg7"),
    ("2", "cupial"),
    ("3", "mo-vie"),
    ("4", "ao"),
    ("5", "mrci"),
    ("6", "lilienmat"),
    ("7", "brisen-lp"),
    ("8", "aukera"),
    ("9", "null"),
]
EXTRA_MATTERS_BY_NAME = ("kitzbuhel-six-senses", "kitz-kempinski", "steininger", "edita-russo", "theailogy", "baker-internal", "personal")


def extract_meta(body: str) -> dict:
    """Pull From/To/Date/Subject out of stored thread header if present."""
    meta: dict = {}
    for key in ("Date", "Participants", "From", "To", "Subject"):
        m = re.search(rf"^{key}:\s*(.+)$", body, flags=re.MULTILINE)
        if m:
            meta[key] = m.group(1).strip()
    return meta


def main():
    if len(sys.argv) < 2:
        print("usage: present_signal.py <idx>", file=sys.stderr)
        sys.exit(2)
    idx = int(sys.argv[1])

    with open(UNLABELED) as f:
        rows = [json.loads(l) for l in f]
    if not (0 <= idx < len(rows)):
        print(f"ERROR: idx {idx} out of range [0,{len(rows)})", file=sys.stderr)
        sys.exit(2)

    r = rows[idx]
    body = r.get("raw_content") or ""
    meta = extract_meta(body)
    hint = r.get("hint_matter_if_tagged") or None

    bar = "━" * 44
    print(bar)
    header = f"Signal {idx + 1}/{len(rows)} | source: {r['source']}"
    if meta.get("Date"):
        header += f" | date: {meta['Date'].split('T')[0]}"
    print(header)

    if r["source"] == "email":
        from_ = meta.get("Participants") or meta.get("From") or "(unknown)"
        print(f"From: {from_}")
        if r.get("title"):
            print(f"Subject: {r['title']}")
    elif r["source"] == "whatsapp":
        if meta.get("Participants"):
            print(f"Chat: {meta['Participants']}")
    elif r["source"] == "meeting":
        if r.get("title"):
            print(f"Title: {r['title']}")

    preview_limit = 1200 if r["source"] != "meeting" else 2000
    preview = body if len(body) <= preview_limit else body[:preview_limit] + f"\n... [truncated — full len {len(body)}]"
    print()
    print(preview)
    print()
    print(f"Hint matter (from tags): {hint or 'none'}")
    print(bar)

    vedana_line = "Vedana:   (1) opportunity   (2) threat   (3) routine"
    print(vedana_line)

    matter_parts = []
    for num, slug in MATTERS:
        star = "*" if hint == slug else " "
        matter_parts.append(f"({num}){star}{slug}")
    print("Matter:   " + "   ".join(matter_parts))
    print("Others (type by name): " + ", ".join(EXTRA_MATTERS_BY_NAME))
    print("Alert:    (y) yes   (n) no")
    print()
    print("Reply: <v#> | <m#> | <related m# CSV or -> | <y/n> | <notes optional>")


if __name__ == "__main__":
    main()
