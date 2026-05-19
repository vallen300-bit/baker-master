"""Backfill Director Cards for tier_b_pending Cortex cycles missing them.

Iterates cycles with status='tier_b_pending' that have a ``synthesis``
artifact but no ``director_card`` artifact, calls
``translate_to_director_card`` for each, and persists the result.

Idempotent: a cycle that already has a ``director_card`` row is skipped.

Cost-capped: hard exit if the estimated total spend exceeds the cap
(default €1.00 ≈ 280 cycles at the typical Haiku 4.5 per-call cost).

Brief: ``briefs/BRIEF_CORTEX_DIRECTOR_CARD_V1.md`` (criterion 6).

Usage:
    # Dry-run (default — prints what would be done, no API spend):
    python3 scripts/backfill_director_cards.py

    # Live run (explicit flag required):
    python3 scripts/backfill_director_cards.py --live

    # Cap override (default 1.00 EUR):
    python3 scripts/backfill_director_cards.py --live --cost-cap 0.50

    # Limit (sanity, default 500):
    python3 scripts/backfill_director_cards.py --live --limit 50
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("backfill_director_cards")

# Typical Haiku 4.5 per-call cost on the prompt size we send (~€0.003);
# we estimate conservatively at €0.005 per cycle for cap math.
_PER_CYCLE_EST_EUR = 0.005


def _fetch_target_cycles(conn, limit: int) -> list[dict]:
    """Cycles in tier_b_pending with synthesis but no director_card."""
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute(
            """
            SELECT
                c.cycle_id::text AS cycle_id,
                c.matter_slug,
                c.cost_dollars,
                c.cost_tokens,
                (
                  SELECT po.payload->>'proposal_text'
                  FROM cortex_phase_outputs po
                  WHERE po.cycle_id = c.cycle_id
                    AND po.artifact_type = 'synthesis'
                  ORDER BY po.created_at DESC
                  LIMIT 1
                ) AS proposal_text
            FROM cortex_cycles c
            WHERE c.status = 'tier_b_pending'
              AND NOT EXISTS (
                  SELECT 1 FROM cortex_phase_outputs po2
                  WHERE po2.cycle_id = c.cycle_id
                    AND po2.artifact_type = 'director_card'
              )
            ORDER BY c.started_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()
        conn.commit()
        return [dict(r) for r in rows]
    finally:
        cur.close()


def _summarize_card(card: Optional[dict]) -> str:
    if not isinstance(card, dict):
        return "(no card returned)"
    return (
        f"matter={card.get('matter')!r} "
        f"reco={card.get('recommendation')!r} "
        f"confidence={card.get('confidence')!r} "
        f"action={card.get('action')!r}"
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--live", action="store_true",
                    help="actually call Haiku + write rows. Default is dry-run.")
    ap.add_argument("--cost-cap", type=float, default=1.00,
                    help="hard exit if estimated total spend exceeds this EUR cap (default 1.00)")
    ap.add_argument("--limit", type=int, default=500,
                    help="max cycles to process (sanity cap; default 500)")
    args = ap.parse_args()

    if args.live and not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("--live requires ANTHROPIC_API_KEY env var")

    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    if conn is None:
        raise SystemExit("DB connection unavailable")

    try:
        cycles = _fetch_target_cycles(conn, args.limit)
    finally:
        store._put_conn(conn)

    n = len(cycles)
    est_total = n * _PER_CYCLE_EST_EUR
    logger.info(
        "found %d cycle(s) needing director_card; estimated total cost ≈ €%.4f (cap €%.2f)",
        n, est_total, args.cost_cap,
    )
    if est_total > args.cost_cap:
        raise SystemExit(
            f"estimated total spend €{est_total:.4f} exceeds cap €{args.cost_cap:.2f} — "
            "raise --cost-cap or lower --limit"
        )

    if not args.live:
        logger.info("DRY-RUN: would translate %d cycles. Pass --live to execute.", n)
        for c in cycles[:5]:  # show first 5 as a sample
            logger.info(
                "  - cycle_id=%s matter=%s proposal_len=%d",
                c["cycle_id"], c.get("matter_slug"),
                len(c.get("proposal_text") or ""),
            )
        if n > 5:
            logger.info("  - ... (%d more)", n - 5)
        return

    # Live path
    from orchestrator.cortex_phase4_5_director_card import (
        translate_to_director_card,
        persist_director_card,
    )

    written = 0
    skipped = 0
    failed = 0
    total_actual_eur = 0.0
    sample_cards: list[dict] = []
    for c in cycles:
        cycle_id = c["cycle_id"]
        proposal_text = c.get("proposal_text") or ""
        if not proposal_text:
            logger.info("skip cycle_id=%s (no proposal_text)", cycle_id)
            skipped += 1
            continue
        card = translate_to_director_card(
            cycle_id=cycle_id,
            proposal_text=proposal_text,
            matter_slug=c.get("matter_slug") or "",
            cost_telemetry={
                "cost_dollars": float(c.get("cost_dollars") or 0.0),
                "cost_tokens": int(c.get("cost_tokens") or 0),
            },
        )
        if card is None:
            logger.warning("translate failed (fail-open) for cycle_id=%s", cycle_id)
            failed += 1
            continue
        meta = card.get("_meta") or {}
        total_actual_eur += float(meta.get("card_gen_cost_eur") or 0.0)
        ok = persist_director_card(cycle_id, card)
        if not ok:
            logger.error("persist failed for cycle_id=%s", cycle_id)
            failed += 1
            continue
        written += 1
        if len(sample_cards) < 2:
            sample_cards.append({"cycle_id": cycle_id, "card": card})
        logger.info("wrote director_card for cycle_id=%s — %s", cycle_id, _summarize_card(card))

    logger.info(
        "DONE: wrote=%d skipped=%d failed=%d actual_total≈€%.4f",
        written, skipped, failed, total_actual_eur,
    )
    if sample_cards:
        print("\n=== Sample cards (for ship-report attachment) ===")
        print(json.dumps(sample_cards, indent=2, default=str))


if __name__ == "__main__":
    main()
