#!/usr/bin/env python3
"""
Sentinel AI — Store-Back Verification Script
Tests all PostgreSQL operations against the Neon cloud database.

Usage: python3 scripts/test_storeback.py
"""
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
import psycopg2.extras
from config.settings import config

PASS = "\033[92m PASS\033[0m"
FAIL = "\033[91m FAIL\033[0m"

test_trigger_id = None
test_decision_id = None
test_alert_id = None


def check(label: str, condition: bool, detail: str = ""):
    status = PASS if condition else FAIL
    print(f"  [{status}] {label}" + (f"  ({detail})" if detail else ""))
    return condition


def main():
    print("=" * 60)
    print("Sentinel Store-Back — Verification Suite")
    print("=" * 60)
    passed = 0
    total = 9

    # -------------------------------------------------------
    # 1. Connect to PostgreSQL
    # -------------------------------------------------------
    print("\n1. Connect to PostgreSQL")
    conn = None
    try:
        conn = psycopg2.connect(**config.postgres.dsn_params)
        if check("Connection established", conn is not None, config.postgres.host):
            passed += 1
    except Exception as e:
        check("Connection established", False, str(e))
        print("\n  FATAL: Cannot connect to PostgreSQL. Aborting.")
        sys.exit(1)

    cur = conn.cursor()

    # -------------------------------------------------------
    # 2. Verify all 6 tables exist
    # -------------------------------------------------------
    print("\n2. Verify all 6 tables exist")
    cur.execute("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public' ORDER BY table_name
    """)
    tables = [row[0] for row in cur.fetchall()]
    expected = {"alerts", "contacts", "deals", "decisions", "preferences", "trigger_log"}
    found = expected.issubset(set(tables))
    if check("All 6 tables present", found, f"found: {', '.join(sorted(tables))}"):
        passed += 1

    # -------------------------------------------------------
    # 3. Verify seed data (10 contacts)
    # -------------------------------------------------------
    print("\n3. Verify seed data")
    cur.execute("SELECT count(*) FROM contacts")
    count = cur.fetchone()[0]
    if check("10 seed contacts exist", count >= 10, f"count={count}"):
        passed += 1

    # -------------------------------------------------------
    # 4. Insert a test trigger_log entry
    # -------------------------------------------------------
    print("\n4. Insert test trigger_log entry")
    global test_trigger_id
    try:
        cur.execute(
            """
            INSERT INTO trigger_log (type, source_id, content, priority, received_at)
            VALUES ('test', 'test-verification-script', 'Test trigger from verification', 'low', NOW())
            RETURNING id
            """,
        )
        test_trigger_id = cur.fetchone()[0]
        conn.commit()
        if check("Trigger inserted", test_trigger_id is not None, f"id={test_trigger_id}"):
            passed += 1
    except Exception as e:
        conn.rollback()
        check("Trigger inserted", False, str(e))

    # -------------------------------------------------------
    # 5. Insert a test decision
    # -------------------------------------------------------
    print("\n5. Insert test decision")
    global test_decision_id
    try:
        cur.execute(
            """
            INSERT INTO decisions (decision, reasoning, confidence, trigger_type, created_at)
            VALUES ('Test decision', 'Verification script test', 'high', 'test', NOW())
            RETURNING id
            """,
        )
        test_decision_id = cur.fetchone()[0]
        conn.commit()
        if check("Decision inserted", test_decision_id is not None, f"id={test_decision_id}"):
            passed += 1
    except Exception as e:
        conn.rollback()
        check("Decision inserted", False, str(e))

    # -------------------------------------------------------
    # 6. Create and resolve a test alert
    # -------------------------------------------------------
    print("\n6. Create and resolve test alert")
    global test_alert_id
    try:
        cur.execute(
            """
            INSERT INTO alerts (tier, title, body, action_required, trigger_id, created_at)
            VALUES (3, 'Test alert', 'Verification script test alert', FALSE, %s, NOW())
            RETURNING id
            """,
            (test_trigger_id,),
        )
        test_alert_id = cur.fetchone()[0]
        conn.commit()

        # Resolve it
        cur.execute(
            "UPDATE alerts SET status = 'resolved', resolved_at = NOW() WHERE id = %s",
            (test_alert_id,),
        )
        conn.commit()

        # Verify resolved
        cur.execute("SELECT status FROM alerts WHERE id = %s", (test_alert_id,))
        status = cur.fetchone()[0]
        if check("Alert created and resolved", status == "resolved", f"id={test_alert_id}, status={status}"):
            passed += 1
    except Exception as e:
        conn.rollback()
        check("Alert created and resolved", False, str(e))

    # -------------------------------------------------------
    # 7. Upsert a contact with behavioral update
    # -------------------------------------------------------
    print("\n7. Upsert contact with behavioral update")
    try:
        # Update existing seed contact
        cur.execute(
            """
            UPDATE contacts
            SET communication_style = 'formal', response_pattern = 'fast_responder',
                last_contact = NOW(), updated_at = NOW()
            WHERE name = 'Andrey Oskolkov'
            RETURNING id, name, communication_style
            """,
        )
        row = cur.fetchone()
        conn.commit()
        if check(
            "Contact behavioral update",
            row is not None and row[2] == "formal",
            f"name={row[1]}, style={row[2]}" if row else "not found",
        ):
            passed += 1
    except Exception as e:
        conn.rollback()
        check("Contact behavioral update", False, str(e))

    # -------------------------------------------------------
    # 8. Fuzzy match a contact name
    # -------------------------------------------------------
    print("\n8. Fuzzy match contact name")
    try:
        cur.execute(
            """
            SELECT name, similarity(name, %s) AS sim
            FROM contacts
            WHERE similarity(name, %s) > 0.3
            ORDER BY similarity(name, %s) DESC
            LIMIT 1
            """,
            ("Andrey Osk", "Andrey Osk", "Andrey Osk"),
        )
        row = cur.fetchone()
        if check(
            "Fuzzy match works",
            row is not None and "Andrey" in row[0],
            f"query='Andrey Osk' → '{row[0]}' (sim={row[1]:.2f})" if row else "no match",
        ):
            passed += 1
    except Exception as e:
        check("Fuzzy match works", False, str(e))

    # -------------------------------------------------------
    # 9. Clean up test data
    # -------------------------------------------------------
    print("\n9. Clean up test data")
    try:
        cleaned = 0
        if test_alert_id:
            cur.execute("DELETE FROM alerts WHERE id = %s", (test_alert_id,))
            cleaned += cur.rowcount
        if test_decision_id:
            cur.execute("DELETE FROM decisions WHERE id = %s", (test_decision_id,))
            cleaned += cur.rowcount
        if test_trigger_id:
            cur.execute("DELETE FROM trigger_log WHERE id = %s", (test_trigger_id,))
            cleaned += cur.rowcount
        # Revert contact update
        cur.execute(
            """
            UPDATE contacts SET communication_style = NULL, response_pattern = NULL
            WHERE name = 'Andrey Oskolkov'
            """,
        )
        conn.commit()
        if check("Test data cleaned up", cleaned >= 3, f"deleted {cleaned} rows"):
            passed += 1
    except Exception as e:
        conn.rollback()
        check("Test data cleaned up", False, str(e))

    # -------------------------------------------------------
    # Summary
    # -------------------------------------------------------
    cur.close()
    conn.close()

    print(f"\n{'=' * 60}")
    color = "\033[92m" if passed == total else "\033[93m"
    print(f"  Result: {color}{passed}/{total} checks passed\033[0m")
    print(f"{'=' * 60}")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
