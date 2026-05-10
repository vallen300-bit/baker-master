"""Unit tests for ``kbl/priorities_registry.py``.

Loader exercises the singleton pattern, multi-slug row expansion, all 5
importance enum values, all category buckets, fail-soft on missing file,
fail-loud on schema violation, and reload semantics.

Tests do NOT require BAKER_VAULT_PATH at runtime: each test points the
loader at a fixture path via the BAKER_VAULT_PATH env var, with a mini
``wiki/_priorities.yml`` symlink-or-copy under ``tests/fixtures/priorities``.
"""
from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

import pytest

from kbl import priorities_registry as pr


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "priorities"
MINI_FIXTURE = FIXTURE_DIR / "_priorities_mini.yml"
BAD_SCHEMA_FIXTURE = FIXTURE_DIR / "_priorities_bad_schema.yml"


def _build_vault(tmp_path: Path, fixture: Path) -> Path:
    """Lay out tmp_path/wiki/_priorities.yml from `fixture`. Returns vault root."""
    wiki = tmp_path / "wiki"
    wiki.mkdir(parents=True, exist_ok=True)
    shutil.copy(fixture, wiki / "_priorities.yml")
    return tmp_path


@pytest.fixture(autouse=True)
def _reset_registry_between_tests():
    pr.reload()
    yield
    pr.reload()


@pytest.fixture
def mini_vault(tmp_path, monkeypatch):
    vault = _build_vault(tmp_path, MINI_FIXTURE)
    monkeypatch.setenv("BAKER_VAULT_PATH", str(vault))
    return vault


def test_singleton_loads_once(mini_vault):
    """Two calls to get_all() reuse the cache (no re-parse)."""
    first = pr.get_all()
    second = pr.get_all()
    # Same Priority objects (frozen dataclasses are value-equal AND id-equal
    # because cache returns same tuple).
    assert first == second
    assert all(a is b for a, b in zip(first, second))


def test_multi_slug_row_expansion(mini_vault):
    """slugs: [lilienmatt, annaberg, aukera] -> 3 Priority objects."""
    all_p = pr.get_all()
    multi = [p for p in all_p if p.triaga_ref == "Q7"]
    assert len(multi) == 3
    assert {p.slug for p in multi} == {"lilienmatt", "annaberg", "aukera"}
    # Every multi-row Priority shares the same metadata fields.
    assert {p.importance for p in multi} == {"medium"}
    assert {p.category for p in multi} == {"active-deal"}


def test_severity_for_critical(mini_vault):
    assert pr.severity_for("hagenauer-rg7") == "critical"


def test_severity_for_high(mini_vault):
    assert pr.severity_for("mrci") == "high"


def test_severity_for_medium(mini_vault):
    assert pr.severity_for("lilienmatt") == "medium"


def test_severity_for_low(mini_vault):
    assert pr.severity_for("vie-tax") == "low"


def test_severity_for_frozen(mini_vault):
    assert pr.severity_for("dormant-research") == "frozen"


def test_severity_for_unknown_slug_returns_none(mini_vault):
    assert pr.severity_for("not-a-real-slug") is None


def test_severity_for_picks_highest_when_slug_in_multiple_rows(mini_vault):
    """hagenauer-rg7 appears at importance critical (Q1) AND high (Q2);
    severity_for must return critical (the higher of the two)."""
    rows = pr.get_all_for_slug("hagenauer-rg7")
    assert len(rows) == 2
    assert {r.importance for r in rows} == {"critical", "high"}
    assert pr.severity_for("hagenauer-rg7") == "critical"


def test_category_for_active_deal(mini_vault):
    assert pr.category_for("mrci") == "active-deal"


def test_category_for_tax(mini_vault):
    assert pr.category_for("vie-tax") == "tax"


def test_category_for_unknown_slug_returns_none(mini_vault):
    assert pr.category_for("nope") is None


def test_is_active_priority_true(mini_vault):
    assert pr.is_active_priority("mrci") is True


def test_is_active_priority_false(mini_vault):
    assert pr.is_active_priority("kitz-kempinski") is False


def test_get_all_for_slug_multi_slug_row(mini_vault):
    rows = pr.get_all_for_slug("lilienmatt")
    assert len(rows) == 1
    assert rows[0].triaga_ref == "Q7"


def test_registry_version_returns_schema_version(mini_vault):
    assert pr.registry_version() == 1


def test_registry_ratified_at_returns_iso_string(mini_vault):
    assert pr.registry_ratified_at() == "2026-04-29T18:45:00+02:00"


def test_missing_file_returns_empty_warns_once(tmp_path, monkeypatch, caplog):
    """File absent: get_all() returns []; warning logged exactly once."""
    monkeypatch.setenv("BAKER_VAULT_PATH", str(tmp_path))  # no wiki/_priorities.yml
    pr.reload()
    with caplog.at_level(logging.WARNING, logger="kbl.priorities_registry"):
        first = pr.get_all()
        second = pr.get_all()
    assert first == []
    assert second == []
    warning_count = sum(
        1 for rec in caplog.records if "_priorities.yml" in rec.getMessage() or "priorities_registry" in rec.getMessage()
    )
    assert warning_count == 1, f"expected exactly one warning, got {warning_count}"


def test_missing_file_registry_version_is_none(tmp_path, monkeypatch):
    monkeypatch.setenv("BAKER_VAULT_PATH", str(tmp_path))
    pr.reload()
    assert pr.registry_version() is None
    assert pr.registry_ratified_at() is None
    assert pr.is_active_priority("anything") is False


def test_missing_baker_vault_path_returns_empty(monkeypatch, caplog):
    """BAKER_VAULT_PATH unset: fail-soft, return empty registry."""
    monkeypatch.delenv("BAKER_VAULT_PATH", raising=False)
    pr.reload()
    with caplog.at_level(logging.WARNING, logger="kbl.priorities_registry"):
        result = pr.get_all()
    assert result == []
    assert any("BAKER_VAULT_PATH" in rec.getMessage() for rec in caplog.records)


def test_malformed_yaml_raises_loud(tmp_path, monkeypatch):
    """Schema violation -> PrioritiesRegistryError (NOT fail-soft)."""
    vault = _build_vault(tmp_path, BAD_SCHEMA_FIXTURE)
    monkeypatch.setenv("BAKER_VAULT_PATH", str(vault))
    pr.reload()
    with pytest.raises(pr.PrioritiesRegistryError, match="importance"):
        pr.get_all()


def test_unknown_importance_enum_raises_loud(tmp_path, monkeypatch):
    """Same fixture, named explicitly per acceptance criterion."""
    vault = _build_vault(tmp_path, BAD_SCHEMA_FIXTURE)
    monkeypatch.setenv("BAKER_VAULT_PATH", str(vault))
    pr.reload()
    with pytest.raises(pr.PrioritiesRegistryError):
        pr.get_all()


def test_reload_re_reads_file(tmp_path, monkeypatch):
    """Modify fixture content between reads; reload() picks up changes."""
    vault = _build_vault(tmp_path, MINI_FIXTURE)
    monkeypatch.setenv("BAKER_VAULT_PATH", str(vault))
    pr.reload()
    assert pr.is_active_priority("mrci") is True

    yml = vault / "wiki" / "_priorities.yml"
    yml.write_text(
        "schema_version: 1\n"
        "ratified_at: '2026-05-10T00:00:00Z'\n"
        "categories: [active-deal]\n"
        "matters:\n"
        "  - slug: only-one-now\n"
        "    when: urgent\n"
        "    importance: low\n"
        "    category: active-deal\n"
        "    triaga_ref: Q99\n"
        "    description: replaced fixture\n"
        "    notes: []\n",
        encoding="utf-8",
    )

    # Without reload, cache is stale.
    assert pr.is_active_priority("mrci") is True
    # After reload, new content visible.
    pr.reload()
    assert pr.is_active_priority("mrci") is False
    assert pr.is_active_priority("only-one-now") is True
    assert pr.severity_for("only-one-now") == "low"
