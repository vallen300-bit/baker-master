"""WIKI_LINT_1 — check 4 one_way_cross_ref."""
from __future__ import annotations

from kbl.lint_checks import one_way_cross_ref as M
from kbl.lint_checks._common import Severity
from tests.fixtures.wiki_lint import build_fixture_vault


def test_one_way_edge_flagged(tmp_path):
    """nested-good links to nested-missing (no hub, no frontmatter back-edge)
    so the edge is one-way — must be flagged."""
    vault = build_fixture_vault(tmp_path)
    # Append a new outbound link from nested-good to nested-missing
    idx = vault / "wiki/matters/nested-good/_index.md"
    idx.write_text(idx.read_text("utf-8") + "\nAlso: [[matters/nested-missing]].\n", encoding="utf-8")
    hits = M.run(vault, {})
    msgs = [(h.path, h.message) for h in hits]
    assert any("`nested-good`" in m and "`nested-missing`" in m for _p, m in msgs), msgs


def test_reciprocal_edge_not_flagged(tmp_path):
    """movie-x ↔ movie-sub is reciprocal — neither direction flagged."""
    vault = build_fixture_vault(tmp_path)
    hits = M.run(vault, {})
    pairs = [
        (h.message)
        for h in hits
    ]
    bad = [p for p in pairs if "movie-sub" in p and "movie-x" in p]
    assert not bad, f"unexpected one-way for movie-x/movie-sub: {bad}"


def test_severity_warn(tmp_path):
    vault = build_fixture_vault(tmp_path)
    hits = M.run(vault, {})
    assert all(h.severity is Severity.WARN for h in hits)


def test_no_matters_no_hits(tmp_path):
    (tmp_path / "baker-vault" / "wiki").mkdir(parents=True)
    assert M.run(tmp_path / "baker-vault", {}) == []


def test_frontmatter_related_matters_creates_edge(tmp_path):
    """flat-old's frontmatter declares related_matters: [nested-good]; the
    nested-good _index.md links back to flat-old, so the edge IS reciprocal —
    must NOT be flagged."""
    vault = build_fixture_vault(tmp_path)
    hits = M.run(vault, {})
    bad = [h for h in hits if "`flat-old`" in h.message and "`nested-good`" in h.message]
    assert not bad, "flat-old↔nested-good edge is reciprocal (frontmatter back-edge)"
