"""Tests for kbl.gold_drift_detector — pre-write + full-corpus scans."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from kbl import gold_drift_detector as gdd
from kbl.gold_drift_detector import DriftIssue, audit_all, validate_entry


def _entry(**overrides):
    base = dict(
        iso_date="2026-04-26",
        topic="example topic",
        ratification_quote='"yes" (Director, 2026-04-26). DV.',
        background="Some background.",
        resolution="Some resolution.",
        authority_chain="Director RA-21",
        carry_forward="none",
        matter=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# ----------------------------- validate_entry ----------------------------- #


def test_validate_entry_clean_returns_empty(tmp_path: Path):
    target = tmp_path / "gold.md"
    issues = validate_entry(_entry(), target)
    assert issues == []


def test_validate_entry_bad_iso_date():
    issues = validate_entry(_entry(iso_date="04-26-2026"), Path("/dev/null"))
    codes = {i.code for i in issues}
    assert "SCHEMA" in codes


def test_validate_entry_missing_required_field():
    issues = validate_entry(_entry(resolution=""), Path("/dev/null"))
    codes = {i.code for i in issues}
    assert "SCHEMA" in codes


def test_validate_entry_does_not_flag_missing_dv_in_quote(tmp_path: Path):
    """validate_entry is belt-and-braces — gold_writer appends DV. via renderer.
    DV_ONLY flagging happens in audit_all (manual file writes bypassing renderer).
    """
    issues = validate_entry(
        _entry(ratification_quote='"yes" (Director, 2026-04-26).'),
        tmp_path / "gold.md",
    )
    codes = {i.code for i in issues}
    assert "DV_ONLY" not in codes


def test_validate_entry_unknown_matter_slug(monkeypatch: pytest.MonkeyPatch):
    """Use real slug_registry against a fixture vault — typo'd slug rejected."""
    fixtures = Path(__file__).parent / "fixtures"
    monkeypatch.setenv("BAKER_VAULT_PATH", str(fixtures / "vault"))
    from kbl import slug_registry
    slug_registry.reload()
    try:
        issues = validate_entry(
            _entry(matter="not-a-real-slug"),
            Path("/dev/null"),
        )
        codes = {i.code for i in issues}
        assert "SLUG_UNKNOWN" in codes
    finally:
        slug_registry.reload()


def test_validate_entry_canonical_matter_slug_passes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    fixtures = Path(__file__).parent / "fixtures"
    monkeypatch.setenv("BAKER_VAULT_PATH", str(fixtures / "vault"))
    from kbl import slug_registry
    slug_registry.reload()
    try:
        issues = validate_entry(_entry(matter="alpha"), tmp_path / "gold.md")
        assert not any(i.code == "SLUG_UNKNOWN" for i in issues)
    finally:
        slug_registry.reload()


def test_validate_entry_material_conflict_on_same_topic(tmp_path: Path):
    target = tmp_path / "gold.md"
    target.write_text(
        "## 2026-04-20 — Example Topic\n\n"
        '**Ratification:** "Earlier ratification" DV.\n',
        encoding="utf-8",
    )
    issues = validate_entry(_entry(topic="example topic"), target)
    codes = {i.code for i in issues}
    assert "MATERIAL_CONFLICT" in codes


def test_validate_entry_no_conflict_for_distinct_topic(tmp_path: Path):
    target = tmp_path / "gold.md"
    target.write_text(
        "## 2026-04-20 — Different Topic\n\n"
        '**Ratification:** "first" DV.\n',
        encoding="utf-8",
    )
    issues = validate_entry(_entry(topic="brand new topic"), target)
    assert not any(i.code == "MATERIAL_CONFLICT" for i in issues)


# -------------------------------- audit_all ------------------------------- #


def _seed_global(vault: Path, body: str = "") -> Path:
    out = vault / "_ops" / "director-gold-global.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        "---\n"
        "title: Director Gold — Global\n"
        "type: gold\n"
        "---\n"
        + body,
        encoding="utf-8",
    )
    return out


def test_audit_all_clean_corpus_returns_empty(tmp_path: Path):
    _seed_global(
        tmp_path,
        body=(
            '## 2026-04-26 — Topic A\n\n**Ratification:** "yes" DV.\n\n'
            '## 2026-04-25 — Topic B\n\n**Ratification:** "ok" DV.\n'
        ),
    )
    issues = audit_all(tmp_path)
    assert issues == []


def test_audit_all_flags_missing_dv_initials(tmp_path: Path):
    _seed_global(
        tmp_path,
        body=(
            "## 2026-04-26 — Topic With No Initials\n\n"
            '**Ratification:** "yes" (Director).\n'
        ),
    )
    issues = audit_all(tmp_path)
    assert any(i.code == "DV_ONLY" for i in issues)


def test_audit_all_flags_duplicate_topic_key(tmp_path: Path):
    _seed_global(
        tmp_path,
        body=(
            '## 2026-04-26 — Same Topic\n\n**Ratification:** "first" DV.\n\n'
            '## 2026-04-25 — Same Topic\n\n**Ratification:** "second" DV.\n'
        ),
    )
    issues = audit_all(tmp_path)
    assert any(i.code == "MATERIAL_CONFLICT" for i in issues)


def test_audit_all_flags_orphan_proposal_over_30d(tmp_path: Path):
    matter_dir = tmp_path / "wiki" / "matters" / "movie"
    matter_dir.mkdir(parents=True)
    old_date = (datetime.now(timezone.utc) - timedelta(days=45)).date().isoformat()
    (matter_dir / "proposed-gold.md").write_text(
        "## Proposed Gold (agent-drafted)\n\n"
        f"### {old_date} — Aging proposal\n\n"
        "**Proposer:** cortex-3t (confidence 0.50)\n",
        encoding="utf-8",
    )
    issues = audit_all(tmp_path)
    assert any(i.code == "ORPHAN_PROPOSAL" for i in issues)


def test_audit_all_does_not_flag_recent_proposal(tmp_path: Path):
    matter_dir = tmp_path / "wiki" / "matters" / "movie"
    matter_dir.mkdir(parents=True)
    recent = (datetime.now(timezone.utc) - timedelta(days=3)).date().isoformat()
    (matter_dir / "proposed-gold.md").write_text(
        "## Proposed Gold (agent-drafted)\n\n"
        f"### {recent} — Recent proposal\n\n"
        "**Proposer:** cortex-3t\n",
        encoding="utf-8",
    )
    issues = audit_all(tmp_path)
    assert not any(i.code == "ORPHAN_PROPOSAL" for i in issues)


def test_audit_all_skips_proposed_section_in_global(tmp_path: Path):
    """Proposed Gold (agent-drafted) section in global is not subject to DV-only."""
    _seed_global(
        tmp_path,
        body=(
            '## 2026-04-26 — Real Entry\n\n**Ratification:** "yes" DV.\n\n'
            "## Proposed Gold (agent-drafted)\n\n"
            "### 2026-04-26 — Cortex draft\n\n"
            "**Proposer:** cortex-3t\n"
        ),
    )
    issues = audit_all(tmp_path)
    # Cortex draft should NOT trigger DV_ONLY since it's in the proposed section.
    assert not any(
        i.code == "DV_ONLY" and "Cortex draft" in i.message for i in issues
    )
