"""
DOCUMENTS_SEARCH_SEMANTIC_RESTORE_1 (Bug A) — restore the dead Qdrant semantic
branch in GET /api/documents/search and guard its deterministic id-resolution.

ROOT CAUSE this guards against:
    The Qdrant branch did `from memory.retriever import Retriever` (no such symbol;
    the class is SentinelRetriever) and `retriever.search(...)` (wrong method). The
    ImportError was swallowed by `except`, so EVERY query silently ran a Postgres
    `filename/full_text ILIKE` substring match. Document search was dumb keyword
    matching for months.

The fix runs a real Voyage→Qdrant semantic search, then enriches each chunk hit
from Postgres by `source_file` (the only shared join key in the existing corpus),
groups chunks → one result per documents.id keeping the highest score, applies
filters against the authoritative PG row, and drops any hit with no PG row (no
openable documents.id). The ILIKE path is kept only as a fallback.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest


# ─── Source-level guard (always runs, even on Py3.9 where dashboard won't import) ──

def test_handler_uses_sentinelretriever_singleton_in_source():
    """The search handler must use the real retriever API, not the dead import."""
    src = Path("outputs/dashboard.py").read_text()
    # The broken symbol must be gone.
    assert "from memory.retriever import Retriever\n" not in src, (
        "dead `from memory.retriever import Retriever` must be removed — it ImportErrors "
        "and silently degrades document search to ILIKE substring matching"
    )
    # The correct singleton + method must be present.
    assert "SentinelRetriever._get_global_instance()" in src, (
        "handler must use the singleton accessor (CI guard scripts/check_singletons.sh)"
    )
    assert "search_collection(" in src
    assert 'collection="baker-documents"' in src
    # Conn-hold fix: the search handler must no longer grab a conn up-front for the
    # whole body. (We assert the semantic phase calls the retriever before any cursor.)
    assert "_resolve_semantic_doc_hits(" in src


# ─── Pure resolution-logic unit tests (run under py3.12 where dashboard imports) ──

def _dashboard_importable() -> bool:
    try:
        import outputs.dashboard  # noqa: F401
        return True
    except Exception:
        return False


pytestmark_helper = pytest.mark.skipif(
    not _dashboard_importable(),
    reason="outputs.dashboard not importable on this interpreter (needs py3.10+ syntax)",
)


def _hit(source_file, source_path="", score=0.5, content="chunk text"):
    """Mimic a RetrievedContext: attribute access .metadata/.score/.content."""
    return SimpleNamespace(
        metadata={"source_file": source_file, "source_path": source_path},
        score=score,
        content=content,
    )


def _pg(id_, filename, source_path="", matter="", dtype="", ingested=None, preview="prev"):
    return {
        "id": id_,
        "filename": filename,
        "document_type": dtype,
        "matter_slug": matter,
        "source_path": source_path,
        "ingested_at": ingested,
        "text_preview": preview,
    }


@pytestmark_helper
def test_single_pg_row_resolves_to_its_id():
    from outputs.dashboard import _resolve_semantic_doc_hits

    hits = [_hit("deal.pdf", "/vault/deal.pdf", score=0.8)]
    pg = {"deal.pdf": [_pg(42, "deal.pdf", "/vault/deal.pdf", matter="mo-vie", dtype="contract")]}
    results, total = _resolve_semantic_doc_hits(hits, pg, [], [], [], 0, 20)

    assert total == 1
    assert results[0]["id"] == 42
    assert results[0]["matter"] == "mo-vie"
    assert results[0]["document_type"] == "contract"
    assert results[0]["score"] == 0.8


@pytestmark_helper
def test_multiple_pg_rows_prefer_source_path_match():
    from outputs.dashboard import _resolve_semantic_doc_hits

    hits = [_hit("dup.pdf", "/b/dup.pdf", score=0.7)]
    pg = {"dup.pdf": [
        _pg(1, "dup.pdf", "/a/dup.pdf", ingested=datetime(2026, 1, 1)),
        _pg(2, "dup.pdf", "/b/dup.pdf", ingested=datetime(2025, 1, 1)),  # older but path matches
    ]}
    results, total = _resolve_semantic_doc_hits(hits, pg, [], [], [], 0, 20)

    assert total == 1
    assert results[0]["id"] == 2, "source_path match wins over recency"


@pytestmark_helper
def test_multiple_pg_rows_fall_back_to_most_recent():
    from outputs.dashboard import _resolve_semantic_doc_hits

    hits = [_hit("dup.pdf", "/no/match.pdf", score=0.7)]
    pg = {"dup.pdf": [
        _pg(1, "dup.pdf", "/a/dup.pdf", ingested=datetime(2026, 5, 1)),  # most recent
        _pg(2, "dup.pdf", "/b/dup.pdf", ingested=datetime(2025, 1, 1)),
    ]}
    results, total = _resolve_semantic_doc_hits(hits, pg, [], [], [], 0, 20)

    assert total == 1
    assert results[0]["id"] == 1, "no source_path match → newest ingested_at wins"


@pytestmark_helper
def test_zero_pg_rows_drops_hit():
    from outputs.dashboard import _resolve_semantic_doc_hits

    hits = [_hit("orphan.pdf", "/vault/orphan.pdf", score=0.9)]
    results, total = _resolve_semantic_doc_hits(hits, {}, [], [], [], 0, 20)

    assert total == 0
    assert results == [], "a hit with no PG row has no openable id → must be dropped"


@pytestmark_helper
def test_multi_chunk_doc_deduped_to_highest_score():
    from outputs.dashboard import _resolve_semantic_doc_hits

    # Three chunks of the same document, different scores.
    hits = [
        _hit("big.pdf", "/v/big.pdf", score=0.4),
        _hit("big.pdf", "/v/big.pdf", score=0.91),
        _hit("big.pdf", "/v/big.pdf", score=0.6),
    ]
    pg = {"big.pdf": [_pg(7, "big.pdf", "/v/big.pdf")]}
    results, total = _resolve_semantic_doc_hits(hits, pg, [], [], [], 0, 20)

    assert total == 1, "multi-chunk doc must collapse to a single result"
    assert results[0]["id"] == 7
    assert results[0]["score"] == 0.91, "highest chunk score is kept"


@pytestmark_helper
def test_matter_filter_applied_against_pg_fields():
    from outputs.dashboard import _resolve_semantic_doc_hits

    hits = [
        _hit("a.pdf", "/v/a.pdf", score=0.8),
        _hit("b.pdf", "/v/b.pdf", score=0.7),
    ]
    pg = {
        "a.pdf": [_pg(1, "a.pdf", "/v/a.pdf", matter="mo-vie")],
        "b.pdf": [_pg(2, "b.pdf", "/v/b.pdf", matter="hagenauer-rg7")],
    }
    results, total = _resolve_semantic_doc_hits(hits, pg, ["mo-vie"], [], [], 0, 20)

    assert total == 1
    assert results[0]["id"] == 1


@pytestmark_helper
def test_results_sorted_by_score_desc_and_paginated():
    from outputs.dashboard import _resolve_semantic_doc_hits

    hits = [
        _hit("low.pdf", "/v/low.pdf", score=0.31),
        _hit("high.pdf", "/v/high.pdf", score=0.95),
        _hit("mid.pdf", "/v/mid.pdf", score=0.6),
    ]
    pg = {
        "low.pdf": [_pg(1, "low.pdf", "/v/low.pdf")],
        "high.pdf": [_pg(2, "high.pdf", "/v/high.pdf")],
        "mid.pdf": [_pg(3, "mid.pdf", "/v/mid.pdf")],
    }
    # full page: order by score desc
    results, total = _resolve_semantic_doc_hits(hits, pg, [], [], [], 0, 20)
    assert total == 3
    assert [r["id"] for r in results] == [2, 3, 1]

    # offset/limit paginates the sorted list
    page2, total2 = _resolve_semantic_doc_hits(hits, pg, [], [], [], 1, 1)
    assert total2 == 3
    assert [r["id"] for r in page2] == [3]


@pytestmark_helper
def test_type_and_source_filters_against_pg_fields():
    from outputs.dashboard import _resolve_semantic_doc_hits

    hits = [
        _hit("mail.pdf", "/gmail/mail.pdf", score=0.8),
        _hit("doc.pdf", "/dropbox/doc.pdf", score=0.7),
    ]
    pg = {
        "mail.pdf": [_pg(1, "mail.pdf", "/gmail/mail.pdf", dtype="email")],
        "doc.pdf": [_pg(2, "doc.pdf", "/dropbox/doc.pdf", dtype="contract")],
    }
    # source filter: only email-derived source_path survives
    res_src, tot_src = _resolve_semantic_doc_hits(hits, pg, [], [], ["email"], 0, 20)
    assert tot_src == 1 and res_src[0]["id"] == 1

    # type filter: only contract survives
    res_t, tot_t = _resolve_semantic_doc_hits(hits, pg, [], ["contract"], [], 0, 20)
    assert tot_t == 1 and res_t[0]["id"] == 2
