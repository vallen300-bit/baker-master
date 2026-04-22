# BRIEF: AO_PM_EXTENSION_1_PHASE2 — residual work (tomorrow)

## Context

Phase 1 (`BRIEF_AO_PM_EXTENSION_1.md`) shipped tonight: routing diagnostic + system prompt Part C addendum + `wiki_pages` content refresh + smoke test. Phase 1 gave Director a functional AO PM with dated-citation behavior, reading fresh content from Postgres.

This brief covers the residual work from the original full scope — the parts that were **cosmetic tonight** because the runtime reads `wiki_pages` (Postgres), not the filesystem, when `wiki_context_enabled=True`.

**Why still ship it:**
- 3-layer SoT ratification (2026-04-22) names Obsidian `.md` as the L2 primary. Until vault is primary, drift risk compounds.
- Dropbox exit ratification (2026-04-19) — `data/ao_pm/` lives in the Dropbox-shadowed baker-code repo. Moving to the vault repo cuts the residual Dropbox coupling.
- Director-authored edits land in Obsidian natively; `data/ao_pm/` is read-only from Obsidian's perspective.
- `refresh_ao_pm_wiki_pages.py` (Phase 1) is manual-only; the proper ingest pipeline auto-refreshes on vault mtime.

## Estimated time: ~4h
## Complexity: Medium
## Prerequisites: Phase 1 shipped and smoke-tested green.

---

## Scope — 4 deliverables

| # | Deliverable | Files touched |
|---|---|---|
| 1 | Vault migration: 8 files `cp` + rename + frontmatter, 7 new scaffolds, 3 Gold shells, `ao_pm_lessons.md`, `interactions/README.md` | `baker-vault/wiki/matters/oskolkov/**` |
| 2 | Runtime wiring: `_resolve_view_dir` helper, PM_REGISTRY path flip, sub-matter on-demand loader, `PM_REGISTRY_VERSION` bump | `orchestrator/capability_runner.py` |
| 3 | vault→`wiki_pages` ingest script (replaces manual `refresh_ao_pm_wiki_pages.py`) | `scripts/ingest_vault_matter.py` (new), `scripts/refresh_ao_pm_wiki_pages.py` (removed) |
| 4 | Weekly vault lint + scheduler wiring | `scripts/lint_ao_pm_vault.py` (new), `triggers/embedded_scheduler.py` (+ job) |

Substrate Slack push + Anthropic Memory-tool pilot stay out-of-scope (defer to successor brief when substrate architecture lands).

---

## Deliverable 1 — Vault migration

### Scope

From `data/ao_pm/` → `baker-vault/wiki/matters/oskolkov/`:

- `cp` 8 files into vault, rename `_` → `-` in filenames to match `_index.md` wikilinks laid out by seed_migration 2026-04-14. Absorb `SCHEMA.md` content into `_index.md`.
- Add frontmatter to each file (`title`, `matter`, `type`, `layer: 2`, `live_state_refs: []`, `owner`, `last_audit`).
- Create 7 new scaffolds: `_overview.md`, `red-flags.md`, `financial-facts.md`, `sub-matters/{rg7-equity,capital-calls,restructuring,personal-loan,fx-mayr,tuscany}.md`.
- Create 3 Gold shells: `gold.md`, `proposed-gold.md`, `ao_pm_lessons.md` (with Worked/Didn't-work section structure).
- Create `interactions/README.md` (episodic stub; episodic fully wired via `BRIEF_CAPABILITY_THREADS_1`).

### Frontmatter template

```yaml
---
title: "<Human title>"
matter: oskolkov
type: distilled-knowledge
layer: 2
live_state_refs: []
owner: Director
last_audit: 2026-04-22
---
```

Set `owner: Edita + Baker` for `financing-to-completion.md` and `ftc-table-explanations.md`. Set `type: procedural-memory` for `ao_pm_lessons.md`. Set `status: empty` on the 3 Gold shells.

### `ao_pm_lessons.md` initial content

```markdown
---
title: AO PM Lessons
matter: oskolkov
type: procedural-memory
layer: 2
live_state_refs: []
owner: AI Head + Director
last_audit: 2026-04-22
status: scaffold
---

# AO PM Lessons

Consolidated process learnings between Silver (`baker_corrections` rows) and Gold (`gold.md`).

**Promotion rule:** a `baker_corrections` row that fires 3+ times (via `retrieval_count`) is a candidate for promotion here.
**Demotion rule:** a lesson not referenced in 60+ days is a candidate for retirement (lint flags).

## Worked — why
(Empty — populate as patterns emerge.)
Format: `- [YYYY-MM-DD] Pattern X worked because Y. Source: <baker_task_id / decision>`

## Didn't work — why
(Empty — populate as patterns emerge.)
Format: `- [YYYY-MM-DD] Pattern X failed because Y. Root cause: Z. Source: <ref>`

## Counterparty tactical
- [2026-04-22] Cite every past AO statement with exact date inline. Reason: AO remembers dates but feigns amnesia. Source: `_ops/ideas/2026-04-22-ao-pm-revision-v3.md` §C.

## Pending promotion to gold.md
(Empty — populated by AI Head review.)
```

### Do NOT delete `data/ao_pm/`

Retain as fallback until Deliverable 2 is verified in production.

### Verification

```bash
ls -la /Users/dimitry/baker-vault/wiki/matters/oskolkov/
ls -la /Users/dimitry/baker-vault/wiki/matters/oskolkov/sub-matters/
grep -L "^---$" /Users/dimitry/baker-vault/wiki/matters/oskolkov/*.md
# expect: empty (all files have frontmatter)
```

Commit in the vault repo:

```bash
cd ~/baker-vault
git add wiki/matters/oskolkov/
git commit -m "AO_PM_EXTENSION_1_PHASE2: vault migration + scaffolds"
```

---

## Deliverable 2 — Runtime wiring (`_resolve_view_dir`)

### Current state
- `orchestrator/capability_runner.py:1296` resolves `view_dir` against baker-code repo root.
- `PM_REGISTRY["ao_pm"]["view_dir"] = "data/ao_pm"` (line 48).
- `view_file_order` at line 49 uses underscored filenames; must become hyphenated to match vault filenames.

### Helper (new, near line 1286 before `_load_pm_view_files`)

```python
def _resolve_view_dir(self, view_dir_config: str) -> str:
    """Resolve PM view_dir config to an absolute filesystem path.

    If view_dir starts with 'wiki/', resolve against BAKER_VAULT_PATH env var.
    Otherwise resolve against baker-code repo root (legacy).
    """
    import os
    if view_dir_config.startswith("wiki/"):
        vault_path = os.environ.get("BAKER_VAULT_PATH")
        if not vault_path:
            logger.warning(
                "BAKER_VAULT_PATH not set; cannot resolve %s — legacy fallback",
                view_dir_config,
            )
            return os.path.join(
                os.path.dirname(os.path.dirname(__file__)), view_dir_config
            )
        return os.path.join(vault_path, view_dir_config)
    return os.path.join(
        os.path.dirname(os.path.dirname(__file__)), view_dir_config
    )
```

### `_load_pm_view_files` — replace line 1296

```python
# BEFORE
view_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), config["view_dir"])
# AFTER
view_dir = self._resolve_view_dir(config["view_dir"])
```

### PM_REGISTRY update (line 44, bump version + path flip)

```python
PM_REGISTRY_VERSION = 2  # bumped — path scheme changed

PM_REGISTRY = {
    "ao_pm": {
        "registry_version": 2,
        "name": "AO Project Manager",
        "view_dir": "wiki/matters/oskolkov",  # was: "data/ao_pm"
        "view_file_order": [
            "_index.md",
            "_overview.md",
            "psychology.md",
            "investment-channels.md",       # was: investment_channels.md
            "financing-to-completion.md",   # was: financing_to_completion.md
            "ftc-table-explanations.md",    # NEW in order
            "agenda.md",
            "sensitive-issues.md",          # was: sensitive_issues.md
            "communication-rules.md",       # was: communication_rules.md
            "red-flags.md",
            "financial-facts.md",
        ],
        # ... rest of config unchanged (keep all signal patterns, keywords, etc.)
        "extraction_view_files": [
            # mirror the hyphenated names (line 84-88)
            "psychology.md", "investment-channels.md",
            "financing-to-completion.md",
            "sensitive-issues.md", "communication-rules.md", "agenda.md",
        ],
    },
    ...
}
```

### Sub-matter on-demand loader (append to `_load_pm_view_files` after the main loop)

```python
# Sub-matters: load only active ones per pm_project_state
try:
    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack._get_global_instance()
    state = store.get_pm_project_state(pm_slug) or {}
    sub_matters = (state.get("state_json") or {}).get("sub_matters") or {}
    active_slugs = [k for k, v in sub_matters.items() if v]
    sub_dir = os.path.join(view_dir, "sub-matters")
    if os.path.isdir(sub_dir) and active_slugs:
        for slug in active_slugs:
            fname = f"{slug.replace('_', '-')}.md"
            fpath = os.path.join(sub_dir, fname)
            if os.path.isfile(fpath):
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        content = f.read()
                    parts.append(f"## SUB-MATTER VIEW: {fname}\n{content}")
                except Exception as e:
                    logger.warning(
                        "Failed to read sub-matter %s/%s: %s", pm_slug, fname, e
                    )
except Exception as e:
    logger.warning("Sub-matter loading failed for %s: %s", pm_slug, e)
```

### Do NOT change
- `_load_wiki_context` priority logic (line 844-859). Dual-run pattern stays; wiki_pages keeps priority, filesystem is fallback. Deliverable 3 (ingest pipeline) keeps wiki_pages fresh from vault.

### Verification

```bash
python3 -c "import py_compile; py_compile.compile('orchestrator/capability_runner.py', doraise=True)"
export BAKER_VAULT_PATH=/Users/dimitry/baker-vault
python3 -c "
from orchestrator.capability_runner import CapabilityRunner, PM_REGISTRY
r = CapabilityRunner.__new__(CapabilityRunner)
path = r._resolve_view_dir(PM_REGISTRY['ao_pm']['view_dir'])
import os
print('path=', path, 'exists=', os.path.isdir(path))
"
```

---

## Deliverable 3 — vault→`wiki_pages` ingest pipeline

### Scope
Replace Phase 1's `scripts/refresh_ao_pm_wiki_pages.py` (manual, reads `data/ao_pm/`) with `scripts/ingest_vault_matter.py` (matter-generic, reads `BAKER_VAULT_PATH/wiki/matters/<slug>/`).

### `scripts/ingest_vault_matter.py` (new, ~100 lines)

```python
"""Ingest a vault matter folder into wiki_pages.

Wipes existing rows for agent_owner=<pm_slug> and re-inserts from vault.
Matter-generic — works for ao_pm, movie_am, etc.

Usage: python3 scripts/ingest_vault_matter.py oskolkov
"""
import os
import sys
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MATTER_TO_PM = {
    "oskolkov": "ao_pm",
    "movie":    "movie_am",
}


def main(matter_slug: str):
    vault_path = os.environ.get("BAKER_VAULT_PATH")
    if not vault_path:
        raise RuntimeError("BAKER_VAULT_PATH not set")
    matter_dir = Path(vault_path) / "wiki" / "matters" / matter_slug
    if not matter_dir.is_dir():
        raise RuntimeError(f"Matter dir not found: {matter_dir}")
    pm_slug = MATTER_TO_PM.get(matter_slug)
    if not pm_slug:
        raise RuntimeError(f"Unknown matter: {matter_slug}")

    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    if not conn:
        raise RuntimeError("DB connection unavailable")
    try:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM wiki_pages WHERE agent_owner = %s AND page_type = 'agent_knowledge'",
            (pm_slug,),
        )
        logger.info("Deleted %d stale rows for %s", cur.rowcount, pm_slug)

        inserted = 0
        for path in sorted(matter_dir.glob("*.md")):
            if path.name == "_lint-report.md":
                continue
            content = path.read_text(encoding="utf-8")
            title = _extract_title(content) or path.stem
            cur.execute(
                """
                INSERT INTO wiki_pages (slug, title, content, agent_owner, page_type)
                VALUES (%s, %s, %s, %s, 'agent_knowledge')
                """,
                (path.stem, title, content, pm_slug),
            )
            inserted += 1
        sub_dir = matter_dir / "sub-matters"
        if sub_dir.is_dir():
            for path in sorted(sub_dir.glob("*.md")):
                content = path.read_text(encoding="utf-8")
                title = _extract_title(content) or path.stem
                cur.execute(
                    """
                    INSERT INTO wiki_pages (slug, title, content, agent_owner, page_type)
                    VALUES (%s, %s, %s, %s, 'agent_knowledge')
                    """,
                    (f"sub-matters/{path.stem}", title, content, pm_slug),
                )
                inserted += 1

        conn.commit()
        logger.info("Inserted %d fresh rows for %s", inserted, pm_slug)
    except Exception as e:
        conn.rollback()
        logger.error("Ingest failed: %s", e)
        raise
    finally:
        cur.close()
        store._put_conn(conn)


def _extract_title(content: str) -> str | None:
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
```

### After Deliverable 2 deploys, run ingest:

```bash
export BAKER_VAULT_PATH=/opt/render/project/src/baker-vault-mirror  # Render
python3 scripts/ingest_vault_matter.py oskolkov
```

Then delete `scripts/refresh_ao_pm_wiki_pages.py` and `data/ao_pm/` (after verifying Quality Checkpoint below).

### Verification

```sql
SELECT slug, LENGTH(content) AS chars, updated_at
FROM wiki_pages WHERE agent_owner = 'ao_pm' AND page_type = 'agent_knowledge'
ORDER BY slug LIMIT 25;
-- expect: 11 top-level + 6 sub-matters = 17 rows, updated_at within last 5 min
```

---

## Deliverable 4 — Weekly vault lint

### Scope
Weekly lint catches drift (Layer 2 ref to non-existent Layer 1 field), broken wikilinks, missing frontmatter, stale `baker_corrections` rules (60+ days no retrieval), `interactions/` files missing 4 required timestamps.

### `scripts/lint_ao_pm_vault.py` (new, ~150 lines)

[Full script spec — see original BRIEF_AO_PM_EXTENSION_1 commit `HEAD~1` in this file's history, Deliverable 5. Re-use that spec verbatim; it was pre-reviewed.]

Key checks:
- `_check_frontmatter` — every `.md` has title/matter/type/layer
- `_check_wikilinks` — `[[target]]` resolves to an existing file
- `_check_drift` — `live_state_refs:` in frontmatter references existing `pm_project_state.state_json` keys
- `_check_stale_lessons` — `baker_corrections` rows with `last_retrieved_at < NOW() - 60 days`, LIMIT 20
- `_check_interactions` — files in `interactions/` contain `source_at`, `ingest_at`, `recall_at`, `decision_at`

Output: `baker-vault/wiki/matters/oskolkov/_lint-report.md` (overwritten each run).

### Scheduler wiring — `triggers/embedded_scheduler.py`

Piggyback the existing APScheduler pattern at line 221 (`wiki_lint` — daily). Add alongside:

```python
# AO PM matter lint — weekly Sunday 06:00 UTC
scheduler.add_job(
    _run_ao_pm_lint,
    CronTrigger(day_of_week="sun", hour=6, minute=0, timezone="UTC"),
    id="ao_pm_lint", name="ao_pm_lint",
    coalesce=True, max_instances=1, replace_existing=True,
)
logger.info("Registered: ao_pm_lint (Sunday 06:00 UTC)")
```

Helper near `_run_wiki_lint` (line 716):

```python
def _run_ao_pm_lint():
    """BRIEF_AO_PM_EXTENSION_1_PHASE2: Run AO PM vault lint and log results."""
    try:
        from scripts.lint_ao_pm_vault import main as _ao_lint_main
        _ao_lint_main()
        logger.info("ao_pm_lint: completed")
        try:
            from triggers.sentinel_health import report_success
            report_success("ao_pm_lint", {})
        except Exception:
            pass
    except Exception as e:
        logger.error("ao_pm_lint failed: %s", e)
        try:
            from triggers.sentinel_health import report_failure
            report_failure("ao_pm_lint", str(e))
        except Exception:
            pass
```

---

## Files Modified

**baker-vault repo:**
- `wiki/matters/oskolkov/**` — 11 top-level files (8 migrated + 3 new) + 6 sub-matters + 3 Gold shells + `ao_pm_lessons.md` + `interactions/README.md` + updated `_index.md`

**baker-code repo:**
- `orchestrator/capability_runner.py` — `_resolve_view_dir` (new), `_load_pm_view_files` call site, `PM_REGISTRY["ao_pm"]` path + file list, sub-matter loader, `PM_REGISTRY_VERSION` → 2
- `scripts/ingest_vault_matter.py` — NEW
- `scripts/lint_ao_pm_vault.py` — NEW
- `triggers/embedded_scheduler.py` — `ao_pm_lint` job + helper
- `scripts/refresh_ao_pm_wiki_pages.py` — DELETED (superseded by ingest script)
- `data/ao_pm/` — DELETED (after verification)

## Do NOT Touch
- `capability_sets.system_prompt` for `ao_pm` — already carries Phase 1 addendum; do not re-apply.
- Any wiki_pages row for `agent_owner ≠ 'ao_pm'`.
- `_load_wiki_context` priority logic — dual-run stays.
- MOVIE AM — its own extension brief applies the same pattern separately.

## Quality Checkpoints
1. All Python files syntax-check.
2. Vault files present (11 + 6 + 3 + lessons + interactions README).
3. Every vault .md has valid frontmatter.
4. `_resolve_view_dir("wiki/matters/oskolkov")` returns the Render mirror path on prod.
5. `wiki_pages` row count for `ao_pm` matches vault file count after ingest.
6. AO PM invocation after deploy still returns dated citations (Phase 1 behavior preserved) and now includes content from `_overview.md` / `red-flags.md` / `financial-facts.md` (new files).
7. Lint runs without crash, writes `_lint-report.md`.
8. Scheduler shows `ao_pm_lint` registered in logs at next restart.

## Deployment Order

1. Deliverable 1 (vault commit) — vault repo only, no baker-code deploy.
2. Deliverable 3 (ingest script) — code deploy. Run script once after deploy. Verify `wiki_pages` refreshed. **Do not delete `data/ao_pm/` yet.**
3. Deliverable 2 (runtime wiring) — code deploy. Smoke-test an AO PM invocation.
4. Delete `data/ao_pm/` and `scripts/refresh_ao_pm_wiki_pages.py` after #3 verified.
5. Deliverable 4 (lint) — code deploy. Lint runs next Sunday.

## Rollback

1. **Vault content:** `git revert` the vault commit.
2. **Runtime wiring:** revert `PM_REGISTRY["ao_pm"]` path + file list + `_resolve_view_dir` diff.
3. **Ingest script:** no rollback needed; idempotent.
4. **Lint:** remove scheduler wiring; script is dormant when not invoked.

## Reference trail
- Phase 1: `briefs/BRIEF_AO_PM_EXTENSION_1.md`
- Ratified architecture: `/Users/dimitry/baker-vault/_ops/ideas/2026-04-22-ao-pm-revision-v3.md`
- Charter: `/Users/dimitry/baker-vault/_ops/processes/ai-head-autonomy-charter.md`
