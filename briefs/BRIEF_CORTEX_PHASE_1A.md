# BRIEF: CORTEX-PHASE-1A — Wiki Infrastructure + Dual-Run Knowledge Migration

## Context
Baker Cortex v2 Phase 0 is done (store_decision hotfix, commit `73dea80`). Phase 1A builds the wiki infrastructure that underpins all future Cortex work. Director's requirement: migrate ALL current knowledge (not just stubs) into `wiki_pages` table, but keep originals untouched. AO PM and MOVIE AM continue working on the old filesystem path. A feature flag (`wiki_context_enabled`) controls which path is used. When verified, one flag flip switches over.

**Parent brief:** `briefs/BRIEF_AGENT_ORCHESTRATION_1.md` — full Cortex v2 architecture.

## Estimated time: ~6-8h
## Complexity: Medium
## Prerequisites: None (Phase 0 complete)

---

## The Approach: Dual-Run with Feature Flag

```
wiki_context_enabled = false  →  AO PM reads from data/ao_pm/*.md (CURRENT — unchanged)
wiki_context_enabled = true   →  AO PM reads from wiki_pages table (NEW)
```

**Originals untouched:** `data/ao_pm/` and `data/movie_am/` directories stay as-is. No files deleted. No filesystem paths changed. Render deploys continue working.

**Zero risk:** If wiki path breaks, flip flag back to `false` — instant rollback, no redeploy.

---

## Step 1: Create `wiki_pages` Table

### Problem
No wiki infrastructure exists. Agents have no shared knowledge layer.

### Current State
Knowledge lives in filesystem (`data/ao_pm/*.md`, `data/movie_am/*.md`) loaded by `_load_pm_view_files()` at `capability_runner.py:1271`. No database table for wiki content.

### Implementation

Add `_ensure_wiki_pages_table()` to `memory/store_back.py`. Follow the exact pattern of `_ensure_capability_sets_table()` (line 2180).

```python
def _ensure_wiki_pages_table(self):
    """Create wiki_pages table + indexes. Idempotent."""
    conn = self._get_conn()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS wiki_pages (
                id BIGSERIAL PRIMARY KEY,
                slug TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                agent_owner TEXT,
                page_type TEXT NOT NULL,
                matter_slugs TEXT[],
                backlinks TEXT[],
                generation INT DEFAULT 1,
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                updated_by TEXT
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_wiki_pages_type ON wiki_pages(page_type)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_wiki_pages_owner ON wiki_pages(agent_owner)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_wiki_pages_matter ON wiki_pages USING GIN(matter_slugs)")
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_wiki_pages_slug ON wiki_pages(slug)")
        conn.commit()
        cur.close()
        logger.info("wiki_pages table verified")
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning(f"Could not ensure wiki_pages table: {e}")
    finally:
        self._put_conn(conn)
```

Then add the call to the `__init__` method of `SentinelStoreBack`, right after `_ensure_pm_project_state_table()` (line 165):

```python
self._ensure_wiki_pages_table()
```

### Verification
```sql
SELECT column_name, data_type FROM information_schema.columns
WHERE table_name = 'wiki_pages' ORDER BY ordinal_position;
```
→ Should show all 11 columns: id, slug, title, content, agent_owner, page_type, matter_slugs, backlinks, generation, updated_at, updated_by

---

## Step 2: Create `cortex_config` Table with Feature Flags

### Problem
Need feature flags for zero-downtime rollback. No config table exists.

### Implementation

Add `_ensure_cortex_config_table()` to `memory/store_back.py`:

```python
def _ensure_cortex_config_table(self):
    """Create cortex_config table with feature flags. Idempotent."""
    conn = self._get_conn()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS cortex_config (
                key TEXT PRIMARY KEY,
                value JSONB NOT NULL,
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        # Seed feature flags — only if not present (idempotent)
        cur.execute("""
            INSERT INTO cortex_config (key, value) VALUES
                ('wiki_context_enabled', 'false'::jsonb),
                ('auto_merge_enabled', 'false'::jsonb),
                ('tool_router_enabled', 'false'::jsonb)
            ON CONFLICT (key) DO NOTHING
        """)
        conn.commit()
        cur.close()
        logger.info("cortex_config table verified (3 feature flags)")
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning(f"Could not ensure cortex_config table: {e}")
    finally:
        self._put_conn(conn)
```

Add the call in `__init__`, right after `_ensure_wiki_pages_table()`:

```python
self._ensure_cortex_config_table()
```

Also add a helper to read config values (used throughout Cortex):

```python
def get_cortex_config(self, key: str, default=None):
    """Read a Cortex feature flag. Returns Python value (bool/str/dict)."""
    conn = self._get_conn()
    if not conn:
        return default
    try:
        cur = conn.cursor()
        cur.execute("SELECT value FROM cortex_config WHERE key = %s", (key,))
        row = cur.fetchone()
        cur.close()
        if row:
            import json
            return json.loads(row[0]) if isinstance(row[0], str) else row[0]
        return default
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning(f"get_cortex_config({key}) failed: {e}")
        return default
    finally:
        self._put_conn(conn)
```

### Verification
```sql
SELECT * FROM cortex_config;
```
→ Should show 3 rows: `wiki_context_enabled=false`, `auto_merge_enabled=false`, `tool_router_enabled=false`

---

## Step 3: Add `wiki_config` JSONB to `capability_sets`

### Problem
Need per-agent config: which matters, documents, and compiled state pages each agent loads at session start.

### Current State
`capability_sets` has 17 columns (verified via `information_schema`). No `wiki_config` column.

### Implementation

In `_ensure_capability_sets_table()` at `store_back.py:2212`, add after the `use_thinking` ALTER:

```python
# CORTEX-PHASE-1A: Add wiki_config for agent knowledge routing
cur.execute("ALTER TABLE capability_sets ADD COLUMN IF NOT EXISTS wiki_config JSONB DEFAULT '{}'::jsonb")
```

Then after the `use_thinking` UPDATE block (line 2225), add:

```python
# CORTEX-PHASE-1A: Set wiki_config for AO PM and MOVIE AM
cur.execute("""
    UPDATE capability_sets SET wiki_config = %s
    WHERE slug = 'ao_pm' AND (wiki_config IS NULL OR wiki_config = '{}'::jsonb)
""", (json.dumps({
    "matters": ["hagenauer", "ao", "morv", "balgerstrasse"],
    "shared_docs": [
        "documents/hma-mo-vienna",
        "documents/ftc-table-v008",
        "documents/participation-agreement",
        "documents/hagenauer-insolvency"
    ],
    "compiled_state": ["deadlines-active", "decisions-recent", "contacts-vip"]
}),))

cur.execute("""
    UPDATE capability_sets SET wiki_config = %s
    WHERE slug = 'movie_am' AND (wiki_config IS NULL OR wiki_config = '{}'::jsonb)
""", (json.dumps({
    "matters": ["movie", "rg7"],
    "shared_docs": [
        "documents/hma-mo-vienna",
        "documents/movie-operating-budget"
    ],
    "compiled_state": ["deadlines-active", "decisions-recent", "contacts-vip"]
}),))
```

**Note:** Import json at top of function: `import json`

### Verification
```sql
SELECT name, wiki_config FROM capability_sets WHERE slug IN ('ao_pm', 'movie_am');
```
→ Both rows should have populated JSONB with matters and shared_docs arrays.

---

## Step 4: Populate wiki_pages with ALL Current Knowledge

### Problem
wiki_pages table exists but empty. Need to migrate everything AO PM and MOVIE AM currently know.

### Current Knowledge Sources

**AO PM (7 files, 383 lines total):**
| File | Lines | Slug in wiki_pages |
|------|-------|--------------------|
| `data/ao_pm/SCHEMA.md` | 18 | `ao_pm/index` |
| `data/ao_pm/psychology.md` | 63 | `ao_pm/psychology` |
| `data/ao_pm/investment_channels.md` | 68 | `ao_pm/investment-channels` |
| `data/ao_pm/financing_to_completion.md` | 111 | `ao_pm/financing-to-completion` |
| `data/ao_pm/sensitive_issues.md` | 37 | `ao_pm/sensitive-issues` |
| `data/ao_pm/communication_rules.md` | 46 | `ao_pm/communication-rules` |
| `data/ao_pm/agenda.md` | 40 | `ao_pm/agenda` |

**MOVIE AM (6 files, 572 lines total):**
| File | Lines | Slug in wiki_pages |
|------|-------|--------------------|
| `data/movie_am/SCHEMA.md` | 18 | `movie_am/index` |
| `data/movie_am/agreements_framework.md` | 209 | `movie_am/agreements-framework` |
| `data/movie_am/operator_dynamics.md` | 69 | `movie_am/operator-dynamics` |
| `data/movie_am/kpi_framework.md` | 83 | `movie_am/kpi-framework` |
| `data/movie_am/owner_obligations.md` | 88 | `movie_am/owner-obligations` |
| `data/movie_am/agenda.md` | 105 | `movie_am/agenda` |

**FTC Table Explanations (220 lines) — from Claude memory:**
This file lives at `~/.claude/projects/-Users-dimitry-Desktop-baker-code/memory/ao-ftc-table-explanations.md`. It is NOT in git. Copy it into the repo first, then seed it.

### Implementation

Create a seed script: `scripts/seed_wiki_pages.py`

```python
#!/usr/bin/env python3
"""
CORTEX-PHASE-1A: Seed wiki_pages from existing view files.
Run ONCE after wiki_pages table is created.
Idempotent — uses ON CONFLICT DO NOTHING (preserves manual edits).
"""
import os
import sys
import psycopg2
import json

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL not set")
    sys.exit(1)


def get_conn():
    return psycopg2.connect(DATABASE_URL)


def slug_from_filename(pm_slug: str, filename: str) -> str:
    """Convert 'SCHEMA.md' → 'ao_pm/index', 'psychology.md' → 'ao_pm/psychology'."""
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
```

### Pre-seed step
Copy FTC explanations into the repo so the seed script can find it on Render:

```bash
cp ~/.claude/projects/-Users-dimitry-Desktop-baker-code/memory/ao-ftc-table-explanations.md \
   data/ao_pm/ftc-table-explanations.md
```

### Verification
```sql
SELECT slug, agent_owner, page_type, LENGTH(content) as chars, updated_by
FROM wiki_pages ORDER BY slug LIMIT 20;
```
→ Should show 14 pages (8 AO PM + 6 MOVIE AM), all with `updated_by='seed_script'`

---

## Step 5: Implement `load_agent_context()` with Feature Flag

### Problem
Need a function that loads wiki context for agents at session start, but only when the feature flag is ON. When OFF, the existing filesystem path must work unchanged.

### Current State
`_build_system_prompt()` at `capability_runner.py:828` checks `if capability.slug in PM_REGISTRY` and calls `_load_pm_view_files()` to read from filesystem. This must continue working when the flag is OFF.

### Implementation

Add two methods to the `CapabilityRunner` class in `capability_runner.py`:

**Method 1: Read feature flag**

```python
def _get_cortex_config(self, key: str, default=False):
    """Read a Cortex config flag from cortex_config table."""
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        return store.get_cortex_config(key, default)
    except Exception:
        return default
```

**Method 2: Load wiki context**

```python
def _load_wiki_context(self, pm_slug: str) -> str:
    """CORTEX-PHASE-1A: Load agent context from wiki_pages table.
    Budget: ~8K tokens. Returns formatted string for system prompt injection.
    Falls back to empty string on any error (filesystem path is the backup)."""
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return ""

        cur = conn.cursor()

        # 1. Load all agent_knowledge pages for this PM
        cur.execute("""
            SELECT slug, title, content FROM wiki_pages
            WHERE agent_owner = %s AND page_type = 'agent_knowledge'
            ORDER BY CASE WHEN slug LIKE '%%/index' THEN 0 ELSE 1 END, slug
            LIMIT 20
        """, (pm_slug,))

        pages = cur.fetchall()
        cur.close()
        store._put_conn(conn)

        if not pages:
            logger.info("wiki_context: no pages for %s, falling back to filesystem", pm_slug)
            return ""

        # Format: same structure as _load_pm_view_files() for compatibility
        parts = []
        total_chars = 0
        max_chars = 32000  # ~8K tokens

        for slug, title, content in pages:
            if total_chars + len(content) > max_chars:
                logger.warning("wiki_context: budget exceeded at %s (%d chars), truncating", slug, total_chars)
                break
            parts.append(f"## WIKI: {title}\n{content}")
            total_chars += len(content)

        logger.info("wiki_context: loaded %d pages for %s (%d chars)", len(parts), pm_slug, total_chars)
        return "\n\n---\n\n".join(parts) if parts else ""

    except Exception as e:
        logger.warning("wiki_context failed for %s: %s — falling back to filesystem", pm_slug, e)
        return ""
```

**Method 3: Modify `_build_system_prompt()` — the dual-run switch**

At `capability_runner.py:834`, change the view file loading block. Replace:

```python
                if capability.slug in PM_REGISTRY:
                    pm_slug = capability.slug
                    pm_config = PM_REGISTRY[pm_slug]
                    label = pm_config.get("state_label", pm_slug)
                    # View files: stable compiled intelligence
                    view_ctx = self._load_pm_view_files(pm_slug)
                    if view_ctx:
                        prompt += f"\n\n# {label} VIEW (from {pm_config['view_dir']}/)\n{view_ctx}\n"
```

With:

```python
                if capability.slug in PM_REGISTRY:
                    pm_slug = capability.slug
                    pm_config = PM_REGISTRY[pm_slug]
                    label = pm_config.get("state_label", pm_slug)

                    # CORTEX-PHASE-1A: Dual-run — wiki or filesystem
                    wiki_enabled = self._get_cortex_config('wiki_context_enabled', False)
                    if wiki_enabled:
                        view_ctx = self._load_wiki_context(pm_slug)
                        if view_ctx:
                            prompt += f"\n\n# {label} KNOWLEDGE (from wiki_pages)\n{view_ctx}\n"
                        else:
                            # Wiki returned empty — fall back to filesystem
                            logger.warning("wiki_context empty for %s, falling back to filesystem", pm_slug)
                            view_ctx = self._load_pm_view_files(pm_slug)
                            if view_ctx:
                                prompt += f"\n\n# {label} VIEW (from {pm_config['view_dir']}/)\n{view_ctx}\n"
                    else:
                        # Feature flag OFF — use existing filesystem path (unchanged)
                        view_ctx = self._load_pm_view_files(pm_slug)
                        if view_ctx:
                            prompt += f"\n\n# {label} VIEW (from {pm_config['view_dir']}/)\n{view_ctx}\n"
```

### Key Constraints
- **The `else` branch (flag OFF) is IDENTICAL to the current code.** Zero behavior change when flag is off.
- **Wiki path has automatic fallback.** If wiki returns empty (table empty, connection failed), falls back to filesystem. Belt AND suspenders.
- **Budget cap: 32,000 chars (~8K tokens).** Prevents runaway context from wiki pages.
- **LIMIT 20 on SQL query.** Unbounded queries are a known anti-pattern.

### Verification

**Flag OFF (default):**
1. Deploy. AO PM session starts.
2. Check logs for: `wiki_context` should NOT appear in logs.
3. AO PM gets view files from filesystem — behavior unchanged.

**Flag ON (manual flip):**
```sql
UPDATE cortex_config SET value = 'true'::jsonb WHERE key = 'wiki_context_enabled';
```
4. AO PM session starts.
5. Check logs for: `wiki_context: loaded N pages for ao_pm`
6. System prompt now contains `# AO PM KNOWLEDGE (from wiki_pages)` instead of `# AO PM VIEW`
7. Content should be identical (same source files, just loaded from DB).

**Flag ON + wiki empty (safety):**
8. Delete all wiki_pages rows: `DELETE FROM wiki_pages WHERE agent_owner = 'ao_pm'`
9. AO PM session starts.
10. Logs: `wiki_context empty for ao_pm, falling back to filesystem`
11. System prompt has `# AO PM VIEW (from data/ao_pm/)` — filesystem fallback works.

---

## Step 6: Test AO PM Session with Wiki Context

### Implementation
This is a manual verification step, not code.

1. Deploy to Render (git push)
2. Wait for deploy to complete
3. Verify tables created:
```sql
SELECT table_name FROM information_schema.tables
WHERE table_name IN ('wiki_pages', 'cortex_config') ORDER BY table_name;
```
4. Run seed script on Render:
```bash
# From Render shell or via dashboard.py endpoint
python scripts/seed_wiki_pages.py
```
5. Verify wiki_pages populated:
```sql
SELECT slug, agent_owner, LENGTH(content) FROM wiki_pages ORDER BY slug LIMIT 20;
```
6. Flip the flag:
```sql
UPDATE cortex_config SET value = 'true'::jsonb WHERE key = 'wiki_context_enabled';
```
7. Start an AO PM conversation. Ask: "What are the open actions?"
8. Compare response quality with flag ON vs OFF (should be identical — same source data).
9. If satisfied → leave flag ON. If any issue → flip back to `false`.

---

## Files Modified

- `memory/store_back.py` — Add `_ensure_wiki_pages_table()`, `_ensure_cortex_config_table()`, `get_cortex_config()`. Modify `_ensure_capability_sets_table()` to add `wiki_config` column.
- `orchestrator/capability_runner.py` — Add `_get_cortex_config()`, `_load_wiki_context()`. Modify `_build_system_prompt()` for dual-run.
- `scripts/seed_wiki_pages.py` — NEW. One-time seed script.
- `data/ao_pm/ftc-table-explanations.md` — NEW. Copy from Claude memory.

## Do NOT Touch

- `data/ao_pm/*.md` — Original view files stay untouched (backup)
- `data/movie_am/*.md` — Original view files stay untouched (backup)
- `orchestrator/agent.py` — No tool router changes in Phase 1A
- `pipeline.py` — Pipeline flow unchanged
- `capability_registry.py` — Tool filtering unchanged
- Agent system prompts in `capability_sets` DB rows — Agents stay dumb about wiki vs filesystem

## Quality Checkpoints

1. `wiki_pages` table exists with all 11 columns
2. `cortex_config` table has 3 feature flags, all `false`
3. `capability_sets.wiki_config` populated for `ao_pm` and `movie_am`
4. `wiki_pages` has 14 pages (8 AO PM + 6 MOVIE AM)
5. Flag OFF → AO PM works exactly as before (filesystem path)
6. Flag ON → AO PM loads from wiki_pages, identical content
7. Flag ON + wiki empty → automatic fallback to filesystem
8. Context budget: total wiki content < 32,000 chars per agent
9. All Python files pass syntax check: `python3 -c "import py_compile; py_compile.compile('FILE', doraise=True)"`
10. `data/ao_pm/` and `data/movie_am/` directories are UNTOUCHED after deployment

## Verification SQL
```sql
-- Check tables exist
SELECT table_name FROM information_schema.tables
WHERE table_name IN ('wiki_pages', 'cortex_config') ORDER BY table_name;

-- Check feature flags
SELECT * FROM cortex_config;

-- Check wiki_config on capabilities
SELECT name, wiki_config FROM capability_sets WHERE slug IN ('ao_pm', 'movie_am');

-- Check wiki pages
SELECT slug, agent_owner, page_type, LENGTH(content) as chars, updated_by
FROM wiki_pages ORDER BY slug LIMIT 20;

-- Check page count per agent
SELECT agent_owner, COUNT(*) FROM wiki_pages GROUP BY agent_owner;
```

## Seed Script Execution

The seed script (`scripts/seed_wiki_pages.py`) needs `DATABASE_URL` env var. On Render, this is already set. To run:

**Option A: Via Render shell**
```bash
cd /opt/render/project/src && python scripts/seed_wiki_pages.py
```

**Option B: Add a one-time endpoint** (remove after use)
```python
@app.get("/api/admin/seed-wiki")
async def seed_wiki():
    """One-time: seed wiki_pages from view files. Remove after use."""
    import subprocess
    result = subprocess.run(
        ["python", "scripts/seed_wiki_pages.py"],
        capture_output=True, text=True, timeout=30
    )
    return {"stdout": result.stdout, "stderr": result.stderr, "returncode": result.returncode}
```

**Option C: Auto-seed in `_ensure_wiki_pages_table()`** — add after table creation:
```python
# Auto-seed if table is empty
cur.execute("SELECT COUNT(*) FROM wiki_pages")
if cur.fetchone()[0] == 0:
    self._seed_wiki_from_view_files(cur)
    conn.commit()
```

**Recommended: Option C** — same pattern as `_seed_capability_sets()`. Runs once on first deploy, idempotent. No manual step needed.
