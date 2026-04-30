"""Tests for CORTEX_BOOTSTRAP_MATTER_1: entity-row append generator."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "bootstrap_entities.py"

if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts import bootstrap_entities as boot  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_vault(tmp_path: Path, *, version: int = 5,
                existing: list[dict] | None = None) -> Path:
    """Build a tmp baker-vault with entities.yml at the given version."""
    vault = tmp_path / "vault"
    vault.mkdir(parents=True, exist_ok=True)
    entities = existing if existing is not None else [
        {"slug": "brisen-capital-sa", "status": "active",
         "description": "Brisen Capital SA — Geneva holding.",
         "aliases": ["bcsa"]},
    ]
    (vault / "entities.yml").write_text(
        yaml.safe_dump({
            "version": version,
            "updated_at": "2026-04-23",
            "entities": entities,
        }),
        encoding="utf-8",
    )
    return vault


def _write_batch(tmp_path: Path, rows: list[dict], *, name: str = "batch.yml") -> Path:
    p = tmp_path / name
    p.write_text(yaml.safe_dump({"entities": rows}), encoding="utf-8")
    return p


def _valid_row(slug: str = "new-entity") -> dict:
    return {
        "slug": slug,
        "status": "active",
        "description": "Sufficiently long description for validation.",
        "aliases": [],
    }


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_dry_run_validates_and_prints_intent(tmp_path, capsys):
    vault = _make_vault(tmp_path, version=5)
    batch = _write_batch(tmp_path, [_valid_row("alpha"), _valid_row("beta")])
    rc = boot.main([
        "--input", str(batch),
        "--vault-root", str(vault),
        "--out-root", str(tmp_path / "out"),
        "--today", "2026-04-30",
        "--dry-run",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "[DRY-RUN]" in out
    assert "5 -> 6" in out
    assert "alpha" in out and "beta" in out
    # Nothing written.
    assert not (tmp_path / "out").exists() or not list((tmp_path / "out").iterdir())


def test_real_run_stages_batch_with_version_bump(tmp_path):
    vault = _make_vault(tmp_path, version=5)
    batch = _write_batch(tmp_path, [_valid_row("gamma")])
    out = tmp_path / "out"
    rc = boot.main([
        "--input", str(batch),
        "--vault-root", str(vault),
        "--out-root", str(out),
        "--today", "2026-04-30",
    ])
    assert rc == 0
    staged = list(out.glob("entities.yml.append-batch-*.yml"))
    assert len(staged) == 1
    text = staged[0].read_text()
    assert "version: 6" in text
    assert "gamma" in text
    # Header carries Mac Mini merge instructions.
    assert "Mac Mini merge instructions" in text
    assert "5 ->" in text or "5 to 6" in text or "version == 5" in text


def test_dry_run_bypasses_out_root_existence(tmp_path, capsys):
    """--dry-run must not require out_root to exist."""
    vault = _make_vault(tmp_path, version=1)
    batch = _write_batch(tmp_path, [_valid_row("solo")])
    rc = boot.main([
        "--input", str(batch),
        "--vault-root", str(vault),
        "--out-root", str(tmp_path / "deep" / "deeper" / "outdir"),
        "--dry-run",
    ])
    assert rc == 0


# ---------------------------------------------------------------------------
# Validation — negative cases
# ---------------------------------------------------------------------------


def test_rejects_duplicate_slug_against_canonical(tmp_path, capsys):
    vault = _make_vault(tmp_path, version=2)  # already has brisen-capital-sa
    batch = _write_batch(tmp_path, [_valid_row("brisen-capital-sa")])
    rc = boot.main([
        "--input", str(batch),
        "--vault-root", str(vault),
        "--out-root", str(tmp_path / "out"),
    ])
    assert rc == 2
    assert "already in entities.yml" in capsys.readouterr().err


def test_rejects_duplicate_slug_against_alias(tmp_path, capsys):
    """Alias collision is also rejected (aliases hold canonical-equivalent space)."""
    vault = _make_vault(tmp_path, version=2)  # alias 'bcsa' present
    batch = _write_batch(tmp_path, [_valid_row("bcsa")])
    rc = boot.main([
        "--input", str(batch),
        "--vault-root", str(vault),
        "--out-root", str(tmp_path / "out"),
    ])
    assert rc == 2
    assert "already in entities.yml" in capsys.readouterr().err


def test_rejects_intra_batch_duplicate(tmp_path, capsys):
    vault = _make_vault(tmp_path, version=1)
    batch = _write_batch(tmp_path, [_valid_row("delta"), _valid_row("delta")])
    rc = boot.main([
        "--input", str(batch),
        "--vault-root", str(vault),
        "--out-root", str(tmp_path / "out"),
    ])
    assert rc == 2
    assert "duplicated within this batch" in capsys.readouterr().err


def test_rejects_bad_status_enum(tmp_path, capsys):
    vault = _make_vault(tmp_path, version=1)
    row = _valid_row("epsilon")
    row["status"] = "deprecated"  # not in enum
    batch = _write_batch(tmp_path, [row])
    rc = boot.main([
        "--input", str(batch),
        "--vault-root", str(vault),
        "--out-root", str(tmp_path / "out"),
    ])
    assert rc == 2
    assert "status" in capsys.readouterr().err


def test_rejects_short_description(tmp_path, capsys):
    vault = _make_vault(tmp_path, version=1)
    row = _valid_row("zeta")
    row["description"] = "tooshort"  # < 10 chars
    batch = _write_batch(tmp_path, [row])
    rc = boot.main([
        "--input", str(batch),
        "--vault-root", str(vault),
        "--out-root", str(tmp_path / "out"),
    ])
    assert rc == 2
    assert "description" in capsys.readouterr().err


def test_rejects_non_kebab_slug(tmp_path, capsys):
    vault = _make_vault(tmp_path, version=1)
    row = _valid_row("Bad_Slug")
    batch = _write_batch(tmp_path, [row])
    rc = boot.main([
        "--input", str(batch),
        "--vault-root", str(vault),
        "--out-root", str(tmp_path / "out"),
    ])
    assert rc == 2
    assert "kebab-case" in capsys.readouterr().err


def test_rejects_alias_collision_with_existing_canonical(tmp_path, capsys):
    """A new entity claiming an alias that's already a canonical slug fails."""
    vault = _make_vault(tmp_path, version=1)
    row = _valid_row("eta")
    row["aliases"] = ["brisen-capital-sa"]  # canonical of existing
    batch = _write_batch(tmp_path, [row])
    rc = boot.main([
        "--input", str(batch),
        "--vault-root", str(vault),
        "--out-root", str(tmp_path / "out"),
    ])
    assert rc == 2
    assert "collides" in capsys.readouterr().err


def test_rejects_missing_input(tmp_path, capsys):
    vault = _make_vault(tmp_path, version=1)
    rc = boot.main([
        "--input", str(tmp_path / "nope.yml"),
        "--vault-root", str(vault),
        "--out-root", str(tmp_path / "out"),
    ])
    assert rc == 2
    assert "not found" in capsys.readouterr().err


def test_rejects_empty_batch(tmp_path, capsys):
    vault = _make_vault(tmp_path, version=1)
    batch = tmp_path / "batch.yml"
    batch.write_text(yaml.safe_dump({"entities": []}), encoding="utf-8")
    rc = boot.main([
        "--input", str(batch),
        "--vault-root", str(vault),
        "--out-root", str(tmp_path / "out"),
    ])
    assert rc == 2
    assert "non-empty 'entities' list" in capsys.readouterr().err


def test_rejects_missing_entities_yml(tmp_path, capsys):
    vault = tmp_path / "novault"
    vault.mkdir()  # no entities.yml inside
    batch = _write_batch(tmp_path, [_valid_row("theta")])
    rc = boot.main([
        "--input", str(batch),
        "--vault-root", str(vault),
        "--out-root", str(tmp_path / "out"),
    ])
    assert rc == 2
    assert "entities.yml not found" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Idempotency — re-running same batch after merge fails fast
# ---------------------------------------------------------------------------


def test_idempotency_re_run_after_merge_fails(tmp_path, capsys):
    """After a successful stage-and-merge, re-running with the same input
    must hit the duplicate-slug rejection.
    """
    # Step 1: stage batch with new entity 'iota'.
    vault = _make_vault(tmp_path, version=5)
    batch = _write_batch(tmp_path, [_valid_row("iota")])
    out = tmp_path / "out"
    rc = boot.main([
        "--input", str(batch),
        "--vault-root", str(vault),
        "--out-root", str(out),
    ])
    assert rc == 0
    # Step 2: simulate Mac Mini merge — append to entities.yml.
    new_vault = _make_vault(
        tmp_path / "post-merge",
        version=6,
        existing=[
            {"slug": "brisen-capital-sa", "status": "active",
             "description": "Brisen Capital SA — Geneva holding.",
             "aliases": ["bcsa"]},
            {"slug": "iota", "status": "active",
             "description": "Sufficiently long description for validation.",
             "aliases": []},
        ],
    )
    # Step 3: re-run same batch against post-merge vault → must fail.
    rc = boot.main([
        "--input", str(batch),
        "--vault-root", str(new_vault),
        "--out-root", str(out),
    ])
    assert rc == 2
    assert "already in entities.yml" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# CHANDA #9 — must not write directly to baker-vault
# ---------------------------------------------------------------------------


def test_no_db_or_vault_writes_in_script_text():
    src = SCRIPT.read_text()
    for verb in ("INSERT ", "UPDATE ", "DELETE "):
        assert verb not in src.upper().replace("CO-AUTHORED-BY", ""), f"{verb} found"
    # No direct writes to baker-vault path components.
    assert "baker-vault/entities.yml" not in src or "Mac Mini" in src
