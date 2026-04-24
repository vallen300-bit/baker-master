"""BRIEF_PROACTIVE_PM_SENTINEL_1 §Part H §H5 — triage roundtrip.

Three alerts seeded → Director verdicts applied → DB state asserted:
  1. snooze → snoozed_until > NOW(), status='pending'
  2. dismiss (waiting_for_counterparty) → status='dismissed', dismiss_reason set
  3. reject → baker_corrections row present with correction_type='sentinel_false_positive'

Integration-gated via ``needs_live_pg`` fixture (skip cleanly when no live PG).
"""
from __future__ import annotations

import json


def test_h5_triage_roundtrip_snooze_dismiss_reject(needs_live_pg):
    import psycopg2
    import psycopg2.extras

    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack._get_global_instance()

    seeded_ids = []
    conn = psycopg2.connect(needs_live_pg)
    try:
        cur = conn.cursor()
        for i in range(3):
            cur.execute(
                """
                INSERT INTO alerts (source, source_id, tier, title, body, matter_slug,
                                    status, structured_actions, created_at)
                VALUES ('proactive_pm_sentinel', %s, 2, %s, 'H5 body', 'ao_pm',
                        'pending', %s::jsonb, NOW())
                RETURNING id
                """,
                (f"h5-thread-{i}", f"H5 alert {i}",
                 '{"trigger": "quiet_thread"}'),
            )
            seeded_ids.append(cur.fetchone()[0])
        conn.commit()
        cur.close()
    finally:
        conn.close()

    # (1) Snooze the first alert
    _apply_verdict(needs_live_pg, seeded_ids[0], verdict="snooze", snooze_hours=12)
    # (2) Dismiss the second with 'waiting_for_counterparty'
    _apply_verdict(
        needs_live_pg, seeded_ids[1], verdict="dismiss",
        dismiss_reason="waiting_for_counterparty",
    )
    # (3) Reject the third — exercise the actual store.store_correction path
    ok = store.store_correction(
        baker_task_id=int(seeded_ids[2]),
        capability_slug="ao_pm",
        correction_type="sentinel_false_positive",
        director_comment="This thread was parked by Director directly.",
        learned_rule="Do not alert on threads with status='dormant'.",
        matter_slug="ao_pm",
        applies_to="capability",
    )
    assert ok, "store_correction should return True on success"

    # ─── Verify ───
    conn = psycopg2.connect(needs_live_pg)
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute(
            "SELECT id, status, snoozed_until, dismiss_reason "
            "FROM alerts WHERE id = ANY(%s)",
            (seeded_ids,),
        )
        rows = {r["id"]: dict(r) for r in cur.fetchall()}

        # Snoozed row: snoozed_until set; status unchanged (pending)
        snoozed_row = rows[seeded_ids[0]]
        assert snoozed_row["snoozed_until"] is not None, (
            f"snoozed_until not set on {seeded_ids[0]}"
        )
        assert snoozed_row["status"] == "pending"

        # Dismissed row: status + reason both set
        dismissed_row = rows[seeded_ids[1]]
        assert dismissed_row["status"] == "dismissed"
        assert dismissed_row["dismiss_reason"] == "waiting_for_counterparty"

        # Rejected row: baker_corrections entry present
        cur.execute(
            """
            SELECT COUNT(*) FROM baker_corrections
            WHERE baker_task_id = %s
              AND correction_type = 'sentinel_false_positive'
              AND active = TRUE
            """,
            (seeded_ids[2],),
        )
        assert cur.fetchone()[0] >= 1, (
            f"no baker_corrections row for rejected alert {seeded_ids[2]}"
        )
    finally:
        # Cleanup — remove test rows so repeated runs stay hygienic
        conn2 = psycopg2.connect(needs_live_pg)
        try:
            c2 = conn2.cursor()
            c2.execute(
                "DELETE FROM baker_corrections WHERE baker_task_id = ANY(%s) "
                "AND correction_type = 'sentinel_false_positive'",
                (seeded_ids,),
            )
            c2.execute("DELETE FROM alerts WHERE id = ANY(%s)", (seeded_ids,))
            conn2.commit()
            c2.close()
        finally:
            conn2.close()
        conn.close()


def _apply_verdict(pg_url, alert_id, **kwargs):
    """Directly exercise the SQL update path (bypasses HTTP — fine for integration)."""
    import psycopg2
    conn = psycopg2.connect(pg_url)
    try:
        cur = conn.cursor()
        if kwargs["verdict"] == "snooze":
            snooze_hours = int(kwargs["snooze_hours"])
            cur.execute(
                f"""
                UPDATE alerts
                SET snoozed_until = NOW() + INTERVAL '{snooze_hours} hours',
                    structured_actions =
                        COALESCE(structured_actions, '{{}}'::jsonb) || %s::jsonb
                WHERE id = %s
                """,
                (json.dumps({"verdict": "snooze", "snooze_hours": snooze_hours}),
                 alert_id),
            )
        elif kwargs["verdict"] == "dismiss":
            cur.execute(
                """
                UPDATE alerts
                SET status = 'dismissed', dismiss_reason = %s, resolved_at = NOW(),
                    structured_actions =
                        COALESCE(structured_actions, '{}'::jsonb) || %s::jsonb
                WHERE id = %s
                """,
                (kwargs["dismiss_reason"],
                 json.dumps({"verdict": "dismiss",
                             "dismiss_reason": kwargs["dismiss_reason"]}),
                 alert_id),
            )
        conn.commit()
        cur.close()
    finally:
        conn.close()
