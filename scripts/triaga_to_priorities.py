#!/usr/bin/env python3
"""Convert a ratified Triaga export markdown file into ``_priorities.yml``.

Wave-1 Track-5c. Spec: ``baker-vault/_ops/processes/cortex-priorities-schema.md``
(spec_version: 1, ratified 2026-04-29).

Input
-----
A Director-ratified Triaga export at
``_01_INBOX_FROM_CLAUDE/<date>-b1-brisen-triage-ratified-export.md``.
Each ratification is two lines (plus optional ``note:`` follow-ups):

::

    **Q<N> — <slug-text> — <description>**
    → STATUS: <Active|Completed|Dismiss> · WHEN: <When> · IMPORTANCE: <Imp> · CATEGORY: <Cat>
    note: <free text, may span lines>

Output
------
A YAML file at ``baker-vault/wiki/_priorities.yml`` matching the schema:
``schema_version: 1, ratified_at, ratified_by, ratified_from, categories[],
matters[], dismissed[], completed[], null_routine[], not_null_elevate[],
provenance{}``.

The downstream regen script (``scripts/regen_hot_md.py``, Track 5b) consumes
this file. Round-trip is asserted in the test suite.

CLI
---
::

    python3 scripts/triaga_to_priorities.py \\
        --export _01_INBOX_FROM_CLAUDE/2026-04-29-b1-brisen-triage-ratified-export.md \\
        --out baker-vault/wiki/_priorities.yml

Slug-field handling
-------------------
* ``[private-assets — slug TBD]`` → strip brackets + ``— slug TBD`` suffix.
* Multi-slug separators ``+`` / ``/``: split into list, primary slug first.
* Combined-slug overrides (``COMBINED_SLUGS_BY_REF``): some Q-IDs collapse a
  ``X + Y`` field into a single compound slug ``x-y`` per Director intent
  (e.g. Q33 NVIDIA + Corinthia → ``nvidia-corinthia``). Override map is
  exposed so callers can extend/replace it without code edits.
* Q19 NVIDIA+Corinthia AI Originations folds into Q33 (Director-ratified
  duplicate; B1 export note flags it). Configurable via ``DUPLICATE_FOLDS``.
"""
from __future__ import annotations

import argparse
import dataclasses
import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Union

import yaml

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants — value mappings (export pretty form → schema enum)
# ---------------------------------------------------------------------------

WHEN_MAP = {
    "asap": "asap",
    "urgent": "urgent",
    "4 weeks": "4w",
    "4w": "4w",
    "not urgent": "not-urgent",
}

IMPORTANCE_MAP = {
    "critical": "critical",
    "high": "high",
    "medium": "medium",
    "low": "low",
}

CATEGORY_MAP = {
    "active deal": "active-deal",
    "legal risk": "legal-risk",
    "financial": "financial",
    "financial / liquidity": "financial",
    "origination": "origination",
    "tax": "tax",
    "admin/ops/pr": "admin-ops-pr",
    "admin / ops / pr": "admin-ops-pr",
    "private assets": "private-assets",
    "personal": "personal-admin",
    "personal admin": "personal-admin",
    "pending": "pending",
}

DEFAULT_CATEGORIES = [
    "active-deal",
    "legal-risk",
    "financial",
    "origination",
    "tax",
    "admin-ops-pr",
    "private-assets",
    "personal-admin",
]

DEFAULT_NULL_ROUTINE = [
    "Marketing newsletters.",
    "Auction invite blasts.",
    "Generic event promos (conferences, summits, unrelated training).",
]

DEFAULT_NOT_NULL_ELEVATE = [
    "MIO »OBSERVER« press digest — always read + communicate to Director.",
    "Subscription renewal notices — Baker-critical (auto-renewal failure breaks Baker).",
]

# Q-IDs whose ``X + Y`` slug field collapses to a single compound slug.
# Director-ratified intent: NVIDIA+Corinthia is one origination matter, not two.
COMBINED_SLUGS_BY_REF: dict[str, str] = {
    "Q33": "nvidia-corinthia",
}

# Duplicate folds: source Q-ID → target Q-ID. Source rows are dropped silently.
# Q19 (NVIDIA+Corinthia AI Originations) folds into Q33 per the export's own
# B1 note: "probably duplicate of Q33".
DUPLICATE_FOLDS: dict[str, str] = {
    "Q19": "Q33",
}

_STATUS_VALUES = {"Active", "Completed", "Dismiss"}

_HEADER_LINE_RE = re.compile(r"^\*\*(Q\d+)\s+—\s+(.+?)\s+—\s+(.+?)\*\*\s*$")
_META_LINE_RE = re.compile(r"^→\s+STATUS:\s*(\S+)(.*)$")
_NOTE_LINE_RE = re.compile(r"^note:\s*(.+)$", re.IGNORECASE)
_DATE_LINE_RE = re.compile(r"^\*\*Date:\*\*\s*(\S+)\s*$")


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------


@dataclass
class TriagaItem:
    triaga_ref: str                  # "Q1"
    slug_field: str                  # raw slug text from header
    description: str                 # raw description
    status: str                      # "Active" | "Completed" | "Dismiss"
    when: Optional[str] = None       # schema enum after mapping
    importance: Optional[str] = None
    category: Optional[str] = None
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def parse_export(text: str) -> dict:
    """Parse a Triaga export markdown into a structured intermediate.

    Returns a dict with keys:
    - ``items``: list[TriagaItem]
    - ``ratified_date``: str (YYYY-MM-DD from the ``**Date:**`` header), or ``""``

    Raises ``ValueError`` on malformed entries (missing ``→ STATUS:`` line, or
    a status outside the allowed set).
    """
    items: list[TriagaItem] = []
    ratified_date = ""

    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()

        date_m = _DATE_LINE_RE.match(line)
        if date_m and not ratified_date:
            ratified_date = date_m.group(1)
            i += 1
            continue

        header_m = _HEADER_LINE_RE.match(line)
        if not header_m:
            i += 1
            continue

        triaga_ref = header_m.group(1)
        slug_field = header_m.group(2).strip()
        description = header_m.group(3).strip()

        # Find the next non-blank line — must be the meta line.
        j = i + 1
        while j < len(lines) and lines[j].strip() == "":
            j += 1
        if j >= len(lines):
            raise ValueError(
                f"{triaga_ref}: header at line {i + 1} has no following meta line"
            )
        meta_line = lines[j].rstrip()
        meta_m = _META_LINE_RE.match(meta_line)
        if not meta_m:
            raise ValueError(
                f"{triaga_ref}: expected '→ STATUS: …' on line {j + 1}, "
                f"got: {meta_line!r}"
            )
        status = meta_m.group(1).rstrip(",.;:")
        if status not in _STATUS_VALUES:
            raise ValueError(
                f"{triaga_ref}: status must be one of {sorted(_STATUS_VALUES)}, "
                f"got {status!r}"
            )
        rest = meta_m.group(2)

        when, importance, category = _parse_meta_rest(rest, status, triaga_ref)

        # Walk forward to capture note: lines until a blank line followed by
        # another header OR a section break (line starting with '---' / '##').
        notes: list[str] = []
        k = j + 1
        while k < len(lines):
            ln = lines[k].rstrip()
            note_m = _NOTE_LINE_RE.match(ln.lstrip())
            if note_m:
                notes.append(note_m.group(1).strip())
                k += 1
                continue
            stripped = ln.strip()
            # Continuation of last note (free-text follow-on, indented or plain)
            # only if previous non-blank was a note line and this isn't a header.
            if stripped == "":
                k += 1
                continue
            if (
                _HEADER_LINE_RE.match(ln)
                or stripped.startswith("##")
                or stripped.startswith("---")
            ):
                break
            # Treat as a continuation line on the most recent note (rare).
            if notes:
                notes[-1] = (notes[-1] + " " + stripped).strip()
                k += 1
                continue
            break

        items.append(
            TriagaItem(
                triaga_ref=triaga_ref,
                slug_field=slug_field,
                description=description,
                status=status,
                when=when,
                importance=importance,
                category=category,
                notes=notes,
            )
        )
        i = k

    return {"items": items, "ratified_date": ratified_date}


def _parse_meta_rest(
    rest: str, status: str, triaga_ref: str
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Parse the ``· WHEN: ... · IMPORTANCE: ... · CATEGORY: ...`` tail.

    Active items must have all three fields; Completed/Dismiss items are
    allowed to omit them entirely.
    """
    fields_text = rest.lstrip(" ·")
    parts = [p.strip() for p in re.split(r"\s+·\s+", fields_text) if p.strip()]
    pulled: dict[str, str] = {}
    for part in parts:
        if ":" not in part:
            continue
        key, val = part.split(":", 1)
        pulled[key.strip().lower()] = val.strip()

    when = _map_value("when", pulled.get("when"), WHEN_MAP, triaga_ref) if pulled.get("when") else None
    importance = (
        _map_value("importance", pulled.get("importance"), IMPORTANCE_MAP, triaga_ref)
        if pulled.get("importance")
        else None
    )
    category = (
        _map_value("category", pulled.get("category"), CATEGORY_MAP, triaga_ref)
        if pulled.get("category")
        else None
    )

    if status == "Active" and not (when and importance and category):
        raise ValueError(
            f"{triaga_ref}: Active item missing WHEN/IMPORTANCE/CATEGORY "
            f"(got when={when!r} importance={importance!r} category={category!r})"
        )
    return when, importance, category


def _map_value(field_name: str, raw: str, table: dict, triaga_ref: str) -> str:
    key = raw.strip().lower()
    if key in table:
        return table[key]
    # Fall back to the raw lowercased token — regen will surface unknown
    # categories as-is, which lets new ratification rounds introduce them
    # without blocking the converter on map maintenance.
    if field_name == "category":
        return key
    raise ValueError(
        f"{triaga_ref}: {field_name}={raw!r} not in known values "
        f"({sorted(table)})"
    )


# ---------------------------------------------------------------------------
# Slug-field normalization
# ---------------------------------------------------------------------------


_TBD_BRACKET_RE = re.compile(r"^\[(.+?)(?:\s+—\s+slug\s+TBD)?(?:\s+—\s+see\s+note)?\]$", re.IGNORECASE)


def normalize_slug_field(
    raw: str,
    triaga_ref: str,
    *,
    combined_slugs_by_ref: Optional[dict[str, str]] = None,
) -> Union[str, list[str]]:
    """Translate the raw ``slug-text`` field into a string OR a list of slugs.

    Steps:
    1. If wrapped in ``[...]``, strip brackets + ``— slug TBD`` / ``— see note``
       suffixes — leaves only the slug hint inside.
    2. If ``triaga_ref`` is in ``combined_slugs_by_ref``, return that compound
       slug as a single string (overrides any split logic).
    3. Otherwise split on ``+`` or ``/`` separators, trim whitespace, lowercase,
       and return list-of-slugs (single-element list collapses to bare string).
    """
    overrides = combined_slugs_by_ref if combined_slugs_by_ref is not None else COMBINED_SLUGS_BY_REF
    if triaga_ref in overrides:
        return overrides[triaga_ref]

    cleaned = raw.strip()
    bracket_m = _TBD_BRACKET_RE.match(cleaned)
    if bracket_m:
        cleaned = bracket_m.group(1).strip()

    parts = [p.strip().lower() for p in re.split(r"\s*[+/]\s*", cleaned) if p.strip()]
    if not parts:
        raise ValueError(f"{triaga_ref}: empty slug field after normalization")
    if len(parts) == 1:
        return parts[0]
    return parts


# ---------------------------------------------------------------------------
# Convert parsed items → schema dict
# ---------------------------------------------------------------------------


def to_priorities_dict(
    parsed: dict,
    *,
    ratified_at: str,
    source_inbox: str,
    archive_copy: str = "",
    combined_slugs_by_ref: Optional[dict[str, str]] = None,
    duplicate_folds: Optional[dict[str, str]] = None,
) -> dict:
    """Build the final ``_priorities.yml`` dict from a ``parse_export`` result."""
    items: list[TriagaItem] = list(parsed["items"])
    folds = duplicate_folds if duplicate_folds is not None else DUPLICATE_FOLDS

    # Drop folded duplicates first (Q19 → Q33).
    folded_refs = set(folds.keys())
    items = [it for it in items if it.triaga_ref not in folded_refs]

    matters: list[dict] = []
    dismissed: list[dict] = []
    completed: list[dict] = []
    partial_count = 0

    ratified_date = ratified_at.split("T", 1)[0] if "T" in ratified_at else ratified_at[:10]

    for it in items:
        slug_value = normalize_slug_field(
            it.slug_field, it.triaga_ref, combined_slugs_by_ref=combined_slugs_by_ref
        )
        if it.status == "Active":
            entry: dict[str, Any] = {}
            if isinstance(slug_value, list):
                entry["slugs"] = slug_value
            else:
                entry["slug"] = slug_value
            entry["when"] = it.when
            entry["importance"] = it.importance
            entry["category"] = it.category
            if it.category == "pending":
                partial_count += 1
            entry["triaga_ref"] = it.triaga_ref
            entry["description"] = it.description
            entry["notes"] = []
            matters.append(entry)
        elif it.status == "Completed":
            entry = {"triaga_ref": it.triaga_ref}
            if isinstance(slug_value, list):
                entry["slugs"] = slug_value
            else:
                entry["slug"] = slug_value
            entry["completed_at"] = ratified_date
            entry["summary"] = it.description
            completed.append(entry)
        else:  # Dismiss
            entry = {"triaga_ref": it.triaga_ref}
            if isinstance(slug_value, list):
                entry["slugs"] = slug_value
            else:
                entry["slug"] = slug_value
            entry["reason"] = " ".join(it.notes) if it.notes else f"Director dismissed ({it.triaga_ref})."
            entry["dismissed_at"] = ratified_date
            dismissed.append(entry)

    out: dict[str, Any] = {
        "schema_version": 1,
        "ratified_at": ratified_at,
        "ratified_by": "director",
        "ratified_from": source_inbox,
        "last_regen_at": None,
        "last_regen_sha": None,
        "categories": list(DEFAULT_CATEGORIES),
        "matters": matters,
        "dismissed": dismissed,
        "completed": completed,
        "null_routine": list(DEFAULT_NULL_ROUTINE),
        "not_null_elevate": list(DEFAULT_NOT_NULL_ELEVATE),
        "provenance": {
            "source_inbox": source_inbox,
            "archive_copy": archive_copy,
            "ratified_count": len(items),
            "active_count": len(matters),
            "completed_count": len(completed),
            "dismissed_count": len(dismissed),
            "partial_count": partial_count,
        },
    }
    return out


# ---------------------------------------------------------------------------
# YAML emission
# ---------------------------------------------------------------------------


def render_yaml(data: dict) -> str:
    """Dump the priorities dict to YAML with stable, human-readable formatting."""
    return yaml.safe_dump(
        data,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
        width=10_000,        # single-line strings — no auto-wrap
    )


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------


def triaga_export_to_priorities(
    export_md_path: Union[str, Path],
    out_yml_path: Union[str, Path],
    *,
    ratified_at: Optional[str] = None,
    source_inbox: Optional[str] = None,
    archive_copy: str = "",
    combined_slugs_by_ref: Optional[dict[str, str]] = None,
    duplicate_folds: Optional[dict[str, str]] = None,
) -> dict:
    """Convert a Triaga export markdown file → ``_priorities.yml`` on disk.

    Parameters
    ----------
    export_md_path
        Path to the ratified export markdown.
    out_yml_path
        Path to write ``_priorities.yml``.
    ratified_at
        ISO timestamp for the ``ratified_at:`` field. Defaults to
        ``<date-from-export>T18:45:00+02:00`` (matches the schema-spec example
        time when only a date is on the header).
    source_inbox
        Override for ``ratified_from:`` and ``provenance.source_inbox``.
        Defaults to the export filename relative to the inbox root.
    archive_copy
        Optional ``provenance.archive_copy`` value.
    combined_slugs_by_ref
        Override the default Q-ID → compound-slug map.
    duplicate_folds
        Override the default duplicate-fold map.

    Returns
    -------
    dict
        The priorities dict that was written (callers can re-use without
        re-reading from disk).
    """
    export_path = Path(export_md_path)
    out_path = Path(out_yml_path)
    text = export_path.read_text(encoding="utf-8")
    parsed = parse_export(text)

    if not ratified_at:
        date = parsed.get("ratified_date") or ""
        if not date:
            raise ValueError(
                "ratified_at not given and export has no '**Date:** YYYY-MM-DD' header"
            )
        ratified_at = f"{date}T18:45:00+02:00"

    if source_inbox is None:
        # Default: export filename under _01_INBOX_FROM_CLAUDE/.
        source_inbox = f"_01_INBOX_FROM_CLAUDE/{export_path.name}"

    data = to_priorities_dict(
        parsed,
        ratified_at=ratified_at,
        source_inbox=source_inbox,
        archive_copy=archive_copy,
        combined_slugs_by_ref=combined_slugs_by_ref,
        duplicate_folds=duplicate_folds,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_yaml(data), encoding="utf-8")
    return data


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--export", required=True, help="Triaga export markdown path")
    parser.add_argument("--out", required=True, help="Output _priorities.yml path")
    parser.add_argument("--ratified-at", help="Override ratified_at ISO timestamp")
    parser.add_argument("--source-inbox", help="Override provenance.source_inbox")
    parser.add_argument("--archive-copy", default="", help="Optional provenance.archive_copy")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    data = triaga_export_to_priorities(
        args.export,
        args.out,
        ratified_at=args.ratified_at,
        source_inbox=args.source_inbox,
        archive_copy=args.archive_copy,
    )
    prov = data["provenance"]
    print(
        f"OK: wrote {args.out} "
        f"({prov['ratified_count']} items: "
        f"{prov['active_count']} Active · "
        f"{prov['completed_count']} Completed · "
        f"{prov['dismissed_count']} Dismissed · "
        f"{prov['partial_count']} Partial)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
