"""Tests for kbl/citations.py + Slack render helpers.

CITATIONS_API_SCAN_1 — Anthropic Citations adapter coverage.
Uses SimpleNamespace for SDK response stubs (no unittest.mock.patch).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from kbl.citations import (
    Citation,
    ExtractedResponse,
    build_document_blocks,
    extract_citations,
    render_citations_markdown,
    render_citations_slack_blocks,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture
def sample_docs():
    return [
        {
            "title": "Hagenauer RG7 Overview",
            "body": "RG7 is a Baden bei Wien project. Insolvency Mar 2026.",
        },
        {
            "title": "Cupial Dispute Timeline",
            "body": "Tops 4,5,6,18 handover contested by Michal Hassa.",
        },
    ]


def _fake_response(texts_and_citations):
    """Build a fake Anthropic response object.

    texts_and_citations: list of (text, [Citation]) tuples.
    """
    blocks = []
    for text, cites in texts_and_citations:
        cite_objs = [
            SimpleNamespace(
                type="char_location",
                cited_text=c.cited_text,
                document_index=c.document_index,
                document_title=c.document_title,
                start_char_index=c.start_char_index,
                end_char_index=c.end_char_index,
            )
            for c in cites
        ]
        blocks.append(
            SimpleNamespace(type="text", text=text, citations=cite_objs),
        )
    return SimpleNamespace(content=blocks)


# ─── build_document_blocks ────────────────────────────────────────────────

def test_build_document_blocks_happy(sample_docs):
    out = build_document_blocks(sample_docs)
    assert len(out) == 2
    assert out[0]["type"] == "document"
    assert out[0]["source"]["type"] == "text"
    assert out[0]["source"]["media_type"] == "text/plain"
    assert out[0]["source"]["data"] == sample_docs[0]["body"]
    assert out[0]["title"] == sample_docs[0]["title"]
    assert out[0]["citations"] == {"enabled": True}


def test_build_document_blocks_skips_empty_body():
    docs = [{"title": "X", "body": ""}, {"title": "Y", "body": "content"}]
    out = build_document_blocks(docs)
    assert len(out) == 1
    assert out[0]["title"] == "Y"


def test_build_document_blocks_missing_title_uses_fallback():
    docs = [{"body": "body only"}]
    out = build_document_blocks(docs)
    assert out[0]["title"] == "Document 1"


# ─── extract_citations ────────────────────────────────────────────────────

def test_extract_citations_simple():
    cite = Citation(0, "Doc A", "cited span", 10, 22)
    resp = _fake_response([("Some text.", [cite])])
    extracted = extract_citations(resp)
    assert extracted.text == "Some text."
    assert len(extracted.citations_flat) == 1
    assert extracted.citations_flat[0].document_title == "Doc A"
    assert len(extracted.citations_by_paragraph) == 1
    assert extracted.citations_by_paragraph[0][0] == cite


def test_extract_citations_multiple_blocks():
    c1 = Citation(0, "Doc A", "span1", 0, 10)
    c2 = Citation(1, "Doc B", "span2", 5, 15)
    resp = _fake_response([("First.", [c1]), ("Second.", [c2])])
    extracted = extract_citations(resp)
    assert extracted.text == "First.Second."
    assert len(extracted.citations_flat) == 2


def test_extract_citations_response_without_citations_attr():
    """Older SDK / citations disabled — blocks lack 'citations' attr."""
    blocks = [SimpleNamespace(type="text", text="plain response")]
    resp = SimpleNamespace(content=blocks)
    extracted = extract_citations(resp)
    assert extracted.text == "plain response"
    assert extracted.citations_flat == []


def test_extract_citations_empty_response():
    resp = SimpleNamespace(content=[])
    extracted = extract_citations(resp)
    assert extracted.text == ""
    assert extracted.citations_flat == []


def test_extract_citations_tolerates_malformed_citation():
    bad = SimpleNamespace()  # no citation attrs at all
    blocks = [SimpleNamespace(type="text", text="text", citations=[bad])]
    resp = SimpleNamespace(content=blocks)
    extracted = extract_citations(resp)
    # Bad citation skipped; text still extracted.
    assert extracted.text == "text"
    assert len(extracted.citations_flat) == 0


# ─── render_citations_markdown ────────────────────────────────────────────

def test_render_markdown_empty():
    assert render_citations_markdown(ExtractedResponse(text="x")) == ""


def test_render_markdown_numbered():
    cites = [
        Citation(0, "Doc A", "span a", 0, 10),
        Citation(1, "Doc B", "span b", 5, 15),
    ]
    out = render_citations_markdown(
        ExtractedResponse(text="", citations_flat=cites),
    )
    assert "## Sources" in out
    assert "1. **Doc A**" in out
    assert "2. **Doc B**" in out


def test_render_markdown_dedups_identical_spans():
    c1 = Citation(0, "Doc A", "span", 10, 20)
    c2 = Citation(0, "Doc A", "span", 10, 20)  # identical key
    out = render_citations_markdown(
        ExtractedResponse(text="", citations_flat=[c1, c2]),
    )
    assert out.count("1. **Doc A**") == 1
    assert "2. " not in out  # only one line


# ─── render_citations_slack_blocks ────────────────────────────────────────

def test_render_slack_empty():
    assert render_citations_slack_blocks(ExtractedResponse(text="x")) == []


def test_render_slack_shape():
    cites = [Citation(0, "Doc A", "span a", 0, 10)]
    blocks = render_citations_slack_blocks(
        ExtractedResponse(text="", citations_flat=cites),
    )
    assert blocks[0] == {"type": "divider"}
    assert blocks[1]["type"] == "section"
    assert blocks[2]["type"] == "context"
    assert len(blocks[2]["elements"]) == 1
    assert "1." in blocks[2]["elements"][0]["text"]
    assert "Doc A" in blocks[2]["elements"][0]["text"]


def test_render_slack_caps_at_10_elements():
    cites = [
        Citation(i, f"Doc {i}", f"span {i}", 0, 10) for i in range(15)
    ]
    blocks = render_citations_slack_blocks(
        ExtractedResponse(text="", citations_flat=cites),
    )
    assert len(blocks[2]["elements"]) == 10  # capped
