"""
COCKPIT_REFERENCE_DESK_1 Fix 3 — one-off bulk-expire of stale cockpit signals.

The landing cockpit carried 660 pending alerts (16,356 already dismissed) and 13
"active" deadlines already past due — alarm fatigue that makes every real fire
invisible. This one-off expires the stale, low-severity, un-flagged backlog while
PRESERVING everything a human might have flagged:

  - alerts: keep tier-1 and action_required rows; only expire pending, tier>1,
    non-action-required alerts older than 14 days.
  - deadlines: keep is_critical rows; only expire active, non-critical deadlines
    that are >2 days past due.

This is NOT a schema migration and NOT a recurring job (recurring hygiene is a
separate decision). Run once, by hand, against prod.

Usage:
  python3 scripts/cockpit_shrink_cleanup.py --dry-run   # preview counts, no write
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

# Rows matched by the cleanup — shared by preview (SELECT COUNT) and execute
# (UPDATE) so the number previewed is exactly the number changed.
_ALERTS_WHERE = """
    status = 'pending'
    AND created_at < now() - interval '14 days'
    AND tier > 1
    AND (action_required IS NOT TRUE)
"""
_DEADLINES_WHERE = """
    status = 'active'
    AND due_date < now() - interval '2 days'
    AND (is_critical IS NOT TRUE)
"""


def get_conn():
    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack._get_global_instance()
    return store, store._get_conn()


def _count(cur, table, where):
    cur.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}")
    return cur.fetchone()[0]


def _status_dist(cur, table):
    cur.execute(f"SELECT status, COUNT(*) FROM {table} GROUP BY status ORDER BY 2 DESC LIMIT 10")
    return cur.fetchall()


def run(dry_run=True):
    store, conn = get_conn()
    if not conn:
        logger.error("No DB connection (is DATABASE_URL set?)")
        return 1

    try:
        cur = conn.cursor()

        # BEFORE snapshot
        alerts_match = _count(cur, "alerts", _ALERTS_WHERE)
        deadlines_match = _count(cur, "deadlines", _DEADLINES_WHERE)
        logger.info("BEFORE: alerts status distribution: %s", _status_dist(cur, "alerts"))
        logger.info("BEFORE: deadlines status distribution: %s", _status_dist(cur, "deadlines"))
        logger.info("Matched to expire — alerts: %d, deadlines: %d", alerts_match, deadlines_match)

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
        store._put_conn(conn)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="COCKPIT_REFERENCE_DESK_1 Fix 3 bulk-expire")
    grp = ap.add_mutually_exclusive_group()
    grp.add_argument("--dry-run", action="store_true", help="preview counts, no write (default)")
    grp.add_argument("--run", action="store_true", help="execute the expiry inside a transaction + commit")
    args = ap.parse_args()
    # Default to dry-run unless --run is explicitly passed.
    sys.exit(run(dry_run=not args.run))
