#!/usr/bin/env python3
"""
CORTEX-PHASE-1A: Seed wiki_pages from existing view files.
Run ONCE after wiki_pages table is created.
Idempotent — uses ON CONFLICT DO NOTHING (preserves manual edits).
"""
import os
import sys
import psycopg2

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL not set")
    sys.exit(1)


def get_conn():
    return psycopg2.connect(DATABASE_URL)


def slug_from_filename(pm_slug: str, filename: str) -> str:
    """Convert 'SCHEMA.md' -> 'ao_pm/index', 'psychology.md' -> 'ao_pm/psychology'."""
    base = filename.replace(".md", "").lower().replace("_", "-").replace(" ", "-")
    if base == "schema":
        base = "index"
    return f"{pm_slug}/{base}"


def seed_pm_files(conn, pm_slug: str, view_dir: str, file_order: list):
    """Seed wiki_pages from a PM's view files."""
    cur = conn.cursor()
    base_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), view_dir)

    if not os.path.isdir(base_dir):
        print(f"  SKIP: {base_dir} not found")
        return 0

    count = 0
    for fname in file_order:
        fpath = os.path.join(base_dir, fname)
        if not os.path.isfile(fpath):
            print(f"  SKIP: {fname} not found")
            continue

        with open(fpath, "r", encoding="utf-8") as f:
            content = f.read()

        slug = slug_from_filename(pm_slug, fname)
        title = fname.replace(".md", "").replace("_", " ").title()
        if fname == "SCHEMA.md":
            title = f"{pm_slug.upper().replace('_', ' ')} — Index"

        # Determine matter_slugs based on PM
        matter_slugs = {
            "ao_pm": ["ao", "hagenauer"],
            "movie_am": ["movie", "rg7"],
        }.get(pm_slug, [])

        cur.execute("""
            INSERT INTO wiki_pages (slug, title, content, agent_owner, page_type, matter_slugs, updated_by)
            VALUES (%s, %s, %s, %s, 'agent_knowledge', %s, 'seed_script')
            ON CONFLICT (slug) DO NOTHING
        """, (slug, title, content, pm_slug, matter_slugs))

        if cur.rowcount > 0:
            count += 1
            print(f"  SEEDED: {slug} ({len(content)} chars)")
        else:
            print(f"  EXISTS: {slug} (skipped)")

    conn.commit()
    cur.close()
    return count


def seed_ftc_explanations(conn):
    """Seed FTC table explanations as an AO PM knowledge page."""
    # Try multiple possible locations
    candidates = [
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "data", "ao_pm", "ftc-table-explanations.md"),
        os.path.expanduser(
            "~/.claude/projects/-Users-dimitry-Desktop-baker-code/memory/ao-ftc-table-explanations.md"
        ),
    ]

    content = None
    for path in candidates:
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            print(f"  Found FTC explanations at: {path}")
            break

    if not content:
        print("  SKIP: FTC table explanations not found at any candidate path")
        return 0

    cur = conn.cursor()
    cur.execute("""
        INSERT INTO wiki_pages (slug, title, content, agent_owner, page_type, matter_slugs, updated_by)
        VALUES (%s, %s, %s, %s, 'agent_knowledge', %s, 'seed_script')
        ON CONFLICT (slug) DO NOTHING
    """, (
        "ao_pm/ftc-table-explanations",
        "AO Financing to Completion — Row-by-Row Explanations",
        content,
        "ao_pm",
        ["ao", "hagenauer"],
    ))

    count = 1 if cur.rowcount > 0 else 0
    conn.commit()
    cur.close()
    return count


def main():
    conn = get_conn()

    # Verify table exists
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'wiki_pages'")
    if cur.fetchone()[0] == 0:
        print("ERROR: wiki_pages table does not exist. Run the app first to create it.")
        sys.exit(1)
    cur.close()

    total = 0

    # AO PM view files
    print("\n=== AO PM ===")
    total += seed_pm_files(conn, "ao_pm", "data/ao_pm", [
        "SCHEMA.md", "psychology.md", "investment_channels.md",
        "financing_to_completion.md", "sensitive_issues.md",
        "communication_rules.md", "agenda.md",
    ])

    # AO PM FTC explanations
    print("\n=== FTC Table Explanations ===")
    total += seed_ftc_explanations(conn)

    # MOVIE AM view files
    print("\n=== MOVIE AM ===")
    total += seed_pm_files(conn, "movie_am", "data/movie_am", [
        "SCHEMA.md", "agreements_framework.md", "operator_dynamics.md",
        "kpi_framework.md", "owner_obligations.md", "agenda.md",
    ])

    print(f"\n=== DONE: {total} pages seeded ===")

    # Final count
    cur = conn.cursor()
    cur.execute("SELECT agent_owner, COUNT(*) FROM wiki_pages GROUP BY agent_owner ORDER BY agent_owner")
    for row in cur.fetchall():
        print(f"  {row[0]}: {row[1]} pages")
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
