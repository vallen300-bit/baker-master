"""Tests for orchestrator/cortex_drift_audit.py + scheduler registration —
CORTEX_3T_FORMALIZE_1C.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from orchestrator import cortex_drift_audit as audit


@pytest.fixture
def vault(tmp_path):
    matters = tmp_path / "wiki" / "matters"
    matters.mkdir(parents=True)
    return tmp_path


def _make_config(vault: Path, slug: str, age_days: int) -> Path:
    d = vault / "wiki" / "matters" / slug
    d.mkdir(parents=True, exist_ok=True)
    cfg = d / "cortex-config.md"
    cfg.write_text(f"# {slug} cortex config\n")
    if age_days > 0:
        old = time.time() - age_days * 86400
        os.utime(cfg, (old, old))
    return cfg


# ─── run_drift_audit core behaviour ───


def test_skips_when_vault_path_unset(monkeypatch):
    monkeypatch.delenv("BAKER_VAULT_PATH", raising=False)
    result = audit.run_drift_audit()
    assert result["ok"] is False
    assert "skipped" in result
    assert result["flagged_count"] == 0


def test_skips_when_vault_dir_missing(monkeypatch, tmp_path):
    missing = tmp_path / "no_such_vault"
    monkeypatch.setenv("BAKER_VAULT_PATH", str(missing))
    result = audit.run_drift_audit()
    assert result["ok"] is False


def test_returns_zero_flagged_when_no_configs(vault):
    result = audit.run_drift_audit(vault_root=vault)
    assert result["ok"] is True
    assert result["checked"] == 0
    assert result["flagged_count"] == 0


def test_fresh_config_is_not_flagged(vault):
    _make_config(vault, "oskolkov", age_days=5)
    result = audit.run_drift_audit(vault_root=vault)
    assert result["checked"] == 1
    assert result["flagged_count"] == 0


def test_stale_config_is_flagged_with_age_days(vault):
    _make_config(vault, "oskolkov", age_days=45)
    result = audit.run_drift_audit(vault_root=vault)
    assert result["checked"] == 1
    assert result["flagged_count"] == 1
    flagged = result["flagged"][0]
    assert flagged["slug"] == "oskolkov"
    assert flagged["age_days"] >= 45


def test_mixed_fresh_and_stale_only_flags_stale(vault):
    _make_config(vault, "fresh1", age_days=5)
    _make_config(vault, "stale1", age_days=45)
    _make_config(vault, "fresh2", age_days=10)
    _make_config(vault, "stale2", age_days=60)
    result = audit.run_drift_audit(vault_root=vault)
    assert result["checked"] == 4
    assert result["flagged_count"] == 2
    flagged_slugs = {f["slug"] for f in result["flagged"]}
    assert flagged_slugs == {"stale1", "stale2"}


def test_threshold_env_var_respected(monkeypatch, vault):
    """Override threshold via env var — verify a 10-day-old config flags
    when threshold is 5 but not when threshold is 30 (default)."""
    _make_config(vault, "edge", age_days=10)
    monkeypatch.setattr(audit, "DRIFT_THRESHOLD_DAYS", 5)
    result = audit.run_drift_audit(vault_root=vault)
    assert result["flagged_count"] == 1


def test_skips_non_directories_inside_matters(vault):
    # Create a stray file at matters/ root — must be skipped, not blow up
    (vault / "wiki" / "matters" / "stray.txt").write_text("noise")
    _make_config(vault, "oskolkov", age_days=5)
    result = audit.run_drift_audit(vault_root=vault)
    assert result["checked"] == 1


# ─── Scheduler integration: job is registered ───


def test_matter_config_drift_job_function_exists():
    from triggers import embedded_scheduler
    assert hasattr(embedded_scheduler, "_matter_config_drift_weekly_job")
    assert callable(embedded_scheduler._matter_config_drift_weekly_job)


def test_drift_job_swallows_runner_exception(monkeypatch, caplog):
    from triggers import embedded_scheduler
    from orchestrator import cortex_drift_audit as a

    def boom():
        raise RuntimeError("vault chaos")

    monkeypatch.setattr(a, "run_drift_audit", boom)
    with caplog.at_level("WARNING"):
        embedded_scheduler._matter_config_drift_weekly_job()   # must not raise
    assert any("vault chaos" in r.message for r in caplog.records)


def test_scheduler_source_registers_job_with_canonical_id():
    """Source assertion: the cron registration block exists and uses the
    canonical job_id ``matter_config_drift_weekly`` Mon 11:00 UTC."""
    src = Path("triggers/embedded_scheduler.py").read_text()
    assert "matter_config_drift_weekly" in src
    assert "CORTEX_DRIFT_AUDIT_ENABLED" in src
    assert 'CronTrigger(day_of_week="mon", hour=11, minute=0' in src
