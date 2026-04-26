"""Tests for kbl.gold_parser — emit_audit_report shape + jsonb roundtrip."""
from __future__ import annotations

import json
from pathlib import Path

from kbl.gold_parser import emit_audit_report


def _seed_global(vault: Path, body: str) -> Path:
    out = vault / "_ops" / "director-gold-global.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(body, encoding="utf-8")
    return out


def test_emit_audit_report_clean_corpus(tmp_path: Path):
    _seed_global(
        tmp_path,
        body=(
            '## 2026-04-26 — Topic A\n\n**Ratification:** "yes" DV.\n\n'
            '## 2026-04-25 — Topic B\n\n**Ratification:** "ok" DV.\n'
        ),
    )
    report = emit_audit_report(tmp_path)
    assert report["issues_count"] == 0
    assert report["by_code"] == {}
    assert report["files"] == []
    assert report["payload"] == {"issues": []}


def test_emit_audit_report_dirty_corpus(tmp_path: Path):
    _seed_global(
        tmp_path,
        body=(
            "## 2026-04-26 — Missing DV\n\n"
            '**Ratification:** "no initials".\n'
        ),
    )
    report = emit_audit_report(tmp_path)
    assert report["issues_count"] >= 1
    assert "DV_ONLY" in report["by_code"]
    assert any("director-gold-global.md" in f for f in report["files"])


def test_emit_audit_report_groups_by_code(tmp_path: Path):
    _seed_global(
        tmp_path,
        body=(
            '## 2026-04-26 — Same Topic\n\n**Ratification:** "first" DV.\n\n'
            '## 2026-04-25 — Same Topic\n\n**Ratification:** "second" DV.\n'
        ),
    )
    report = emit_audit_report(tmp_path)
    assert report["by_code"].get("MATERIAL_CONFLICT", 0) >= 1


def test_emit_audit_report_payload_jsonb_serializable(tmp_path: Path):
    _seed_global(
        tmp_path,
        body=(
            "## 2026-04-26 — Bad\n\n"
            '**Ratification:** "no DV".\n'
        ),
    )
    report = emit_audit_report(tmp_path)
    serialized = json.dumps(report["payload"])
    roundtrip = json.loads(serialized)
    assert roundtrip == report["payload"]
    assert "issues" in roundtrip
    assert isinstance(roundtrip["issues"], list)
    assert all("code" in i for i in roundtrip["issues"])


def test_emit_audit_report_files_list_dedupes(tmp_path: Path):
    """Multiple issues in one file produce a single file-list entry."""
    _seed_global(
        tmp_path,
        body=(
            "## 2026-04-26 — First Bad\n\n"
            '**Ratification:** "no DV one".\n\n'
            "## 2026-04-25 — Second Bad\n\n"
            '**Ratification:** "no DV two".\n'
        ),
    )
    report = emit_audit_report(tmp_path)
    assert report["issues_count"] >= 2
    assert len(report["files"]) == 1


def test_emit_audit_report_returns_serialisable_dict(tmp_path: Path):
    """Top-level dict must be JSON-serialisable for gold_audits payload."""
    _seed_global(
        tmp_path,
        body='## 2026-04-26 — Clean\n\n**Ratification:** "yes" DV.\n',
    )
    report = emit_audit_report(tmp_path)
    json.dumps(report)  # raises if not serialisable
