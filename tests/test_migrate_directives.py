"""Tests for scripts.migrate_directives_for_existing_matters.

Brief: CORTEX_CONFIG_DIRECTIVES_SCHEMA_1 §3.3.

Mocks slugs.yml + verifies batch behavior. No DB.
"""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def import_module():
    """Import the script as a module — ``scripts/`` is not a package."""
    import importlib.util
    import sys

    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    path = repo_root / "scripts" / "migrate_directives_for_existing_matters.py"
    spec = importlib.util.spec_from_file_location("migrate_directives", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_slugs_yml(vault_root: Path, content: str) -> None:
    vault_root.mkdir(parents=True, exist_ok=True)
    (vault_root / "slugs.yml").write_text(content, encoding="utf-8")


def test_load_filters_retired(tmp_path: Path, import_module):
    vault_root = tmp_path / "vault"
    _write_slugs_yml(
        vault_root,
        """
matters:
  - {slug: active-one, status: active, description: "A1"}
  - {slug: retired-one, status: retired, description: "R1"}
  - {slug: dev-one, status: development, description: "D1"}
  - {slug: another-active, status: active, description: "A2"}
""",
    )
    matters = import_module.load_active_matters(vault_root)
    slugs = {m["slug"] for m in matters}
    assert "active-one" in slugs
    assert "another-active" in slugs
    assert "dev-one" in slugs
    assert "retired-one" not in slugs
    assert len(matters) == 3


def test_load_skips_malformed_rows(tmp_path: Path, import_module):
    vault_root = tmp_path / "vault"
    _write_slugs_yml(
        vault_root,
        """
matters:
  - {slug: good-one, status: active, description: "G"}
  - "stray-string-row"
  - {status: active, description: "no-slug"}
  - {slug: 42, status: active}
""",
    )
    matters = import_module.load_active_matters(vault_root)
    slugs = {m["slug"] for m in matters}
    assert slugs == {"good-one"}


def test_dry_run_writes_nothing(tmp_path: Path, import_module):
    vault_root = tmp_path / "vault"
    staging = tmp_path / "staging"
    _write_slugs_yml(
        vault_root,
        """
matters:
  - {slug: alpha, status: active, description: "Alpha"}
  - {slug: beta, status: active, description: "Beta"}
""",
    )

    rc = import_module.main(
        [
            "--dry-run",
            "--vault-root",
            str(vault_root),
            "--staging-root",
            str(staging),
        ]
    )
    assert rc == 0
    # No files should have been written under staging.
    assert not (staging / "alpha" / "curated" / "directives.md").exists()
    assert not (staging / "beta" / "curated" / "directives.md").exists()


def test_wet_run_creates_files_then_idempotent(tmp_path: Path, import_module):
    vault_root = tmp_path / "vault"
    staging = tmp_path / "staging"
    _write_slugs_yml(
        vault_root,
        """
matters:
  - {slug: gamma, status: active, description: "Gamma"}
  - {slug: delta, status: development, description: "Delta"}
  - {slug: zombie, status: retired, description: "Z"}
""",
    )

    rc = import_module.main(
        [
            "--vault-root",
            str(vault_root),
            "--staging-root",
            str(staging),
        ]
    )
    assert rc == 0
    assert (staging / "gamma" / "curated" / "directives.md").is_file()
    assert (staging / "delta" / "curated" / "directives.md").is_file()
    assert not (staging / "zombie").exists()

    # Re-run: idempotent — no overwrites, no errors.
    rc2 = import_module.main(
        [
            "--vault-root",
            str(vault_root),
            "--staging-root",
            str(staging),
        ]
    )
    assert rc2 == 0


def test_missing_slugs_yml_raises_systemexit(tmp_path: Path, import_module):
    vault_root = tmp_path / "vault-empty"
    vault_root.mkdir()
    with pytest.raises(SystemExit):
        import_module.load_active_matters(vault_root)
