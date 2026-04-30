"""Tests for ``scripts/triaga_to_priorities.py`` (Wave-1 Track-5c).

Spec: ``baker-vault/_ops/processes/cortex-priorities-schema.md``.

Coverage
--------
* Round-trip: small fixture → _priorities.yml → schema-valid dict
* Empty section handling (zero dismissed)
* Multi-slug list emission (Q3 lilienmatt+annaberg+aukera)
* Combined-slug override (Q33 nvidia-corinthia stays a single compound slug)
* Q19 → Q33 dup-folding (drop Q19 row)
* Q37 Bora-Bora bracketed-TBD slug separation (extracts ``philippe-soulier``)
* Malformed export rows raise ValueError
* Chain-test: converter output feeds ``regen_hot_md`` cleanly with
  ``write=False`` (validation passes; non-empty hot.md generated)
"""
from __future__ import annotations

import shutil
from pathlib import Path
from textwrap import dedent

import pytest
import yaml

from scripts.triaga_to_priorities import (
    COMBINED_SLUGS_BY_REF,
    DUPLICATE_FOLDS,
    normalize_slug_field,
    parse_export,
    render_yaml,
    to_priorities_dict,
    triaga_export_to_priorities,
)
from scripts.regen_hot_md import _build_matters, _parse_priorities, regen_hot_md

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = REPO_ROOT / "scripts" / "test_data"
SAMPLE_EXPORT = FIXTURES / "sample_triaga_export.md"
SAMPLE_SLUGS = FIXTURES / "sample_slugs.yml"
HARDEN_REPRO_EXPORT = FIXTURES / "triaga_export_q17_q18_q30_q31_q37.md"


# ---------------------------------------------------------------------------
# Round-trip on small fixture
# ---------------------------------------------------------------------------


def test_sample_fixture_roundtrip(tmp_path):
    out = tmp_path / "_priorities.yml"
    data = triaga_export_to_priorities(SAMPLE_EXPORT, out)

    assert out.exists()
    reloaded = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert reloaded["schema_version"] == 1
    assert reloaded["ratified_at"] == "2026-04-29T18:45:00+02:00"
    assert reloaded["ratified_by"] == "director"

    # 3 Active matters in `matters[]`
    assert len(reloaded["matters"]) == 3
    triaga_refs = [m["triaga_ref"] for m in reloaded["matters"]]
    assert triaga_refs == ["Q1", "Q2", "Q3"]

    # Multi-slug Q3 rendered as `slugs:` not `slug:`
    q3 = reloaded["matters"][2]
    assert q3["slugs"] == ["lilienmatt", "annaberg", "aukera"]
    assert "slug" not in q3
    assert q3["when"] == "asap"
    assert q3["importance"] == "high"
    assert q3["category"] == "active-deal"

    # Q1 single-slug stays as scalar `slug:`
    q1 = reloaded["matters"][0]
    assert q1["slug"] == "hagenauer-rg7"
    assert "slugs" not in q1
    assert q1["category"] == "legal-risk"

    # Completed + Dismissed
    assert len(reloaded["completed"]) == 1
    assert reloaded["completed"][0]["triaga_ref"] == "Q4"
    assert len(reloaded["dismissed"]) == 1
    assert reloaded["dismissed"][0]["triaga_ref"] == "Q5"
    # Dismiss reason captured from the `note:` line
    assert "Director dismissed" in reloaded["dismissed"][0]["reason"]

    # Static defaults preserved
    assert "Marketing newsletters." in reloaded["null_routine"]
    assert any("OBSERVER" in s for s in reloaded["not_null_elevate"])

    # Provenance counts match
    prov = reloaded["provenance"]
    assert prov["ratified_count"] == 5
    assert prov["active_count"] == 3
    assert prov["completed_count"] == 1
    assert prov["dismissed_count"] == 1

    # The returned dict equals the on-disk YAML (round-trip soundness)
    assert reloaded == data


# ---------------------------------------------------------------------------
# Empty-section handling
# ---------------------------------------------------------------------------


def test_zero_dismissed_emits_empty_list(tmp_path):
    export = tmp_path / "tiny.md"
    export.write_text(
        dedent(
            """\
            **Date:** 2026-04-29

            **Q1 — ao — One active item only**
            → STATUS: Active · WHEN: Urgent · IMPORTANCE: Critical · CATEGORY: Active Deal
            """
        ),
        encoding="utf-8",
    )
    out = tmp_path / "_priorities.yml"
    data = triaga_export_to_priorities(export, out)
    assert data["dismissed"] == []
    assert data["completed"] == []
    assert data["provenance"]["dismissed_count"] == 0
    assert data["provenance"]["completed_count"] == 0
    # YAML must still emit the keys (regen reads .get("dismissed", []) but the
    # explicit empty list keeps the file shape consistent for diffs).
    reloaded = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert reloaded["dismissed"] == []
    assert reloaded["completed"] == []


# ---------------------------------------------------------------------------
# Multi-slug + combined-slug overrides
# ---------------------------------------------------------------------------


def test_multi_slug_plus_separator():
    assert normalize_slug_field("lilienmatt+annaberg+aukera", "Q7") == [
        "lilienmatt",
        "annaberg",
        "aukera",
    ]


def test_multi_slug_plus_with_spaces():
    assert normalize_slug_field("mo-prague + citic", "Q36") == ["mo-prague", "citic"]


def test_slash_no_split_without_registry():
    """Without a canonical-slug set, '/' never splits — '/' in Triaga prose is
    ambiguous (often a category prefix like ``tax /``). Q38's 4-counterparty
    field stays a single literal slug; the canonical-slug check then routes
    it to ``pending_slug_review`` for Director attention.
    """
    result = normalize_slug_field(
        "wertheimer / balducci / minor-hotels / philippe-soulier", "Q38"
    )
    assert isinstance(result, str)
    assert result == "wertheimer / balducci / minor-hotels / philippe-soulier"


def test_slash_splits_only_when_registry_confirms_all_tokens():
    """When a canonical-slug set is supplied AND every slash-token is in it,
    '/' is treated as a multi-slug separator. This is the narrow case where
    a Triaga export legitimately uses '/' for a counterparty list.
    """
    canon = {"wertheimer", "balducci", "minor-hotels", "philippe-soulier"}
    result = normalize_slug_field(
        "wertheimer / balducci / minor-hotels / philippe-soulier",
        "Q38",
        canonical_slugs=canon,
    )
    assert result == ["wertheimer", "balducci", "minor-hotels", "philippe-soulier"]


def test_slash_does_not_split_when_one_token_missing_from_registry():
    """If even one slash-token is absent from the registry, the field stays a
    single literal slug. Mixed canonical/non-canonical lists are too risky to
    auto-split without Director confirmation.
    """
    canon = {"wertheimer", "balducci"}  # minor-hotels + philippe-soulier missing
    result = normalize_slug_field(
        "wertheimer / balducci / minor-hotels / philippe-soulier",
        "Q38",
        canonical_slugs=canon,
    )
    assert isinstance(result, str)


def test_q33_nvidia_corinthia_combined_slug():
    """Q33 'nvidia + corinthia' is a SINGLE compound slug per Director intent.

    The override map collapses the field even though the literal text contains
    a `+` separator. Without this override the converter would emit a 2-slug
    list, which contradicts the ratification.
    """
    assert "Q33" in COMBINED_SLUGS_BY_REF
    result = normalize_slug_field("nvidia + corinthia", "Q33")
    assert result == "nvidia-corinthia"
    assert isinstance(result, str)


def test_combined_slug_override_can_be_disabled():
    # Pass an empty override map to revert to default split behavior.
    result = normalize_slug_field(
        "nvidia + corinthia", "Q33", combined_slugs_by_ref={}
    )
    assert result == ["nvidia", "corinthia"]


# ---------------------------------------------------------------------------
# Q19 → Q33 dup-folding
# ---------------------------------------------------------------------------


def test_q19_folds_into_q33(tmp_path):
    export = tmp_path / "with_dup.md"
    export.write_text(
        dedent(
            """\
            **Date:** 2026-04-29

            **Q19 — [nvidia+corinthia origination — see note] — AI Originations**
            → STATUS: Active · WHEN: Urgent · IMPORTANCE: High · CATEGORY: Origination
            note: Probably duplicate of Q33.

            **Q33 — nvidia + corinthia — Proposal to NVIDIA + Corinthia**
            → STATUS: Active · WHEN: ASAP · IMPORTANCE: High · CATEGORY: Origination
            """
        ),
        encoding="utf-8",
    )
    out = tmp_path / "_priorities.yml"
    data = triaga_export_to_priorities(export, out)

    refs = [m["triaga_ref"] for m in data["matters"]]
    assert "Q19" not in refs, "Q19 must fold into Q33 (Director-ratified duplicate)"
    assert "Q33" in refs
    q33 = next(m for m in data["matters"] if m["triaga_ref"] == "Q33")
    assert q33["slug"] == "nvidia-corinthia"
    assert "slugs" not in q33

    # Default fold map exposes the fold, callers can override.
    assert DUPLICATE_FOLDS == {"Q19": "Q33"}


def test_dup_fold_can_be_disabled(tmp_path):
    export = tmp_path / "with_dup.md"
    export.write_text(
        dedent(
            """\
            **Date:** 2026-04-29

            **Q19 — claimsmax — AI Originations**
            → STATUS: Active · WHEN: Urgent · IMPORTANCE: High · CATEGORY: Origination

            **Q33 — nvidia + corinthia — Proposal**
            → STATUS: Active · WHEN: ASAP · IMPORTANCE: High · CATEGORY: Origination
            """
        ),
        encoding="utf-8",
    )
    out = tmp_path / "_priorities.yml"
    data = triaga_export_to_priorities(export, out, duplicate_folds={})
    refs = [m["triaga_ref"] for m in data["matters"]]
    assert "Q19" in refs and "Q33" in refs


# ---------------------------------------------------------------------------
# Q37 Bora-Bora — bracketed [philippe-soulier — slug TBD] separation
# ---------------------------------------------------------------------------


def test_q37_bora_bora_bracket_strips_to_philippe_soulier():
    """Q37 raw slug field is `[philippe-soulier — slug TBD]`. The converter
    must strip the brackets + ' — slug TBD' suffix and emit `philippe-soulier`
    as the slug. Bora-Bora context lives in the description, not the slug —
    Director's open follow-up (#4) keeps the slug crisp until ratification.
    """
    result = normalize_slug_field("[philippe-soulier — slug TBD]", "Q37")
    assert result == "philippe-soulier"


def test_bracketed_see_note_stripped():
    # Q19's literal field uses ' — see note' (bracketed claimsmax variant).
    result = normalize_slug_field(
        "[private-assets — slug TBD]", "Q17"
    )
    assert result == "private-assets"


# ---------------------------------------------------------------------------
# Malformed input → ValueError
# ---------------------------------------------------------------------------


def test_malformed_missing_meta_line_raises(tmp_path):
    export = tmp_path / "bad.md"
    export.write_text(
        "**Date:** 2026-04-29\n\n**Q1 — ao — orphan header**\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="no following meta line"):
        parse_export(export.read_text(encoding="utf-8"))


def test_malformed_unknown_status_raises(tmp_path):
    export = tmp_path / "bad.md"
    export.write_text(
        dedent(
            """\
            **Date:** 2026-04-29

            **Q1 — ao — bad status**
            → STATUS: Frobnicate · WHEN: Urgent · IMPORTANCE: Critical · CATEGORY: Active Deal
            """
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="status must be one of"):
        parse_export(export.read_text(encoding="utf-8"))


def test_malformed_active_missing_when_raises(tmp_path):
    export = tmp_path / "bad.md"
    export.write_text(
        dedent(
            """\
            **Date:** 2026-04-29

            **Q1 — ao — missing fields**
            → STATUS: Active · IMPORTANCE: Critical · CATEGORY: Active Deal
            """
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="missing WHEN"):
        parse_export(export.read_text(encoding="utf-8"))


def test_unknown_when_raises(tmp_path):
    export = tmp_path / "bad.md"
    export.write_text(
        dedent(
            """\
            **Date:** 2026-04-29

            **Q1 — ao — bad when**
            → STATUS: Active · WHEN: Eventually · IMPORTANCE: Critical · CATEGORY: Active Deal
            """
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="when="):
        parse_export(export.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Chain test — converter output is regen-script-compatible
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Bug 1 — em-dash split bleeds bracket suffix into slug (Q17 / Q18 / Q37)
# ---------------------------------------------------------------------------


def test_q17_uk_homes_bracket_em_dash():
    """Q17 raw header line `**Q17 — [private-assets — slug TBD] — Barclays UK
    mortgage renewal form issued**` must produce slug=``private-assets`` and
    description=``Barclays UK mortgage renewal form issued``.

    Pre-fix bug: non-greedy ` — ` split bisected at the first em-dash,
    leaving slug=``[private-assets`` and description=``slug TBD] — Barclays
    UK mortgage renewal form issued``.
    """
    export_text = (
        "**Date:** 2026-04-29\n\n"
        "**Q17 — [private-assets — slug TBD] — Barclays UK mortgage renewal form issued**\n"
        "→ STATUS: Active · WHEN: 4 weeks · IMPORTANCE: High · CATEGORY: Financial\n"
    )
    parsed = parse_export(export_text)
    assert len(parsed["items"]) == 1
    item = parsed["items"][0]
    assert item.triaga_ref == "Q17"
    assert item.slug_field == "[private-assets — slug TBD]"
    assert item.description == "Barclays UK mortgage renewal form issued"
    assert normalize_slug_field(item.slug_field, "Q17") == "private-assets"


def test_q18_uk_homes_bracket_em_dash():
    """Q18 has a SECOND em-dash in the description (`Strutt Parker vs Monaco`
    follows another ` — `). The bracket-anchored split must still produce
    a single slug and a single (em-dash-bearing) description string.
    """
    export_text = (
        "**Date:** 2026-04-29\n\n"
        "**Q18 — [private-assets — slug TBD] — Barclays UK valuer discrepancy — Strutt Parker vs Monaco**\n"
        "→ STATUS: Active · WHEN: Urgent · IMPORTANCE: High · CATEGORY: Financial\n"
    )
    parsed = parse_export(export_text)
    item = parsed["items"][0]
    assert item.triaga_ref == "Q18"
    assert item.slug_field == "[private-assets — slug TBD]"
    # Description preserves its internal em-dash verbatim.
    assert item.description == "Barclays UK valuer discrepancy — Strutt Parker vs Monaco"
    assert normalize_slug_field(item.slug_field, "Q18") == "private-assets"


def test_q37_bora_bora_bracket():
    """Q37 end-to-end via parse_export: bracketed `[philippe-soulier — slug
    TBD]` must extract slug=``philippe-soulier`` and description=``Bora-Bora
    pipeline``. (The unit-level `normalize_slug_field` test for the same
    Q-ID continues to live alongside; this one exercises the header parser.)
    """
    export_text = (
        "**Date:** 2026-04-29\n\n"
        "**Q37 — [philippe-soulier — slug TBD] — Bora-Bora pipeline**\n"
        "→ STATUS: Active · WHEN: Not urgent · IMPORTANCE: Low · CATEGORY: Origination\n"
    )
    parsed = parse_export(export_text)
    item = parsed["items"][0]
    assert item.triaga_ref == "Q37"
    assert item.slug_field == "[philippe-soulier — slug TBD]"
    assert item.description == "Bora-Bora pipeline"
    assert normalize_slug_field(item.slug_field, "Q37") == "philippe-soulier"


# ---------------------------------------------------------------------------
# Bug 2 — '/' always splits slug field (Q30 / Q31)
# ---------------------------------------------------------------------------


def test_q30_slash_no_split(tmp_path):
    """Q30 raw header line `**Q30 — tax / lana — Expected €650K tax return on
    Lana issue**` must produce a single slug, NOT a 2-element list. ``tax``
    is a category prefix in Triaga prose, not a canonical slug — splitting
    on '/' here was the Wave-1 bug.
    """
    export = tmp_path / "q30.md"
    export.write_text(
        "**Date:** 2026-04-29\n\n"
        "**Q30 — tax / lana — Expected €650K tax return on Lana issue**\n"
        "→ STATUS: Active · WHEN: ASAP · IMPORTANCE: High · CATEGORY: Active Deal\n",
        encoding="utf-8",
    )
    out = tmp_path / "_priorities.yml"
    data = triaga_export_to_priorities(export, out)
    assert len(data["matters"]) == 1
    q30 = data["matters"][0]
    assert q30["triaga_ref"] == "Q30"
    assert "slug" in q30, "Q30 must emit `slug:` (single), not `slugs:` (list)"
    assert "slugs" not in q30
    # Literal text preserved (lowercased / outer-trimmed); will route to
    # pending_slug_review when a registry is supplied.
    assert q30["slug"] == "tax / lana"


def test_q31_slash_no_split(tmp_path):
    """Q31 (Dismiss) `**Q31 — tax / cbp — US CBP tariff refund portal**` must
    produce a single slug in the dismissed[] entry, not slugs: [tax, cbp].
    """
    export = tmp_path / "q31.md"
    export.write_text(
        "**Date:** 2026-04-29\n\n"
        "**Q31 — tax / cbp — US CBP tariff refund portal**\n"
        "→ STATUS: Dismiss\n",
        encoding="utf-8",
    )
    out = tmp_path / "_priorities.yml"
    data = triaga_export_to_priorities(export, out)
    assert len(data["dismissed"]) == 1
    q31 = data["dismissed"][0]
    assert q31["triaga_ref"] == "Q31"
    assert "slug" in q31 and "slugs" not in q31
    assert q31["slug"] == "tax / cbp"


# ---------------------------------------------------------------------------
# Bug 3 — non-canonical slugs route to pending_slug_review
# ---------------------------------------------------------------------------


def test_non_canonical_slug_routes_to_pending_review(tmp_path):
    """Non-canonical slugs (not in supplied ``canonical_slugs``) are emitted
    as-is in the matter row AND surface in ``pending_slug_review[]`` for
    Director attention. Default mode is strict: the section is populated.

    Loose mode (CANONICAL_SLUG_LOOSE / kwarg) only logs warnings.
    """
    export = tmp_path / "noncanon.md"
    export.write_text(
        "**Date:** 2026-04-29\n\n"
        "**Q1 — ao — Canonical AO matter**\n"
        "→ STATUS: Active · WHEN: Urgent · IMPORTANCE: Critical · CATEGORY: Active Deal\n\n"
        "**Q30 — tax / lana — Expected €650K tax return on Lana issue**\n"
        "→ STATUS: Active · WHEN: ASAP · IMPORTANCE: High · CATEGORY: Active Deal\n\n"
        "**Q41 — orbit / amir — Amir Frankfurt May 8-9 touchpoint**\n"
        "→ STATUS: Active · WHEN: 4 weeks · IMPORTANCE: Medium · CATEGORY: Origination\n",
        encoding="utf-8",
    )
    out = tmp_path / "_priorities.yml"
    canonical = {"ao", "hagenauer-rg7", "lilienmatt"}  # tax/lana, orbit/amir absent
    data = triaga_export_to_priorities(export, out, canonical_slugs=canonical)

    assert len(data["matters"]) == 3
    pending = data["pending_slug_review"]
    refs_in_pending = {p["triaga_ref"] for p in pending}
    assert refs_in_pending == {"Q30", "Q41"}, f"got {refs_in_pending}"
    # Q1 (ao) is canonical — must NOT appear in pending review.
    assert "Q1" not in refs_in_pending

    # Each pending entry preserves the raw slug field for Director context.
    q30_pending = next(p for p in pending if p["triaga_ref"] == "Q30")
    assert q30_pending["slug"] == "tax / lana"
    assert q30_pending["raw_slug_field"] == "tax / lana"
    assert q30_pending["section"] == "matters"

    # Provenance count matches.
    assert data["provenance"]["pending_slug_review_count"] == 2

    # Loose mode: warning-only, pending_slug_review empty.
    out2 = tmp_path / "_priorities_loose.yml"
    data_loose = triaga_export_to_priorities(
        export, out2, canonical_slugs=canonical, canonical_slug_loose=True
    )
    assert data_loose["pending_slug_review"] == []
    assert data_loose["provenance"]["pending_slug_review_count"] == 0
    # Slugs are still emitted in the matter rows in loose mode.
    assert any(m["triaga_ref"] == "Q30" and m["slug"] == "tax / lana" for m in data_loose["matters"])


# ---------------------------------------------------------------------------
# End-to-end on the trimmed reproducer fixture (all 3 bugs at once)
# ---------------------------------------------------------------------------


def test_harden_repro_fixture_clean_extraction(tmp_path):
    """Run converter on the dedicated reproducer fixture and assert clean
    output for all 5 affected Q-IDs simultaneously.
    """
    out = tmp_path / "_priorities.yml"
    canonical = {"private-assets", "philippe-soulier", "ao"}  # match neither tax nor lana
    data = triaga_export_to_priorities(
        HARDEN_REPRO_EXPORT, out, canonical_slugs=canonical
    )

    by_ref = {m["triaga_ref"]: m for m in data["matters"]}
    # Q17, Q18 — bracket strip clean
    assert by_ref["Q17"]["slug"] == "private-assets"
    assert by_ref["Q17"]["description"] == "Barclays UK mortgage renewal form issued"
    assert by_ref["Q18"]["slug"] == "private-assets"
    assert by_ref["Q18"]["description"] == "Barclays UK valuer discrepancy — Strutt Parker vs Monaco"
    # Q37 — bracket strip clean
    assert by_ref["Q37"]["slug"] == "philippe-soulier"
    assert by_ref["Q37"]["description"] == "Bora-Bora pipeline"
    # Q30 — single slug, NOT split
    assert by_ref["Q30"]["slug"] == "tax / lana"
    assert "slugs" not in by_ref["Q30"]

    # Q31 — single slug in dismissed[]
    q31 = next(d for d in data["dismissed"] if d["triaga_ref"] == "Q31")
    assert q31["slug"] == "tax / cbp"

    # pending_slug_review captures the non-canonical slugs (tax / lana,
    # tax / cbp). private-assets + philippe-soulier are canonical here so
    # they should NOT appear in pending.
    pending_refs = {p["triaga_ref"] for p in data["pending_slug_review"]}
    assert "Q30" in pending_refs
    assert "Q31" in pending_refs
    assert "Q17" not in pending_refs
    assert "Q37" not in pending_refs


# ---------------------------------------------------------------------------
# Chain test — converter output is regen-script-compatible
# ---------------------------------------------------------------------------


def test_chain_converter_output_feeds_regen(tmp_path):
    """End-to-end soundness: sample export → _priorities.yml → regen reads
    it cleanly + emits non-empty hot.md.

    Build a temp vault with the same sample slugs.yml the regen tests use,
    write the converter output as wiki/_priorities.yml, then call regen
    with ``write=False`` and assert validation passes.
    """
    vault = tmp_path / "vault"
    (vault / "wiki").mkdir(parents=True)
    shutil.copy(SAMPLE_SLUGS, vault / "slugs.yml")

    priorities_path = vault / "wiki" / "_priorities.yml"
    triaga_export_to_priorities(SAMPLE_EXPORT, priorities_path)

    # Schema-level smoke first (matches what regen does internally).
    raw = priorities_path.read_text(encoding="utf-8")
    parsed = _parse_priorities(raw)
    matters = _build_matters(parsed["matters"])
    assert len(matters) == 3
    assert matters[2].slugs == ["lilienmatt", "annaberg", "aukera"]

    # Full regen pass (dry run; no writes).
    result = regen_hot_md(
        priorities_path,
        vault,
        write=False,
        generated_at="2026-04-29T20:00:00+00:00",
        today="2026-04-29",
    )
    assert result.validation_passed is True
    assert result.validation_error is None
    assert "Hot — Director-curated priorities cache" in result.hot_md
    # Confirm Q1 + Q2 (Urgent + Critical) land in the right hot.md section.
    assert "**hagenauer-rg7**" in result.hot_md
    assert "**ao**" in result.hot_md
    # Multi-tag entry rendered with " + " join.
    assert "**lilienmatt + annaberg + aukera**" in result.hot_md
