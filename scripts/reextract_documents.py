"""
Re-extract documents that were classified but not extracted.

Handles two cases:
  1. type='other' — no extraction schema → marks extracted_at = NOW() (no structured data)
  2. All other types — re-runs extract_document() to produce structured data

Usage:
  python3 scripts/reextract_documents.py --diagnose     # Just report counts
  python3 scripts/reextract_documents.py --run           # Run extraction
  python3 scripts/reextract_documents.py --run --limit 5 # Run on first 5 docs
"""
import argparse
import logging
import sys
import time
from pathlib import Path

# Project root on sys.path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("reextract")


def get_conn():
    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack._get_global_instance()
    return store, store._get_conn()


def diagnose():
    """Report breakdown of classified-but-not-extracted documents."""
    store, conn = get_conn()
    if not conn:
        logger.error("No DB connection")
        return

    try:
        cur = conn.cursor()

        # Total gap
        cur.execute("""
            SELECT COUNT(*) FROM documents
            WHERE classified_at IS NOT NULL AND extracted_at IS NULL
        """)
        total_gap = cur.fetchone()[0]

        # Breakdown by document_type
        cur.execute("""
            SELECT document_type, COUNT(*) FROM documents
            WHERE classified_at IS NOT NULL AND extracted_at IS NULL
            GROUP BY document_type ORDER BY COUNT(*) DESC
        """)
        by_type = cur.fetchall()

        # How many have full_text?
        cur.execute("""
            SELECT COUNT(*) FROM documents
            WHERE classified_at IS NOT NULL AND extracted_at IS NULL
              AND full_text IS NOT NULL AND LENGTH(full_text) > 0
        """)
        has_text = cur.fetchone()[0]

        # Known schemas
        HAS_SCHEMA = ('contract', 'invoice', 'nachtrag', 'schlussrechnung',
                       'correspondence', 'protocol', 'report')

        # No extraction schema (other, proposal, presentation, etc.)
        cur.execute("""
            SELECT COUNT(*) FROM documents
            WHERE classified_at IS NOT NULL AND extracted_at IS NULL
              AND document_type NOT IN %s
        """, (HAS_SCHEMA,))
        no_schema = cur.fetchone()[0]

        # Extractable = has schema + has text
        cur.execute("""
            SELECT COUNT(*) FROM documents
            WHERE classified_at IS NOT NULL AND extracted_at IS NULL
              AND document_type IN %s
              AND full_text IS NOT NULL AND LENGTH(full_text) > 0
        """, (HAS_SCHEMA,))
        extractable = cur.fetchone()[0]

        cur.close()
    finally:
        store._put_conn(conn)

    print(f"\n{'='*60}")
    print(f"  UNEXTRACTED DOCUMENTS DIAGNOSIS")
    print(f"{'='*60}")
    print(f"  Total classified, not extracted:  {total_gap}")
    print(f"  Have full_text:                   {has_text}")
    print(f"  No schema (stamp only):           {no_schema}")
    print(f"  Extractable (schema+text):        {extractable}")
    print(f"\n  Breakdown by type:")
    for doc_type, count in by_type:
        extractable_marker = " *" if doc_type != "other" else "  (skip)"
        print(f"    {doc_type or 'NULL':25s} {count:5d}{extractable_marker}")
    print(f"{'='*60}\n")


def run_extraction(limit=None):
    """Re-run extraction on classified docs that failed extraction."""
    from tools.document_pipeline import extract_document
    from orchestrator.cost_monitor import check_circuit_breaker

    store, conn = get_conn()
    if not conn:
        logger.error("No DB connection")
        return

    try:
        cur = conn.cursor()

        # Known extraction schemas (from document_pipeline.py _EXTRACTION_SCHEMAS)
        HAS_SCHEMA = ('contract', 'invoice', 'nachtrag', 'schlussrechnung',
                       'correspondence', 'protocol', 'report')

        # Phase 1: Mark docs without extraction schema as extracted
        # (other, proposal, presentation, statement, etc.)
        cur.execute("""
            UPDATE documents SET extracted_at = NOW()
            WHERE classified_at IS NOT NULL AND extracted_at IS NULL
              AND document_type NOT IN %s
        """, (HAS_SCHEMA,))
        other_marked = cur.rowcount
        conn.commit()
        logger.info(f"Phase 1: marked {other_marked} schema-less docs as extracted (no schema)")

        # Phase 2: Get extractable docs (types with schemas)
        cur.execute("""
            SELECT id, filename, document_type FROM documents
            WHERE classified_at IS NOT NULL AND extracted_at IS NULL
              AND document_type IN %s
              AND full_text IS NOT NULL AND LENGTH(full_text) > 0
            ORDER BY id
        """, (HAS_SCHEMA,))
        rows = cur.fetchall()
        cur.close()
    finally:
        store._put_conn(conn)

    total = len(rows)
    if limit:
        rows = rows[:limit]
    logger.info(f"Phase 2: {total} extractable docs, processing {len(rows)}")

    extracted = 0
    errors = 0
    for i, (doc_id, filename, doc_type) in enumerate(rows):
        allowed, daily_cost = check_circuit_breaker()
        if not allowed:
            logger.warning(f"Circuit breaker at €{daily_cost:.2f}, stopping after {extracted} extractions")
            break

        # Get full text
        store2, conn2 = get_conn()
        if not conn2:
            logger.error("Lost DB connection")
            break
        try:
            cur2 = conn2.cursor()
            cur2.execute("SELECT full_text FROM documents WHERE id = %s", (doc_id,))
            row = cur2.fetchone()
            cur2.close()
            full_text = row[0] if row else None
        finally:
            store2._put_conn(conn2)

        if not full_text:
            logger.warning(f"  [{i+1}/{len(rows)}] doc {doc_id} has no text, skipping")
            continue

        try:
            result = extract_document(doc_id, full_text, doc_type)
            if result:
                extracted += 1
                logger.info(f"  [{i+1}/{len(rows)}] Extracted doc {doc_id}: {filename} ({doc_type}, {len(result)} fields)")
            else:
                errors += 1
                logger.warning(f"  [{i+1}/{len(rows)}] No result for doc {doc_id}: {filename} ({doc_type})")
        except Exception as e:
            errors += 1
            logger.error(f"  [{i+1}/{len(rows)}] Failed doc {doc_id} ({filename}): {e}")

        time.sleep(2)  # Rate limit

        if (i + 1) % 20 == 0:
            logger.info(f"Progress: {i+1}/{len(rows)} — {extracted} extracted, {errors} errors")

    print(f"\n{'='*60}")
    print(f"  RE-EXTRACTION COMPLETE")
    print(f"{'='*60}")
    print(f"  'other' docs marked:  {other_marked}")
    print(f"  Extracted:            {extracted}")
    print(f"  Errors:               {errors}")
    print(f"  Remaining:            {total - extracted - errors}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Re-extract classified-but-unextracted documents")
    parser.add_argument("--diagnose", action="store_true", help="Report counts only")
    parser.add_argument("--run", action="store_true", help="Run extraction")
    parser.add_argument("--limit", type=int, default=None, help="Max docs to process")
    args = parser.parse_args()

    if args.diagnose:
        diagnose()
    elif args.run:
        run_extraction(limit=args.limit)
    else:
        parser.print_help()
