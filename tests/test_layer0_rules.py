"""Tests for kbl.layer0_rules — mirrors test_slug_registry.py layout.

Each test monkeypatches KBL_LAYER0_RULES_PATH (or BAKER_VAULT_PATH) to a
fixture file and calls layer0_rules.reload() to drop module-level cache so
runs are isolated. Do NOT assert on production rule content — that lives
in baker-vault and is B3/Director-owned; loader tests exercise the loader
contract only.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from kbl import layer0_rules
from kbl.layer0_rules import Layer0Rule, Layer0Rules, Layer0RulesError

FIXTURES = Path(__file__).parent / "fixtures"
VALID = FIXTURES / "layer0_rules_valid.yml"
MALFORMED = FIXTURES / "layer0_rules_malformed.yml"


@pytest.fixture(autouse=True)
def _reset_cache():
    layer0_rules.reload()
    yield
    layer0_rules.reload()


@pytest.fixture
def _clean_env(monkeypatch: pytest.MonkeyPatch):
    """Start each test from a clean env — no stray KBL_LAYER0_RULES_PATH or
    BAKER_VAULT_PATH leaking in from the shell."""
    monkeypatch.delenv("KBL_LAYER0_RULES_PATH", raising=False)
    monkeypatch.delenv("BAKER_VAULT_PATH", raising=False)


def _write(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "layer0_rules.yml"
    p.write_text(content, encoding="utf-8")
    return p


# ------------------------------ happy path ------------------------------


def test_load_happy_path_via_explicit_path() -> None:
    rules = layer0_rules.load_layer0_rules(VALID)
    assert isinstance(rules, Layer0Rules)
    assert rules.version == 1
    assert isinstance(rules.version, int)
    assert len(rules.rules) == 2
    r0 = rules.rules[0]
    assert isinstance(r0, Layer0Rule)
    assert r0.name == "test_email_null_sender"
    assert r0.source == "email"
    assert r0.match == {"sender_domain_in": ["nytimes.com"]}
    assert "null" in r0.detail
    assert rules.source_path == VALID


def test_load_happy_path_via_env(
    monkeypatch: pytest.MonkeyPatch, _clean_env: None
) -> None:
    monkeypatch.setenv("KBL_LAYER0_RULES_PATH", str(VALID))
    rules = layer0_rules.load_layer0_rules()
    assert rules.version == 1
    assert len(rules.rules) == 2


# ------------------------------ fail-loud paths ------------------------------


def test_missing_file_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, _clean_env: None
) -> None:
    monkeypatch.setenv("KBL_LAYER0_RULES_PATH", str(tmp_path / "does_not_exist.yml"))
    with pytest.raises(Layer0RulesError, match="points at missing file"):
        layer0_rules.load_layer0_rules()


def test_missing_env_and_explicit_raises(_clean_env: None) -> None:
    with pytest.raises(Layer0RulesError, match="BAKER_VAULT_PATH"):
        layer0_rules.load_layer0_rules()


def test_malformed_yaml_raises() -> None:
    with pytest.raises(Layer0RulesError, match="failed to read"):
        layer0_rules.load_layer0_rules(MALFORMED)


def test_missing_version_key_raises(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        "rules:\n  - name: x\n    source: email\n    match: {}\n    detail: y\n",
    )
    with pytest.raises(Layer0RulesError, match="missing required top-level key `version`"):
        layer0_rules.load_layer0_rules(p)


def test_missing_rules_key_raises(tmp_path: Path) -> None:
    p = _write(tmp_path, 'version: 1\n')
    with pytest.raises(Layer0RulesError, match="missing required top-level key `rules`"):
        layer0_rules.load_layer0_rules(p)


def test_string_version_rejected(tmp_path: Path) -> None:
    """String versions (e.g., 'semver: 1.0.0') are rejected. Matches SLUGS-1
    convention + B3's Step 0 draft that uses integer `version: 1`."""
    p = _write(
        tmp_path,
        'version: "1.0.0"\nrules:\n  - name: x\n    source: email\n    '
        "match: {}\n    detail: y\n",
    )
    with pytest.raises(Layer0RulesError, match="`version` must be an int"):
        layer0_rules.load_layer0_rules(p)


def test_bool_version_rejected(tmp_path: Path) -> None:
    """Python's bool is a subclass of int — explicit guard prevents
    `version: true` from being accepted as `version: 1`."""
    p = _write(
        tmp_path,
        "version: true\nrules:\n  - name: x\n    source: email\n    "
        "match: {}\n    detail: y\n",
    )
    with pytest.raises(Layer0RulesError, match="`version` must be an int"):
        layer0_rules.load_layer0_rules(p)


def test_per_rule_missing_match_raises(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        'version: 1\nrules:\n  - name: x\n    source: email\n    detail: y\n',
    )
    with pytest.raises(Layer0RulesError, match=r"rules\[0\] missing required key\(s\).*match"):
        layer0_rules.load_layer0_rules(p)


def test_per_rule_match_not_mapping_raises(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        'version: 1\nrules:\n  - name: x\n    source: email\n    '
        'match: "not a dict"\n    detail: y\n',
    )
    with pytest.raises(Layer0RulesError, match="match must be a mapping"):
        layer0_rules.load_layer0_rules(p)


def test_duplicate_rule_name_raises(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        'version: 1\nrules:\n'
        '  - name: dup\n    source: email\n    match: {}\n    detail: a\n'
        '  - name: dup\n    source: whatsapp\n    match: {}\n    detail: b\n',
    )
    with pytest.raises(Layer0RulesError, match="duplicate rule name"):
        layer0_rules.load_layer0_rules(p)


# ------------------------------ cache semantics ------------------------------


def test_cache_reuse_across_calls(
    monkeypatch: pytest.MonkeyPatch, _clean_env: None
) -> None:
    monkeypatch.setenv("KBL_LAYER0_RULES_PATH", str(VALID))
    first = layer0_rules.load_layer0_rules()
    second = layer0_rules.load_layer0_rules()
    assert first is second, "default-path calls must return cached instance"


def test_reload_forces_reread(
    monkeypatch: pytest.MonkeyPatch, _clean_env: None
) -> None:
    monkeypatch.setenv("KBL_LAYER0_RULES_PATH", str(VALID))
    first = layer0_rules.load_layer0_rules()
    layer0_rules.reload()
    second = layer0_rules.load_layer0_rules()
    assert first is not second, "reload() must produce a fresh object"
    # Content still equal — same fixture file
    assert first.version == second.version
    assert len(first.rules) == len(second.rules)


def test_explicit_path_bypasses_cache(
    monkeypatch: pytest.MonkeyPatch, _clean_env: None
) -> None:
    """Explicit-path calls must never populate or serve from the cache, so
    that test and ad-hoc paths can't mutate production-path cache state."""
    monkeypatch.setenv("KBL_LAYER0_RULES_PATH", str(VALID))
    cached = layer0_rules.load_layer0_rules()          # populates cache via env
    explicit = layer0_rules.load_layer0_rules(VALID)   # same file, explicit path
    assert cached is not explicit, "explicit path must return fresh object"
    # But subsequent default-path call still returns the original cached one
    cached_again = layer0_rules.load_layer0_rules()
    assert cached is cached_again
