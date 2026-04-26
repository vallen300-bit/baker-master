"""WIKI_LINT_1 — check 3 orphan_matter_dir."""
from __future__ import annotations

import datetime as _dt

from kbl.lint_checks import orphan_matter_dir as M
from kbl.lint_checks._common import Severity
from tests.fixtures.wiki_lint import build_fixture_vault, NOW


def test_orphan_flat_flagged_when_no_signals(tmp_path):
    vault = build_fixture_vault(tmp_path)
    registries = {
        "now_utc": NOW.isoformat(),
        "orphan_days": 90,
        "signal_last_seen": {},  # nothing seen for any matter
    }
    hits = M.run(vault, registries)
    paths = sorted({h.path for h in hits})
    assert "wiki/orphan-flat" in paths
    orphans = [h for h in hits if h.path == "wiki/orphan-flat"]
    assert all(h.severity is Severity.WARN for h in orphans)


def test_recent_signal_suppresses_orphan(tmp_path):
    vault = build_fixture_vault(tmp_path)
    registries = {
        "now_utc": NOW.isoformat(),
        "orphan_days": 90,
        "signal_last_seen": {"orphan-flat": NOW - _dt.timedelta(days=10)},
    }
    hits = M.run(vault, registries)
    paths = {h.path for h in hits}
    assert "wiki/orphan-flat" not in paths


def test_old_signal_does_not_suppress(tmp_path):
    vault = build_fixture_vault(tmp_path)
    registries = {
        "now_utc": NOW.isoformat(),
        "orphan_days": 90,
        "signal_last_seen": {"orphan-flat": NOW - _dt.timedelta(days=120)},
    }
    hits = M.run(vault, registries)
    paths = {h.path for h in hits}
    assert "wiki/orphan-flat" in paths


def test_inbound_link_suppresses_orphan(tmp_path):
    """nested-good has inbound from movie-x and outbound to flat-old; not
    orphan-eligible regardless of signal age."""
    vault = build_fixture_vault(tmp_path)
    registries = {
        "now_utc": NOW.isoformat(),
        "orphan_days": 90,
        "signal_last_seen": {},
    }
    hits = M.run(vault, registries)
    paths = {h.path for h in hits}
    assert "wiki/matters/nested-good" not in paths
    assert "wiki/matters/movie-x/sub-matters/movie-sub" not in paths


def test_orphan_days_threshold_env(tmp_path):
    vault = build_fixture_vault(tmp_path)
    registries = {
        "now_utc": NOW.isoformat(),
        "orphan_days": 30,
        "signal_last_seen": {"orphan-flat": NOW - _dt.timedelta(days=45)},
    }
    hits = M.run(vault, registries)
    paths = {h.path for h in hits}
    assert "wiki/orphan-flat" in paths
