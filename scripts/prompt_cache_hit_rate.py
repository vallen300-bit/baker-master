"""Compute 24h cache hit rate from baker_actions. Alert Director via Slack if <60%.

Usage: python3 scripts/prompt_cache_hit_rate.py [--hours N] [--threshold 0.60] [--alert]

Reads baker_actions where action_type='claude:cache_usage' within the
time window, aggregates (cache_read_tokens / (cache_read + input_tokens))
weighted by total token volume, prints summary table + overall rate.

If --alert supplied AND overall rate < threshold, fires a Slack DM to the
Director's channel via the existing Slack-notifier module. If the notifier
helper is missing, the alert falls back to stderr print.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DIRECTOR_DM_CHANNEL = "D0AFY28N030"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--hours", type=int, default=24)
    p.add_argument("--threshold", type=float, default=0.60)
    p.add_argument("--alert", action="store_true",
                   help="Fire Slack alert if below threshold")
    args = p.parse_args()

    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack._get_global_instance()
    if store is None:
        print("Store unavailable", file=sys.stderr)
        return 1

    conn = store._get_conn()
    if conn is None:
        print("DB connection unavailable", file=sys.stderr)
        return 1

    rows = []
    try:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                SELECT
                  COALESCE(payload->>'call_site', 'unknown') AS site,
                  SUM((payload->>'input_tokens')::int) AS input_tok,
                  SUM((payload->>'cache_read_tokens')::int) AS cache_read_tok,
                  SUM((payload->>'cache_write_tokens')::int) AS cache_write_tok,
                  COUNT(*) AS n_calls
                FROM baker_actions
                WHERE action_type = 'claude:cache_usage'
                  AND created_at > NOW() - (INTERVAL '1 hour' * %s)
                GROUP BY site
                ORDER BY cache_read_tok DESC
                LIMIT 50
                """,
                (args.hours,),
            )
            rows = cur.fetchall()
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            print(f"Query failed: {e}", file=sys.stderr)
            return 1
        finally:
            cur.close()
    finally:
        store._put_conn(conn)

    if not rows:
        print(f"No cache_usage rows in last {args.hours}h - has telemetry landed?")
        return 0

    total_input = sum(r[1] or 0 for r in rows)
    total_cache_read = sum(r[2] or 0 for r in rows)
    total_cache_write = sum(r[3] or 0 for r in rows)
    denom = total_input + total_cache_read
    overall = total_cache_read / denom if denom > 0 else 0.0

    print(f"Cache hit rate over {args.hours}h: {overall:.2%}")
    print(f"Total input tokens: {total_input:,}")
    print(f"Total cache-read tokens: {total_cache_read:,}")
    print(f"Total cache-write tokens: {total_cache_write:,}")
    print()
    print("Per call_site (top 10):")
    for site, inp, cread, cwrite, n in rows[:10]:
        inp = inp or 0
        cread = cread or 0
        site_rate = cread / (cread + inp) if (cread + inp) > 0 else 0.0
        print(f"  {site_rate:6.2%}  n={n:4d}  in={inp:,}  cache_read={cread:,}  site={site}")

    if args.alert and overall < args.threshold:
        _slack_alert(overall, args.threshold, args.hours, rows[:5])

    return 0


def _slack_alert(overall, threshold, hours, top_rows):
    msg = (
        f":warning: Prompt-cache hit rate below target.\n"
        f"Last {hours}h: *{overall:.2%}* (target >={threshold:.0%}).\n"
        f"Top sites by traffic:\n"
        + "\n".join(
            f"- `{s}` - n={n}, read={(cr or 0):,}"
            for s, _inp, cr, _cw, n in top_rows
        )
    )
    # Preferred: dedicated Director DM helper (not present as of 2026-04-24).
    try:
        from outputs.slack_notifier import post_to_director_dm  # type: ignore
        post_to_director_dm(msg)
        return
    except Exception:
        pass
    # Fallback: generic channel post to Director's DM channel.
    try:
        from outputs.slack_notifier import post_to_channel
        ok = post_to_channel(DIRECTOR_DM_CHANNEL, msg)
        if ok:
            return
    except Exception as e:
        print(f"Slack post failed: {e}", file=sys.stderr)
    # Last-resort fallback: stderr.
    print("ALERT (Slack unavailable):\n" + msg, file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
