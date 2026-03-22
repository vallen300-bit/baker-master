"""
DOC-RECLASSIFY-1 + TAGGING-OVERHAUL-1: Re-classify documents.

Phase A: Deterministic triage (free) — tag media_asset/corrupted/empty.
Phase B: Re-classify surviving "other" docs with expanded taxonomy (Haiku).

Usage:
  python3 scripts/reclassify_docs.py                    # Phase A only (free)
  python3 scripts/reclassify_docs.py --phase b          # Phase A + B
  python3 scripts/reclassify_docs.py --phase b --limit 5  # Test on 5 docs
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


def run_triage():
    """Phase A: Deterministic content triage (no Haiku cost)."""
    from memory.store_back import SentinelStoreBack
    from tools.document_pipeline import triage_document

    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    if not conn:
        print("No DB connection")
        return

    try:
        cur = conn.cursor()
        # Ensure column exists
        cur.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS content_class VARCHAR(20) DEFAULT 'document'")
        conn.commit()

        cur.execute("SELECT id, filename, full_text, source_path FROM documents")
        docs = cur.fetchall()
        cur.close()
    finally:
        store._put_conn(conn)

    counts = {'document': 0, 'media_asset': 0, 'corrupted': 0, 'empty': 0}
    print(f"Phase A: Triaging {len(docs)} documents...")

    conn2 = store._get_conn()
    if not conn2:
        print("Lost DB connection")
        return
    try:
        cur = conn2.cursor()
        for i, (doc_id, filename, full_text, source_path) in enumerate(docs):
            cc = triage_document(filename or "", full_text, source_path or "")
            counts[cc] = counts.get(cc, 0) + 1
            cur.execute("UPDATE documents SET content_class = %s WHERE id = %s", (cc, doc_id))
            if (i + 1) % 500 == 0:
                conn2.commit()
                print(f"  Progress: {i+1}/{len(docs)}")
        conn2.commit()
        cur.close()
    finally:
        store._put_conn(conn2)

    print(f"\n{'='*60}")
    print(f"  PHASE A — TRIAGE COMPLETE")
    print(f"{'='*60}")
    for k, v in sorted(counts.items()):
        print(f"  {k:15s}: {v:5d}")
    print(f"  {'total':15s}: {sum(counts.values()):5d}")
    print(f"{'='*60}\n")


def run_reclassify(limit: int = None, sleep_between: float = 2.0):
    """Phase B: Re-classify 'other' docs with expanded taxonomy (Haiku)."""
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
        cur.execute("""
            SELECT id, full_text FROM documents
            WHERE document_type = 'other'
              AND COALESCE(content_class, 'document') = 'document'
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
    print(f"Phase B: Found {total} 'other' docs (post-triage), processing {len(targets)}")

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
    print(f"  PHASE B — RE-CLASSIFICATION COMPLETE")
    print(f"{'='*60}")
    print(f"  Processed:      {len(targets)}")
    print(f"  Reclassified:   {reclassified}")
    print(f"  Extracted:      {extracted}")
    print(f"  Still 'other':  {remained_other}")
    print(f"  Errors:         {errors}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Re-classify documents with triage + expanded taxonomy")
    parser.add_argument("--phase", choices=["a", "b", "ab"], default="a",
                        help="Phase to run: a=triage only, b=triage+reclassify, ab=both")
    parser.add_argument("--limit", type=int, default=None, help="Max docs to process (Phase B only)")
    args = parser.parse_args()

    if args.phase in ("a", "ab"):
        run_triage()
    if args.phase in ("b", "ab"):
        run_reclassify(limit=args.limit)
