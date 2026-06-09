"""M365_MAIL_BLINDSPOT_DIAGNOSE_FIX_1 — tests for the mail tool-surface fix.

Reproduces the blindspot (baker_gmail_search silent-empty on brisengroup/M365
mail) and proves the fix:
  1. baker_gmail_search no longer fails silent — empty / brisengroup-scoped
     results carry a LOUD pointer to baker_email_search.
  2. baker_email_search reads the merged email_messages store (Gmail + Graph),
     so the post-migration Spanyi email is findable.
  3. A store backend OUTAGE surfaces loudly (not read as "no mail").
  4. graph_mail_poll is wired into the staleness watchdog.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from memory.retriever import SearchBackendUnavailable


# ── fixtures ───────────────────────────────────────────────────────────────

# A row shaped like _ROW_COLS in tools.email:
# (message_id, thread_id, sender_name, sender_email, subject, snippet, received_date, source)
def _spanyi_row() -> tuple:
    """The exact post-migration email Director could not find (Graph-ingested)."""
    return (
        "AAQkAGEzNGM4OWM4LWZjN2YtNDg2ZS05Y2NkLWIxNzkwODEyOGUxMA==",
        "AAQkconv",
        "Spanyi Mario",
        "M.Spanyi@eh.at",
        "Preparing for the hearing scheduled for 10 June 2026",
        "Dear Mr Vallen, ahead of the 10 June 2026 hearing ...",
        "2026-06-06 15:59:24+00:00",
        "graph",
    )


def _empty_gmail_service() -> MagicMock:
    """A Gmail service whose list() returns zero messages (the blindspot)."""
    service = MagicMock()
    service.users().messages().list().execute.return_value = {
        "messages": [],
        "resultSizeEstimate": 0,
    }
    return service


# ── baker_email_search: the merged store surface ──────────────────────────

def test_email_search_store_finds_graph_email():
    """baker_email_search (provider=store) returns the post-migration Spanyi mail."""
    from tools.email import dispatch_email

    with patch("tools.email._run_email_query", return_value=[_spanyi_row()]) as run:
        out = json.loads(dispatch_email(
            "baker_email_search",
            {"query": "Spanyi hearing 10 June", "provider": "store"},
        ))

    assert out["provider"] == "store"
    assert out["match_count"] >= 1
    blob = json.dumps(out).lower()
    assert "spanyi" in blob
    assert "10 june 2026" in blob
    assert out["matches"][0]["source"] == "graph"
    run.assert_called_once()


def test_email_search_tokenizes_multiterm():
    """The match MUST tokenize — each term ANDed, OR across fields. This is the
    core fix: whole-query ILIKE silently misses 'Spanyi hearing 10 June'."""
    from tools.email import _build_email_search_sql, _MATCH_FIELDS

    sql, params = _build_email_search_sql("Spanyi hearing 10 June", None, 10)

    # 4 tokens × 4 fields = 16 ILIKE params + 1 LIMIT param.
    assert sql.count("ILIKE") == 4 * len(_MATCH_FIELDS)
    assert sql.count(" AND ") == 3  # 4 token-groups joined by AND
    assert params[-1] == 10
    assert params[:16] == [
        v for tok in ("Spanyi", "hearing", "10", "June")
        for v in [f"%{tok}%"] * len(_MATCH_FIELDS)
    ]


def test_email_search_source_filter_applied():
    """provider=store with source='graph' filters to Outlook/M365 mail."""
    from tools.email import _build_email_search_sql

    sql, params = _build_email_search_sql("hearing", "graph", 5)
    assert "source = %s" in sql
    assert "graph" in params


def test_email_search_empty_query_returns_recent():
    """No query → most-recent rows (WHERE TRUE), still routed through the store."""
    from tools.email import _build_email_search_sql, dispatch_email

    sql, params = _build_email_search_sql("", None, 10)
    assert "WHERE TRUE" in sql
    assert "ILIKE" not in sql

    with patch("tools.email._run_email_query", return_value=[_spanyi_row()]) as run:
        out = json.loads(dispatch_email("baker_email_search", {"provider": "store"}))
    assert out["match_count"] >= 1
    run.assert_called_once()


def test_email_search_backend_outage_is_loud_not_empty():
    """A store OUTAGE must NOT read as 'no mail' — surface backend_unavailable."""
    from tools.email import dispatch_email

    with patch(
        "tools.email._run_email_query",
        side_effect=SearchBackendUnavailable("pg conn refused"),
    ):
        out = json.loads(dispatch_email(
            "baker_email_search",
            {"query": "Spanyi", "provider": "store"},
        ))

    assert out.get("backend_unavailable") is True
    assert out["match_count"] == 0
    # The payload must say "retry / unavailable", never imply an empty mailbox.
    assert "unavailable" in json.dumps(out).lower()


# ── baker_gmail_search: no more silent-empty ──────────────────────────────

def test_gmail_search_zero_results_carries_m365_pointer():
    """Any empty Gmail result carries a LOUD pointer to baker_email_search."""
    from tools.gmail import dispatch_gmail

    with patch(
        "triggers.email_trigger._get_gmail_service",
        return_value=_empty_gmail_service(),
    ):
        out = json.loads(dispatch_gmail(
            "baker_gmail_search",
            {"query": "from:M.Spanyi@eh.at after:2026/06/05"},
        ))

    assert out["match_count"] == 0
    blob = json.dumps(out).lower()
    assert "m365" in blob or "outlook" in blob
    assert "baker_email_search" in blob


def test_gmail_search_brisengroup_scoped_warns_even_on_hit():
    """A brisengroup-scoped query is M365-territory — warn regardless of hits."""
    from tools.gmail import dispatch_gmail

    with patch(
        "triggers.email_trigger._get_gmail_service",
        return_value=_empty_gmail_service(),
    ):
        out = json.loads(dispatch_gmail(
            "baker_gmail_search",
            {"query": "from:dvallen@brisengroup.com"},
        ))

    blob = json.dumps(out).lower()
    assert "brisengroup" in blob
    assert "baker_email_search" in blob


# ── staleness watchdog ─────────────────────────────────────────────────────

def test_graph_mail_in_stale_watchdog():
    """graph_mail_poll is monitored so a silent ingestion death gets flagged."""
    from triggers.sentinel_health import _WATERMARK_MAX_AGE

    assert "graph_mail_poll" in _WATERMARK_MAX_AGE
    # Mail can be quiet; allow some slack but not unbounded.
    assert 1 <= _WATERMARK_MAX_AGE["graph_mail_poll"] <= 12
