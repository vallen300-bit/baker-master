"""
KBL Pre-Shadow Eval — Seed Builder

Samples 50 real signals from PostgreSQL (stratified 25 email + 15 WhatsApp + 10
meeting, ~60/40 Hagenauer vs other) and writes two JSONL artifacts:

  outputs/kbl_eval_set_<YYYYMMDD>.jsonl
      One signal per line: {id, source, raw_content, hint_matter_if_tagged}

  outputs/kbl_eval_set_<YYYYMMDD>_labeling_template.jsonl
      Same IDs + empty Director label fields, ready for Option A manual edit.

Reproducible via deterministic seeded random (md5 of id + seed); re-runs
produce the same sample for the same seed.

Usage:
  python3 scripts/build_eval_seed.py                     # seed=42, today
  python3 scripts/build_eval_seed.py --seed 42 --date 20260417
  python3 scripts/build_eval_seed.py --out-dir outputs/  # default

Requires DATABASE_URL (or POSTGRES_* env vars) in the shell that runs it,
same as any other baker-code script.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("build_eval_seed")

sys.path.insert(0, ".")


MATTER_HINTS = {
    "hagenauer-rg7": ["hagenauer", "rg7"],
    "cupial": ["cupial", "cupials", "monika cupial", "cupial-zgryzek"],
    "mo-vie": ["mandarin oriental", "mo vienna", "mohg", "movie"],
    "ao": ["oskolkov", "andrey oskolkov"],
    "brisen-lp": ["wertheimer", "epi bond"],
    "mrci": ["mrci"],
    "lilienmat": ["lilienmat"],
    "edita-russo": ["edita russo"],
    "theailogy": ["theailogy"],
}


def guess_matter_hint(text: str) -> Optional[str]:
    """Very light hint to help Director (never authoritative). Returns first match or None."""
    if not text:
        return None
    lower = text.lower()
    for matter, keywords in MATTER_HINTS.items():
        if any(k in lower for k in keywords):
            return matter
    return None


def sample_query(seed: int) -> str:
    """Stratified seeded-random sample: 25 email (15H+10O), 15 WA (10H+5O), 10 mtg (7H+3O)."""
    return f"""
    WITH
      email_hg AS (
        SELECT 'email' AS source, id::text AS sid, subject AS title,
               LEFT(COALESCE(full_body, ''), 3000) AS raw_content
          FROM email_messages
         WHERE (subject ILIKE '%hagenauer%' OR full_body ILIKE '%hagenauer%'
                OR subject ILIKE '%RG7%')
         ORDER BY md5(id::text || '{seed}') LIMIT 15
      ),
      email_other AS (
        SELECT 'email', id::text, subject,
               LEFT(COALESCE(full_body, ''), 3000)
          FROM email_messages
         WHERE NOT (subject ILIKE '%hagenauer%' OR full_body ILIKE '%hagenauer%' OR subject ILIKE '%RG7%')
           AND full_body IS NOT NULL
           AND length(full_body) > 100
         ORDER BY md5(id::text || '{seed}') LIMIT 10
      ),
      wa_hg AS (
        SELECT 'whatsapp', id::text, NULL::text,
               LEFT(COALESCE(full_text, ''), 3000)
          FROM whatsapp_messages
         WHERE full_text ILIKE '%hagenauer%' OR full_text ILIKE '%RG7%'
         ORDER BY md5(id::text || '{seed}') LIMIT 10
      ),
      wa_other AS (
        SELECT 'whatsapp', id::text, NULL::text,
               LEFT(COALESCE(full_text, ''), 3000)
          FROM whatsapp_messages
         WHERE NOT (full_text ILIKE '%hagenauer%' OR full_text ILIKE '%RG7%')
           AND full_text IS NOT NULL
           AND length(full_text) > 50
         ORDER BY md5(id::text || '{seed}') LIMIT 5
      ),
      mtg_hg AS (
        SELECT 'meeting', id::text, title,
               LEFT(COALESCE(full_transcript, ''), 4000)
          FROM meeting_transcripts
         WHERE (title ILIKE '%hagenauer%' OR full_transcript ILIKE '%hagenauer%'
                OR full_transcript ILIKE '%RG7%')
         ORDER BY md5(id::text || '{seed}') LIMIT 7
      ),
      mtg_other AS (
        SELECT 'meeting', id::text, title,
               LEFT(COALESCE(full_transcript, ''), 4000)
          FROM meeting_transcripts
         WHERE NOT (title ILIKE '%hagenauer%' OR full_transcript ILIKE '%hagenauer%' OR full_transcript ILIKE '%RG7%')
           AND full_transcript IS NOT NULL
           AND length(full_transcript) > 200
         ORDER BY md5(id::text || '{seed}') LIMIT 3
      )
    SELECT source, sid, title, raw_content FROM email_hg
    UNION ALL SELECT source, sid, title, raw_content FROM email_other
    UNION ALL SELECT source, sid, title, raw_content FROM wa_hg
    UNION ALL SELECT source, sid, title, raw_content FROM wa_other
    UNION ALL SELECT source, sid, title, raw_content FROM mtg_hg
    UNION ALL SELECT source, sid, title, raw_content FROM mtg_other
    ORDER BY source, sid;
    """


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out-dir", default="outputs")
    parser.add_argument("--date", default=None,
                        help="YYYYMMDD override for filename; defaults to today UTC")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the SQL and counts, don't write files")
    args = parser.parse_args()

    from memory.store_back import SentinelStoreBack  # noqa: E402
    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    if conn is None:
        logger.error("No DB connection — check POSTGRES_* or DATABASE_URL env")
        sys.exit(1)

    date_str = args.date or datetime.now(timezone.utc).strftime("%Y%m%d")
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    unlabeled_path = out_dir / f"kbl_eval_set_{date_str}.jsonl"
    template_path = out_dir / f"kbl_eval_set_{date_str}_labeling_template.jsonl"

    sql = sample_query(args.seed)
    try:
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        cur.close()
    finally:
        store._put_conn(conn)

    logger.info("sampled %d signals (seed=%s)", len(rows), args.seed)
    by_source: Dict[str, int] = {}
    for src, *_ in rows:
        by_source[src] = by_source.get(src, 0) + 1
    for src, n in sorted(by_source.items()):
        logger.info("  %s: %d", src, n)

    if args.dry_run:
        logger.info("--dry-run: no files written")
        return

    with open(unlabeled_path, "w") as f_un, open(template_path, "w") as f_tp:
        for source, sid, title, raw in rows:
            hint = guess_matter_hint(f"{title or ''}\n{raw or ''}")
            base = {
                "signal_id": f"{source}:{sid}",
                "source": source,
                "title": title,
                "raw_content": raw,
                "hint_matter_if_tagged": hint,
            }
            f_un.write(json.dumps(base, ensure_ascii=False) + "\n")

            template = dict(base)
            template.update({
                # Director fills these in Option A (see KBL_EVAL_SET_PLAYBOOK.md §3)
                "vedana_expected": None,          # 'pleasant' | 'unpleasant' | 'neutral'
                "primary_matter_expected": None,  # matter slug or null
                "related_matters_expected": [],   # list of matter slugs
                "triage_threshold_pass_expected": None,   # true = should have alerted
                "notes": "",
            })
            f_tp.write(json.dumps(template, ensure_ascii=False) + "\n")

    logger.info("wrote unlabeled -> %s (%d bytes)", unlabeled_path, unlabeled_path.stat().st_size)
    logger.info("wrote template  -> %s (%d bytes)", template_path,  template_path.stat().st_size)

    if len(rows) != 50:
        logger.warning("expected 50 signals, got %d — source counts above may be short. "
                       "Re-run with --seed or relax Hagenauer filters if needed.", len(rows))


if __name__ == "__main__":
    main()
