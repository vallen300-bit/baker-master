"""Baker AI — CLI Batch Ingestion Script (INGEST-1).

Usage:
    # Single file, auto-classify collection:
    python -m tools.ingest.cli data/contacts.csv

    # Single file, explicit collection:
    python -m tools.ingest.cli data/report.pdf --collection baker-documents

    # Whole directory (recursive):
    python -m tools.ingest.cli data/ --collection baker-projects

    # Dry run (preview without API calls):
    python -m tools.ingest.cli data/ --dry-run

    # Skip LLM classifier (heuristic only):
    python -m tools.ingest.cli data/ --no-llm

    # Skip duplicate detection:
    python -m tools.ingest.cli data/ --no-dedup

Run from the 01_build directory.
"""
import argparse
import logging
import sys
from pathlib import Path

# Ensure project root is on sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from tools.ingest.extractors import SUPPORTED_EXTENSIONS
from tools.ingest.pipeline import ingest_file


def _collect_files(source: Path) -> list[Path]:
    """Collect all supported files from a path (file or directory)."""
    if source.is_file():
        if source.suffix.lower() in SUPPORTED_EXTENSIONS:
            return [source]
        else:
            print(f"  SKIP: Unsupported file type '{source.suffix}' — {source.name}")
            return []

    if source.is_dir():
        files = []
        for ext in SUPPORTED_EXTENSIONS:
            files.extend(source.rglob(f"*{ext}"))
        return sorted(files)

    return []


def main():
    parser = argparse.ArgumentParser(
        description="Baker AI — Batch file ingestion into Qdrant vector store",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m tools.ingest.cli data/contacts.csv
  python -m tools.ingest.cli data/ --collection baker-projects
  python -m tools.ingest.cli data/ --dry-run --verbose
        """,
    )
    parser.add_argument(
        "source",
        type=Path,
        help="File or directory to ingest (recursive for directories)",
    )
    parser.add_argument(
        "--collection", "-c",
        type=str,
        default=None,
        help="Target Qdrant collection (auto-classified if omitted)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be ingested without calling APIs",
    )
    parser.add_argument(
        "--no-dedup",
        action="store_true",
        help="Skip duplicate detection (re-ingest even if already present)",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Skip LLM classification (use heuristic rules only)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output with per-file details",
    )

    args = parser.parse_args()

    # Setup logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(levelname)-5s  %(message)s",
    )

    if not args.source.exists():
        print(f"ERROR: Source not found: {args.source}")
        sys.exit(1)

    # Collect files
    files = _collect_files(args.source)
    if not files:
        print("No supported files found.")
        print(f"Supported types: {', '.join(sorted(SUPPORTED_EXTENSIONS))}")
        sys.exit(0)

    # Header
    mode = "DRY RUN" if args.dry_run else "LIVE"
    collection_label = args.collection or "auto-classify"
    print(f"\n{'='*60}")
    print(f"Baker Ingest [{mode}]")
    print(f"Source: {args.source}")
    print(f"Files:  {len(files)}")
    print(f"Target: {collection_label}")
    print(f"{'='*60}\n")

    # Process each file
    results = []
    for i, filepath in enumerate(files, 1):
        print(f"[{i}/{len(files)}] {filepath.name}")

        result = ingest_file(
            filepath=filepath,
            collection=args.collection,
            dry_run=args.dry_run,
            skip_dedup=args.no_dedup,
            skip_llm=args.no_llm,
            verbose=args.verbose,
        )
        results.append(result)

        if result.skipped:
            print(f"  SKIP: {result.skip_reason}")
        elif result.error:
            print(f"  ERROR: {result.error}")
        else:
            print(f"  OK: {result.chunk_count} chunks → {result.collection}")

    # Summary
    total = len(results)
    ingested = [r for r in results if not r.skipped and not r.error]
    skipped = [r for r in results if r.skipped]
    errors = [r for r in results if r.error]
    total_chunks = sum(r.chunk_count for r in ingested)

    print(f"\n{'='*60}")
    print(f"Summary: {len(ingested)} ingested, {len(skipped)} skipped, {len(errors)} errors")
    print(f"Total chunks: {total_chunks}")
    if args.dry_run:
        print("(Dry run — no APIs called)")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
