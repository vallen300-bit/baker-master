"""Tests for orchestrator.pipeline._match_matter_slug AND-gate overlay.

HAG_TRANSCRIPT_CLASSIFIER_TIGHTEN_1 — per-matter YAML overlay activates
require_all_groups AND-gate semantics.
"""
from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from orchestrator import pipeline as pipeline_mod
from orchestrator.pipeline import _match_matter_slug


@pytest.fixture
def vault_tmpdir(monkeypatch, tmp_path):
    """Point BAKER_VAULT_PATH at a tmpdir; clear the YAML cache between tests."""
    monkeypatch.setenv("BAKER_VAULT_PATH", str(tmp_path))
    monkeypatch.setattr(pipeline_mod, "_VAULT_PATH", tmp_path)
    pipeline_mod._CLASSIFIER_RULES_CACHE.clear()
    yield tmp_path
    pipeline_mod._CLASSIFIER_RULES_CACHE.clear()


def _write_hag_overlay(vault: Path) -> None:
    overlay_dir = vault / "wiki" / "matters" / "hagenauer-rg7"
    overlay_dir.mkdir(parents=True, exist_ok=True)
    (overlay_dir / "classifier-keywords.yml").write_text(textwrap.dedent("""
        matter_slug: hagenauer-rg7
        rule: require_all_groups
        groups:
          counterparty:
            - hagenauer
            - K-Co-Hag
            - ofenheimer
            - riel
          dispute_context:
            - Konkurs
            - Insolvenz
            - Forderungsanmeldung
            - Mangel
            - ClaimsMax
            - Schlussabrechnung
    """).strip())


def _make_store(matters: list) -> MagicMock:
    store = MagicMock()
    store.get_matters.return_value = matters
    return store


HAG_MATTER = {
    "matter_name": "hagenauer-rg7",
    "keywords": ["hagenauer", "rg7", "K-Co-Hag"],
    "people": ["Mario Hagenauer", "Stephan Riel"],
}


# AC5 Case 1: counterparty + dispute context → tags hagenauer-rg7
def test_case_1_counterparty_plus_dispute_matches(vault_tmpdir):
    _write_hag_overlay(vault_tmpdir)
    store = _make_store([HAG_MATTER])
    result = _match_matter_slug(
        title="Forderungsanmeldung Hagenauer status",
        body="Discussed claim submission with Ofenheimer; Insolvenzverwalter Riel pushed deadline.",
        store=store,
    )
    assert result == "hagenauer-rg7"


# AC5 Case 2: RG7 mention + AO/parent-finance context only → does NOT tag
def test_case_2_rg7_alone_in_parent_finance_does_not_match(vault_tmpdir):
    _write_hag_overlay(vault_tmpdir)
    store = _make_store([HAG_MATTER])
    result = _match_matter_slug(
        title="RG7 equity restructure with Oskolkov",
        body="AO debt rollover; LCG-RG7 shareholder loan terms; capital call schedule.",
        store=store,
    )
    assert result is None  # AND-gate excludes (no dispute_context group hit)


# AC5 Case 3: Hagenauer counterparty + no dispute context → does NOT tag
def test_case_3_counterparty_alone_does_not_match(vault_tmpdir):
    _write_hag_overlay(vault_tmpdir)
    store = _make_store([HAG_MATTER])
    result = _match_matter_slug(
        title="Hagenauer dinner update",
        body="Mentioned by Ofenheimer in catch-up; no project status changes; pure social mention.",
        store=store,
    )
    assert result is None


# AC5 Case 4: RG7 mention + no counterparty + no dispute → does NOT tag
def test_case_4_rg7_alone_does_not_match(vault_tmpdir):
    _write_hag_overlay(vault_tmpdir)
    store = _make_store([HAG_MATTER])
    result = _match_matter_slug(
        title="RG7 corporate finance review",
        body="Pure SPV cap-table discussion. No counterparty, no defects.",
        store=store,
    )
    assert result is None


# AC5 Case 5: matter without overlay falls through to default OR scoring
def test_case_5_matter_without_overlay_unchanged(vault_tmpdir):
    no_overlay_matter = {
        "matter_name": "movie",
        "keywords": ["mandarin", "mohg"],
        "people": ["James Riley"],
    }
    store = _make_store([no_overlay_matter])
    result = _match_matter_slug(
        title="MOHG monthly Mandarin update",
        body="Mandarin Oriental Vienna F&B numbers.",
        store=store,
    )
    assert result == "movie"


# Bonus regression: missing overlay file does NOT crash + falls through
def test_missing_overlay_file_falls_through_to_default(vault_tmpdir):
    store = _make_store([HAG_MATTER])
    result = _match_matter_slug(
        title="hagenauer rg7 meeting",
        body="",
        store=store,
    )
    assert result == "hagenauer-rg7"  # default scoring still works


# Bonus regression: malformed YAML fails open
def test_malformed_overlay_fails_open(vault_tmpdir):
    overlay_dir = vault_tmpdir / "wiki" / "matters" / "hagenauer-rg7"
    overlay_dir.mkdir(parents=True, exist_ok=True)
    (overlay_dir / "classifier-keywords.yml").write_text("not: [valid: yaml")
    store = _make_store([HAG_MATTER])
    result = _match_matter_slug(
        title="hagenauer rg7",
        body="",
        store=store,
    )
    assert result == "hagenauer-rg7"
