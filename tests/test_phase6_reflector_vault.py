"""Vault write tests for orchestrator.cortex_phase6_reflector.

Brief: CORTEX_PHASE6_REFLECTOR_1 §5.5.

Pure filesystem (tmp_path). Asserts:
  * first write creates frontmatter + first cycle block
  * second write appends a cycle block, frontmatter unchanged
  * frontmatter conforms to kbl/ingest_endpoint.validate_frontmatter
"""
from __future__ import annotations

from pathlib import Path

import yaml

from kbl.ingest_endpoint import validate_frontmatter
from orchestrator.cortex_phase6_reflector import write_proposed_actions_to_vault


def _extract_frontmatter(content: str) -> dict:
    assert content.startswith("---\n"), "missing leading frontmatter delimiter"
    end = content.find("\n---\n", 4)
    assert end != -1, "frontmatter not terminated"
    return yaml.safe_load(content[4:end])


def test_first_write_creates_frontmatter(tmp_path: Path):
    target = write_proposed_actions_to_vault(
        cycle_id="11111111-1111-1111-1111-111111111111",
        matter_slug="oskolkov",
        proposal_text="Send AO follow-up email by Friday.",
        cited_ids=["oskolkov-001"],
        triaga_outcome="helpful",
        today_iso="2026-04-30",
        staging_root=tmp_path,
    )
    assert target.is_file()
    assert target == tmp_path / "matters" / "oskolkov" / "proposed-config-deltas.md"

    content = target.read_text(encoding="utf-8")
    fm = _extract_frontmatter(content)
    validate_frontmatter(fm)  # raises on validator failure
    assert fm["type"] == "matter"
    assert fm["slug"] == "oskolkov"
    assert fm["voice"] == "silver"
    assert "cortex-reflector" in fm["tags"]
    # First block present
    assert "Cycle 11111111-1111-1111-1111-111111111111" in content
    assert "Send AO follow-up email by Friday." in content
    assert "[directive] not used in body proper" not in content


def test_second_write_appends_block(tmp_path: Path):
    """Frontmatter once; multiple cycle blocks append after."""
    write_proposed_actions_to_vault(
        cycle_id="aaaa-1",
        matter_slug="movie",
        proposal_text="First proposal.",
        cited_ids=["movie-001"],
        triaga_outcome="helpful",
        today_iso="2026-04-30",
        staging_root=tmp_path,
    )
    write_proposed_actions_to_vault(
        cycle_id="bbbb-2",
        matter_slug="movie",
        proposal_text="Second proposal.",
        cited_ids=[],
        triaga_outcome="stale",
        today_iso="2026-04-30",
        staging_root=tmp_path,
    )
    content = (tmp_path / "matters" / "movie" / "proposed-config-deltas.md").read_text(
        encoding="utf-8"
    )
    # Frontmatter delimiter appears exactly twice (open + close), plus internal `---\n` cycle separators.
    assert content.startswith("---\ntype: matter")
    fm = _extract_frontmatter(content)
    validate_frontmatter(fm)
    assert "First proposal." in content
    assert "Second proposal." in content
    # Untraceable badge for second cycle (no cited ids).
    assert "_none — flagged untraceable_" in content


def test_path_follows_staging_convention(tmp_path: Path):
    """Path is {staging_root}/matters/<slug>/proposed-config-deltas.md."""
    target = write_proposed_actions_to_vault(
        cycle_id="cc",
        matter_slug="hagenauer-rg7",
        proposal_text="x",
        cited_ids=[],
        triaga_outcome="harmful",
        today_iso="2026-04-30",
        staging_root=tmp_path,
    )
    assert target.parent == tmp_path / "matters" / "hagenauer-rg7"
    assert target.name == "proposed-config-deltas.md"


def test_outcome_marker_present_in_block(tmp_path: Path):
    """Cycle block header must surface triaga_outcome for human readers."""
    write_proposed_actions_to_vault(
        cycle_id="dd",
        matter_slug="cupial",
        proposal_text="-",
        cited_ids=["cupial-001"],
        triaga_outcome="harmful",
        today_iso="2026-04-30",
        staging_root=tmp_path,
    )
    content = (tmp_path / "matters" / "cupial" / "proposed-config-deltas.md").read_text(
        encoding="utf-8"
    )
    assert "(harmful)" in content
