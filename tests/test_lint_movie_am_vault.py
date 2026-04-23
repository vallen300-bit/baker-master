"""Ship gate for BRIEF_MOVIE_AM_RETROFIT_1 D5.

Covers:
  1. Module imports cleanly; lint `main()` is callable.
  2. Lint on a known-good vault snapshot produces zero wikilink / frontmatter
     violations (DB-dependent checks are no-ops without BAKER DB).
  3. Lint on a vault with an unresolved wikilink produces a flag.
  4. Scheduler file registers `movie_am_lint` with the expected cron + id.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _good_vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    m = root / "wiki" / "matters" / "movie"
    sub = m / "sub-matters"
    _write(m / "_index.md", _fm("Index", "index") + "See [[_overview]] and [[sub-matters/hma-compliance]].\n")
    _write(m / "_overview.md", _fm("Overview", "semantic") + "Overview.\n")
    _write(sub / "hma-compliance.md", _fm("HMA Compliance", "state") + "Stub.\n")
    return root


def _fm(title: str, _type: str) -> str:
    return (
        "---\n"
        f"title: {title}\n"
        "matter: movie\n"
        f"type: {_type}\n"
        "layer: 2\n"
        "last_audit: 2026-04-23\n"
        "owner: AI Head + Director\n"
        "---\n\n"
        f"# {title}\n\n"
    )


def test_module_imports():
    from scripts import lint_movie_am_vault  # noqa: F401
    from scripts.lint_movie_am_vault import main  # noqa: F401
    assert callable(main)


def test_lint_passes_on_good_vault(tmp_path, monkeypatch):
    root = _good_vault(tmp_path)
    monkeypatch.setenv("BAKER_VAULT_PATH", str(root))
    from scripts.lint_movie_am_vault import main
    main()
    report = (root / "wiki" / "matters" / "movie" / "_lint-report.md").read_text()
    assert "violation_count: 0" in report
    assert "All checks passed." in report


def test_lint_flags_broken_wikilink(tmp_path, monkeypatch):
    root = _good_vault(tmp_path)
    broken = root / "wiki" / "matters" / "movie" / "_index.md"
    broken.write_text(
        _fm("Index", "index") + "Link to [[this-does-not-exist]].\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("BAKER_VAULT_PATH", str(root))
    from scripts.lint_movie_am_vault import main
    main()
    report = (root / "wiki" / "matters" / "movie" / "_lint-report.md").read_text()
    assert "Broken wikilink" in report
    assert "this-does-not-exist" in report


def test_lint_flags_missing_frontmatter(tmp_path, monkeypatch):
    root = _good_vault(tmp_path)
    bad = root / "wiki" / "matters" / "movie" / "no-frontmatter.md"
    bad.write_text("# Just a header, no frontmatter\n", encoding="utf-8")
    monkeypatch.setenv("BAKER_VAULT_PATH", str(root))
    from scripts.lint_movie_am_vault import main
    main()
    report = (root / "wiki" / "matters" / "movie" / "_lint-report.md").read_text()
    assert "Missing frontmatter" in report


def test_scheduler_registers_movie_am_lint():
    """Static check: scheduler file references the MOVIE lint job."""
    src = Path("triggers/embedded_scheduler.py").read_text()
    assert "movie_am_lint" in src
    assert 'CronTrigger(day_of_week="sun", hour=6, minute=5, timezone="UTC")' in src
    assert "MOVIE_AM_LINT_ENABLED" in src
    assert "_run_movie_am_lint" in src
