"""Integration tests for kbl.ingest_endpoint.validate_slug_in_registry().

Exercises the KBL_REGISTRY_STRICT flag interaction with people / entity
registries. Uses a combined fixture vault that has slugs.yml + people.yml +
entities.yml so the matter-type path keeps working too.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from kbl import entity_registry, people_registry, slug_registry
from kbl.ingest_endpoint import KBLIngestError, validate_slug_in_registry

FIXTURES = Path(__file__).parent / "fixtures"
COMBINED = FIXTURES / "registries_combined"


@pytest.fixture(autouse=True)
def _combined_vault(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BAKER_VAULT_PATH", str(COMBINED))
    slug_registry.reload()
    people_registry.reload()
    entity_registry.reload()
    yield
    slug_registry.reload()
    people_registry.reload()
    entity_registry.reload()


def _person_fm(slug: str) -> dict:
    return {"type": "person", "slug": slug}


def _entity_fm(slug: str) -> dict:
    return {"type": "entity", "slug": slug}


def _matter_fm(slug: str) -> dict:
    return {"type": "matter", "slug": slug}


def test_flag_off_unregistered_person_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("KBL_REGISTRY_STRICT", raising=False)
    # Should NOT raise — current behaviour preserved when flag default-off.
    validate_slug_in_registry(_person_fm("andrey-okolkov"))  # typo, not canonical


def test_flag_on_unregistered_person_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KBL_REGISTRY_STRICT", "true")
    with pytest.raises(KBLIngestError, match="people.yml registry"):
        validate_slug_in_registry(_person_fm("andrey-okolkov"))


def test_flag_on_canonical_person_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KBL_REGISTRY_STRICT", "true")
    validate_slug_in_registry(_person_fm("dimitry-vallen"))  # canonical


def test_flag_on_matter_type_still_runs_matter_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KBL_REGISTRY_STRICT", "true")
    # Canonical matter accepted.
    validate_slug_in_registry(_matter_fm("alpha"))
    # Unknown matter still rejected — flag does not affect matter path.
    with pytest.raises(KBLIngestError, match="slugs.yml registry"):
        validate_slug_in_registry(_matter_fm("not-a-matter"))


def test_flag_on_unregistered_entity_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KBL_REGISTRY_STRICT", "true")
    with pytest.raises(KBLIngestError, match="entities.yml registry"):
        validate_slug_in_registry(_entity_fm("aelio-holdng-ltd"))


def test_flag_on_canonical_entity_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KBL_REGISTRY_STRICT", "true")
    validate_slug_in_registry(_entity_fm("aelio-holding-ltd"))


def test_flag_off_unregistered_entity_warn_only(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.delenv("KBL_REGISTRY_STRICT", raising=False)
    import logging

    with caplog.at_level(logging.WARNING, logger="baker.kbl.ingest_endpoint"):
        validate_slug_in_registry(_entity_fm("nonexistent-co"))
    assert any("would-reject entity" in r.message for r in caplog.records)
