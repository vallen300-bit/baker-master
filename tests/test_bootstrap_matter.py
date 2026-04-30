"""Tests for CORTEX_BOOTSTRAP_MATTER_1: generic matter scaffolding generator."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "bootstrap_matter.py"

if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts import bootstrap_matter as boot  # noqa: E402
from kbl.ingest_endpoint import validate_frontmatter  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _minimal_input() -> dict:
    """Smallest valid input that passes validate_input + emits cleanly."""
    return {
        "matter_slug": "test-matter",
        "matter_name": "Test Matter",
        "absorbed_from": "seed (test fixture)",
        "absorbed_by": "test",
        "authority_chain": "test ratification",
        "ratified_at": "2026-04-30",
        "entities": {
            "primary": ["test-primary"],
            "counterparties": ["test-cp"],
        },
        "trigger_patterns": [r"\b(test)\b"],
    }


def _write_input(tmp_path: Path, cfg: dict, *, name: str = "input.yml") -> Path:
    p = tmp_path / name
    p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return p


def _run_main(tmp_path: Path, cfg: dict, *, extra_args: list[str] | None = None) -> int:
    inp = _write_input(tmp_path, cfg)
    out = tmp_path / "out"
    args = [
        "--input", str(inp),
        "--out-root", str(out),
        "--vault-root", str(tmp_path / "no-vault"),
        "--today", "2026-04-30",
    ]
    if extra_args:
        args += extra_args
    return boot.main(args)


# ---------------------------------------------------------------------------
# Defaults + apply_defaults
# ---------------------------------------------------------------------------


def test_apply_defaults_fills_missing_fields():
    cfg = {"matter_slug": "x", "matter_name": "X"}
    merged = boot.apply_defaults(cfg)
    assert merged["autonomy_level"] == "recommend_wait"
    assert merged["specialist_cap_per_cycle"] == 5
    assert merged["counterparty_iteration_horizon"] == "infinite_repeated"
    assert merged["auto_trigger"] == {"severity_floor": "high", "confidence_floor": 0.8}


def test_apply_defaults_input_wins_on_collision():
    cfg = {
        "matter_slug": "x", "matter_name": "X",
        "autonomy_level": "auto_execute",
        "auto_trigger": {"severity_floor": "low"},
    }
    merged = boot.apply_defaults(cfg)
    assert merged["autonomy_level"] == "auto_execute"
    # auto_trigger field-level merge: input override + default fallback
    assert merged["auto_trigger"]["severity_floor"] == "low"
    assert merged["auto_trigger"]["confidence_floor"] == 0.8


# ---------------------------------------------------------------------------
# validate_input — happy path
# ---------------------------------------------------------------------------


def test_validate_input_accepts_minimal_valid_config(tmp_path):
    cfg = boot.apply_defaults(_minimal_input())
    boot.validate_input(cfg, vault_root=None)  # no raise


# ---------------------------------------------------------------------------
# validate_input — negative cases (≥5 per brief Verif #5)
# ---------------------------------------------------------------------------


def test_validate_input_rejects_missing_required_field(tmp_path):
    cfg = _minimal_input()
    del cfg["matter_slug"]
    cfg = boot.apply_defaults(cfg)
    with pytest.raises(boot.BootstrapError, match="missing required fields"):
        boot.validate_input(cfg, vault_root=None)


def test_validate_input_rejects_non_kebab_slug(tmp_path):
    cfg = _minimal_input()
    cfg["matter_slug"] = "Test_Matter"  # underscores + uppercase
    cfg = boot.apply_defaults(cfg)
    with pytest.raises(boot.BootstrapError, match="kebab-case"):
        boot.validate_input(cfg, vault_root=None)


def test_validate_input_rejects_invalid_regex(tmp_path):
    cfg = _minimal_input()
    cfg["trigger_patterns"] = ["[unclosed"]  # invalid regex
    cfg = boot.apply_defaults(cfg)
    with pytest.raises(boot.BootstrapError, match="regex .* invalid"):
        boot.validate_input(cfg, vault_root=None)


def test_validate_input_rejects_bad_autonomy_enum(tmp_path):
    cfg = _minimal_input()
    cfg["autonomy_level"] = "bogus_mode"
    cfg = boot.apply_defaults(cfg)
    with pytest.raises(boot.BootstrapError, match="autonomy_level"):
        boot.validate_input(cfg, vault_root=None)


def test_validate_input_rejects_bad_horizon_enum(tmp_path):
    cfg = _minimal_input()
    cfg["counterparty_iteration_horizon"] = "forever"
    cfg = boot.apply_defaults(cfg)
    with pytest.raises(boot.BootstrapError, match="counterparty_iteration_horizon"):
        boot.validate_input(cfg, vault_root=None)


def test_validate_input_rejects_empty_primary_entities(tmp_path):
    cfg = _minimal_input()
    cfg["entities"] = {"primary": [], "counterparties": ["x"]}
    cfg = boot.apply_defaults(cfg)
    with pytest.raises(boot.BootstrapError, match="entities.primary"):
        boot.validate_input(cfg, vault_root=None)


def test_validate_input_rejects_empty_trigger_patterns(tmp_path):
    cfg = _minimal_input()
    cfg["trigger_patterns"] = []
    cfg = boot.apply_defaults(cfg)
    with pytest.raises(boot.BootstrapError, match="trigger_patterns"):
        boot.validate_input(cfg, vault_root=None)


def test_validate_input_rejects_bad_ratified_date(tmp_path):
    cfg = _minimal_input()
    cfg["ratified_at"] = "30-04-2026"  # wrong format
    cfg = boot.apply_defaults(cfg)
    with pytest.raises(boot.BootstrapError, match="ratified_at"):
        boot.validate_input(cfg, vault_root=None)


def test_validate_input_rejects_bad_entity_slug(tmp_path):
    cfg = _minimal_input()
    cfg["entities"]["counterparties"] = ["NotKebab"]
    cfg = boot.apply_defaults(cfg)
    with pytest.raises(boot.BootstrapError, match="invalid slug"):
        boot.validate_input(cfg, vault_root=None)


def test_validate_input_rejects_collision_with_existing_vault_dir(tmp_path):
    """Refuse to clobber an existing wiki/matters/<slug>/."""
    vault = tmp_path / "vault"
    (vault / "wiki" / "matters" / "test-matter").mkdir(parents=True)
    cfg = boot.apply_defaults(_minimal_input())
    with pytest.raises(boot.BootstrapError, match="already exists in vault"):
        boot.validate_input(cfg, vault_root=vault)


# ---------------------------------------------------------------------------
# Frontmatter validation — every emitted .md passes validate_frontmatter
# ---------------------------------------------------------------------------


def test_emitted_frontmatter_passes_kbl_validation(tmp_path):
    rc = _run_main(tmp_path, _minimal_input())
    assert rc == 0
    out = tmp_path / "out"
    md_files = sorted(out.glob("*.md"))
    assert len(md_files) == 7, f"expected 7 .md files, got {len(md_files)}"
    for f in md_files:
        fm = boot._extract_frontmatter(f.read_text(encoding="utf-8"))
        validate_frontmatter(fm)  # raises on schema drift


def test_emit_creates_curated_gitkeep(tmp_path):
    rc = _run_main(tmp_path, _minimal_input())
    assert rc == 0
    gk = tmp_path / "out" / "curated" / ".gitkeep"
    assert gk.is_file()


def test_emit_marks_director_content_on_appropriate_files(tmp_path):
    rc = _run_main(tmp_path, _minimal_input())
    assert rc == 0
    out = tmp_path / "out"
    # _index.md and cortex-config.md don't get the marker (auto-populated).
    assert boot.NEEDS_CONTENT_MARKER not in (out / "_index.md").read_text()
    # The other 5 do (cortex-config.md DOES get marker only if input fields
    # missing — minimal config triggers it).
    for fn in ("_overview.md", "agenda.md", "state.md", "gold.md", "proposed-gold.md"):
        assert boot.NEEDS_CONTENT_MARKER in (out / fn).read_text(), fn


def test_cortex_config_carries_cortex_schema_keys(tmp_path):
    """cortex-config.md frontmatter must keep the Cortex-specific keys
    consumed by triggers/cortex_pre_review_gate.matter_notification_deferred()
    and the per-matter Phase-2 brain loader."""
    rc = _run_main(tmp_path, _minimal_input())
    assert rc == 0
    cfg_text = (tmp_path / "out" / "cortex-config.md").read_text()
    fm = boot._extract_frontmatter(cfg_text)
    for key in (
        "matter_slug", "matter_name", "absorbed_from", "absorbed_by",
        "autonomy_level", "sense_sources", "entities", "trigger_patterns",
        "default_specialists", "specialist_cap_per_cycle",
        "auto_trigger", "counterparty_iteration_horizon", "state_file",
        "gold_file", "curated_dir",
    ):
        assert key in fm, f"cortex-config missing {key!r}"
    assert fm["matter_slug"] == "test-matter"
    assert fm["state_file"] == "state.md"
    assert fm["curated_dir"] == "curated/"


# ---------------------------------------------------------------------------
# CLI flow — dry-run, force, default-fail
# ---------------------------------------------------------------------------


def test_dry_run_emits_zero_files(tmp_path, capsys):
    inp = _write_input(tmp_path, _minimal_input())
    out = tmp_path / "out"
    rc = boot.main([
        "--input", str(inp),
        "--out-root", str(out),
        "--vault-root", str(tmp_path / "no-vault"),
        "--dry-run",
    ])
    assert rc == 0
    assert not out.exists() or not list(out.rglob("*.md"))
    captured = capsys.readouterr()
    assert "[DRY-RUN]" in captured.out
    assert "cortex-config.md" in captured.out
    assert "curated/.gitkeep" in captured.out


def test_default_overwrite_fails(tmp_path):
    cfg = _minimal_input()
    rc = _run_main(tmp_path, cfg)
    assert rc == 0
    with pytest.raises(SystemExit) as exc:
        _run_main(tmp_path, cfg)  # second run, no --force
    assert exc.value.code == 1


def test_force_overwrite_succeeds_and_restamps(tmp_path):
    cfg = _minimal_input()
    rc = _run_main(tmp_path, cfg)
    assert rc == 0
    inp = _write_input(tmp_path, cfg, name="input.yml")
    out = tmp_path / "out"
    rc = boot.main([
        "--input", str(inp),
        "--out-root", str(out),
        "--vault-root", str(tmp_path / "no-vault"),
        "--today", "2026-05-01",
        "--force",
    ])
    assert rc == 0
    fm = boot._extract_frontmatter((out / "_overview.md").read_text())
    assert fm["updated"] == "2026-05-01"


def test_input_with_missing_required_field_returns_2(tmp_path, capsys):
    cfg = _minimal_input()
    del cfg["matter_name"]
    inp = _write_input(tmp_path, cfg)
    rc = boot.main([
        "--input", str(inp),
        "--out-root", str(tmp_path / "out"),
        "--vault-root", str(tmp_path / "no-vault"),
    ])
    assert rc == 2
    err = capsys.readouterr().err
    assert "ERROR" in err and "matter_name" in err


def test_nonexistent_input_file_returns_2(tmp_path, capsys):
    rc = boot.main([
        "--input", str(tmp_path / "no-such.yml"),
        "--out-root", str(tmp_path / "out"),
        "--vault-root", str(tmp_path / "no-vault"),
    ])
    assert rc == 2
    assert "not found" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Real fixture — capital-call end-to-end
# ---------------------------------------------------------------------------


def test_capital_call_fixture_dry_run(tmp_path, capsys):
    fixture = REPO / "briefs" / "_inputs" / "bootstrap_capital_call.yml"
    if not fixture.is_file():
        pytest.skip("capital-call fixture not present")
    rc = boot.main([
        "--input", str(fixture),
        "--out-root", str(tmp_path / "out"),
        "--vault-root", str(tmp_path / "no-vault"),
        "--dry-run",
    ])
    assert rc == 0
    captured = capsys.readouterr()
    assert "8 files" in captured.out
    assert "cortex-config.md" in captured.out


def test_capital_call_fixture_emits_full_skeleton(tmp_path):
    fixture = REPO / "briefs" / "_inputs" / "bootstrap_capital_call.yml"
    if not fixture.is_file():
        pytest.skip("capital-call fixture not present")
    out = tmp_path / "out"
    rc = boot.main([
        "--input", str(fixture),
        "--out-root", str(out),
        "--vault-root", str(tmp_path / "no-vault"),
        "--today", "2026-04-30",
    ])
    assert rc == 0
    md_files = sorted(out.glob("*.md"))
    assert len(md_files) == 7
    for f in md_files:
        fm = boot._extract_frontmatter(f.read_text())
        validate_frontmatter(fm)
    # cortex-config carries body sections from fixture
    cfg_text = (out / "cortex-config.md").read_text()
    assert "EUR 7M" in cfg_text
    assert "Aelio Holding Ltd" in cfg_text


# ---------------------------------------------------------------------------
# CHANDA #9 — script must not write to baker-vault directly
# ---------------------------------------------------------------------------


def test_no_baker_vault_writes_in_script_text():
    src = SCRIPT.read_text()
    assert "ingest_endpoint.ingest(" not in src
    for verb in ("INSERT ", "UPDATE ", "DELETE "):
        assert verb not in src.upper().replace("CO-AUTHORED-BY", ""), f"{verb} found"


# ---------------------------------------------------------------------------
# Subprocess smoke — script invokable from shell
# ---------------------------------------------------------------------------


def test_script_runs_end_to_end_via_subprocess(tmp_path):
    cfg = _minimal_input()
    inp = _write_input(tmp_path, cfg)
    out = tmp_path / "out"
    result = subprocess.run(
        [sys.executable, str(SCRIPT),
         "--input", str(inp),
         "--out-root", str(out),
         "--vault-root", str(tmp_path / "no-vault"),
         "--dry-run"],
        capture_output=True, text=True, cwd=str(REPO),
    )
    assert result.returncode == 0, result.stderr
    assert "[DRY-RUN]" in result.stdout
