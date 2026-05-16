"""BRIEF_AO_PM_READ_CURATED_WIKI_1 tests — kbl.curated_wiki_reader + orchestrator integration.

Pure-unit (no DB, no anthropic). Each test sets BAKER_VAULT_PATH to a tmp_path
and builds the minimal wiki/matters/<slug>/curated/ layout. Slug allow-list is
provided by stubbing kbl.slug_registry so we don't depend on the real slugs.yml
during the test (which would couple test stability to vault state).
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest


# ─── Setup helpers ───

def _make_vault(tmp_path: Path, slug: str, files: dict[str, str]) -> Path:
    """Build wiki/matters/<slug>/curated/ with the given filename -> body map."""
    curated = tmp_path / "wiki" / "matters" / slug / "curated"
    curated.mkdir(parents=True, exist_ok=True)
    for fname, body in files.items():
        (curated / fname).write_text(body, encoding="utf-8")
    return tmp_path


@pytest.fixture
def vault(tmp_path, monkeypatch):
    monkeypatch.setenv("BAKER_VAULT_PATH", str(tmp_path))
    return tmp_path


@pytest.fixture(autouse=True)
def stub_slug_registry(monkeypatch):
    """Replace slug_registry.normalize with a fixed allow-list for test stability."""
    import kbl.slug_registry as sr
    allow = {
        "capital-call", "oskolkov", "hagenauer-rg7", "aukera", "ao",
        "mo-vie-am",
    }
    monkeypatch.setattr(sr, "normalize", lambda x: x if isinstance(x, str) and x in allow else None)


# ─── Slug validation ───

def test_rejects_empty_slug():
    from kbl.curated_wiki_reader import read_curated, CuratedWikiError
    with pytest.raises(CuratedWikiError):
        read_curated("")


def test_rejects_path_traversal_slug():
    from kbl.curated_wiki_reader import read_curated, CuratedWikiError
    with pytest.raises(CuratedWikiError):
        read_curated("../../etc/passwd")


def test_rejects_slug_with_slash():
    from kbl.curated_wiki_reader import read_curated, CuratedWikiError
    with pytest.raises(CuratedWikiError):
        read_curated("foo/bar")


def test_rejects_uppercase_slug():
    from kbl.curated_wiki_reader import read_curated, CuratedWikiError
    with pytest.raises(CuratedWikiError):
        read_curated("Capital-Call")


def test_rejects_unknown_slug(vault):
    from kbl.curated_wiki_reader import read_curated, CuratedWikiError
    # Passes regex but not on the (stubbed) allow-list
    with pytest.raises(CuratedWikiError):
        read_curated("bogus-slug-xyz")


def test_rejects_unsafe_filename(vault):
    from kbl.curated_wiki_reader import read_curated, CuratedWikiError
    with pytest.raises(CuratedWikiError):
        read_curated("capital-call", files=("../escape.md",))


# ─── Vault env ───

def test_raises_when_vault_env_unset(monkeypatch):
    from kbl.curated_wiki_reader import read_curated, CuratedWikiError
    monkeypatch.delenv("BAKER_VAULT_PATH", raising=False)
    with pytest.raises(CuratedWikiError):
        read_curated("capital-call")


# ─── Happy path ───

def test_reads_curated_files(vault):
    from kbl.curated_wiki_reader import read_curated
    _make_vault(vault, "capital-call", {
        "00_overview.md": "---\nlast_curated_at: 2026-04-30\n---\n# Overview body",
        "02_money.md": "---\nlast_curated_at: 2026-05-01-Q4-Q10-cascade\n---\nDrawdown #1 RECEIVED",
    })
    out = read_curated("capital-call")
    assert len(out) == 2
    assert out[0].path == "wiki/matters/capital-call/curated/00_overview.md"
    assert out[0].last_curated_at == "2026-04-30"
    assert "Overview body" in out[0].body
    assert out[1].last_curated_at == "2026-05-01-Q4-Q10-cascade"
    assert "RECEIVED" in out[1].body


def test_missing_files_skipped_not_errored(vault):
    """Acceptance #2: graceful no-op when curated dir or files missing."""
    from kbl.curated_wiki_reader import read_curated
    # Only 02_money.md exists
    _make_vault(vault, "aukera", {"02_money.md": "money body"})
    out = read_curated("aukera")
    assert len(out) == 1
    assert out[0].path.endswith("02_money.md")


def test_missing_dir_returns_empty(vault):
    from kbl.curated_wiki_reader import read_curated
    # No vault layout created at all
    out = read_curated("oskolkov")
    assert out == []


def test_char_cap_truncates_with_marker(vault):
    from kbl.curated_wiki_reader import read_curated
    big = "x" * 20000
    _make_vault(vault, "capital-call", {"00_overview.md": big})
    out = read_curated("capital-call", char_cap=100)
    assert out[0].truncated is True
    assert "truncated" in out[0].body
    assert len(out[0].body) < 500  # cap + marker


def test_zero_char_cap_disables_truncation(vault):
    from kbl.curated_wiki_reader import read_curated
    big = "x" * 20000
    _make_vault(vault, "capital-call", {"00_overview.md": big})
    out = read_curated("capital-call", char_cap=0)
    assert out[0].truncated is False
    assert len(out[0].body) == 20000


def test_frontmatter_without_last_curated_returns_none(vault):
    from kbl.curated_wiki_reader import read_curated
    _make_vault(vault, "capital-call", {
        "00_overview.md": "---\nmatter: capital-call\n---\nbody",
    })
    out = read_curated("capital-call")
    assert out[0].last_curated_at is None


def test_no_frontmatter_returns_none(vault):
    from kbl.curated_wiki_reader import read_curated
    _make_vault(vault, "capital-call", {"00_overview.md": "no frontmatter just body"})
    out = read_curated("capital-call")
    assert out[0].last_curated_at is None


# ─── Path-traversal defense (symlink case) ───

def test_symlink_escape_rejected(vault, tmp_path):
    """Symlink inside curated/ pointing outside vault must not be followed."""
    from kbl.curated_wiki_reader import read_curated
    # Build legit dir
    _make_vault(vault, "capital-call", {"00_overview.md": "legit"})
    # Place a sibling target outside vault
    outside = tmp_path.parent / "outside_vault_secret.md"
    outside.write_text("SECRET")
    # Replace the curated DIRECTORY with a symlink to a dir containing a file
    # we should not be able to traverse to. Easier check: symlink the matter
    # dir itself to point outside the vault.
    matter_dir = vault / "wiki" / "matters" / "oskolkov"
    matter_dir.parent.mkdir(parents=True, exist_ok=True)
    try:
        matter_dir.symlink_to(tmp_path.parent / "outside_vault_dir", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unsupported in this environment")
    # The resolved path of <vault>/wiki/matters/oskolkov/curated escapes
    # <vault>/wiki/matters/ — reader must reject.
    from kbl.curated_wiki_reader import CuratedWikiError
    with pytest.raises(CuratedWikiError):
        read_curated("oskolkov")


def test_file_level_symlink_escape_rejected(vault, tmp_path):
    """File-level symlink INSIDE a legit curated/ dir pointing outside vault
    must be skipped (not followed). Closes the file-level containment gap
    that AH1 /security-review flagged on PR #210.
    """
    from kbl.curated_wiki_reader import read_curated, format_for_prompt
    # Build legit matter dir + one legit file.
    _make_vault(vault, "capital-call", {"00_overview.md": "legit overview"})
    curated_dir = vault / "wiki" / "matters" / "capital-call" / "curated"

    # Create a secret file OUTSIDE the vault.
    secret = tmp_path.parent / "outside_vault_file_secret.md"
    secret.write_text("SECRET_OUTSIDE_VAULT")

    # Place a file-level symlink inside curated/ pointing at the outside file.
    link = curated_dir / "02_money.md"
    try:
        link.symlink_to(secret)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unsupported in this environment")

    # 02_money.md is a symlink that escapes vault — reader must skip it,
    # NOT raise (per defense-in-depth: log + continue, like the unsafe
    # is_file() miss). 00_overview.md still readable.
    out = read_curated("capital-call")
    assert len(out) == 1
    assert out[0].path.endswith("00_overview.md")
    assert "SECRET_OUTSIDE_VAULT" not in out[0].body

    # format_for_prompt must not leak the escaping symlink's content either.
    block = format_for_prompt("capital-call")
    assert "SECRET_OUTSIDE_VAULT" not in block
    assert "00_overview.md" in block


def test_rejects_dot_only_filename(vault):
    """LOW-1: filename regex must reject leading-dot names like '.md' / '..md'."""
    from kbl.curated_wiki_reader import read_curated, CuratedWikiError
    _make_vault(vault, "capital-call", {"00_overview.md": "x"})
    with pytest.raises(CuratedWikiError):
        read_curated("capital-call", files=(".md",))
    with pytest.raises(CuratedWikiError):
        read_curated("capital-call", files=("..md",))


# ─── format_for_prompt convenience wrapper ───

def test_format_for_prompt_empty_on_no_files(vault):
    from kbl.curated_wiki_reader import format_for_prompt
    assert format_for_prompt("oskolkov") == ""


def test_format_for_prompt_emits_labels(vault):
    from kbl.curated_wiki_reader import format_for_prompt
    _make_vault(vault, "capital-call", {
        "02_money.md": "---\nlast_curated_at: 2026-05-01\n---\nDrawdown #1 RECEIVED 24-28 Apr",
    })
    block = format_for_prompt("capital-call")
    assert "[CURATED WIKI: wiki/matters/capital-call/curated/02_money.md" in block
    assert "last_curated_at: 2026-05-01" in block
    assert "Drawdown #1 RECEIVED" in block


def test_format_for_prompt_swallows_invalid_slug(vault):
    """format_for_prompt is the safe wrapper for prompt-builder callers — never
    raise; log + return empty so the runner can `if block:` cleanly."""
    from kbl.curated_wiki_reader import format_for_prompt
    assert format_for_prompt("BOGUS_SLUG_/etc/passwd") == ""


# ─── Capability runner integration ───

def test_load_curated_wiki_context_iterates_pm_registry_matters(vault, monkeypatch):
    """Acceptance #4: assert wiki content appears in the runner's PM context block."""
    from kbl.curated_wiki_reader import format_for_prompt as real_fmt  # noqa: F401
    _make_vault(vault, "capital-call", {
        "02_money.md": "---\nlast_curated_at: 2026-05-01\n---\nDrawdown #1 RECEIVED 24-28 Apr 2026",
    })
    _make_vault(vault, "oskolkov", {
        "00_overview.md": "---\nlast_curated_at: 2026-04-30\n---\nAO overview body",
    })

    # Instantiate without running __init__ (avoids anthropic client construction)
    from orchestrator.capability_runner import CapabilityRunner
    runner = CapabilityRunner.__new__(CapabilityRunner)

    block = runner._load_curated_wiki_context("ao_pm")
    assert block
    assert "Drawdown #1 RECEIVED 24-28 Apr 2026" in block
    assert "AO overview body" in block
    # Conflict-resolution directive belongs in the prompt-builder, not the
    # loader — but loader must emit source-labelled blocks so the directive
    # can reference them by path.
    assert "wiki/matters/capital-call/curated/02_money.md" in block
    assert "wiki/matters/oskolkov/curated/00_overview.md" in block


def test_load_curated_wiki_context_unknown_pm_returns_empty():
    from orchestrator.capability_runner import CapabilityRunner
    runner = CapabilityRunner.__new__(CapabilityRunner)
    assert runner._load_curated_wiki_context("__not_a_pm__") == ""


def test_load_curated_wiki_context_pm_without_curated_config_returns_empty(monkeypatch):
    """A PM with no curated_wiki_matters key must be a no-op (graceful)."""
    from orchestrator.capability_runner import CapabilityRunner, PM_REGISTRY
    runner = CapabilityRunner.__new__(CapabilityRunner)
    # movie_am does not have curated_wiki_matters set by this brief
    assert "curated_wiki_matters" not in PM_REGISTRY["movie_am"]
    assert runner._load_curated_wiki_context("movie_am") == ""
