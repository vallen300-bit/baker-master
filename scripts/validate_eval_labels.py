"""
KBL Pre-Shadow Eval — Label Validator

Validates a labeled JSONL file produced by the Director (Option A manual edit
or Option B Baker-chat append). Fails fast on the first invalid row.

Usage:
  python3 scripts/validate_eval_labels.py outputs/kbl_eval_set_20260417_labeling_template.jsonl
  python3 scripts/validate_eval_labels.py <path>

Exit codes:
  0 = all rows valid (e.g. "50/50 valid")
  1 = one or more rows invalid (prints per-row errors, up to --max-errors)

A "valid" row satisfies ALL of:
  signal_id                       — non-empty string
  source                          — in {"email", "whatsapp", "meeting"}
  vedana_expected                 — in {"opportunity", "threat", "routine"} (production schema)
  primary_matter_expected         — in MATTER_ALLOWLIST or None
  related_matters_expected        — list of strings each in MATTER_ALLOWLIST
  triage_threshold_pass_expected  — boolean
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List

VALID_VEDANA = {"opportunity", "threat", "routine"}
VALID_SOURCES = {"email", "whatsapp", "meeting"}

MATTER_ALLOWLIST = {
    "hagenauer-rg7",
    "cupial",
    "mo-vie",
    "ao",
    "brisen-lp",
    "mrci",
    "lilienmat",
    "edita-russo",
    "theailogy",
    "baker-internal",
    "personal",
}


def validate_row(row: dict, line_no: int) -> List[str]:
    errors: List[str] = []

    sid = row.get("signal_id")
    if not isinstance(sid, str) or not sid:
        errors.append(f"line {line_no}: signal_id must be non-empty string (got {sid!r})")

    source = row.get("source")
    if source not in VALID_SOURCES:
        errors.append(
            f"line {line_no} [{sid}]: source={source!r} not in {sorted(VALID_SOURCES)}"
        )

    vedana = row.get("vedana_expected")
    if vedana not in VALID_VEDANA:
        errors.append(
            f"line {line_no} [{sid}]: vedana_expected={vedana!r} must be one of {sorted(VALID_VEDANA)}"
        )

    pm = row.get("primary_matter_expected")
    if pm is not None and pm not in MATTER_ALLOWLIST:
        errors.append(
            f"line {line_no} [{sid}]: primary_matter_expected={pm!r} "
            f"not in allowlist (null OR one of {sorted(MATTER_ALLOWLIST)})"
        )

    rel = row.get("related_matters_expected")
    if not isinstance(rel, list):
        errors.append(
            f"line {line_no} [{sid}]: related_matters_expected must be a list (got {type(rel).__name__})"
        )
    else:
        for i, m in enumerate(rel):
            if m not in MATTER_ALLOWLIST:
                errors.append(
                    f"line {line_no} [{sid}]: related_matters_expected[{i}]={m!r} not in allowlist"
                )
        if pm is not None and pm in rel:
            errors.append(
                f"line {line_no} [{sid}]: primary_matter_expected={pm!r} should NOT also appear in related_matters_expected"
            )

    tp = row.get("triage_threshold_pass_expected")
    if not isinstance(tp, bool):
        errors.append(
            f"line {line_no} [{sid}]: triage_threshold_pass_expected must be true/false "
            f"(got {tp!r} of type {type(tp).__name__})"
        )

    return errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("path", help="Path to labeled JSONL")
    parser.add_argument("--max-errors", type=int, default=10,
                        help="Stop reporting after this many errors (default 10)")
    parser.add_argument("--allow-nulls", action="store_true",
                        help="Pass if labels are still null (dry-run sanity on empty template)")
    args = parser.parse_args()

    p = Path(args.path)
    if not p.exists():
        print(f"ERROR: {p} not found", file=sys.stderr)
        sys.exit(1)

    total = 0
    valid = 0
    errors: List[str] = []
    saw_any_filled = False

    with open(p) as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            total += 1
            try:
                row = json.loads(line)
            except json.JSONDecodeError as e:
                errors.append(f"line {line_no}: invalid JSON ({e})")
                continue

            if args.allow_nulls and row.get("vedana_expected") is None \
                    and row.get("triage_threshold_pass_expected") is None:
                # Template unlabeled — skip validation but count as structural-pass.
                valid += 1
                continue

            if row.get("vedana_expected") is not None:
                saw_any_filled = True

            row_errors = validate_row(row, line_no)
            if not row_errors:
                valid += 1
            else:
                errors.extend(row_errors)
                if len(errors) >= args.max_errors:
                    errors.append(
                        f"... stopping after {args.max_errors} errors (use --max-errors to see more)"
                    )
                    break

    if args.allow_nulls and not saw_any_filled:
        print(f"{valid}/{total} rows structurally valid (dry-run: no labels filled yet)")
        sys.exit(0)

    if errors:
        print(f"{valid}/{total} valid — {total - valid} error(s):")
        for e in errors:
            print(f"  {e}")
        sys.exit(1)

    print(f"{valid}/{total} valid")
    sys.exit(0)


if __name__ == "__main__":
    main()
