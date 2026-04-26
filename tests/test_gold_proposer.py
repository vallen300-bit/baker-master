"""Tests for kbl.gold_proposer — Cortex agent-drafted proposed-gold writes."""
from __future__ import annotations

from pathlib import Path

import pytest

from kbl.gold_proposer import PROPOSED_HEADER, ProposedGoldEntry, propose

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _slug_registry_using_test_vault(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BAKER_VAULT_PATH", str(FIXTURES / "vault"))
    from kbl import slug_registry
    slug_registry.reload()
    yield
    slug_registry.reload()


def _proposed(**overrides) -> ProposedGoldEntry:
    base = dict(
        iso_date="2026-04-26",
        topic="proposed topic",
        proposed_resolution="Maybe do X.",
        proposer="cortex-3t",
        cortex_cycle_id="cycle-001",
        confidence=0.75,
    )
    base.update(overrides)
    return ProposedGoldEntry(**base)


def test_propose_global_appends_to_director_gold_global(tmp_path: Path):
    target = propose(_proposed(), vault_root=tmp_path)
    assert target == tmp_path / "_ops" / "director-gold-global.md"
    text = target.read_text(encoding="utf-8")
    assert PROPOSED_HEADER in text
    assert "### 2026-04-26 — proposed topic" in text
    assert "**Proposer:** cortex-3t (confidence 0.75)" in text
    assert "**Cycle:** cycle-001" in text


def test_propose_matter_writes_to_proposed_gold_md(tmp_path: Path):
    target = propose(_proposed(), matter="alpha", vault_root=tmp_path)
    assert (
        target == tmp_path / "wiki" / "matters" / "alpha" / "proposed-gold.md"
    )
    text = target.read_text(encoding="utf-8")
    assert PROPOSED_HEADER in text


def test_propose_unknown_matter_raises(tmp_path: Path):
    with pytest.raises(ValueError, match="not canonical"):
        propose(_proposed(), matter="not-a-real-slug", vault_root=tmp_path)


def test_propose_does_not_duplicate_header_on_second_call(tmp_path: Path):
    propose(_proposed(), vault_root=tmp_path)
    propose(
        _proposed(topic="second topic", iso_date="2026-04-27"),
        vault_root=tmp_path,
    )
    target = tmp_path / "_ops" / "director-gold-global.md"
    text = target.read_text(encoding="utf-8")
    assert text.count(PROPOSED_HEADER) == 1
    assert "### 2026-04-26 — proposed topic" in text
    assert "### 2026-04-27 — second topic" in text


def test_propose_appends_below_existing_ratified_entries(tmp_path: Path):
    """When the file already has ratified entries, proposed section goes BELOW."""
    target_dir = tmp_path / "_ops"
    target_dir.mkdir(parents=True)
    target = target_dir / "director-gold-global.md"
    target.write_text(
        "## 2026-04-25 — Ratified Entry\n\n"
        '**Ratification:** "yes" DV.\n\n'
        "**Resolution:** something.\n",
        encoding="utf-8",
    )
    propose(_proposed(), vault_root=tmp_path)
    text = target.read_text(encoding="utf-8")
    # Ratified entry preserved
    assert "## 2026-04-25 — Ratified Entry" in text
    # Proposed header appears AFTER the ratified entry
    assert text.index("## 2026-04-25 — Ratified Entry") < text.index(
        PROPOSED_HEADER
    )


def test_propose_no_cycle_id_omits_cycle_line(tmp_path: Path):
    target = propose(
        _proposed(cortex_cycle_id=None), vault_root=tmp_path
    )
    text = target.read_text(encoding="utf-8")
    assert "**Cycle:**" not in text


def test_propose_creates_matter_dir_if_missing(tmp_path: Path):
    """proposer auto-creates the matter dir (parents=True) — distinct from
    gold_writer's fail-loud behavior, since proposed entries are V1 throwaway."""
    target = propose(_proposed(), matter="alpha", vault_root=tmp_path)
    assert target.parent.is_dir()
