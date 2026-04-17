"""Tests for kbl.slug_registry against fixture vaults.

Each test sets BAKER_VAULT_PATH to a fixture dir and calls slug_registry.reload()
to drop the module-level cache so runs are isolated. Do NOT add a test that
asserts on the production 19-slug list — defeats the point of the registry.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from kbl import slug_registry
from kbl.slug_registry import SlugRegistryError

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _reset_cache():
    slug_registry.reload()
    yield
    slug_registry.reload()


def _use_vault(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BAKER_VAULT_PATH", str(FIXTURES / name))
    slug_registry.reload()


def test_load_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_vault("vault", monkeypatch)
    assert slug_registry.registry_version() == 1
    assert slug_registry.canonical_slugs() == {"alpha", "beta", "gamma"}


def test_duplicate_slug_fails_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_vault("vault_dup_slug", monkeypatch)
    with pytest.raises(SlugRegistryError, match="duplicate canonical slug"):
        slug_registry.canonical_slugs()


def test_duplicate_alias_across_slugs_fails_loudly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_vault("vault_dup_alias", monkeypatch)
    with pytest.raises(SlugRegistryError, match="alias .* maps to both"):
        slug_registry.canonical_slugs()


def test_normalize_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_vault("vault", monkeypatch)

    # Exact canonical pass-through
    assert slug_registry.normalize("alpha") == "alpha"
    assert slug_registry.normalize("ALPHA") == "alpha"

    # Alias match
    assert slug_registry.normalize("al") == "alpha"
    assert slug_registry.normalize("bee") == "beta"

    # Whitespace variations
    assert slug_registry.normalize("  alpha  one  ") == "alpha"
    assert slug_registry.normalize("ALPHA ONE") == "alpha"

    # Null-ish inputs
    assert slug_registry.normalize(None) is None
    assert slug_registry.normalize("") is None
    assert slug_registry.normalize("   ") is None
    assert slug_registry.normalize("none") is None
    assert slug_registry.normalize("null") is None
    assert slug_registry.normalize("NULL") is None

    # Unknown -> None
    assert slug_registry.normalize("not-a-slug") is None


def test_active_slugs_filters_retired(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_vault("vault_with_retired", monkeypatch)
    assert slug_registry.canonical_slugs() == {"live-one", "old-closed", "candidate"}
    assert slug_registry.active_slugs() == {"live-one"}


def test_is_canonical(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_vault("vault", monkeypatch)
    assert slug_registry.is_canonical(None) is True
    assert slug_registry.is_canonical("alpha") is True
    assert slug_registry.is_canonical("not-a-slug") is False


def test_missing_env_var_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BAKER_VAULT_PATH", raising=False)
    slug_registry.reload()
    with pytest.raises(SlugRegistryError, match="BAKER_VAULT_PATH"):
        slug_registry.canonical_slugs()


def test_missing_file_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BAKER_VAULT_PATH", str(tmp_path))
    slug_registry.reload()
    with pytest.raises(SlugRegistryError, match="not found"):
        slug_registry.canonical_slugs()


def test_describe_and_aliases_for(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_vault("vault", monkeypatch)
    assert slug_registry.describe("alpha") == "Alpha test matter"
    assert set(slug_registry.aliases_for("alpha")) == {"al", "alpha one"}
    assert slug_registry.aliases_for("gamma") == []
    with pytest.raises(KeyError):
        slug_registry.describe("no-such-slug")
    with pytest.raises(KeyError):
        slug_registry.aliases_for("no-such-slug")
