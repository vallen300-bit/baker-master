"""Tests for kbl.entity_registry against fixture vaults."""
from __future__ import annotations

import threading
from pathlib import Path

import pytest

from kbl import entity_registry
from kbl.entity_registry import (
    Entity,
    EntityRegistryError,
    RegistryVersionError,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _reset_cache():
    entity_registry.reload()
    yield
    entity_registry.reload()


def _use_vault(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BAKER_VAULT_PATH", str(FIXTURES / name))
    entity_registry.reload()


def test_load_returns_canonical_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_vault("registries_entities_ok", monkeypatch)
    loaded = entity_registry.load()
    assert set(loaded.keys()) == {
        "aelio-holding-ltd",
        "brisen-capital-sa",
        "old-vehicle-gmbh",
    }
    assert isinstance(loaded["aelio-holding-ltd"], Entity)


def test_cache_returns_same_object(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_vault("registries_entities_ok", monkeypatch)
    first = entity_registry.load()
    second = entity_registry.load()
    assert first["aelio-holding-ltd"] is second["aelio-holding-ltd"]


def test_is_canonical_hit_and_miss(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_vault("registries_entities_ok", monkeypatch)
    assert entity_registry.is_canonical("aelio-holding-ltd") is True
    assert entity_registry.is_canonical("aelio-holdng-ltd") is False  # typo
    assert entity_registry.is_canonical(None) is True


def test_get_returns_entity_or_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_vault("registries_entities_ok", monkeypatch)
    e = entity_registry.get("aelio-holding-ltd")
    assert e is not None
    assert e.slug == "aelio-holding-ltd"
    assert "aelio" in e.aliases
    assert entity_registry.get("nope") is None


def test_version_returns_int(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_vault("registries_entities_ok", monkeypatch)
    assert entity_registry.version() == 1


def test_active_slugs_filters_retired(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_vault("registries_entities_ok", monkeypatch)
    assert "old-vehicle-gmbh" not in entity_registry.active_slugs()
    assert "aelio-holding-ltd" in entity_registry.active_slugs()


def test_lint_catches_missing_version() -> None:
    issues = entity_registry.lint(
        FIXTURES / "registries_entities_no_version" / "entities.yml"
    )
    codes = {i.code for i in issues}
    assert "VERSION_MISSING" in codes


def test_lint_catches_duplicate_slugs() -> None:
    issues = entity_registry.lint(
        FIXTURES / "registries_entities_dup_slug" / "entities.yml"
    )
    codes = {i.code for i in issues}
    assert "DUP_SLUG" in codes


def test_lint_clean_on_valid_yml() -> None:
    issues = entity_registry.lint(
        FIXTURES / "registries_entities_ok" / "entities.yml"
    )
    assert issues == []


def test_missing_env_var_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BAKER_VAULT_PATH", raising=False)
    entity_registry.reload()
    with pytest.raises(EntityRegistryError, match="BAKER_VAULT_PATH"):
        entity_registry.canonical_slugs()


def test_missing_file_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BAKER_VAULT_PATH", str(tmp_path))
    entity_registry.reload()
    with pytest.raises(EntityRegistryError, match="not found"):
        entity_registry.canonical_slugs()


def test_dup_slug_raises_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_vault("registries_entities_dup_slug", monkeypatch)
    with pytest.raises(EntityRegistryError, match="duplicate canonical slug"):
        entity_registry.load()


def test_no_version_raises_registry_version_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_vault("registries_entities_no_version", monkeypatch)
    with pytest.raises(RegistryVersionError, match="version"):
        entity_registry.load()


def test_concurrent_load_is_thread_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_vault("registries_entities_ok", monkeypatch)
    entity_registry.reload()

    results: list[dict[str, Entity]] = []
    errors: list[BaseException] = []

    def worker():
        try:
            results.append(entity_registry.load())
        except BaseException as e:
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert len(results) == 16
    canonical = results[0]["aelio-holding-ltd"]
    for r in results[1:]:
        assert r["aelio-holding-ltd"] is canonical
