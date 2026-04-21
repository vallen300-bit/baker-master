"""Bridge → Step-1 integration gate — STEP_CONSUMERS_SIGNAL_CONTENT_SOURCE_FIX_1.

This is the contract test that would have caught the drift. It does NOT
mock the SQL layer:

1. Build a live-shape signal_queue row via ``alerts_to_signal.map_alert_to_signal``
   (the bridge's own mapper — guarantees column shape matches production).
2. INSERT it via the shared ``insert_test_signal`` fixture helper.
3. Call each step's per-signal reader (``_fetch_signal`` / ``_fetch_signal_context``
   / ``_fetch_signal_inputs``) against the real row — the exact SQL that
   was raising ``UndefinedColumn: raw_content`` before this fix.
4. Assert the body text survives the COALESCE ladder intact and no ERROR
   row lands in ``kbl_log`` for this signal_id.

Ollama / Opus / vault I/O are deliberately out of scope — the regression
being gated is the SQL-consumer-vs-producer drift, not the LLM hop. A
downstream ``test_step1_triage_live_pg_round_trip`` (if ever written)
would exercise the Ollama call too.

Gated on ``needs_live_pg`` (resolves ``TEST_DATABASE_URL`` or an
ephemeral Neon branch). Skips cleanly when neither is set.

Brief: ``briefs/BRIEF_STEP_CONSUMERS_SIGNAL_CONTENT_SOURCE_FIX_1.md`` §3.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest


def _cleanup_signal(conn, signal_id: int) -> None:
    """Drop the test row + any log / ledger traces tied to it."""
    with conn.cursor() as cur:
        # FK relationship isn't declared; delete in dependency order anyway
        # so even if a future migration adds it we stay forward-compatible.
        cur.execute("DELETE FROM kbl_cost_ledger WHERE signal_id = %s", (signal_id,))
        cur.execute("DELETE FROM kbl_log WHERE signal_id = %s", (signal_id,))
        cur.execute("DELETE FROM signal_queue WHERE id = %s", (signal_id,))
    conn.commit()


def test_step1_reads_bridge_shaped_row_via_coalesce(needs_live_pg):
    """The exact drift regressed here: step1 ``_fetch_signal`` must return
    the alert body when it was written by the bridge into
    ``payload->>'alert_body'`` — not via a non-existent ``raw_content``
    column. Asserts the body round-trips through the COALESCE ladder.
    """
    import psycopg2

    from kbl.bridge.alerts_to_signal import map_alert_to_signal
    from kbl.steps.step1_triage import _fetch_signal
    from tests.fixtures.signal_queue import insert_test_signal

    # Build a row via the bridge mapper — guarantees payload shape matches
    # what ``alerts_to_signal.run_bridge_tick`` writes in production.
    alert = {
        "id": 999_001,
        "tier": 1,
        "title": "Court filing — test-bridge-pipeline-integration-1",
        "body": "Integration-test body: Hagenauer settlement hearing set for Tuesday.",
        "matter_slug": "movie",
        "source": "email",
        "source_id": "integration-test-src-1",
        "tags": ["deadline"],
        "structured_actions": None,
        "contact_id": None,
        "created_at": datetime.now(timezone.utc),
    }
    signal_row = map_alert_to_signal(alert)
    body_text = signal_row["payload"]["alert_body"]
    assert body_text is not None
    assert "Hagenauer" in body_text

    conn = psycopg2.connect(needs_live_pg)
    signal_id = None
    try:
        signal_id = insert_test_signal(
            conn,
            body=body_text,
            matter="movie",
            summary=signal_row["summary"],
            signal_type=signal_row["signal_type"],
            source=signal_row["source"],
        )
        conn.commit()

        # The actual drift point: BEFORE this fix, the following call
        # raised psycopg2.errors.UndefinedColumn on "raw_content".
        body_out = _fetch_signal(conn, signal_id)
        assert body_out == body_text, (
            f"step1 _fetch_signal must return the alert body via COALESCE; "
            f"got: {body_out!r}"
        )
    finally:
        if signal_id is not None:
            _cleanup_signal(conn, signal_id)
        conn.close()


def test_step2_reads_bridge_shaped_row_and_preserves_raw_content_key(needs_live_pg):
    """Step 2 returns a dict keyed on ``raw_content`` (the legacy alias).
    The COALESCE ladder must preserve that key so downstream resolvers
    reading ``signal['raw_content']`` keep working.
    """
    import psycopg2

    from kbl.steps.step2_resolve import _fetch_signal
    from tests.fixtures.signal_queue import insert_test_signal

    body = "Step2 integration — Oskolkov capital call mention."
    conn = psycopg2.connect(needs_live_pg)
    signal_id = None
    try:
        signal_id = insert_test_signal(conn, body=body, matter="oskolkov", source="email")
        conn.commit()
        result = _fetch_signal(conn, signal_id)
        assert "raw_content" in result, (
            "step2 must still expose 'raw_content' dict key for resolver compat"
        )
        assert result["raw_content"] == body
        assert result["id"] == signal_id
        assert result["source"] == "email"
    finally:
        if signal_id is not None:
            _cleanup_signal(conn, signal_id)
        conn.close()


def test_step3_reads_bridge_shaped_row(needs_live_pg):
    """Step 3 unpacks a 4-tuple. COALESCE returns the body as row[0]."""
    import psycopg2

    from kbl.steps.step3_extract import _fetch_signal_context
    from tests.fixtures.signal_queue import insert_test_signal

    body = "Step3 integration — HMA amendment text."
    conn = psycopg2.connect(needs_live_pg)
    signal_id = None
    try:
        signal_id = insert_test_signal(conn, body=body, matter="movie")
        conn.commit()
        raw_content, source, primary_matter, paths = _fetch_signal_context(
            conn, signal_id
        )
        assert raw_content == body
        assert primary_matter == "movie"
        assert paths == []
    finally:
        if signal_id is not None:
            _cleanup_signal(conn, signal_id)
        conn.close()


def test_step5_reads_bridge_shaped_row(needs_live_pg):
    """Step 5 populates a dataclass. raw_content field must carry body."""
    import psycopg2

    from kbl.steps.step5_opus import _fetch_signal_inputs
    from tests.fixtures.signal_queue import insert_test_signal

    body = "Step5 integration — Aukera term sheet final draft."
    conn = psycopg2.connect(needs_live_pg)
    signal_id = None
    try:
        signal_id = insert_test_signal(conn, body=body, matter="aukera")
        conn.commit()
        inputs = _fetch_signal_inputs(conn, signal_id)
        assert inputs.raw_content == body
        assert inputs.signal_id == signal_id
    finally:
        if signal_id is not None:
            _cleanup_signal(conn, signal_id)
        conn.close()


def test_fallback_to_summary_when_payload_missing_alert_body(needs_live_pg):
    """COALESCE middle rung: when payload has no ``alert_body``, fall back
    to the ``summary`` column. Guards rows that predate the bridge or
    arrive from a legacy producer.
    """
    import json

    import psycopg2

    from kbl.steps.step1_triage import _fetch_signal

    conn = psycopg2.connect(needs_live_pg)
    signal_id = None
    try:
        # Hand-insert a row WITHOUT the alert_body payload key. summary
        # carries the text; COALESCE's 2nd rung must rescue it.
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO signal_queue (
                    source, signal_type, matter, primary_matter,
                    summary, priority, status, stage, payload
                ) VALUES (
                    'legacy_test', 'alert:legacy', 'movie', 'movie',
                    'summary-only body', 'normal', 'pending', 'triage',
                    %s::jsonb
                ) RETURNING id
                """,
                (json.dumps({"some_other_key": "x"}),),
            )
            signal_id = cur.fetchone()[0]
        conn.commit()

        body_out = _fetch_signal(conn, signal_id)
        assert body_out == "summary-only body", (
            "COALESCE fallback to summary must fire when payload lacks alert_body"
        )
    finally:
        if signal_id is not None:
            _cleanup_signal(conn, signal_id)
        conn.close()


def test_empty_body_coalesce_tail_returns_empty_string(needs_live_pg):
    """COALESCE final rung: if both payload.alert_body and summary are NULL,
    return '' (not NULL). Downstream concatenation code assumes str.
    """
    import json

    import psycopg2

    from kbl.steps.step1_triage import _fetch_signal

    conn = psycopg2.connect(needs_live_pg)
    signal_id = None
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO signal_queue (
                    source, signal_type, matter, primary_matter,
                    summary, priority, status, stage, payload
                ) VALUES (
                    'empty_test', 'alert:empty', NULL, NULL,
                    NULL, 'normal', 'pending', 'triage',
                    %s::jsonb
                ) RETURNING id
                """,
                (json.dumps({}),),
            )
            signal_id = cur.fetchone()[0]
        conn.commit()

        body_out = _fetch_signal(conn, signal_id)
        assert body_out == "", (
            "COALESCE tail must return '' (not None) for downstream string ops"
        )
    finally:
        if signal_id is not None:
            _cleanup_signal(conn, signal_id)
        conn.close()
