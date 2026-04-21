"""Shared test fixture — INSERT a live-shape signal_queue row.

Introduced in STEP_CONSUMERS_SIGNAL_CONTENT_SOURCE_FIX_1 (2026-04-21).

Body text lives in ``payload->>'alert_body'`` — that's what the bridge
(``kbl/bridge/alerts_to_signal.py``) actually writes, and what the step
consumers now read via a ``COALESCE(payload->>'alert_body', summary, '')``
ladder. Hand-rolled INSERTs in other test files used to pass
``raw_content`` as a column (which doesn't exist in the live schema),
which is the exact class of drift this helper prevents — every test
that needs a realistic signal row should go through this function.

Used by:
* ``tests/test_bridge_pipeline_integration.py`` (new integration gate)
* Any future step-consumer test that seeds a row for end-to-end flow.
"""
from __future__ import annotations

import json
from typing import Any, Optional


def insert_test_signal(
    conn: Any,
    *,
    body: str = "test body",
    matter: Optional[str] = None,
    source: str = "legacy_alert",
    status: str = "pending",
    stage: str = "triage",
    priority: str = "normal",
    summary: Optional[str] = None,
    signal_type: str = "alert:email",
    extra_payload: Optional[dict] = None,
) -> int:
    """INSERT a signal_queue row in the bridge's canonical shape; return id.

    Only the columns a realistic bridge write would populate are set.
    Step-specific columns (triage_score, vedana, extracted_entities, ...)
    stay NULL so downstream step tests can exercise the full pipeline
    from Step 1. Callers needing pre-populated step-N state should
    UPDATE after calling this helper.

    The ``body`` argument is placed under ``payload['alert_body']``
    (NOT as a non-existent ``raw_content`` column). ``summary`` defaults
    to the same body text so the COALESCE fallback also resolves.
    """
    payload: dict = dict(extra_payload or {})
    payload.setdefault("alert_body", body)

    effective_summary = summary if summary is not None else body

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO signal_queue (
                source, signal_type, matter, primary_matter,
                summary, priority, status, stage, payload
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            RETURNING id
            """,
            (
                source,
                signal_type,
                matter,
                matter,
                effective_summary,
                priority,
                status,
                stage,
                json.dumps(payload),
            ),
        )
        return cur.fetchone()[0]
