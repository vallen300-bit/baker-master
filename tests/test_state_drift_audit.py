"""Tests for BRIEF_STATE_FILE_REFRESH_1 — state drift audit.

Golden-file approach: build a temp baker-vault layout with 5 synthetic
matters (2 canonical-clean, 2 canonical-drifted, 1 non-canonical), point
BAKER_VAULT_PATH at it, run audit, assert classifications.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from triggers import state_drift_audit as sda


def _make_matter(matter_dir: Path, cortex_updated: str, decisions: list[str] | None) -> None:
    matter_dir.mkdir(parents=True)
    cc = matter_dir / "cortex-config.md"
    cc.write_text(
        f"---\ntype: matter\nslug: {matter_dir.name}\n"
        f"updated: '{cortex_updated}'\n---\n\n# Cortex Config — {matter_dir.name}\n",
        encoding="utf-8",
    )
    if decisions is not None:
        curated = matter_dir / "curated"
        curated.mkdir()
        dl = curated / "06_decisions_log.md"
        dl.write_text(
            "---\nmatter: " + matter_dir.name + "\n---\n\n# Decisions\n\n"
            + "\n".join(decisions) + "\n",
            encoding="utf-8",
        )


@pytest.fixture
def synth_vault(tmp_path: Path, monkeypatch):
    """Build a synthetic baker-vault and point BAKER_VAULT_PATH at it."""
    vault = tmp_path / "vault"
    matters = vault / "wiki" / "matters"
    matters.mkdir(parents=True)

    # Matter 1: canonical-clean — updated same day as newest decision
    _make_matter(
        matters / "clean1",
        cortex_updated="2026-05-16",
        decisions=["## D-001 — first (2026-05-16)"],
    )
    # Matter 2: canonical-clean — within threshold (2d lag, under 7d)
    _make_matter(
        matters / "clean2",
        cortex_updated="2026-05-10",
        decisions=["## D-001 — first (2026-05-12)"],
    )
    # Matter 3: canonical-drifted — 25 days lag (Aukera-class)
    _make_matter(
        matters / "drift-aukera-class",
        cortex_updated="2026-04-22",
        decisions=["## D-001 — recent (2026-05-17)"],
    )
    # Matter 4: canonical-drifted — 8 days (just over threshold)
    _make_matter(
        matters / "drift-edge",
        cortex_updated="2026-05-09",
        decisions=["## D-001 — recent (2026-05-17)"],
    )
    # Matter 5: non-canonical (no curated/06_decisions_log.md)
    _make_matter(
        matters / "noncanonical",
        cortex_updated="2026-05-01",
        decisions=None,
    )

    monkeypatch.setenv("BAKER_VAULT_PATH", str(vault))
    return vault


def test_discover_matters_returns_only_those_with_cortex_config(synth_vault):
    slugs = sda._discover_matters(sda._matters_dir())
    assert sorted(slugs) == [
        "clean1", "clean2", "drift-aukera-class", "drift-edge", "noncanonical",
    ]


def test_audit_canonical_clean_within_threshold(synth_vault):
    r = sda._audit_matter(sda._matters_dir(), "clean2")
    assert r.layout_class == "canonical"
    assert r.is_drift_candidate is False
    assert r.lag_days == 2


def test_audit_canonical_drift_25d_flagged(synth_vault):
    r = sda._audit_matter(sda._matters_dir(), "drift-aukera-class")
    assert r.layout_class == "canonical"
    assert r.is_drift_candidate is True
    assert r.lag_days == 25


def test_audit_edge_8d_flagged(synth_vault):
    r = sda._audit_matter(sda._matters_dir(), "drift-edge")
    assert r.is_drift_candidate is True


def test_audit_noncanonical_classified_not_flagged(synth_vault):
    r = sda._audit_matter(sda._matters_dir(), "noncanonical")
    assert r.layout_class == "non_canonical_layout"
    assert r.is_drift_candidate is False


def test_full_run_writes_report_and_state(synth_vault, monkeypatch):
    posted = {"called": False}

    def _fake_post(*args, **kwargs):
        posted["called"] = True
        return True

    monkeypatch.setattr(sda, "_post_clickup_summary", _fake_post)

    sda.run_state_drift_audit()

    today = datetime.now(timezone.utc).date()
    report = synth_vault / "_ops" / "reports" / f"state-drift-{today.isoformat()}.md"
    assert report.is_file()
    text = report.read_text()
    assert "Drift candidates: **2**" in text  # drift-aukera-class + drift-edge
    assert "drift-aukera-class" in text
    assert "noncanonical" in text  # non-canonical section present

    state_file = (
        synth_vault / "_ops" / "agents" / "_scanner-state" / "state-drift-last-run.json"
    )
    assert state_file.is_file()
    state = json.loads(state_file.read_text())
    assert "seen_candidates" in state
    assert posted["called"] is True


def test_second_run_no_new_drift_skips_clickup(synth_vault, monkeypatch):
    calls: list[list[str]] = []

    def _capture(*args, **kwargs):
        # _post_clickup_summary signature: (drift_results, new_drift, report_path, today, ...)
        # second positional arg is the new_drift list
        calls.append(list(args[1]))
        return True

    monkeypatch.setattr(sda, "_post_clickup_summary", _capture)

    sda.run_state_drift_audit()  # populates state
    sda.run_state_drift_audit()  # second run — no change in drift bucket

    assert calls[0] != []  # first run surfaced new drift candidates
    assert calls[1] == []  # second run: same bucket, nothing new


@pytest.mark.parametrize("target_file", ["cortex-config.md", "curated/06_decisions_log.md"])
def test_file_level_symlink_refused_not_followed(synth_vault, tmp_path, target_file):
    """File-level symlinks at cortex-config.md or curated/06_decisions_log.md
    must not be read. _is_safe_slug rejects symlinked DIRECTORIES but
    Path.is_file() follows file-level symlinks -- audit must guard at read site.
    """
    slug = "symlinked"
    matter = synth_vault / "wiki" / "matters" / slug
    matter.mkdir(parents=True)
    (matter / "curated").mkdir()

    # Real cortex-config + decisions log; we'll replace ONE with a symlink.
    (matter / "cortex-config.md").write_text(
        f"---\ntype: matter\nslug: {slug}\nupdated: '2026-05-01'\n---\n",
        encoding="utf-8",
    )
    (matter / "curated" / "06_decisions_log.md").write_text(
        "## D-001 — recent (2026-05-17)\n", encoding="utf-8"
    )

    sibling_target = tmp_path / "outside-secret.txt"
    sibling_target.write_text("SECRET-CONTENT-MUST-NOT-LEAK\n", encoding="utf-8")

    victim = matter / target_file
    victim.unlink()
    os.symlink(sibling_target, victim)

    r = sda._audit_matter(sda._matters_dir(), slug)

    if target_file == "cortex-config.md":
        assert any("symlink" in n.lower() for n in r.notes), r.notes
        assert r.cortex_config_updated is None
    else:
        assert r.newest_decision_date is None

    # Belt-and-braces: no field on the result should contain the secret payload.
    for value in (r.notes, [r.cortex_config_updated, r.newest_decision_date, r.lag_days]):
        assert "SECRET-CONTENT-MUST-NOT-LEAK" not in str(value)


def test_malformed_frontmatter_does_not_crash(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    matter = vault / "wiki" / "matters" / "broken"
    matter.mkdir(parents=True)
    (matter / "cortex-config.md").write_text("no frontmatter at all\n", encoding="utf-8")
    monkeypatch.setenv("BAKER_VAULT_PATH", str(vault))
    sda.run_state_drift_audit()  # must not raise
