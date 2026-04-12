#!/usr/bin/env python3
"""
CORTEX-PHASE-2B: One-time backfill of active deadlines + recent decisions
into cortex_obligations Qdrant collection.
Run AFTER deploy. NOT on startup (OOM anti-pattern).
Safe to re-run (upserts by deterministic hash of canonical_id).
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL not set")
    sys.exit(1)


def main():
    import psycopg2
    from models.cortex import upsert_obligation_vector

    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    # Active deadlines
    cur.execute("""
        SELECT id, description, due_date, source_type
        FROM deadlines
        WHERE status = 'active' AND description IS NOT NULL
        ORDER BY id
        LIMIT 200
    """)
    deadlines = cur.fetchall()
    print(f"Found {len(deadlines)} active deadlines to backfill")

    success = 0
    for dl_id, desc, due_date, source_type in deadlines:
        try:
            due_str = due_date.strftime("%Y-%m-%d") if due_date else None
            upsert_obligation_vector(
                canonical_id=dl_id,
                description=desc,
                category="deadline",
                due_date=due_str,
                source_agent=source_type or "backfill",
            )
            success += 1
            if success % 10 == 0:
                print(f"  Backfilled {success}/{len(deadlines)}...")
            time.sleep(0.1)  # Rate limit Voyage AI
        except Exception as e:
            print(f"  FAILED deadline #{dl_id}: {e}")

    print(f"\nDone: {success}/{len(deadlines)} deadlines backfilled to Qdrant")

    # Recent decisions (last 30 days)
    cur.execute("""
        SELECT id, decision
        FROM decisions
        WHERE created_at > NOW() - INTERVAL '30 days'
          AND decision IS NOT NULL
        ORDER BY id
        LIMIT 100
    """)
    decisions = cur.fetchall()
    print(f"\nFound {len(decisions)} recent decisions to backfill")

    d_success = 0
    for dec_id, decision_text in decisions:
        try:
            upsert_obligation_vector(
                canonical_id=dec_id,
                description=decision_text,
                category="decision",
                source_agent="backfill",
            )
            d_success += 1
            if d_success % 10 == 0:
                print(f"  Backfilled {d_success}/{len(decisions)}...")
            time.sleep(0.1)
        except Exception as e:
            print(f"  FAILED decision #{dec_id}: {e}")

    print(f"Done: {d_success}/{len(decisions)} decisions backfilled to Qdrant")
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
