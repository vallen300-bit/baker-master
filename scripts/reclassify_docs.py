"""
DOC-RECLASSIFY-1: Re-classify documents that are currently 'other' or have no tags.

Uses the expanded 16-type taxonomy + controlled 40-tag vocabulary.
Runs as a background job. Respects circuit breaker.

Usage:
  python3 scripts/reclassify_docs.py              # Full run
  python3 scripts/reclassify_docs.py --limit 5     # Test on 5 docs first
"""
import argparse
import logging
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("reclassify")


def run_reclassify(limit: int = None, sleep_between: float = 2.0):
    """Re-classify 'other' docs with the expanded taxonomy."""
    from memory.store_back import SentinelStoreBack
    from tools.document_pipeline import classify_document, extract_document, _EXTRACTION_SCHEMAS
    from orchestrator.cost_monitor import check_circuit_breaker

    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    if not conn:
        print("No DB connection")
        return

    try:
        cur = conn.cursor()
        # Phase A: Re-classify "other" docs that have actual text content
        cur.execute("""
            SELECT id, full_text FROM documents
            WHERE document_type = 'other'
              AND full_text IS NOT NULL
              AND LENGTH(full_text) > 100
            ORDER BY ingested_at DESC
        """)
        targets = cur.fetchall()
        cur.close()
    finally:
        store._put_conn(conn)

    total = len(targets)
    if limit:
        targets = targets[:limit]
    print(f"Found {total} 'other' docs, processing {len(targets)}")

    reclassified = 0
    extracted = 0
    errors = 0
    remained_other = 0

    for i, (doc_id, full_text) in enumerate(targets):
        allowed, daily_cost = check_circuit_breaker()
        if not allowed:
            print(f"Circuit breaker at €{daily_cost:.2f}, stopping after {i} docs")
            break

        try:
            result = classify_document(doc_id, full_text)
            if result:
                new_type = result.get("document_type", "other")
                if new_type != "other":
                    reclassified += 1
                    logger.info(f"  [{i+1}/{len(targets)}] doc {doc_id} → {new_type}")
                    # Run extraction if schema exists
                    if new_type in _EXTRACTION_SCHEMAS:
                        time.sleep(sleep_between)
                        ext = extract_document(doc_id, full_text, new_type)
                        if ext:
                            extracted += 1
                else:
                    remained_other += 1
            else:
                errors += 1
        except Exception as e:
            errors += 1
            logger.warning(f"  [{i+1}/{len(targets)}] doc {doc_id} failed: {e}")

        time.sleep(sleep_between)

        if (i + 1) % 50 == 0:
            print(f"  Progress: {i+1}/{len(targets)} "
                  f"(reclassified={reclassified}, extracted={extracted}, "
                  f"errors={errors}, still_other={remained_other})")

    print(f"\n{'='*60}")
    print(f"  RE-CLASSIFICATION COMPLETE")
    print(f"{'='*60}")
    print(f"  Processed:      {len(targets)}")
    print(f"  Reclassified:   {reclassified}")
    print(f"  Extracted:      {extracted}")
    print(f"  Still 'other':  {remained_other}")
    print(f"  Errors:         {errors}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Re-classify 'other' documents with expanded taxonomy")
    parser.add_argument("--limit", type=int, default=None, help="Max docs to process")
    args = parser.parse_args()
    run_reclassify(limit=args.limit)
