"""Tests for kbl.people_registry against fixture vaults.

Each test sets BAKER_VAULT_PATH to a fixture dir and calls people_registry.reload()
to drop the module-level cache so runs are isolated.
"""
from __future__ import annotations

import threading
from pathlib import Path

import pytest

from kbl import people_registry
from kbl.people_registry import (
    PeopleRegistryError,
    Person,
    RegistryVersionError,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _reset_cache():
    people_registry.reload()
    yield
    people_registry.reload()


def _use_vault(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BAKER_VAULT_PATH", str(FIXTURES / name))
    people_registry.reload()


def test_load_returns_canonical_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_vault("registries_people_ok", monkeypatch)
    loaded = people_registry.load()
    assert set(loaded.keys()) == {"dimitry-vallen", "andrey-oskolkov", "jane-doe"}
    assert isinstance(loaded["dimitry-vallen"], Person)
    assert loaded["dimitry-vallen"].status == "active"


def test_cache_returns_same_object(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_vault("registries_people_ok", monkeypatch)
    first = people_registry.load()
    second = people_registry.load()
    # load() returns a defensive copy each call, but the underlying entries
    # come from the cached registry — same Person instances.
    assert first["dimitry-vallen"] is second["dimitry-vallen"]


def test_is_canonical_hit_and_miss(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_vault("registries_people_ok", monkeypatch)
    assert people_registry.is_canonical("dimitry-vallen") is True
    assert people_registry.is_canonical("andrey-okolkov") is False  # typo
    assert people_registry.is_canonical(None) is True


def test_get_returns_person_or_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_vault("registries_people_ok", monkeypatch)
    p = people_registry.get("andrey-oskolkov")
    assert p is not None
    assert p.slug == "andrey-oskolkov"
    assert "ao" in p.aliases
    assert people_registry.get("nope") is None


def test_version_returns_int(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_vault("registries_people_ok", monkeypatch)
    assert people_registry.version() == 1


def test_lint_catches_missing_version() -> None:
    issues = people_registry.lint(
        FIXTURES / "registries_people_no_version" / "people.yml"
    )
    codes = {i.code for i in issues}
    assert "VERSION_MISSING" in codes


def test_lint_catches_duplicate_slugs() -> None:
    issues = people_registry.lint(
        FIXTURES / "registries_people_dup_slug" / "people.yml"
    )
    codes = {i.code for i in issues}
    assert "DUP_SLUG" in codes


def test_lint_catches_duplicate_aliases() -> None:
    issues = people_registry.lint(
        FIXTURES / "registries_people_dup_alias" / "people.yml"
    )
    codes = {i.code for i in issues}
    assert "DUP_ALIAS" in codes


def test_lint_clean_on_valid_yml() -> None:
    issues = people_registry.lint(
        FIXTURES / "registries_people_ok" / "people.yml"
    )
    assert issues == []


def test_missing_env_var_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BAKER_VAULT_PATH", raising=False)
    people_registry.reload()
    with pytest.raises(PeopleRegistryError, match="BAKER_VAULT_PATH"):
        people_registry.canonical_slugs()


def test_missing_file_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BAKER_VAULT_PATH", str(tmp_path))
    people_registry.reload()
    with pytest.raises(PeopleRegistryError, match="not found"):
        people_registry.canonical_slugs()


def test_dup_slug_raises_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_vault("registries_people_dup_slug", monkeypatch)
    with pytest.raises(PeopleRegistryError, match="duplicate canonical slug"):
        people_registry.load()


def test_no_version_raises_registry_version_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_vault("registries_people_no_version", monkeypatch)
    with pytest.raises(RegistryVersionError, match="version"):
        people_registry.load()


def test_concurrent_load_is_thread_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    """Module-level cache must be initialized exactly once under contention."""
    _use_vault("registries_people_ok", monkeypatch)
    people_registry.reload()

    results: list[dict[str, Person]] = []
    errors: list[BaseException] = []

    def worker():
        try:
            results.append(people_registry.load())
        except BaseException as e:
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert len(results) == 16
    # Every thread sees the same Person instance for a given slug.
    canonical = results[0]["dimitry-vallen"]
    for r in results[1:]:
        assert r["dimitry-vallen"] is canonical
