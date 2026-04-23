"""Backfill PM state from recent conversation_memory history.

BRIEF_PM_SIDEBAR_STATE_WRITE_1 D4. Iterates over conversation_memory rows in a
rolling window and runs the same Opus extraction that the sidebar hook (D2)
runs on live scans. Writes to pm_project_state with mutation_source=
'backfill_YYYY-MM-DD'. Idempotent via pm_backfill_processed(pm_slug,
conversation_id) PK.

Usage:
    python3 scripts/backfill_pm_state.py <pm_slug> [--since 14d] [--dry-run]

Requires: DATABASE_URL env var (read by SentinelStoreBack).
"""
import argparse
import logging
import os
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("backfill_pm_state")


def _parse_since(since: str) -> int:
    m = re.match(r"^(\d+)d$", since)
    if not m:
        raise ValueError(f"--since must be Nd (e.g. 14d); got {since}")
    return int(m.group(1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pm_slug", help="e.g. ao_pm, movie_am")
    ap.add_argument("--since", default="14d",
                    help="lookback window, Nd format (default 14d)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print matched rows without extracting")
    args = ap.parse_args()

    days = _parse_since(args.since)

    from orchestrator.capability_runner import (
        PM_REGISTRY,
        extract_and_update_pm_state,
    )
    if args.pm_slug not in PM_REGISTRY:
        raise SystemExit(f"Unknown pm_slug: {args.pm_slug}")

    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    if not conn:
        raise SystemExit("DB connection unavailable")

    cur = None
    try:
        cur = conn.cursor()

        # Match set: project match (post-D3) OR regex on question (pre-D3 rows
        # labeled 'general'). Regex sources are the PM's own
        # signal_orbit_patterns + signal_keyword_patterns — no new regex to
        # maintain.
        cfg = PM_REGISTRY[args.pm_slug]
        orbit = cfg.get("signal_orbit_patterns", [])
        keyword = cfg.get("signal_keyword_patterns", [])
        patterns = orbit + keyword
        regex_alt = "|".join(f"({p})" for p in patterns) if patterns else None

        cur.execute("""
            SELECT id, question, answer, project, created_at
            FROM conversation_memory
            WHERE created_at > NOW() - (%s || ' days')::interval
              AND answer IS NOT NULL
              AND LENGTH(answer) > 100
            ORDER BY created_at ASC
            LIMIT 500
        """, (str(int(days)),))
        rows = cur.fetchall()

        cur.execute(
            "SELECT conversation_id FROM pm_backfill_processed "
            "WHERE pm_slug = %s LIMIT 500",
            (args.pm_slug,),
        )
        processed_ids = {r[0] for r in cur.fetchall()}

        tag = f"backfill_{datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
        matched = 0
        skipped = 0
        extracted = 0

        for row_id, question, answer, project, created_at in rows:
            if row_id in processed_ids:
                skipped += 1
                continue

            is_match = False
            if project == args.pm_slug:
                is_match = True
            elif regex_alt:
                combined = f"{question or ''} {(answer or '')[:500]}"
                try:
                    if re.search(regex_alt, combined, re.IGNORECASE):
                        is_match = True
                except re.error as _re_e:
                    logger.warning(f"regex failed for {args.pm_slug}: {_re_e}")

            if not is_match:
                continue

            matched += 1
            if args.dry_run:
                logger.info(
                    f"DRY-RUN match: conv#{row_id} [{created_at}] "
                    f"{(question or '')[:80]}"
                )
                continue

            result = extract_and_update_pm_state(
                pm_slug=args.pm_slug,
                question=question or "",
                answer=answer or "",
                mutation_source=tag,
                conversation_id=row_id,
            )
            if result:
                extracted += 1
                cur.execute("""
                    INSERT INTO pm_backfill_processed
                        (pm_slug, conversation_id, mutation_source)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (pm_slug, conversation_id) DO NOTHING
                """, (args.pm_slug, row_id, tag))
                conn.commit()
                logger.info(
                    f"Extracted conv#{row_id} → {args.pm_slug} "
                    f"(summary: {result['summary'][:60]})"
                )
            else:
                logger.warning(
                    f"Extract returned None for conv#{row_id} "
                    f"— not recorded as processed"
                )

        logger.info(
            f"Backfill done [{args.pm_slug}][{args.since}]: "
            f"scanned {len(rows)}, matched {matched}, "
            f"skipped-already-processed {skipped}, extracted {extracted}"
        )
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(f"Backfill failed: {e}")
        raise
    finally:
        if cur:
            cur.close()
        store._put_conn(conn)


if __name__ == "__main__":
    main()
