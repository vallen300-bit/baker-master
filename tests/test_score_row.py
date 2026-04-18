"""Tests for scripts/run_kbl_eval.py::score_row — `unknown_non_canonical` guard.

The registry tests (test_slug_registry.py) verify that normalize() returns None
for unknown inputs. This test verifies that the RUNNER-side guard in score_row
correctly rejects a model output that is a non-empty, non-null-ish string but
fails to normalize to any canonical slug — i.e., the model emitted a generic
category like "hospitality" instead of a valid slug.

Without this guard, `out_matter == label_pm` would be `None == None → True`
when both sides normalize to None, spuriously scoring the model correct even
when the model emitted garbage. The guard flips those False.

Covers B2's trace table in briefs/_reports/B2_slugs1_review_20260417.md §3 S1.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
FIXTURES = Path(__file__).parent / "fixtures"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from kbl import slug_registry  # noqa: E402
import run_kbl_eval  # noqa: E402


@pytest.fixture(autouse=True)
def _use_fixture_vault(monkeypatch: pytest.MonkeyPatch) -> None:
    """Point slug_registry at the 3-slug fixture vault (alpha/beta/gamma)
    so tests don't depend on the production vault's 19-slug list."""
    monkeypatch.setenv("BAKER_VAULT_PATH", str(FIXTURES / "vault"))
    slug_registry.reload()
    yield
    slug_registry.reload()


def _run(
    *,
    label_matter,
    out_matter_raw,
    label_vedana="opportunity",
    out_vedana="opportunity",
    label_pass=True,
    out_score=50,
    json_ok=True,
) -> dict:
    """Thin wrapper — only the fields under test matter; fill the rest sanely."""
    label = {
        "signal_id": "test-1",
        "source": "fixture",
        "vedana_expected": label_vedana,
        "primary_matter_expected": label_matter,
        "triage_threshold_pass_expected": label_pass,
    }
    parsed = {
        "vedana": out_vedana,
        "matter": out_matter_raw,
        "triage_score": out_score,
    }
    return run_kbl_eval.score_row(label, parsed, json_ok)


# -- B2 trace table, adapted to fixture vault (alpha plays Hagenauer's role) --


def test_non_canonical_string_vs_none_label_is_false() -> None:
    """Model emits 'hospitality' (non-canonical), label is None. Guard MUST fire.

    Pre-registry semantic preserved: normalize returns None for 'hospitality',
    but the guard prevents that None from spuriously equalling label=None.
    """
    result = _run(out_matter_raw="hospitality", label_matter=None)
    assert result["matter_ok"] is False


def test_canonical_alias_vs_none_label_is_false() -> None:
    """Model emits valid alias ('al' → 'alpha'), label is None. Normal
    disagreement — not guard-related, but verifies the alias path still works.
    """
    result = _run(out_matter_raw="al", label_matter=None)
    assert result["matter_ok"] is False


def test_canonical_alias_matches_canonical_label_is_true() -> None:
    """Model emits alias with whitespace+case variation, label is canonical.
    Registry normalization must collapse both to the same key.
    """
    result = _run(out_matter_raw="  ALPHA  ", label_matter="alpha")
    assert result["matter_ok"] is True


def test_both_none_is_true() -> None:
    """Model correctly returned JSON null, label is None. Legitimate match."""
    result = _run(out_matter_raw=None, label_matter=None)
    assert result["matter_ok"] is True


def test_string_none_is_treated_as_null_and_matches_none_label() -> None:
    """Model returned the string 'none'/'null' instead of JSON null. The guard's
    null-ish set lets these through as legitimate None — they score True
    against a None label (don't trigger the non-canonical guard).
    """
    for variant in ("none", "null", "NONE", "Null", "   "):
        result = _run(out_matter_raw=variant, label_matter=None)
        assert result["matter_ok"] is True, f"variant={variant!r} should match None"


def test_json_ko_forces_matter_ok_false() -> None:
    """Regression guard: if json_ok=False, matter_ok is always False regardless
    of semantic match. Prevents the refactored score_row from leaking True on
    JSON-parse failure.
    """
    result = _run(out_matter_raw="alpha", label_matter="alpha", json_ok=False)
    assert result["matter_ok"] is False
