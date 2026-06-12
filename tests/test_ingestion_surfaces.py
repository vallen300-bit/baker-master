from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from kbl.ingestion_surfaces import (
    build_ingestion_surfaces_prompt_block,
    load_ingestion_surfaces,
    parse_ingestion_surfaces_markdown,
)


SAMPLE_MARKDOWN = """---
type: process
name: ingestion-surfaces
version: v1
ratified: 2026-06-13 (Director)
owner: AH1
purpose: Canonical master list of ALL Brisen data surfaces.
---

# Ingestion surfaces - canonical sweep checklist (v1, 15 rows)

| # | Surface | What is inside | Access | Sweep |
|---|---------|----------------|--------|-------|
| 1 | Baker search | cross-source semantic index | `baker_search` | always |
| 2 | Email - Baker store | Gmail + M365 Graph | `baker_email_search` | always |
| 3 | Bluewin private email | dvallen@bluewin.ch | `baker_email_search source="bluewin"` | always |
| 4 | Outlook local archive | pre-migration mail history | Spotlight recipe | topic |
| 5 | WhatsApp | all threads | `whatsapp-pull-via-api` skill | always |
| 6 | Transcripts - matter-tagged | Plaud + Fireflies + YouTube | `GET /api/transcripts/by-matter/{slug}` | always |
| 7 | Fireflies direct | all meetings | `fireflies_search` MCP | always |
| 8 | Plaud raw | untagged voice memos | `baker_raw_query` | always |
| 9 | Dropbox | file tree | Dropbox MCP + local find/grep | always |
| 10 | Vault wiki | matter rooms, curated knowledge | `baker_vault_list` | always |
| 11 | ClaimsMax | construction claims archive | `baker_claimsmax_search` | topic |
| 12 | RSS / news + Substack | market + news signals | `baker_rss_articles` | always |
| 13 | Tasks - ClickUp + Todoist | open tasks and backlogs | `baker_clickup_tasks` | always |
| 14 | Calendar | meetings and attendees | calendar MCP `list_events` | always |
| 15 | Pipeline internals | signal queue and analyses | `baker_briefing_queue` | always |
"""


def test_parse_ingestion_surfaces_markdown_returns_15_rows():
    snapshot = parse_ingestion_surfaces_markdown(
        SAMPLE_MARKDOWN,
        last_commit_sha="abc123",
        sha256="def456",
    )

    assert snapshot["version"] == "v1"
    assert snapshot["ratified"].startswith("2026-06-13")
    assert snapshot["row_count"] == 15
    assert snapshot["source_last_commit_sha"] == "abc123"
    assert snapshot["surfaces"][0]["surface"] == "Baker search"
    assert snapshot["surfaces"][8]["surface"] == "Dropbox"
    assert snapshot["surfaces"][10]["sweep"] == "topic"


def test_parse_frontmatter_only_markdown_is_degraded():
    malformed = """---
type: process
name: ingestion-surfaces
version: v1
ratified: 2026-06-13 (Director)
---

# no table here
"""

    snapshot = parse_ingestion_surfaces_markdown(malformed)

    assert snapshot["version"] == "v1"
    assert snapshot["row_count"] == 0
    assert snapshot["surfaces"] == []
    assert snapshot["error"] == "no_rows_parsed"


def test_parse_missing_required_metadata_is_degraded():
    missing_metadata = SAMPLE_MARKDOWN.replace("version: v1\n", "")

    snapshot = parse_ingestion_surfaces_markdown(missing_metadata)

    assert snapshot["row_count"] == 15
    assert snapshot["error"] == "missing_metadata:version"


def test_prompt_block_includes_current_surface_list():
    with patch(
        "kbl.ingestion_surfaces.load_ingestion_surfaces",
        return_value=parse_ingestion_surfaces_markdown(SAMPLE_MARKDOWN),
    ):
        block = build_ingestion_surfaces_prompt_block()

    assert "CANONICAL INGESTION SURFACES" in block
    assert "| 15 | Pipeline internals |" in block
    assert "Version: v1" in block


def test_loader_force_refresh_reflects_vault_source_change():
    first = SAMPLE_MARKDOWN.replace("version: v1", "version: v1a")
    second = SAMPLE_MARKDOWN.replace("version: v1", "version: v2")

    with patch(
        "vault_mirror.read_ops_file",
        side_effect=[
            {"content_utf8": first, "path": "_ops/processes/ingestion-surfaces.md"},
            {"content_utf8": second, "path": "_ops/processes/ingestion-surfaces.md"},
        ],
    ):
        assert load_ingestion_surfaces(force_refresh=True)["version"] == "v1a"
        assert load_ingestion_surfaces(force_refresh=True)["version"] == "v2"


def test_ingestion_surfaces_endpoint_returns_snapshot():
    from outputs.dashboard import app, verify_api_key

    app.dependency_overrides[verify_api_key] = lambda: None
    try:
        with patch(
            "outputs.dashboard.load_ingestion_surfaces",
            return_value=parse_ingestion_surfaces_markdown(SAMPLE_MARKDOWN),
        ):
            resp = TestClient(app).get("/api/ingestion-surfaces")
    finally:
        app.dependency_overrides.pop(verify_api_key, None)

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["row_count"] == 15
    assert body["surfaces"][6]["surface"] == "Fireflies direct"


def test_ingestion_surfaces_endpoint_reports_degraded_snapshot():
    from outputs.dashboard import app, verify_api_key

    app.dependency_overrides[verify_api_key] = lambda: None
    try:
        with patch(
            "outputs.dashboard.load_ingestion_surfaces",
            return_value=parse_ingestion_surfaces_markdown("---\nversion: v1\nratified: x\n---\n"),
        ):
            resp = TestClient(app).get("/api/ingestion-surfaces")
    finally:
        app.dependency_overrides.pop(verify_api_key, None)

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["row_count"] == 0
    assert body["error"] == "no_rows_parsed"


def test_scan_system_prompt_includes_ingestion_surfaces():
    from outputs.dashboard import _build_scan_system_prompt

    with patch(
        "outputs.dashboard.build_ingestion_surfaces_prompt_block",
        return_value="## CANONICAL INGESTION SURFACES\n| 1 | Baker search | `baker_search` | always |",
    ):
        prompt = _build_scan_system_prompt(deadline_only=True)

    assert "CANONICAL INGESTION SURFACES" in prompt
    assert "baker_search" in prompt
