"""Provisioning function tests for orchestrator.cortex_directives.

Brief: CORTEX_CONFIG_DIRECTIVES_SCHEMA_1 §3.2.

No DB required — pure filesystem round-trips on tmp_path.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from kbl.ingest_endpoint import validate_frontmatter
from orchestrator.cortex_directives import (
    DIRECTIVES_FILENAME,
    provision_directive_schema,
    render_directives_template,
)


def _extract_frontmatter(content: str) -> dict:
    assert content.startswith("---\n"), "missing leading frontmatter delimiter"
    end = content.find("\n---\n", 4)
    assert end != -1, "frontmatter not terminated"
    return yaml.safe_load(content[4:end])


def test_render_template_passes_kbl_validator():
    """Option C: directives.md frontmatter conforms to validate_frontmatter
    with no validator skip and no validator extension."""
    content = render_directives_template("test-matter", "Test Matter", "2026-04-30")
    fm = _extract_frontmatter(content)
    validate_frontmatter(fm)
    assert fm["type"] == "matter"
    assert fm["slug"] == "test-matter"
    assert fm["voice"] == "silver"
    assert fm["author"] == "agent"
    assert "directives" in fm["tags"]
    assert "cortex-phase6" in fm["tags"]
    assert fm["related"] == []
    # Documentation-only fields ignored by validator but useful for humans.
    assert fm["directive_count"] == 0
    assert fm["schema_version"] == 1


def test_provision_creates_file(tmp_path: Path):
    out_dir = tmp_path / "matters" / "test-matter"
    created = provision_directive_schema(
        "test-matter", "Test Matter", out_dir, "2026-04-30"
    )
    assert created is True

    target = out_dir / DIRECTIVES_FILENAME
    assert target.is_file()
    content = target.read_text(encoding="utf-8")
    assert content.startswith("---\n")
    assert "slug: test-matter" in content
    assert "directive_count: 0" in content
    assert "Test Matter — Directives Playbook" in content


def test_provision_idempotent_skip(tmp_path: Path):
    out_dir = tmp_path / "matters" / "test-matter"
    (out_dir / "curated").mkdir(parents=True)
    (out_dir / DIRECTIVES_FILENAME).write_text("PRE-EXISTING\n", encoding="utf-8")
    created = provision_directive_schema(
        "test-matter", "Test Matter", out_dir, "2026-04-30"
    )
    assert created is False
    assert (out_dir / DIRECTIVES_FILENAME).read_text(encoding="utf-8") == "PRE-EXISTING\n"


def test_provision_force_overwrites(tmp_path: Path):
    out_dir = tmp_path / "matters" / "test-matter"
    (out_dir / "curated").mkdir(parents=True)
    (out_dir / DIRECTIVES_FILENAME).write_text("PRE-EXISTING\n", encoding="utf-8")
    created = provision_directive_schema(
        "test-matter", "Test Matter", out_dir, "2026-04-30", force=True
    )
    assert created is True
    content = (out_dir / DIRECTIVES_FILENAME).read_text(encoding="utf-8")
    assert "PRE-EXISTING" not in content
    assert "slug: test-matter" in content


def test_provision_rejects_empty_slug(tmp_path: Path):
    with pytest.raises(ValueError, match="matter_slug"):
        provision_directive_schema("", "Test Matter", tmp_path, "2026-04-30")


def test_provision_rejects_empty_name(tmp_path: Path):
    with pytest.raises(ValueError, match="matter_name"):
        provision_directive_schema("test-matter", "", tmp_path, "2026-04-30")


def test_provision_creates_curated_subdir(tmp_path: Path):
    """Parent dirs are created idempotently — caller need not pre-mkdir."""
    out_dir = tmp_path / "matters" / "fresh-slug"
    assert not out_dir.exists()
    created = provision_directive_schema(
        "fresh-slug", "Fresh Slug", out_dir, "2026-04-30"
    )
    assert created is True
    assert (out_dir / "curated").is_dir()
    assert (out_dir / DIRECTIVES_FILENAME).is_file()
