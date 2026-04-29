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


def test_multi_slug_slash_separator():
    assert normalize_slug_field(
        "wertheimer / balducci / minor-hotels / philippe-soulier", "Q38"
    ) == ["wertheimer", "balducci", "minor-hotels", "philippe-soulier"]


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
