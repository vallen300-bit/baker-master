#!/usr/bin/env python3
"""LONG_RUNNING_JOB_OWNERSHIP_1 — ownership-register validator.

Validates config/long_running_jobs.yml: every entry must have all required
fields, name only KNOWN role slugs (validated against the codebase's canonical
slug set), carry a positive integer stall threshold, and declare a well-formed
cursor_source. Exits non-zero on any violation.

Wired into .githooks/pre-commit (Part 6) so an ownerless / unknown-slug /
bad-threshold register can never be committed.

Usage:
    python3 scripts/validate_long_running_jobs.py [--file PATH]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_REGISTER = _REPO_ROOT / "config" / "long_running_jobs.yml"

# Reuse the codebase's canonical slug set rather than re-listing the fleet.
# Falls back to a hardcoded current-fleet list (with a TODO) only if the
# generated registry is unavailable for some reason.
try:
    sys.path.insert(0, str(_REPO_ROOT))
    from orchestrator.agent_identity_data import VALID_BUS_SLUGS as _KNOWN_SLUGS_RAW
    KNOWN_SLUGS = set(_KNOWN_SLUGS_RAW)
except Exception:  # pragma: no cover - defensive fallback
    # TODO: keep in sync with orchestrator.agent_identity_data.VALID_BUS_SLUGS
    KNOWN_SLUGS = {
        "director", "daemon", "lead", "cowork-ah1", "deputy", "deputy-codex",
        "cortex", "aid", "b1", "b2", "b3", "b4", "researcher", "codex",
        "codex-arch", "clerk", "clerk-haiku", "russo-ai", "hag-desk",
        "origination-desk", "ao-desk", "CM-1", "CM-2", "CM-3", "CM-4",
        "hag-filer",
    }

_REQUIRED_SCALAR_FIELDS = (
    "job_id", "description", "trigger_reason", "stall_threshold_hours",
    "responsible", "accountable",
)
_REQUIRED_LIST_FIELDS = ("consulted", "informed")
_VALID_TRIGGER_REASONS = {"detached", "long-runtime", "multi-session"}
_SCALAR_SLUG_FIELDS = ("responsible", "accountable")

_CURSOR_SOURCE_REQUIRED = {
    "progress_table": (
        "table", "cursor_col", "updated_col", "key_col", "key_val", "total_col",
    ),
    "heartbeat": ("job_id",),
}


def load_yaml(path) -> dict:
    """Parse a register YAML file into a dict."""
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _validate_entry(entry: dict, idx: int) -> list[str]:
    errs: list[str] = []
    label = entry.get("job_id", f"<entry #{idx}>")

    if not isinstance(entry, dict):
        return [f"entry #{idx}: not a mapping"]

    for field in _REQUIRED_SCALAR_FIELDS:
        if field not in entry or entry[field] in (None, ""):
            errs.append(f"{label}: missing required field '{field}'")

    for field in _REQUIRED_LIST_FIELDS:
        if field not in entry:
            errs.append(f"{label}: missing required field '{field}'")
        elif not isinstance(entry[field], list):
            errs.append(f"{label}: field '{field}' must be a list")

    # trigger_reason
    tr = entry.get("trigger_reason")
    if tr is not None and tr not in _VALID_TRIGGER_REASONS:
        errs.append(
            f"{label}: invalid trigger_reason '{tr}' "
            f"(expected one of {sorted(_VALID_TRIGGER_REASONS)})"
        )

    # threshold must be a positive int
    thr = entry.get("stall_threshold_hours")
    if thr is not None:
        if not isinstance(thr, int) or isinstance(thr, bool) or thr <= 0:
            errs.append(
                f"{label}: stall_threshold_hours must be a positive integer "
                f"(got {thr!r})"
            )

    # slug validation — scalar owner fields
    for field in _SCALAR_SLUG_FIELDS:
        slug = entry.get(field)
        if slug is not None and slug not in KNOWN_SLUGS:
            errs.append(f"{label}: unknown role slug '{slug}' in '{field}'")

    # slug validation — list fields
    for field in _REQUIRED_LIST_FIELDS:
        vals = entry.get(field)
        if isinstance(vals, list):
            for slug in vals:
                if slug not in KNOWN_SLUGS:
                    errs.append(
                        f"{label}: unknown role slug '{slug}' in '{field}'"
                    )

    # cursor_source
    cs = entry.get("cursor_source")
    if cs is None:
        errs.append(f"{label}: missing required field 'cursor_source'")
    elif not isinstance(cs, dict):
        errs.append(f"{label}: cursor_source must be a mapping")
    else:
        kind = cs.get("kind")
        if kind not in _CURSOR_SOURCE_REQUIRED:
            errs.append(
                f"{label}: cursor_source.kind '{kind}' invalid "
                f"(expected one of {sorted(_CURSOR_SOURCE_REQUIRED)})"
            )
        else:
            for sub in _CURSOR_SOURCE_REQUIRED[kind]:
                if sub not in cs or cs[sub] in (None, ""):
                    errs.append(
                        f"{label}: cursor_source missing '{sub}' "
                        f"(required for kind '{kind}')"
                    )

    return errs


def validate(doc: dict) -> list[str]:
    """Return a list of human-readable validation errors (empty == valid)."""
    errs: list[str] = []
    if not isinstance(doc, dict):
        return ["register root must be a mapping with a 'jobs' list"]
    jobs = doc.get("jobs")
    if not isinstance(jobs, list) or not jobs:
        return ["register must contain a non-empty 'jobs' list"]

    seen_ids: set[str] = set()
    for idx, entry in enumerate(jobs):
        if isinstance(entry, dict):
            jid = entry.get("job_id")
            if jid in seen_ids:
                errs.append(f"duplicate job_id '{jid}'")
            elif jid:
                seen_ids.add(jid)
        errs.extend(_validate_entry(entry, idx))
    return errs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Validate the long-running-jobs ownership register."
    )
    ap.add_argument("--file", default=str(_DEFAULT_REGISTER),
                    help="path to the register YAML (default: config/long_running_jobs.yml)")
    args = ap.parse_args(argv)

    path = Path(args.file)
    if not path.exists():
        print(f"[validate_long_running_jobs] ERROR: {path} not found", file=sys.stderr)
        return 2

    try:
        doc = load_yaml(path)
    except yaml.YAMLError as e:
        print(f"[validate_long_running_jobs] ERROR: YAML parse failed: {e}",
              file=sys.stderr)
        return 2

    errs = validate(doc)
    if errs:
        print(f"[validate_long_running_jobs] {len(errs)} error(s) in {path}:",
              file=sys.stderr)
        for e in errs:
            print(f"  - {e}", file=sys.stderr)
        return 1

    n = len(doc.get("jobs", []))
    print(f"[validate_long_running_jobs] OK: {n} job(s) valid in {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
