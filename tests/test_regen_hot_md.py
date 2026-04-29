"""Tests for ``scripts/regen_hot_md.py`` (Wave-1 Track-5b).

Spec: ``baker-vault/_ops/processes/cortex-priorities-schema.md``.

Coverage
--------
* Parse + sort: importance order, within-section alpha
* hot.md byte-identical idempotence (same input → same output)
* Multi-tag display ("slug1 + slug2")
* slugs.yml: ``add`` appends + version bump + updated_at refresh
* slugs.yml: ``dismissed[].slug_action: retire`` flips status + prepends RETIRED note
* Proposed-gold.md: append candidate, flip status:empty → status:candidates,
  idempotent re-run skips already-present id
* Validation: invalid slugs.yml (duplicate slug) aborts + reverts + writes
  regen_failed.log
* Drift detection: existing hot.md ≠ regen output → drift_detected=True
* Golden fixture comparison (3-matter _priorities.yml round-trip)
"""
from __future__ import annotations

import shutil
from pathlib import Path
from textwrap import dedent

import pytest

from scripts.regen_hot_md import (  # noqa: E402
    _build_matters,
    _parse_priorities,
    apply_slug_changes,
    regen_hot_md,
    render_hot_md,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = REPO_ROOT / "scripts" / "test_data"
SAMPLE_PRIORITIES = FIXTURES / "sample_priorities.yml"
SAMPLE_SLUGS = FIXTURES / "sample_slugs.yml"
EXPECTED_HOT_MD = FIXTURES / "expected_hot.md"

PINNED_GENERATED_AT = "2026-04-29T20:00:00+00:00"
PINNED_TODAY = "2026-04-29"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_vault(tmp_path: Path) -> Path:
    """Build a temp vault dir from the fixture sample slugs + priorities."""
    vault = tmp_path / "vault"
    (vault / "wiki" / "matters" / "oskolkov").mkdir(parents=True)
    shutil.copy(SAMPLE_SLUGS, vault / "slugs.yml")
    shutil.copy(SAMPLE_PRIORITIES, vault / "wiki" / "_priorities.yml")
    return vault


# ---------------------------------------------------------------------------
# Parser + sort
# ---------------------------------------------------------------------------


def test_parse_rejects_wrong_schema_version():
    bad = "schema_version: 2\nmatters: []\n"
    with pytest.raises(ValueError, match="schema_version"):
        _parse_priorities(bad)


def test_parse_rejects_both_slug_and_slugs():
    bad = dedent(
        """\
        schema_version: 1
        matters:
          - slug: foo
            slugs: [bar, baz]
            when: urgent
            importance: high
            category: x
            triaga_ref: Q1
            description: x
        """
    )
    data = _parse_priorities(bad)
    with pytest.raises(ValueError, match="slug.*OR.*slugs"):
        _build_matters(data["matters"])


def test_matter_sort_key_critical_before_high():
    raw = [
        {"slug": "zzz", "when": "urgent", "importance": "high",
         "category": "c", "triaga_ref": "Q9", "description": "z"},
        {"slug": "aaa", "when": "urgent", "importance": "critical",
         "category": "c", "triaga_ref": "Q1", "description": "a"},
    ]
    matters = _build_matters(raw)
    matters.sort(key=lambda m: m.sort_key)
    assert [m.primary for m in matters] == ["aaa", "zzz"]


def test_matter_sort_alpha_within_same_importance():
    raw = [
        {"slug": "zebra", "when": "urgent", "importance": "critical",
         "category": "c", "triaga_ref": "Q1", "description": "z"},
        {"slug": "alpha", "when": "urgent", "importance": "critical",
         "category": "c", "triaga_ref": "Q2", "description": "a"},
        {"slug": "mango", "when": "urgent", "importance": "critical",
         "category": "c", "triaga_ref": "Q3", "description": "m"},
    ]
    matters = _build_matters(raw)
    matters.sort(key=lambda m: m.sort_key)
    assert [m.primary for m in matters] == ["alpha", "mango", "zebra"]


# ---------------------------------------------------------------------------
# hot.md rendering
# ---------------------------------------------------------------------------


def test_render_includes_required_section_headers():
    text = SAMPLE_PRIORITIES.read_text()
    rendered = render_hot_md(_parse_priorities(text), PINNED_GENERATED_AT)
    assert "## Actively pressing (elevate — ASAP / Urgent)" in rendered
    assert "### ASAP (0 items)" in rendered
    assert "### Urgent + Critical (2 items)" in rendered
    assert "### Urgent + High (0 items)" in rendered
    assert "## Watch list (elevate on any mention — 4-week horizon)" in rendered
    assert "## Not urgent (0 items — log + monitor only, do NOT elevate)" in rendered
    assert "## Actively frozen / dismissed (suppress signals on these matters)" in rendered
    assert "## Null / routine (always suppress)" in rendered
    assert "**NOT null — always elevate:**" in rendered


def test_render_multi_tag_display():
    text = SAMPLE_PRIORITIES.read_text()
    rendered = render_hot_md(_parse_priorities(text), PINNED_GENERATED_AT)
    assert "**aukera + mo-vie-am**" in rendered


def test_render_critical_capitalization():
    text = SAMPLE_PRIORITIES.read_text()
    rendered = render_hot_md(_parse_priorities(text), PINNED_GENERATED_AT)
    # Urgent+Critical bullets always use literal "Critical" per spec.
    assert "(Q2, Critical, legal-risk)" in rendered
    assert "(Q20, Critical, active-deal)" in rendered


def test_render_idempotent_byte_identical():
    text = SAMPLE_PRIORITIES.read_text()
    a = render_hot_md(_parse_priorities(text), PINNED_GENERATED_AT)
    b = render_hot_md(_parse_priorities(text), PINNED_GENERATED_AT)
    assert a == b
    assert a.encode("utf-8") == b.encode("utf-8")


def test_render_strips_trailing_whitespace():
    text = SAMPLE_PRIORITIES.read_text()
    rendered = render_hot_md(_parse_priorities(text), PINNED_GENERATED_AT)
    for line in rendered.splitlines():
        assert line == line.rstrip(), f"trailing whitespace in: {line!r}"


def test_render_uses_lf_line_endings():
    text = SAMPLE_PRIORITIES.read_text()
    rendered = render_hot_md(_parse_priorities(text), PINNED_GENERATED_AT)
    assert "\r\n" not in rendered
    assert rendered.endswith("\n")


# ---------------------------------------------------------------------------
# slugs.yml mutations
# ---------------------------------------------------------------------------


def test_apply_slug_changes_add_appends_and_bumps_version():
    yml = SAMPLE_SLUGS.read_text()
    priorities = _parse_priorities(SAMPLE_PRIORITIES.read_text())
    new_yml, summary = apply_slug_changes(yml, priorities, today=PINNED_TODAY)
    assert "version: 14" in new_yml
    assert f"updated_at: {PINNED_TODAY}" in new_yml
    assert "  - slug: uk-homes" in new_yml
    add_ops = [s for s in summary if s["action"] == "add" and s["applied"]]
    assert len(add_ops) == 1
    assert add_ops[0]["slug"] == "uk-homes"


def test_apply_slug_changes_dismissed_retire_flips_status():
    yml = SAMPLE_SLUGS.read_text()
    priorities = _parse_priorities(SAMPLE_PRIORITIES.read_text())
    new_yml, summary = apply_slug_changes(yml, priorities, today=PINNED_TODAY)

    # brisen-lp must now be retired with prepended note.
    block = _slug_block(new_yml, "brisen-lp")
    assert "status: retired" in block
    assert f"RETIRED {PINNED_TODAY} per Triaga (Q28)." in block

    retire_ops = [s for s in summary if s["action"] == "retire" and s["applied"]]
    assert len(retire_ops) == 1
    assert retire_ops[0]["slug"] == "brisen-lp"


def test_apply_slug_changes_idempotent():
    """Running apply_slug_changes twice should be a no-op the second time
    (already retired + already added)."""
    yml = SAMPLE_SLUGS.read_text()
    priorities = _parse_priorities(SAMPLE_PRIORITIES.read_text())
    once, _ = apply_slug_changes(yml, priorities, today=PINNED_TODAY)
    twice, summary2 = apply_slug_changes(once, priorities, today=PINNED_TODAY)
    assert once == twice  # second pass changes nothing
    # Second-pass summary: no real applies.
    real_applies = [s for s in summary2 if s.get("applied")]
    assert real_applies == []


def _slug_block(yml: str, slug: str) -> str:
    """Extract the YAML block for a single slug entry."""
    lines = yml.splitlines()
    out: list[str] = []
    capturing = False
    for line in lines:
        if line.startswith(f"  - slug: {slug}") or line.startswith(f"  - slug: {slug} "):
            capturing = True
            out.append(line)
            continue
        if capturing:
            if line.startswith("  - slug:") or (line and not line.startswith(" ")):
                break
            out.append(line)
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Full pipeline: regen_hot_md
# ---------------------------------------------------------------------------


def test_regen_writes_hot_md_and_appends_proposed_gold(tmp_path):
    vault = _make_vault(tmp_path)
    # Pre-existing proposed-gold.md with status: empty so we exercise the flip.
    pg_path = vault / "wiki" / "matters" / "oskolkov" / "proposed-gold.md"
    pg_path.write_text(
        "---\n"
        "title: \"AO Proposed Gold\"\n"
        "matter: oskolkov\n"
        "type: proposed-gold\n"
        "layer: 2\n"
        "live_state_refs: []\n"
        "owner: \"AI Head\"\n"
        "last_audit: 2026-04-22\n"
        "status: empty\n"
        "---\n\n"
        "# Proposed Gold\n\n"
        "(Empty — awaits first candidate.)\n",
        encoding="utf-8",
    )

    result = regen_hot_md(
        vault / "wiki" / "_priorities.yml",
        vault,
        write=True,
        generated_at=PINNED_GENERATED_AT,
        today=PINNED_TODAY,
    )

    assert result.validation_passed is True
    hot_md = (vault / "wiki" / "hot.md").read_text(encoding="utf-8")
    assert "**hagenauer-rg7**" in hot_md
    assert "**aukera + mo-vie-am**" in hot_md
    assert "## Actively frozen / dismissed" in hot_md

    # Proposed-gold append: status flipped, candidate appended.
    pg_text = pg_path.read_text(encoding="utf-8")
    assert "status: candidates" in pg_text
    assert "status: empty" not in pg_text
    assert "## Candidate G1 — figure-correction" in pg_text
    assert f"last_audit: {PINNED_TODAY}" in pg_text
    assert ("oskolkov", "G1") in result.proposed_gold_appends


def test_regen_idempotent_second_run_no_drift(tmp_path):
    vault = _make_vault(tmp_path)
    r1 = regen_hot_md(
        vault / "wiki" / "_priorities.yml",
        vault,
        write=True,
        generated_at=PINNED_GENERATED_AT,
        today=PINNED_TODAY,
    )
    assert r1.validation_passed
    # Second run on the same fixture: hot.md byte-identical, no drift.
    hot_md_before = (vault / "wiki" / "hot.md").read_text()
    r2 = regen_hot_md(
        vault / "wiki" / "_priorities.yml",
        vault,
        write=True,
        generated_at=PINNED_GENERATED_AT,
        today=PINNED_TODAY,
    )
    hot_md_after = (vault / "wiki" / "hot.md").read_text()
    assert hot_md_before == hot_md_after
    assert r2.drift_detected is False, r2.drift_diff


def test_regen_idempotent_proposed_gold_skip_existing_id(tmp_path):
    vault = _make_vault(tmp_path)
    regen_hot_md(
        vault / "wiki" / "_priorities.yml",
        vault,
        write=True,
        generated_at=PINNED_GENERATED_AT,
        today=PINNED_TODAY,
    )
    pg_path = vault / "wiki" / "matters" / "oskolkov" / "proposed-gold.md"
    text_after_first = pg_path.read_text(encoding="utf-8")

    # Re-run: G1 already present, must NOT duplicate.
    r2 = regen_hot_md(
        vault / "wiki" / "_priorities.yml",
        vault,
        write=True,
        generated_at=PINNED_GENERATED_AT,
        today=PINNED_TODAY,
    )
    text_after_second = pg_path.read_text(encoding="utf-8")
    # Exactly one G1 candidate section.
    assert text_after_second.count("## Candidate G1 — figure-correction") == 1
    assert text_after_second == text_after_first
    assert r2.proposed_gold_appends == []  # nothing newly appended on idempotent run


def test_regen_drift_detected_when_hot_md_manually_edited(tmp_path):
    vault = _make_vault(tmp_path)
    regen_hot_md(
        vault / "wiki" / "_priorities.yml",
        vault,
        write=True,
        generated_at=PINNED_GENERATED_AT,
        today=PINNED_TODAY,
    )
    # Manually edit hot.md to simulate operator drift.
    hot_md_path = vault / "wiki" / "hot.md"
    hot_md_path.write_text(
        hot_md_path.read_text() + "\n\n## MANUAL EDIT — OPERATOR DRIFT\n",
        encoding="utf-8",
    )
    # Dry-run check: drift must be detected.
    result = regen_hot_md(
        vault / "wiki" / "_priorities.yml",
        vault,
        write=False,
        generated_at=PINNED_GENERATED_AT,
        today=PINNED_TODAY,
    )
    assert result.drift_detected is True
    assert "MANUAL EDIT" in (result.drift_diff or "")


def test_regen_aborts_on_validation_failure(tmp_path):
    """Inject a duplicate slug into slugs.yml; loader must reject; regen must
    revert + emit regen_failed.log."""
    vault = _make_vault(tmp_path)
    slugs_path = vault / "slugs.yml"
    original = slugs_path.read_text(encoding="utf-8")
    # Duplicate `ao` block to trigger SlugRegistryError (proper indentation
    # under matters: list — 2-space).
    poisoned = original + (
        "\n"
        "  - slug: ao\n"
        "    status: active\n"
        "    description: \"Duplicate ao\"\n"
        "    aliases: []\n"
    )
    slugs_path.write_text(poisoned, encoding="utf-8")

    result = regen_hot_md(
        vault / "wiki" / "_priorities.yml",
        vault,
        write=True,
        generated_at=PINNED_GENERATED_AT,
        today=PINNED_TODAY,
    )

    assert result.validation_passed is False
    assert result.validation_error is not None
    assert "duplicate" in result.validation_error.lower()
    # slugs.yml must be reverted to the poisoned state (we revert to what we
    # read on entry; in this test that's the poisoned version since we
    # poisoned BEFORE calling regen).
    assert slugs_path.read_text(encoding="utf-8") == poisoned

    # regen_failed.log emitted next to script.
    log_path = REPO_ROOT / "scripts" / "regen_failed.log"
    assert log_path.exists()
    assert "validation failed" in log_path.read_text()


def test_regen_dry_run_does_not_write(tmp_path):
    vault = _make_vault(tmp_path)
    hot_md_path = vault / "wiki" / "hot.md"
    slugs_path = vault / "slugs.yml"
    original_slugs = slugs_path.read_text()
    assert not hot_md_path.exists()

    result = regen_hot_md(
        vault / "wiki" / "_priorities.yml",
        vault,
        write=False,
        generated_at=PINNED_GENERATED_AT,
        today=PINNED_TODAY,
    )

    assert result.validation_passed is True
    assert not hot_md_path.exists(), "dry-run must not write hot.md"
    assert slugs_path.read_text() == original_slugs, "dry-run must not mutate slugs.yml"


# ---------------------------------------------------------------------------
# Golden fixture round-trip
# ---------------------------------------------------------------------------


def test_golden_hot_md_matches(tmp_path):
    """The 3-matter fixture must regenerate to expected_hot.md byte-for-byte
    (modulo the pinned generated_at)."""
    vault = _make_vault(tmp_path)
    result = regen_hot_md(
        vault / "wiki" / "_priorities.yml",
        vault,
        write=True,
        generated_at=PINNED_GENERATED_AT,
        today=PINNED_TODAY,
    )
    actual = (vault / "wiki" / "hot.md").read_text(encoding="utf-8")
    expected = EXPECTED_HOT_MD.read_text(encoding="utf-8")
    assert actual == expected, (
        "hot.md golden mismatch.\n\n"
        f"--- expected ({len(expected)} bytes) ---\n{expected}\n"
        f"--- actual ({len(actual)} bytes) ---\n{actual}\n"
    )
    assert result.summary["matters_count"] == 3
