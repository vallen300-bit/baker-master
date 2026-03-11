"""
DOC-TRIAGE-1: Backfill matter_slug from Dropbox folder paths.

Maps known folder patterns to matter_slugs for documents that have
source_path but no matter_slug. Zero LLM cost — pure path matching.

Usage:
  python3 scripts/backfill_matter_from_path.py --dry-run   # Preview
  python3 scripts/backfill_matter_from_path.py --run        # Execute
"""
import argparse
import logging
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("backfill_matter")

# Folder pattern → matter_slug mapping
# Matched case-insensitively against source_path
FOLDER_MATTER_MAP = [
    # Order matters: more specific patterns first
    ("01_MOVIE_PROJECT/04_Sales_Marketing_PR", "Mandarin Oriental Sales"),
    ("01_MOVIE_PROJECT", "Mandarin Oriental Sales"),
    ("MOVIE", "Mandarin Oriental Sales"),
    ("MORV", "Mandarin Oriental Sales"),

    ("02_BADEN_ PROJECTS/BADEN- ANABERG", "Baden-Baden Projects"),
    ("02_BADEN_ PROJECTS/BADEN - MRC", "Baden-Baden Projects"),
    ("02_BADEN_ PROJECTS/Annaberg", "Baden-Baden Projects"),
    ("02_BADEN_ PROJECTS", "Baden-Baden Projects"),
    ("BADEN", "Baden-Baden Projects"),
    ("Annaberg", "Baden-Baden Projects"),
    ("Lilienmatt", "Baden-Baden Projects"),

    ("03_CAP FERRAT", "Cap Ferrat Villa"),
    ("Cap Ferrat", "Cap Ferrat Villa"),
    ("Villaaulivie", "Cap Ferrat Villa"),

    ("05_RE_CASH_PRODUCING_ACQISITIONS/Kitzbuhel-Kempinski", "Kempinski Kitzbühel Acquisition"),
    ("Kempinski", "Kempinski Kitzbühel Acquisition"),
    ("KitzKempi", "Kempinski Kitzbühel Acquisition"),

    ("05_RE_CASH_PRODUCING_ACQISITIONS/Davos", "Owner's Lens"),

    ("AO_MASTER/10_AO_RG7", "Oskolkov-RG7"),
    ("AO_MASTER/AO GF/AO RG7", "Oskolkov-RG7"),
    ("AO_MASTER", "Oskolkov-RG7"),
    ("AO_RG7", "Oskolkov-RG7"),

    ("Cupial", "Cupial"),
    ("Hagenauer", "Hagenauer"),

    ("_03_MIGRATION_TO_ MICROSOFT365", "M365 Migration"),
    ("MICROSOFT365", "M365 Migration"),

    ("Kitzbühel", "Kitzbühel Alp"),
    ("Kitzbuhel", "Kitzbühel Alp"),

    ("ClaimsMax", "ClaimsMax"),
    ("FX Mayr", "FX Mayr"),
    ("NVIDIA", "NVIDIA-GTC-2026"),
    ("GTC", "NVIDIA-GTC-2026"),
]


def get_conn():
    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack._get_global_instance()
    return store, store._get_conn()


def run(dry_run=True):
    store, conn = get_conn()
    if not conn:
        logger.error("No DB connection")
        return

    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, source_path, filename FROM documents
            WHERE matter_slug IS NULL AND source_path IS NOT NULL
        """)
        rows = cur.fetchall()
        cur.close()
    finally:
        store._put_conn(conn)

    logger.info(f"Found {len(rows)} documents with no matter_slug")

    # Match each document
    matches = {}  # matter_slug → list of doc_ids
    unmatched = 0
    for doc_id, source_path, filename in rows:
        path_lower = (source_path or "").lower()
        matched = False
        for pattern, matter in FOLDER_MATTER_MAP:
            if pattern.lower() in path_lower:
                matches.setdefault(matter, []).append(doc_id)
                matched = True
                break
        if not matched:
            unmatched += 1

    # Report
    total_matched = sum(len(ids) for ids in matches.values())
    print(f"\n{'='*60}")
    print(f"  MATTER BACKFILL FROM PATH {'(DRY RUN)' if dry_run else ''}")
    print(f"{'='*60}")
    print(f"  Total with no matter_slug: {len(rows)}")
    print(f"  Matched by folder path:    {total_matched}")
    print(f"  Unmatched:                 {unmatched}")
    print(f"\n  Breakdown by matter:")
    for matter in sorted(matches, key=lambda m: -len(matches[m])):
        print(f"    {matter:40s} {len(matches[matter]):5d}")
    print(f"{'='*60}\n")

    if dry_run:
        logger.info("Dry run complete. Use --run to apply.")
        return

    # Apply updates
    store2, conn2 = get_conn()
    if not conn2:
        logger.error("No DB connection for writes")
        return

    updated = 0
    try:
        cur = conn2.cursor()
        for matter, doc_ids in matches.items():
            cur.execute("""
                UPDATE documents SET matter_slug = %s
                WHERE id = ANY(%s) AND matter_slug IS NULL
            """, (matter, doc_ids))
            updated += cur.rowcount
        conn2.commit()
        cur.close()
    finally:
        store2._put_conn(conn2)

    print(f"\n  Updated {updated} documents with matter_slugs.\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill matter_slug from Dropbox folder paths")
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    parser.add_argument("--run", action="store_true", help="Apply updates")
    args = parser.parse_args()

    if args.dry_run or args.run:
        run(dry_run=not args.run)
    else:
        parser.print_help()
