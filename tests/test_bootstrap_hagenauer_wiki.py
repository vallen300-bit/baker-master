"""Tests for HAGENAUER_WIKI_BOOTSTRAP_1: matter-shape skeleton generator."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "bootstrap_hagenauer_wiki.py"

# Add repo root for direct module import.
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts import bootstrap_hagenauer_wiki as boot  # noqa: E402
from kbl.ingest_endpoint import validate_frontmatter  # noqa: E402


def _make_fake_vault(root: Path) -> Path:
    """Build a minimal baker-vault layout with two reference matter dirs.

    Intersection (required) by construction:
      _index.md, _overview.md, agenda.md, gold.md, red-flags.md
      subdirs: interactions/, sub-matters/
    Optional (in only one):
      psychology.md (oskolkov), kpi-framework.md (movie)
      subdirs: cards/ (movie)
    """
    matters = root / "wiki" / "matters"
    osk = matters / "oskolkov"
    mov = matters / "movie"
    osk.mkdir(parents=True)
    mov.mkdir(parents=True)
    shared = ["_index.md", "_overview.md", "agenda.md", "gold.md", "red-flags.md"]
    for fn in shared:
        (osk / fn).write_text(f"# {fn}", encoding="utf-8")
        (mov / fn).write_text(f"# {fn}", encoding="utf-8")
    (osk / "psychology.md").write_text("# psy", encoding="utf-8")
    (mov / "kpi-framework.md").write_text("# kpi", encoding="utf-8")
    for sd in ("interactions", "sub-matters"):
        (osk / sd).mkdir()
        (mov / sd).mkdir()
        (osk / sd / "_keep.md").write_text("# keep", encoding="utf-8")
        (mov / sd / "_keep.md").write_text("# keep", encoding="utf-8")
    (mov / "cards").mkdir()
    (mov / "cards" / "_keep.md").write_text("# keep", encoding="utf-8")
    return root


def test_discover_matter_shape_intersection(tmp_path):
    """Intersection across the two reference matters yields the required set."""
    vault = _make_fake_vault(tmp_path / "vault")
    shape = boot.discover_matter_shape(vault)
    assert set(shape["required_files"]) == {
        "_index.md", "_overview.md", "agenda.md", "gold.md", "red-flags.md",
    }
    assert set(shape["required_subdirs"]) == {"interactions", "sub-matters"}
    assert "psychology.md" in shape["optional_files"]
    assert "kpi-framework.md" in shape["optional_files"]
    assert "cards" in shape["optional_subdirs"]


def test_discover_raises_on_missing_reference_dir(tmp_path):
    """Fail loud if either reference matter dir is absent."""
    (tmp_path / "wiki" / "matters" / "oskolkov").mkdir(parents=True)
    # 'movie' deliberately missing.
    with pytest.raises(FileNotFoundError):
        boot.discover_matter_shape(tmp_path)


def test_filename_to_slug_handles_underscore_prefix():
    """Leading underscores stripped; underscores converted to hyphens."""
    assert boot.filename_to_slug("_overview.md") == "hagenauer-rg7-overview"
    assert boot.filename_to_slug("financial-facts.md") == "hagenauer-rg7-financial-facts"
    assert boot.filename_to_slug("ao_pm_lessons.md") == "hagenauer-rg7-ao-pm-lessons"


def test_emitted_frontmatter_passes_validation(tmp_path):
    """Every emitted skeleton's frontmatter survives kbl.validate_frontmatter."""
    vault = _make_fake_vault(tmp_path / "vault")
    out = tmp_path / "out"
    rc = boot.main([
        "--vault-root", str(vault),
        "--out-root", str(out),
        "--today", "2026-04-25",
    ])
    assert rc == 0
    md_files = list(out.rglob("*.md"))
    assert md_files, "no skeletons emitted"
    for f in md_files:
        text = f.read_text()
        fm = boot._extract_frontmatter(text)
        validate_frontmatter(fm)  # raises on schema drift
        assert boot.NEEDS_CONTENT_MARKER in text


def test_dry_run_emits_zero_files(tmp_path, capsys):
    """--dry-run lists targets but writes nothing."""
    vault = _make_fake_vault(tmp_path / "vault")
    out = tmp_path / "out"
    rc = boot.main([
        "--vault-root", str(vault),
        "--out-root", str(out),
        "--dry-run",
    ])
    assert rc == 0
    assert not out.exists() or not list(out.rglob("*.md"))
    captured = capsys.readouterr()
    assert "[DRY-RUN]" in captured.out
    assert "_overview.md" in captured.out


def test_default_overwrite_fails(tmp_path):
    """Re-run without --force exits 1 if any skeleton already exists."""
    vault = _make_fake_vault(tmp_path / "vault")
    out = tmp_path / "out"
    boot.main(["--vault-root", str(vault), "--out-root", str(out), "--today", "2026-04-25"])
    with pytest.raises(SystemExit) as exc:
        boot.main(["--vault-root", str(vault), "--out-root", str(out), "--today", "2026-04-25"])
    assert exc.value.code == 1


def test_force_overwrite_succeeds(tmp_path):
    """--force re-emits without raising and stamps the new --today."""
    vault = _make_fake_vault(tmp_path / "vault")
    out = tmp_path / "out"
    boot.main(["--vault-root", str(vault), "--out-root", str(out), "--today", "2026-04-25"])
    rc = boot.main([
        "--vault-root", str(vault),
        "--out-root", str(out),
        "--today", "2026-04-26",
        "--force",
    ])
    assert rc == 0
    fm = boot._extract_frontmatter((out / "_overview.md").read_text())
    assert fm["updated"] == "2026-04-26"


def test_minimum_files_emitted_against_real_vault(tmp_path):
    """Against the real baker-vault (if present) ≥9 files emit, per brief §Verif #2.

    Skipped if ~/baker-vault not present (CI / fresh clone).
    """
    real_vault = Path.home() / "baker-vault"
    if not (real_vault / "wiki" / "matters" / "oskolkov").is_dir():
        pytest.skip("real baker-vault unavailable")
    out = tmp_path / "out"
    rc = boot.main([
        "--vault-root", str(real_vault),
        "--out-root", str(out),
        "--today", "2026-04-26",
    ])
    assert rc == 0
    md_files = list(out.rglob("*.md"))
    assert len(md_files) >= 9, f"expected ≥9 emitted, got {len(md_files)}"


def test_script_runs_end_to_end_via_subprocess(tmp_path):
    """Script is invokable from shell with --dry-run on real vault (or skip)."""
    real_vault = Path.home() / "baker-vault"
    if not (real_vault / "wiki" / "matters" / "oskolkov").is_dir():
        pytest.skip("real baker-vault unavailable")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--dry-run",
         "--vault-root", str(real_vault),
         "--out-root", str(tmp_path / "out")],
        capture_output=True, text=True, cwd=str(REPO),
    )
    assert result.returncode == 0, result.stderr
    assert "[DRY-RUN]" in result.stdout


def test_no_baker_vault_writes_in_script_text():
    """Sanity: script source must not reference writes to baker-vault path."""
    src = SCRIPT.read_text()
    # Generation-only; no DB writes, no kbl.ingest_endpoint.ingest call.
    assert "ingest_endpoint.ingest(" not in src
    assert "ingest(" not in src or "validate_frontmatter" in src  # only validate import
    # No SQL writes (DDL drift check).
    for verb in ("INSERT ", "UPDATE ", "DELETE "):
        assert verb not in src.upper().replace("CO-AUTHORED-BY", ""), f"{verb} found"
