"""WIKI_LINT_1 — check 1 retired_slug_reference."""
from __future__ import annotations

from kbl.lint_checks import retired_slug_reference as M
from kbl.lint_checks._common import Severity
from tests.fixtures.wiki_lint import build_fixture_vault


def _hit_paths(hits):
    return sorted({h.path for h in hits})


def test_no_retired_slugs_no_hits(tmp_path):
    vault = build_fixture_vault(tmp_path)
    hits = M.run(vault, {"retired_slugs": set()})
    assert hits == []


def test_retired_slug_in_wiki_link_is_error(tmp_path):
    vault = build_fixture_vault(tmp_path)
    hits = M.run(vault, {"retired_slugs": {"defunct"}})
    assert hits, "expected at least one hit"
    assert all(h.severity is Severity.ERROR for h in hits)
    paths = _hit_paths(hits)
    assert "wiki/matters/nested-good/_overview.md" in paths


def test_retired_slug_in_frontmatter_primary_matter(tmp_path):
    vault = build_fixture_vault(tmp_path)
    target = vault / "wiki/flat-new/extra.md"
    target.write_text(
        "---\nprimary_matter: defunct\n---\n# uses retired primary\n",
        encoding="utf-8",
    )
    hits = M.run(vault, {"retired_slugs": {"defunct"}})
    rel_hits = [h for h in hits if h.path.endswith("flat-new/extra.md")]
    assert rel_hits, "expected hit on flat-new/extra.md"
    assert any("primary_matter" in h.message for h in rel_hits)


def test_retired_slug_in_frontmatter_related_matters_list(tmp_path):
    vault = build_fixture_vault(tmp_path)
    target = vault / "wiki/flat-new/extra.md"
    target.write_text(
        "---\nprimary_matter: flat-new\nrelated_matters:\n  - defunct\n  - nested-good\n---\n# body\n",
        encoding="utf-8",
    )
    hits = M.run(vault, {"retired_slugs": {"defunct"}})
    rel_hits = [h for h in hits if h.path.endswith("flat-new/extra.md")]
    assert rel_hits
    assert any("related_matters" in h.message for h in rel_hits)


def test_retired_slug_path_component_flagged(tmp_path):
    vault = build_fixture_vault(tmp_path)
    bad_dir = vault / "wiki/defunct"
    bad_dir.mkdir()
    (bad_dir / "leftover.md").write_text("# leftover\n", encoding="utf-8")
    hits = M.run(vault, {"retired_slugs": {"defunct"}})
    paths = _hit_paths(hits)
    assert "wiki/defunct/leftover.md" in paths
    bad_hits = [h for h in hits if h.path == "wiki/defunct/leftover.md"]
    assert any("path contains retired slug" in h.message for h in bad_hits)


def test_no_retired_dict_returns_empty(tmp_path):
    vault = build_fixture_vault(tmp_path)
    assert M.run(vault, {}) == []


def test_missing_wiki_dir_returns_empty(tmp_path):
    # Vault root with no wiki/ — lint should no-op cleanly.
    (tmp_path / "baker-vault").mkdir()
    assert M.run(tmp_path / "baker-vault", {"retired_slugs": {"defunct"}}) == []
