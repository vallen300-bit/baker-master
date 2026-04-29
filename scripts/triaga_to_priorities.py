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
* Header parser handles bracketed slug fields containing em-dashes
  (``[private-assets — slug TBD]``) by anchoring on the bracket close, not
  on the first ` — `. Without this, Q17/Q18/Q37 would emit slug=``[private-assets``
  with the bracket-suffix bleeding into the description.
* Inside the brackets the suffix ``— slug TBD`` / ``— see note`` is stripped.
* Multi-slug separators:
    - ``+`` always splits (per RA-23 — the canonical multi-slug separator).
    - ``/`` splits only when ALL slash-separated tokens match the canonical
      slug shape ``^[a-z0-9][a-z0-9-]+$`` AND a registry is supplied AND
      every token resolves against it. Otherwise ``/`` is treated as prose
      and the slug field stays as a single literal string. Q30 ``tax / lana``
      and Q31 ``tax / cbp`` (where ``tax`` is a category prefix, not a slug)
      no longer split into multi-slug lists.
* Combined-slug overrides (``COMBINED_SLUGS_BY_REF``): some Q-IDs collapse a
  ``X + Y`` field into a single compound slug ``x-y`` per Director intent
  (e.g. Q33 NVIDIA + Corinthia → ``nvidia-corinthia``).
* Q19 NVIDIA+Corinthia AI Originations folds into Q33 (Director-ratified
  duplicate; B1 export note flags it). Configurable via ``DUPLICATE_FOLDS``.

Canonical-slug validation
-------------------------
If a canonical-slug set is supplied (CLI ``--registry path/to/slugs.yml``,
or kwarg ``canonical_slugs=`` to :func:`triaga_export_to_priorities`), every
emitted slug is checked against it. Non-canonical slugs are EMITTED in the
matter row (the converter never blocks on a Director-wishlist slug) AND
recorded in a top-level ``pending_slug_review[]`` section so regen + Director
both see them.

The ``CANONICAL_SLUG_LOOSE`` module flag (default False) gates whether the
``pending_slug_review`` section is populated. When True, the converter only
logs warnings and emits an empty ``pending_slug_review[]`` — useful while the
downstream regen layer is still learning to consume the new section.
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

# Detect a header line — capture Q-ID + everything between it and the trailing **.
# Splitting slug-field from description is a second step (handles bracketed
# slug fields containing internal em-dashes).
_HEADER_LINE_RE = re.compile(r"^\*\*\s*(Q\d+)\s+—\s+(.+)\*\*\s*$")
_META_LINE_RE = re.compile(r"^→\s+STATUS:\s*(\S+)(.*)$")
_NOTE_LINE_RE = re.compile(r"^note:\s*(.+)$", re.IGNORECASE)
_DATE_LINE_RE = re.compile(r"^\*\*Date:\*\*\s*(\S+)\s*$")

# Default-False module flag controlling whether non-canonical slugs are
# recorded in `pending_slug_review[]`. When True, the converter logs warnings
# only — the section is emitted empty so regen can ignore it during the
# transition. See module docstring "Canonical-slug validation" section.
CANONICAL_SLUG_LOOSE: bool = False

# Slug-shape used by the `/` split heuristic (Bug 2 hardening). A token
# qualifies as a possible-slug only if it matches this shape.
_CANONICAL_SLUG_SHAPE = re.compile(r"^[a-z0-9][a-z0-9-]+$")


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


def _split_slug_from_description(rest: str) -> tuple[str, str]:
    """Bisect a header tail into (slug_field, description).

    Bracketed slug fields (``[...]``) may contain em-dashes internally
    (e.g. ``[private-assets — slug TBD]``); anchor on the matching ``]``
    instead of the first ` — ` to keep the bracket suffix from bleeding
    into the description.

    Falls back to first ` — ` for unbracketed slug fields, which preserves
    the prior behaviour for ``hagenauer-rg7 — GC takeover — complete hotel...``
    style entries (description em-dashes survive the non-greedy split).
    """
    rest = rest.strip()
    if rest.startswith("["):
        close = rest.find("]")
        if close >= 0:
            slug_field = rest[: close + 1].strip()
            after = rest[close + 1:].lstrip()
            m = re.match(r"^—\s*(.*)$", after)
            if m:
                return slug_field, m.group(1).strip()
            # Bracket parsed but no '— description' after — degrade gracefully.
            return slug_field, after.strip()
    parts = re.split(r"\s+—\s+", rest, maxsplit=1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return rest, ""


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
        slug_field, description = _split_slug_from_description(header_m.group(2))

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


_BRACKET_OUTER_RE = re.compile(r"^\[(.*)\]$", re.DOTALL)
_BRACKET_SUFFIX_RE = re.compile(
    r"\s+—\s+(?:slug\s+TBD|see\s+note)\b.*$",
    re.IGNORECASE,
)


def _strip_bracket_suffix(inner: str) -> str:
    """Inside a bracketed slug field, strip a trailing ``— slug TBD`` /
    ``— see note`` annotation, even if extra prose follows the sentinel.

    Example: ``private-assets — slug TBD`` → ``private-assets``.
    Example: ``philippe-soulier — slug TBD (Bora-Bora)`` → ``philippe-soulier``.
    """
    return _BRACKET_SUFFIX_RE.sub("", inner).strip()


def normalize_slug_field(
    raw: str,
    triaga_ref: str,
    *,
    combined_slugs_by_ref: Optional[dict[str, str]] = None,
    canonical_slugs: Optional[set[str]] = None,
) -> Union[str, list[str]]:
    """Translate the raw ``slug-text`` field into a string OR a list of slugs.

    Pipeline (Bug-1/Bug-2 hardened):

    1. **Combined-slug override first.** If ``triaga_ref`` is in
       ``combined_slugs_by_ref``, return the compound slug verbatim.
    2. **Bracket strip BEFORE any separator split.** ``[private-assets —
       slug TBD]`` → ``private-assets``. The bracket suffix regex consumes
       ``— slug TBD`` / ``— see note`` even if prose follows the sentinel.
    3. **Split on ``+`` always.** RA-23 declares ``+`` the canonical
       multi-slug separator.
    4. **Split on ``/`` only when shape + canonical-registry agree.** Each
       slash-token must match ``_CANONICAL_SLUG_SHAPE`` AND be present in
       ``canonical_slugs`` (when supplied). Otherwise ``/`` is prose and
       the part stays a single literal token. This keeps Q30 ``tax / lana``
       and Q31 ``tax / cbp`` (where ``tax`` is a category prefix, not a
       canonical slug) as single slugs that the canonical-slug-validation
       layer can flag for ``pending_slug_review``.
    5. **Lowercase + trim.** Final form is lowercased; outer whitespace
       trimmed; internal whitespace preserved verbatim (so the surfaced
       pending-review value matches what the export wrote).
    """
    overrides = combined_slugs_by_ref if combined_slugs_by_ref is not None else COMBINED_SLUGS_BY_REF
    if triaga_ref in overrides:
        return overrides[triaga_ref]

    cleaned = raw.strip()

    # Step 1: bracket strip BEFORE any separator split (Bug 1).
    bracket_m = _BRACKET_OUTER_RE.match(cleaned)
    if bracket_m:
        cleaned = _strip_bracket_suffix(bracket_m.group(1).strip())

    if not cleaned:
        raise ValueError(f"{triaga_ref}: empty slug field after normalization")

    # Step 2: '+'-split always.
    plus_parts = [p.strip() for p in re.split(r"\s*\+\s*", cleaned) if p.strip()]

    # Step 3: per plus-part, maybe further '/'-split (only if shape + registry agree).
    out_parts: list[str] = []
    for part in plus_parts:
        slash_tokens = [t.strip() for t in re.split(r"\s*/\s*", part) if t.strip()]
        if (
            len(slash_tokens) > 1
            and all(_CANONICAL_SLUG_SHAPE.match(t.lower()) for t in slash_tokens)
            and canonical_slugs is not None
            and all(t.lower() in canonical_slugs for t in slash_tokens)
        ):
            out_parts.extend(t.lower() for t in slash_tokens)
        else:
            # Treat '/' as prose — keep the part as a single literal slug
            # (lowercased; internal whitespace preserved).
            out_parts.append(part.lower())

    if not out_parts:
        raise ValueError(f"{triaga_ref}: empty slug field after normalization")
    if len(out_parts) == 1:
        return out_parts[0]
    return out_parts


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
    canonical_slugs: Optional[set[str]] = None,
    canonical_slug_loose: Optional[bool] = None,
) -> dict:
    """Build the final ``_priorities.yml`` dict from a ``parse_export`` result.

    When ``canonical_slugs`` is supplied, each emitted slug is validated.
    Non-canonical slugs are emitted in the matter row regardless (the
    converter never blocks on a Director-wishlist slug) and recorded in
    ``pending_slug_review[]`` unless ``canonical_slug_loose=True``.
    """
    items: list[TriagaItem] = list(parsed["items"])
    folds = duplicate_folds if duplicate_folds is not None else DUPLICATE_FOLDS
    loose = CANONICAL_SLUG_LOOSE if canonical_slug_loose is None else bool(canonical_slug_loose)

    # Drop folded duplicates first (Q19 → Q33).
    folded_refs = set(folds.keys())
    items = [it for it in items if it.triaga_ref not in folded_refs]

    matters: list[dict] = []
    dismissed: list[dict] = []
    completed: list[dict] = []
    partial_count = 0
    # Per-Q-ID raw slug-field text (for pending_slug_review surface).
    raw_by_ref: dict[str, str] = {}

    ratified_date = ratified_at.split("T", 1)[0] if "T" in ratified_at else ratified_at[:10]

    for it in items:
        slug_value = normalize_slug_field(
            it.slug_field,
            it.triaga_ref,
            combined_slugs_by_ref=combined_slugs_by_ref,
            canonical_slugs=canonical_slugs,
        )
        raw_by_ref[it.triaga_ref] = it.slug_field
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

    pending_slug_review = _validate_canonical_slugs(
        matters=matters,
        dismissed=dismissed,
        completed=completed,
        canonical_slugs=canonical_slugs,
        raw_by_ref=raw_by_ref,
        loose=loose,
    )

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
        "pending_slug_review": pending_slug_review,
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
            "pending_slug_review_count": len(pending_slug_review),
        },
    }
    return out


def _validate_canonical_slugs(
    *,
    matters: list[dict],
    dismissed: list[dict],
    completed: list[dict],
    canonical_slugs: Optional[set[str]],
    raw_by_ref: dict[str, str],
    loose: bool,
) -> list[dict]:
    """Walk every emitted slug, log warnings on non-canonical ones, and (unless
    ``loose``) record them in a ``pending_slug_review[]`` list for surfacing
    to regen + Director.

    Returns the list verbatim (caller embeds it in the output dict).
    """
    if canonical_slugs is None:
        return []
    canonical_set = set(canonical_slugs)
    pending: list[dict] = []
    seen: set[tuple[str, str, str]] = set()  # (triaga_ref, slug, section) dedup
    sections: tuple[tuple[str, list[dict]], ...] = (
        ("matters", matters),
        ("dismissed", dismissed),
        ("completed", completed),
    )
    for section_name, entries in sections:
        for entry in entries:
            triaga_ref = entry.get("triaga_ref", "")
            if "slugs" in entry:
                emitted: list[str] = list(entry["slugs"])
            elif "slug" in entry:
                emitted = [entry["slug"]]
            else:
                continue
            for slug in emitted:
                if slug in canonical_set:
                    continue
                logger.warning(
                    "non-canonical slug emitted: triaga_ref=%s slug=%r section=%s",
                    triaga_ref, slug, section_name,
                )
                if loose:
                    continue
                key = (triaga_ref, slug, section_name)
                if key in seen:
                    continue
                seen.add(key)
                pending.append({
                    "triaga_ref": triaga_ref,
                    "slug": slug,
                    "section": section_name,
                    "raw_slug_field": raw_by_ref.get(triaga_ref, ""),
                })
    return pending


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
    canonical_slugs: Optional[set[str]] = None,
    canonical_slug_loose: Optional[bool] = None,
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
        canonical_slugs=canonical_slugs,
        canonical_slug_loose=canonical_slug_loose,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_yaml(data), encoding="utf-8")
    return data


def _load_canonical_slugs_from_registry(registry_path: Path) -> set[str]:
    """Load canonical slugs from a ``slugs.yml`` file via ``kbl.slug_registry``.

    Imported lazily so unit tests don't pay the dependency cost when they
    pass a literal set instead.
    """
    # Make the repo root importable when invoked as ``python3 scripts/...``
    # from a working dir that doesn't already have it on sys.path.
    repo_root = Path(__file__).resolve().parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from kbl.slug_registry import _parse_yaml as parse_registry_yaml
    reg = parse_registry_yaml(Path(registry_path))
    return set(reg.entries.keys())


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
    parser.add_argument(
        "--registry",
        default=None,
        help="Path to slugs.yml; when set, non-canonical slugs land in pending_slug_review[]",
    )
    parser.add_argument(
        "--canonical-slug-loose",
        action="store_true",
        help="Warn but skip pending_slug_review[] population (legacy emit-only mode)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    canonical_slugs: Optional[set[str]] = None
    if args.registry:
        canonical_slugs = _load_canonical_slugs_from_registry(Path(args.registry))

    data = triaga_export_to_priorities(
        args.export,
        args.out,
        ratified_at=args.ratified_at,
        source_inbox=args.source_inbox,
        archive_copy=args.archive_copy,
        canonical_slugs=canonical_slugs,
        canonical_slug_loose=args.canonical_slug_loose,
    )
    prov = data["provenance"]
    print(
        f"OK: wrote {args.out} "
        f"({prov['ratified_count']} items: "
        f"{prov['active_count']} Active · "
        f"{prov['completed_count']} Completed · "
        f"{prov['dismissed_count']} Dismissed · "
        f"{prov['partial_count']} Partial · "
        f"{prov['pending_slug_review_count']} pending review)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
