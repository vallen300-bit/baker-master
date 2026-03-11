# BRIEF: DOC-TRIAGE-1 — Image Triage + Path-to-Matter Mapping

**Author:** AI Head (Session 20)
**For:** Code Brisen or Code 300
**Priority:** HIGH — immediate search quality improvement
**Estimated scope:** 1 Python script + 2 SQL updates
**Cost:** Zero — no LLM calls, pure deterministic logic

---

## Problem

- **1,060 images** (JPG/PNG) classified as "other" pollute every specialist search
- **1,621 docs (51%)** have no matter_slug — specialists can't find docs by project
- The source_path contains obvious matter hints (`/01_MOVIE_PROJECT/`, `/AO_MASTER/`, `/14_HAGENAUER_MASTER/`) that are completely ignored

## Solution — Two deterministic fixes, zero cost

### Fix 1: Image Triage — mark 1,060 images as `media_asset`

Run this SQL directly. No code change needed:

```sql
UPDATE documents
SET document_type = 'media_asset'
WHERE document_type = 'other'
  AND (LOWER(source_path) LIKE '%.jpg'
    OR LOWER(source_path) LIKE '%.jpeg'
    OR LOWER(source_path) LIKE '%.png'
    OR LOWER(source_path) LIKE '%.gif'
    OR LOWER(source_path) LIKE '%.bmp'
    OR LOWER(source_path) LIKE '%.tiff'
    OR LOWER(source_path) LIKE '%.svg'
    OR LOWER(filename) LIKE '%.jpg'
    OR LOWER(filename) LIKE '%.jpeg'
    OR LOWER(filename) LIKE '%.png');
```

Expected: ~1,060 rows updated. "other" drops from 1,340 → ~280.

Then exclude `media_asset` from the retriever. In `memory/retriever.py`, find the document enrichment query and add:

```python
# In _enrich_with_full_text() or wherever documents are queried for search:
# Add: AND document_type != 'media_asset'
```

Also update the Qdrant document search to exclude media_assets if possible. At minimum, the full-text retrieval from PostgreSQL should filter them out.

### Fix 2: Path-to-Matter Mapping — assign matter_slug from source_path

Create a script `scripts/backfill_matter_from_path.py`:

```python
"""
Deterministic matter_slug assignment from source_path.
Maps known Dropbox folder patterns to matter_registry slugs.
Only updates docs where matter_slug IS NULL.
"""
import psycopg2
import logging

logger = logging.getLogger(__name__)

# Folder pattern → matter_slug mapping
# Patterns are checked in order; first match wins.
# Use lowercase for comparison.
PATH_MATTER_MAP = [
    # Top-level project folders
    ("/01_movie_project/", "Mandarin Oriental"),
    ("/movie_project/", "Mandarin Oriental"),
    ("/movie/", "Mandarin Oriental"),

    # Baden-Baden
    ("/02_baden", "Baden-Baden Projects"),
    ("/baden_baden/", "Baden-Baden Projects"),
    ("/baden-baden/", "Baden-Baden Projects"),

    # Cap Ferrat
    ("/03_cap ferrat", "Cap Ferrat Villa"),
    ("/cap_ferrat/", "Cap Ferrat Villa"),
    ("/cap ferrat/", "Cap Ferrat Villa"),

    # Oskolkov / RG7 / AO
    ("/ao_master/", "Oskolkov-RG7"),
    ("/oskolkov", "Oskolkov-RG7"),
    ("/rg7/", "Oskolkov-RG7"),
    ("/aelio/", "Oskolkov-RG7"),

    # Hagenauer
    ("/hagenauer", "Hagenauer"),

    # Cupial
    ("/cupial", "Cupial"),

    # Kempinski
    ("/kempinski", "Kempinski Kitzbühel Acquisition"),

    # Kitzbühel Alp
    ("/kitzb", "Kitzbühel Alp"),
    ("/steininger", "Kitzbühel Alp"),

    # M365 / IT
    ("/m365/", "M365 Migration"),
    ("/bcomm/", "M365 Migration"),

    # AI / Baker
    ("/ai_team/", "Baker"),
    ("/baker/", "Baker"),

    # Financing
    ("/financing/", "Financing Vienna & Baden-Baden"),
    ("/loan/", "Financing Vienna & Baden-Baden"),
    ("/bank/", "Financing Vienna & Baden-Baden"),

    # FX Mayr
    ("/fx_mayr/", "FX Mayr"),
    ("/lilienmatt/", "FX Mayr"),

    # Wertheimer
    ("/wertheimer/", "Wertheimer LP"),

    # ClaimsMax
    ("/claimsmax/", "ClaimsMax"),
    ("/claims/", "ClaimsMax"),
]

# Sub-folder refinements for MOVIE project
MOVIE_SUBPATH_MAP = [
    ("/sales", "Mandarin Oriental Sales"),
    ("/marketing", "Mandarin Oriental Sales"),
    ("/pr/", "Mandarin Oriental Sales"),
    ("/asset_management/", "Mandarin Oriental Asset Management"),
    ("/hotel/", "Mandarin Oriental Asset Management"),
    ("/operations/", "Mandarin Oriental Asset Management"),
    ("/construction/", "Mandarin Oriental Asset Management"),
    ("/hagenauer", "Hagenauer"),
    ("/cupial", "Cupial"),
]


def run_backfill():
    """Assign matter_slug to documents based on source_path patterns."""
    from config.settings import config

    conn = psycopg2.connect(
        host=config.postgres.host,
        port=config.postgres.port,
        dbname=config.postgres.dbname,
        user=config.postgres.user,
        password=config.postgres.password,
    )

    cur = conn.cursor()

    # Fetch all docs without matter_slug
    cur.execute("""
        SELECT id, source_path FROM documents
        WHERE (matter_slug IS NULL OR matter_slug = '')
          AND source_path IS NOT NULL
    """)
    rows = cur.fetchall()
    print(f"Found {len(rows)} documents without matter_slug")

    updated = 0
    for doc_id, source_path in rows:
        path_lower = source_path.lower()
        matter = None

        # Check main path patterns
        for pattern, slug in PATH_MATTER_MAP:
            if pattern in path_lower:
                matter = slug
                break

        # Refine MOVIE project sub-paths
        if matter and "mandarin oriental" in matter.lower():
            for sub_pattern, sub_slug in MOVIE_SUBPATH_MAP:
                if sub_pattern in path_lower:
                    matter = sub_slug
                    break

        if matter:
            cur.execute(
                "UPDATE documents SET matter_slug = %s WHERE id = %s",
                (matter, doc_id),
            )
            updated += 1
            if updated % 100 == 0:
                conn.commit()
                print(f"  Updated {updated}/{len(rows)}...")

    conn.commit()
    cur.close()
    conn.close()
    print(f"Done. Updated {updated}/{len(rows)} documents with matter_slug.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_backfill()
```

Run with: `python3 scripts/backfill_matter_from_path.py`

Expected: ~1,200-1,500 docs get matter_slug assigned. "no matter" drops from 51% to ~10-15%.

### Fix 3: Update the live pipeline to use path hints

In `tools/document_pipeline.py`, modify `classify_document()` to extract a path hint and include it in the Haiku prompt:

After line 65 (`matters_list = _get_active_matters()`), add:

```python
    # Extract path hint for matter matching
    path_hint = ""
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if conn:
            try:
                cur = conn.cursor()
                cur.execute("SELECT source_path FROM documents WHERE id = %s", (doc_id,))
                row = cur.fetchone()
                if row and row[0]:
                    path_hint = f"\nFile path: {row[0]}\n(Use the folder names as hints for matter_slug matching)"
                cur.close()
            finally:
                store._put_conn(conn)
    except Exception:
        pass
```

Then include `path_hint` in the prompt:

```python
    prompt = _CLASSIFY_PROMPT.format(
        matters_list=matters_list,
        text=path_hint + full_text[:8000],  # path hint prepended
    )
```

## Testing

1. Run Fix 1 SQL — verify "other" count drops by ~1,060
2. Run Fix 2 script — verify matter_slug count increases significantly
3. Syntax check `tools/document_pipeline.py`
4. Verify retriever excludes `media_asset` docs from search results

## Summary

| Metric | Before | After |
|--------|--------|-------|
| "other" documents | 1,340 (42%) | ~280 (9%) |
| Images in search | 1,060 | 0 |
| Docs with matter_slug | 1,569 (49%) | ~2,800+ (88%) |
| Cost | — | €0 |
