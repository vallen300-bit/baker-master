"""WIKI_LINT_1 — check 2 missing_required_files."""
from __future__ import annotations

from kbl.lint_checks import missing_required_files as M
from kbl.lint_checks._common import Severity
from tests.fixtures.wiki_lint import build_fixture_vault


def _by_path(hits):
    out: dict[str, list] = {}
    for h in hits:
        out.setdefault(h.path, []).append(h)
    return out


def test_flat_old_grandfathered_to_warn(tmp_path):
    vault = build_fixture_vault(tmp_path)
    hits = _by_path(M.run(vault, {}))
    assert "wiki/flat-old" in hits
    relevant = hits["wiki/flat-old"]
    assert all(h.severity is Severity.WARN for h in relevant)
    assert any("_links.md" in h.message for h in relevant)


def test_flat_new_post_cutoff_is_error(tmp_path):
    vault = build_fixture_vault(tmp_path)
    hits = _by_path(M.run(vault, {}))
    assert "wiki/flat-new" in hits
    flat_new = hits["wiki/flat-new"]
    assert any(h.severity is Severity.ERROR and "_links.md" in h.message for h in flat_new)


def test_nested_missing_two_errors(tmp_path):
    vault = build_fixture_vault(tmp_path)
    hits = _by_path(M.run(vault, {}))
    rel = "wiki/matters/nested-missing"
    assert rel in hits
    msgs = [h.message for h in hits[rel] if h.severity is Severity.ERROR]
    assert any("_index.md" in m for m in msgs)
    assert any("gold.md" in m for m in msgs)


def test_nested_good_no_hits(tmp_path):
    vault = build_fixture_vault(tmp_path)
    hits = _by_path(M.run(vault, {}))
    assert "wiki/matters/nested-good" not in hits
    assert "wiki/matters/movie-x" not in hits
    assert "wiki/matters/movie-x/sub-matters/movie-sub" not in hits


def test_orphan_flat_complete_no_hits(tmp_path):
    vault = build_fixture_vault(tmp_path)
    hits = _by_path(M.run(vault, {}))
    assert "wiki/orphan-flat" not in hits


def test_grandfather_cutoff_override(tmp_path):
    """If we move the cutoff later, flat-old becomes warn; if we move it
    earlier, flat-old becomes ERROR."""
    vault = build_fixture_vault(tmp_path)
    hits = _by_path(M.run(vault, {"grandfather_cutoff": "2026-01-01"}))
    flat_old = hits.get("wiki/flat-old", [])
    assert flat_old, "flat-old still missing _links.md"
    assert all(h.severity is Severity.ERROR for h in flat_old)
