"""
COCKPIT_REFERENCE_DESK_1 Fix 3 — one-off bulk-expire of stale cockpit signals.

The landing cockpit carried 666 pending alerts (16k+ dismissed) and past-due
"active" deadlines — alarm fatigue that hides every real fire. This one-off expires
the auto-generated noise while PRESERVING genuine Director signals.

PROTECTED SET (lead #7515 ruling on b4 #7514, codex G3 M1 / #7513):
  - alerts: tier = 1 (every genuine fire), and tier>1 rows that are action_required
    AND come from a NON-auto source (a real user/Director flag).
  - deadlines: is_critical rows.

AUTO-vs-USER action_required finding (documented per lead bind 2 — data-hygiene
follow-up parked with lead): in prod, `action_required=TRUE` is NOT a Director flag —
it is auto-set by generator sources (pipeline: 194, deadline_cadence: 53, detectors: 3
of the 250 pending TRUE rows). The brief protected action_required assuming
"user-flagged"; literal protection would preserve the very noise the Director ratified
killing. So we protect action_required ONLY from non-auto sources, and expire tier>1
auto-generated rows regardless of their auto action_required. The auto-default itself
is a defect (a separate brief candidate).

EXPIRE PREDICATE (alerts) = the complement of the protected set:
  tier > 1 AND (action_required IS NOT TRUE OR source IN <auto generators>).
Read-only prod probe 2026-07-08: expires 633 of 668 pending → 35 remain (all tier-1
genuine fires). Not a schema migration, not recurring (recurring hygiene is a separate
decision). Run once, by hand, against prod.

Usage:
  python3 scripts/cockpit_shrink_cleanup.py --dry-run   # preview counts + tally, no write
  python3 scripts/cockpit_shrink_cleanup.py --run        # execute inside a txn + commit
"""
import argparse
import logging
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("cockpit_shrink_cleanup")

_EXIT_REASON = "cockpit_shrink_bulk_expire_20260708"

# Auto-generator sources whose action_required is an auto-default, not a Director
# flag — their tier>1 rows expire regardless of action_required (lead #7515).
_AUTO_SOURCES = ("pipeline", "deadline_cadence", "financial_detector", "risk_detector")
_AUTO_SOURCES_SQL = "(" + ",".join(f"'{s}'" for s in _AUTO_SOURCES) + ")"

# Rows matched by the cleanup — shared by preview (SELECT), tally, and execute
# (UPDATE) so the number previewed is exactly the number changed. Protects tier=1
# (every genuine fire) and tier>1 action_required from a NON-auto source.
_ALERTS_WHERE = f"""
    status = 'pending'
    AND tier > 1
    AND (action_required IS NOT TRUE OR source IN {_AUTO_SOURCES_SQL})
"""
_DEADLINES_WHERE = """
    status = 'active'
    AND due_date < now() - interval '2 days'
    AND (is_critical IS NOT TRUE)
"""


def get_conn():
    # Direct psycopg2 against DATABASE_URL — a maintenance one-off must not bootstrap
    # SentinelStoreBack (it pulls in the Voyage embedding client). Dry-run only SELECTs,
    # so a read-only role URL is enough to preview; --run needs a read-write URL.
    import os
    import psycopg2
    url = os.environ.get("DATABASE_URL")
    if not url:
        return None
    return psycopg2.connect(url)


def _count(cur, table, where):
    cur.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}")
    return cur.fetchone()[0]


def _status_dist(cur, table):
    cur.execute(f"SELECT status, COUNT(*) FROM {table} GROUP BY status ORDER BY 2 DESC LIMIT 10")
    return cur.fetchall()


def _alerts_tally_by_source_tier(cur):
    """Per-source / per-tier tally of the alerts being expired (lead bind 1 — audit
    trail). Also reports action_required split so the auto-vs-user finding is visible."""
    cur.execute(f"""
        SELECT source, tier, (action_required IS TRUE) AS action_required, COUNT(*)
        FROM alerts WHERE {_ALERTS_WHERE}
        GROUP BY source, tier, (action_required IS TRUE)
        ORDER BY COUNT(*) DESC
        LIMIT 40
    """)
    return cur.fetchall()


def run(dry_run=True):
    conn = get_conn()
    if not conn:
        logger.error("No DB connection (is DATABASE_URL set?)")
        return 1

    try:
        cur = conn.cursor()

        # BEFORE snapshot + per-source/tier expiry tally (audit trail).
        alerts_match = _count(cur, "alerts", _ALERTS_WHERE)
        deadlines_match = _count(cur, "deadlines", _DEADLINES_WHERE)
        pending_total = _count(cur, "alerts", "status = 'pending'")
        logger.info("BEFORE: alerts status distribution: %s", _status_dist(cur, "alerts"))
        logger.info("BEFORE: deadlines status distribution: %s", _status_dist(cur, "deadlines"))
        logger.info("Alerts expiry tally (source, tier, action_required, count):")
        for row in _alerts_tally_by_source_tier(cur):
            logger.info("  %-24s tier=%s action_required=%-5s count=%s", row[0], row[1], row[2], row[3])
        logger.info(
            "Matched to expire — alerts: %d (of %d pending → %d remain), deadlines: %d",
            alerts_match, pending_total, pending_total - alerts_match, deadlines_match,
        )

        if dry_run:
            logger.info("DRY-RUN: no rows written. Re-run with --run to commit.")
            return 0

        # EXECUTE inside a transaction. psycopg2 opens an implicit txn; commit at end.
        cur.execute(f"""
            UPDATE alerts
               SET status = 'expired',
                   exit_reason = %s
             WHERE {_ALERTS_WHERE}
        """, (_EXIT_REASON,))
        alerts_expired = cur.rowcount

        cur.execute(f"""
            UPDATE deadlines
               SET status = 'expired'
             WHERE {_DEADLINES_WHERE}
        """)
        deadlines_expired = cur.rowcount

        logger.info("EXPIRED — alerts: %d, deadlines: %d (committing)", alerts_expired, deadlines_expired)
        conn.commit()

        # AFTER snapshot
        logger.info("AFTER: alerts status distribution: %s", _status_dist(cur, "alerts"))
        logger.info("AFTER: deadlines status distribution: %s", _status_dist(cur, "deadlines"))
        cur.close()
        return 0
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error("cockpit_shrink_cleanup failed (rolled back): %s", e)
        return 1
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="COCKPIT_REFERENCE_DESK_1 Fix 3 bulk-expire")
    grp = ap.add_mutually_exclusive_group()
    grp.add_argument("--dry-run", action="store_true", help="preview counts + tally, no write (default)")
    grp.add_argument("--run", action="store_true", help="execute the expiry inside a transaction + commit")
    args = ap.parse_args()
    # Default to dry-run unless --run is explicitly passed.
    sys.exit(run(dry_run=not args.run))
