"""
EMAIL_READ_REST_FALLBACK_1 (gate-3 rework): pure-function tests for the two
markdown formatters behind GET /api/emails/search and GET /api/emails/read.

These exercise the formatters against EVERY output shape tools.email can return
(store / graph / provider=all nested results / store outage / store-vs-graph read)
so the md path never renders a false "no mail" and graph reads populate
From/Date/Source. No DB and no FastAPI app are constructed — the formatters are
pure dict->str functions, imported with the same skip-guard the rest of the
dashboard-endpoint tests use (test_iphone_export_endpoint.py).
"""

from __future__ import annotations

from pathlib import Path

import pytest

_DASHBOARD_SRC = Path(__file__).resolve().parent.parent / "outputs" / "dashboard.py"


def _dashboard_importable() -> bool:
    try:
        import outputs.dashboard  # noqa: F401
        return True
    except Exception:
        return False


_skip_without_dashboard = pytest.mark.skipif(
    not _dashboard_importable(),
    reason="outputs.dashboard unimportable (Python 3.9 PEP-604 chain — clears on 3.10+)",
)


# ─── Source-level checks (always run, no import) ────────────────────────────


def test_formatters_and_routes_present_in_source():
    src = _DASHBOARD_SRC.read_text(encoding="utf-8")
    assert "def _format_email_search_md(" in src
    assert "def _format_email_read_md(" in src
    assert '@app.get("/api/emails/search"' in src
    assert '@app.get("/api/emails/read"' in src


def test_search_formatter_handles_nested_results_in_source():
    # Guard against a regression back to the store-only formatter that rendered
    # provider=all / graph as false-empty.
    src = _DASHBOARD_SRC.read_text(encoding="utf-8")
    assert 'data.get("results")' in src, "search md must fall back to nested results"


# ─── Behavior checks (import-gated) ─────────────────────────────────────────

# Fixtures mirror the real tools.email output shapes:
#   _store_search  -> {provider, query, match_count, matches:[_row_to_match]}
#   _graph_search  -> {provider, query, match_count, matches:[{message_id,sender,subject,date,snippet}]}
#   _search(all)   -> {provider:"all", query, match_count, results:{store, graph}}
#   _read(store)   -> {provider:"store", message:{...full_body, sender_name, received_date, source}}
#   _read(graph)   -> {provider:"graph", message_id, sender, subject, date, body}  (top level)

_STORE_MATCH = {
    "message_id": "AAStore=1",
    "sender": "Balazs Kovacs",
    "sender_email": "balazs@example.com",
    "subject": "Annaberg Status - Closing actions",
    "date": "2026-06-29 09:12:00",
    "source": "graph",
    "snippet": "Closing actions for Annaberg, see VDR index.",
}
_GRAPH_MATCH = {
    "message_id": "AAGraph=2",
    "sender": "Aukera ESG",
    "subject": "ESG Questionnaire",
    "date": "2026-06-29T10:00:00Z",
    "snippet": "Please complete the attached questionnaire.",
}


@_skip_without_dashboard
def test_store_matches_render():
    import outputs.dashboard as dash
    out = dash._format_email_search_md(
        {"provider": "store", "query": "Annaberg", "match_count": 1, "matches": [_STORE_MATCH]}
    )
    assert "No emails matched" not in out
    assert "Annaberg Status - Closing actions" in out
    assert "Balazs Kovacs" in out
    assert "AAStore=1" in out
    assert "[graph]" in out  # source rendered
    assert "VDR index" in out  # snippet rendered


@_skip_without_dashboard
def test_graph_matches_render():
    import outputs.dashboard as dash
    out = dash._format_email_search_md(
        {"provider": "graph", "query": "ESG", "match_count": 1, "matches": [_GRAPH_MATCH]}
    )
    assert "No emails matched" not in out
    assert "ESG Questionnaire" in out
    assert "Aukera ESG" in out
    assert "AAGraph=2" in out


@_skip_without_dashboard
def test_provider_all_nested_results_render_both():
    import outputs.dashboard as dash
    data = {
        "provider": "all",
        "query": "x",
        "match_count": 2,
        "results": {
            "store": {"provider": "store", "match_count": 1, "matches": [_STORE_MATCH]},
            "graph": {"provider": "graph", "match_count": 1, "matches": [_GRAPH_MATCH]},
        },
    }
    out = dash._format_email_search_md(data)
    assert "No emails matched" not in out  # the bug we are fixing
    assert "2 match(es)" in out
    assert "Annaberg Status - Closing actions" in out  # store match
    assert "ESG Questionnaire" in out  # graph match


@_skip_without_dashboard
def test_provider_all_store_outage_surfaces_loudly_not_false_empty():
    import outputs.dashboard as dash
    # Store sub is unavailable; only the SUB carries the flag (no top-level).
    data = {
        "provider": "all",
        "query": "x",
        "results": {
            "store": {"provider": "store", "backend_unavailable": True, "matches": []},
            "graph": {"provider": "graph", "match_count": 1, "matches": [_GRAPH_MATCH]},
        },
    }
    out = dash._format_email_search_md(data)
    assert "backend unavailable" in out.lower()
    assert "No emails matched" not in out  # must NOT read outage as "no mail"


@_skip_without_dashboard
def test_read_store_message_wrapper_renders():
    import outputs.dashboard as dash
    data = {
        "provider": "store",
        "message": {
            "message_id": "AAStore=1",
            "subject": "Annaberg Status - Closing actions",
            "sender_name": "Balazs Kovacs",
            "sender_email": "balazs@example.com",
            "received_date": "2026-06-29 09:12:00",
            "source": "graph",
            "full_body": "Full body of the Annaberg closing email.",
        },
    }
    out = dash._format_email_read_md(data)
    assert "# Annaberg Status - Closing actions" in out
    assert "From: Balazs Kovacs" in out
    assert "Source: graph" in out
    assert "2026-06-29 09:12:00" in out
    assert "Full body of the Annaberg closing email." in out


@_skip_without_dashboard
def test_read_graph_top_level_fields_populate():
    import outputs.dashboard as dash
    # Graph read returns fields at top level (no "message" wrapper).
    data = {
        "provider": "graph",
        "message_id": "AAGraph=2",
        "sender": "Aukera ESG",
        "subject": "ESG Questionnaire",
        "date": "2026-06-29T10:00:00Z",
        "body": "Body text from live Graph read.",
    }
    out = dash._format_email_read_md(data)
    assert "# ESG Questionnaire" in out
    assert "From: Aukera ESG" in out  # NOT "From: ?"
    assert "From: ?" not in out
    assert "2026-06-29T10:00:00Z" in out  # Date populated, NOT "?"
    assert "Source: graph" in out  # falls back to provider
    assert "Body text from live Graph read." in out


@_skip_without_dashboard
def test_read_store_miss_hint_renders():
    import outputs.dashboard as dash
    data = {
        "error": "email not found in email_messages",
        "message_id": "AAMiss=3",
        "hint": "try provider=graph for a very recent message not yet ingested.",
    }
    out = dash._format_email_read_md(data)
    assert "email not found" in out
    assert "AAMiss=3" in out
    assert "provider=graph" in out
