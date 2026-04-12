# Code Brisen — CORTEX-PHASE-1A Opening Prompt

## Your Task
Implement Baker Cortex Phase 1A: Wiki infrastructure + dual-run knowledge migration.

## Brief
Read: `briefs/BRIEF_CORTEX_PHASE_1A.md`

## What You're Building
1. `wiki_pages` PostgreSQL table — the knowledge layer for all Baker agents
2. `cortex_config` table — feature flags for zero-downtime rollback
3. `wiki_config` JSONB column on `capability_sets` — per-agent knowledge config
4. Seed 14 wiki pages from existing view files (`data/ao_pm/`, `data/movie_am/`)
5. `load_agent_context()` in `capability_runner.py` — reads from wiki when flag ON, filesystem when OFF
6. Feature flag `wiki_context_enabled` — OFF by default, flip to test wiki path

## Key Rules
- **DUAL-RUN:** When flag is OFF, AO PM works EXACTLY as before. Zero behavior change.
- **Originals untouched:** `data/ao_pm/` and `data/movie_am/` directories must NOT be modified or deleted.
- **Auto-seed pattern:** Use Option C from the brief — seed wiki_pages in `_ensure_wiki_pages_table()` if table is empty, same pattern as `_seed_capability_sets()`.
- **LIMIT on all queries.** Rollback in all except blocks. Verify column names exist.
- **Syntax check every Python file** before committing.

## Files to Modify
- `memory/store_back.py` — 3 new methods + 2 modifications
- `orchestrator/capability_runner.py` — 2 new methods + 1 modification
- `scripts/seed_wiki_pages.py` — NEW file (also used by auto-seed)

## Files NOT to Touch
- `data/ao_pm/*.md`, `data/movie_am/*.md` — backups, read-only
- `orchestrator/agent.py` — no tool router in Phase 1A
- `pipeline.py`, `capability_registry.py` — unchanged

## Verify Before Done
```bash
python3 -c "import py_compile; py_compile.compile('memory/store_back.py', doraise=True)"
python3 -c "import py_compile; py_compile.compile('orchestrator/capability_runner.py', doraise=True)"
python3 -c "import py_compile; py_compile.compile('scripts/seed_wiki_pages.py', doraise=True)"
```

## After Push
Tables auto-create on Render deploy. Wiki pages auto-seed on first startup. Flag starts OFF — zero risk. Flip flag via SQL to test wiki path.
