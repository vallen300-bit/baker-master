"""Ingest a vault matter folder into wiki_pages.

Wipes existing rows for agent_owner=<pm_slug> (page_type='agent_knowledge')
and re-inserts from vault.

Slug convention matches memory/store_back.py:_seed_wiki_from_view_files
(line 2544-2547): {pm_slug}/{base}, where base is filename stem lowercased
with underscores → hyphens, and `_index.md` (→ `-index`) or bare `schema`
map to `index`. Leading `-` (from other `_`-prefixed files) is stripped.

Usage: python3 scripts/ingest_vault_matter.py oskolkov
Requires: BAKER_VAULT_PATH env var.
"""
import logging
import os
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ingest_vault_matter")

# matter_slug → (pm_slug, matter_slugs array). matter_slugs mirrors existing
# seed convention (memory/store_back.py:2515, 2523).
MATTER_CONFIG = {
    "oskolkov": {"pm_slug": "ao_pm",    "matter_slugs": ["ao", "hagenauer"]},
    "movie":    {"pm_slug": "movie_am", "matter_slugs": ["movie", "rg7"]},
}

# Files to skip at the top level (transitional / generated artefacts).
SKIP_FILES = {"_lint-report.md", "_schema-legacy.md"}


def main(matter_slug: str):
    vault_path = os.environ.get("BAKER_VAULT_PATH")
    if not vault_path:
        raise RuntimeError("BAKER_VAULT_PATH not set")
    matter_dir = Path(vault_path) / "wiki" / "matters" / matter_slug
    if not matter_dir.is_dir():
        raise RuntimeError(f"Matter dir not found: {matter_dir}")
    cfg = MATTER_CONFIG.get(matter_slug)
    if not cfg:
        raise RuntimeError(f"Unknown matter: {matter_slug}")
    pm_slug = cfg["pm_slug"]
    matter_slugs = cfg["matter_slugs"]

    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    if not conn:
        raise RuntimeError("DB connection unavailable")
    cur = None
    try:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM wiki_pages WHERE agent_owner = %s AND page_type = 'agent_knowledge'",
            (pm_slug,),
        )
        logger.info("Deleted %d stale rows for %s", cur.rowcount, pm_slug)

        inserted = 0
        # Top-level files
        for path in sorted(matter_dir.glob("*.md")):
            if path.name in SKIP_FILES:
                logger.info("skip top-level: %s", path.name)
                continue
            content = path.read_text(encoding="utf-8")
            title = _extract_title(content) or _default_title(path.stem)
            slug = _make_slug(pm_slug, path.stem)
            cur.execute(
                """
                INSERT INTO wiki_pages
                    (slug, title, content, agent_owner, page_type,
                     matter_slugs, updated_by)
                VALUES (%s, %s, %s, %s, 'agent_knowledge', %s, 'ingest_vault_matter')
                """,
                (slug, title, content, pm_slug, matter_slugs),
            )
            inserted += 1

        # Sub-matters
        sub_dir = matter_dir / "sub-matters"
        if sub_dir.is_dir():
            for path in sorted(sub_dir.glob("*.md")):
                content = path.read_text(encoding="utf-8")
                title = _extract_title(content) or _default_title(path.stem)
                base = path.stem.lower().replace("_", "-")
                slug = f"{pm_slug}/sub-matters/{base}"
                cur.execute(
                    """
                    INSERT INTO wiki_pages
                        (slug, title, content, agent_owner, page_type,
                         matter_slugs, updated_by)
                    VALUES (%s, %s, %s, %s, 'agent_knowledge', %s, 'ingest_vault_matter')
                    """,
                    (slug, title, content, pm_slug, matter_slugs),
                )
                inserted += 1

        conn.commit()
        logger.info("Inserted %d fresh rows for %s", inserted, pm_slug)
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error("Ingest failed: %s", e)
        raise
    finally:
        if cur is not None:
            try:
                cur.close()
            except Exception:
                pass
        store._put_conn(conn)


def _make_slug(pm_slug: str, stem: str) -> str:
    """Match memory/store_back.py:_seed_wiki_from_view_files convention.

    Lowercase, underscores → hyphens, spaces → hyphens. `-index` (from
    `_index.md`) and bare `schema` both map to `index` (legacy SCHEMA.md
    convention). Other `_`-prefixed files strip the leading `-` for URL
    hygiene (e.g. `_overview` → `overview`).
    """
    base = stem.lower().replace("_", "-").replace(" ", "-")
    if base in ("-index", "schema"):
        base = "index"
    elif base.startswith("-"):
        base = base.lstrip("-")
    return f"{pm_slug}/{base}"


def _default_title(stem: str) -> str:
    return stem.replace("_", " ").replace("-", " ").title()


def _extract_title(content: str) -> Optional[str]:
    for line in content.splitlines()[:30]:
        if line.startswith("title:"):
            return line.split(":", 1)[1].strip().strip('"').strip("'")
        if line.startswith("# "):
            return line[2:].strip()
    return None


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: ingest_vault_matter.py <matter_slug>")
        sys.exit(1)
    main(sys.argv[1])
