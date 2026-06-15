"""LONG_RUNNING_JOB_OWNERSHIP_1 — validator tests.

Tests config/long_running_jobs.yml schema enforcement: ownerless / unknown-slug
/ bad-threshold / missing cursor_source entries must fail validation, and the
real committed register must pass. No DB, no live creds.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
VALIDATOR = REPO_ROOT / "scripts" / "validate_long_running_jobs.py"

from scripts.validate_long_running_jobs import validate, load_yaml  # noqa: E402


_GOOD_ENTRY = {
    "job_id": "graph_inbox_backfill",
    "description": "M365 Graph historical backfill — Inbox",
    "trigger_reason": "detached",
    "stall_threshold_hours": 6,
    "responsible": "b1",
    "accountable": "lead",
    "consulted": ["aid"],
    "informed": ["director"],
    "cursor_source": {
        "kind": "progress_table",
        "table": "email_backfill_progress",
        "cursor_col": "done_count",
        "updated_col": "updated_at",
        "key_col": "source",
        "key_val": "graph:Inbox",
        "total_col": "total_estimate",
    },
}


def _doc(*entries):
    return {"jobs": list(entries)}


def test_good_entry_passes():
    assert validate(_doc(_GOOD_ENTRY)) == []


def test_ownerless_fails():
    bad = dict(_GOOD_ENTRY)
    bad.pop("accountable")
    errs = validate(_doc(bad))
    assert errs
    assert any("accountable" in e for e in errs)


def test_unknown_slug_fails():
    bad = dict(_GOOD_ENTRY)
    bad["accountable"] = "not-a-real-slug"
    errs = validate(_doc(bad))
    assert errs
    assert any("not-a-real-slug" in e for e in errs)


def test_unknown_slug_in_consulted_list_fails():
    bad = dict(_GOOD_ENTRY)
    bad["consulted"] = ["aid", "ghost-agent"]
    errs = validate(_doc(bad))
    assert any("ghost-agent" in e for e in errs)


def test_nonpositive_threshold_fails():
    for bad_val in (0, -3):
        bad = dict(_GOOD_ENTRY)
        bad["stall_threshold_hours"] = bad_val
        errs = validate(_doc(bad))
        assert errs, f"threshold {bad_val} should fail"
        assert any("threshold" in e.lower() for e in errs)


def test_missing_cursor_source_fails():
    bad = dict(_GOOD_ENTRY)
    bad.pop("cursor_source")
    errs = validate(_doc(bad))
    assert any("cursor_source" in e for e in errs)


def test_progress_table_missing_subfield_fails():
    bad = dict(_GOOD_ENTRY)
    bad["cursor_source"] = dict(_GOOD_ENTRY["cursor_source"])
    bad["cursor_source"].pop("key_val")
    errs = validate(_doc(bad))
    assert any("key_val" in e for e in errs)


def test_bad_trigger_reason_fails():
    bad = dict(_GOOD_ENTRY)
    bad["trigger_reason"] = "because-i-said-so"
    errs = validate(_doc(bad))
    assert any("trigger_reason" in e for e in errs)


def test_real_committed_register_passes():
    cfg = REPO_ROOT / "config" / "long_running_jobs.yml"
    assert cfg.exists(), "config/long_running_jobs.yml must exist"
    errs = validate(load_yaml(cfg))
    assert errs == [], f"committed register failed validation: {errs}"


def test_real_register_has_four_partitions():
    cfg = REPO_ROOT / "config" / "long_running_jobs.yml"
    doc = load_yaml(cfg)
    ids = {j["job_id"] for j in doc["jobs"]}
    assert {
        "graph_inbox_backfill",
        "graph_sentitems_backfill",
        "bluewin_inbox_backfill",
        "bluewin_sentitems_backfill",
    } <= ids


def test_cli_exit_nonzero_on_bad_file(tmp_path):
    bad_file = tmp_path / "bad.yml"
    bad_file.write_text(textwrap.dedent(
        """
        jobs:
          - job_id: x
            description: missing everything else
        """
    ))
    proc = subprocess.run(
        [sys.executable, str(VALIDATOR), "--file", str(bad_file)],
        capture_output=True, text=True,
    )
    assert proc.returncode != 0


def test_cli_exit_zero_on_real_register():
    proc = subprocess.run(
        [sys.executable, str(VALIDATOR)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
