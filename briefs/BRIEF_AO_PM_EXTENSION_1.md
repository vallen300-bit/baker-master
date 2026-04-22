# BRIEF: AO_PM_EXTENSION_1 — PHASE 1 (tonight, ~2.5h)

## Scope contraction — 2026-04-22 evening

**Research Agent escalation (2026-04-22):** `wiki_context_enabled=True` in prod and 8 `wiki_pages` rows already exist for `agent_owner='ao_pm'`. The runtime **reads Postgres, not the filesystem** (`orchestrator/capability_runner.py:844-852`). Vault migration + `_resolve_view_dir` wiring are therefore **cosmetic tonight** — they don't change what Director sees.

Director's goal: **AO PM functional tonight with Part C date-tactical behavior + fresh knowledge surface.** Not every deliverable complete.

**Tonight's critical path (this brief):**
1. Routing diagnostic (30 min, blocking)
2. System prompt Part C date-tactical addendum (runtime-visible after script run)
3. `wiki_pages` content refresh (UPDATE 8 existing rows from `data/ao_pm/*.md`)
4. Smoke test — Director runs an AO scan, verifies dated citations + fresh content

**Deferred to Phase 2 brief (`briefs/BRIEF_AO_PM_EXTENSION_1_PHASE2.md`, tomorrow):**
- Vault migration (8 `git mv` + 7 scaffolds + 3 Gold shells + `ao_pm_lessons.md` + `interactions/` stub)
- `_resolve_view_dir` runtime wiring + PM_REGISTRY path flip
- vault→`wiki_pages` auto-ingest pipeline
- Weekly lint job

## Estimated time: ~2.5h
## Complexity: Low (no code path changes — DB UPDATE + one system-prompt UPDATE)
## Prerequisites: none blocking — runs against current prod state

---

## Step 0 — Pre-flight (5 min, verify before Step 2 starts)

```sql
-- Confirm wiki_context is actually reading Postgres in prod
SELECT key, value FROM cortex_config WHERE key = 'wiki_context_enabled' LIMIT 1;
-- expect: value = 'true'

-- Confirm 8 wiki_pages rows exist and inspect their slugs
SELECT slug, LENGTH(content) AS chars, updated_at
FROM wiki_pages
WHERE agent_owner = 'ao_pm' AND page_type = 'agent_knowledge'
ORDER BY slug
LIMIT 20;
-- expect: 8 rows. Record the exact slugs — we UPDATE by slug in Step 3.
```

If either query returns unexpected state (flag off, row count ≠ 8), **stop** and flag to AI Head before proceeding. Do not improvise.

---

## Step 1 — Routing diagnostic (30 min, blocking)

### Problem
AO PM is 18 days stale (last run 2026-04-04). v3 §Part D names **case (c) — routing not working** as the suspected cause. Before shipping anything else, confirm whether the signal detector / decomposer are actually firing `ao_pm` on recent AO touchpoints.

### Queries (every query bounded with LIMIT)

```sql
-- (A) Recent AO-related inbound — last 21 days
SELECT COUNT(*) AS ao_mentions_21d
FROM email_messages
WHERE (from_address ILIKE '%oskolkov%' OR from_address ILIKE '%aelio%'
       OR subject ILIKE '%oskolkov%' OR subject ILIKE '%aelio%'
       OR body ILIKE '%oskolkov%' OR body ILIKE '%aelio%')
  AND created_at > NOW() - INTERVAL '21 days'
LIMIT 1;

-- (B) AO-related WhatsApp — last 21 days
SELECT COUNT(*) AS ao_wa_21d
FROM whatsapp_messages
WHERE (full_text ILIKE '%oskolkov%' OR full_text ILIKE '%andrey%')
  AND created_at > NOW() - INTERVAL '21 days'
LIMIT 1;

-- (C) How many ao_pm capability runs fired?
SELECT COUNT(*) AS ao_pm_runs_21d
FROM capability_runs
WHERE capability_slug = 'ao_pm' AND created_at > NOW() - INTERVAL '21 days'
LIMIT 1;

-- (D) Recent decomposer decisions (spot-check 20 most recent that mention AO)
SELECT created_at, input_text, chosen_slugs
FROM decomposer_decisions
WHERE input_text ILIKE '%oskolkov%' OR input_text ILIKE '%aelio%' OR input_text ILIKE '%andrey%'
ORDER BY created_at DESC
LIMIT 20;
-- Confirm: is 'ao_pm' appearing in chosen_slugs for these inputs?
-- If table name differs, grep orchestrator/ for the actual logging table.
```

### Decision tree (report result before Step 2)

- **(A) or (B) > 0 AND (C) > 0, roughly aligned** → routing works. Proceed to Step 2.
- **(A)+(B) > 0, (C) = 0** → routing broken. File `briefs/_reports/B2_AO_ROUTING_DIAGNOSTIC_20260422.md` with inputs-vs-fires delta and the single most likely cause (signal_orbit_patterns miss / decomposer missing `ao_pm` in slug list / Scan handler skipping). STOP and notify AI Head. Still run Step 2 + 3 — they're independent of routing.
- **(A)+(B) = 0** → quiet matter (v3 case a). Note in report; proceed to Step 2.

### Key Constraints
- Every SELECT has a `LIMIT`.
- Read-only — no UPDATEs in this step.
- If `decomposer_decisions` table name is different, check with `\d` or grep `orchestrator/` before running query D. Don't guess.

---

## Step 2 — System prompt Part C date-tactical addendum (runtime-visible)

### Problem
AO remembers precise dates but feigns amnesia in negotiations (v3 §C1, Director-ratified 2026-04-22). AO PM output currently references AO statements without forcing dated citation. This loses operational ammunition every response.

### Current State
- `capability_sets.system_prompt` for slug `ao_pm` set by `scripts/insert_ao_pm_capability.py:17` (`AO_PM_SYSTEM_PROMPT` literal).
- Script is idempotent — re-runs UPDATE the existing row (line 227 path).
- Current prompt does **not** contain the date-tactical section.

### Implementation

**Step 2.1 — Edit `scripts/insert_ao_pm_capability.py`.** Append to the `AO_PM_SYSTEM_PROMPT = """…"""` literal (before the closing triple-quote) the following block. Use a `SENTINEL` comment line to make future insertions idempotent-safe:

```
## ON DATES AND TIMESTAMPS — TACTICAL (MANDATORY)
AO remembers precise dates but feigns amnesia in negotiations. Your dated
recall is operational ammunition, not style.

- Cite every past AO statement with exact date inline: [YYYY-MM-DD]: "quote" (source).
- Never write "AO said X previously" — always dated.
- If date uncertain: "approximately [month YYYY]" — never omit timeline.
- This rule applies to emails, WhatsApp, meetings, calls, all sources.
```

**Step 2.2 — Idempotency guard in the insert script.** Wrap the UPDATE so re-runs don't duplicate the addendum. Simplest: rely on the full-string REPLACE behavior already in the script (line 228-247 sets the entire `system_prompt` column to `AO_PM_SYSTEM_PROMPT` — a single literal constant). Re-runs are safe as long as the literal contains exactly one copy of the addendum. Confirm by grepping the literal after edit:

```bash
grep -c "ON DATES AND TIMESTAMPS" scripts/insert_ao_pm_capability.py
# expect: 1
```

**Step 2.3 — Run the insert script against prod DB.**

```bash
cd /Users/dimitry/Desktop/baker-code
python3 -c "import py_compile; py_compile.compile('scripts/insert_ao_pm_capability.py', doraise=True)"
python3 scripts/insert_ao_pm_capability.py
# expected console: "ao_pm already exists — updating system_prompt and tools"
```

### Verification

```sql
SELECT POSITION('ON DATES AND TIMESTAMPS' IN system_prompt) > 0 AS addendum_present,
       LENGTH(system_prompt) AS prompt_len
FROM capability_sets WHERE slug = 'ao_pm' LIMIT 1;
-- expect: true, prompt_len increased by ~450 chars vs pre-run
```

### Key Constraints
- Do NOT add other system-prompt edits in this session. One change, one verification.
- Do NOT invent a separate update script — reuse `insert_ao_pm_capability.py` per the existing idempotency pattern (lines 225-247).

---

## Step 3 — `wiki_pages` content refresh (UPDATE 8 rows)

### Problem
`wiki_context_enabled=True` means `_load_wiki_context` at `orchestrator/capability_runner.py:1323` is the path AO PM actually reads. If `wiki_pages.content` for the 8 `ao_pm` rows is stale vs. `data/ao_pm/*.md`, Director's smoke test will see old content regardless of any filesystem work.

### Current State
- 8 rows WHERE `agent_owner='ao_pm' AND page_type='agent_knowledge'` (verified in Step 0).
- 8 files in `data/ao_pm/`: `SCHEMA.md`, `psychology.md`, `investment_channels.md`, `financing_to_completion.md`, `ftc-table-explanations.md`, `agenda.md`, `sensitive_issues.md`, `communication_rules.md`.
- Slug convention in `wiki_pages` — inspected in Step 0. Common shapes: file stem (`psychology`), path-like (`ao_pm/psychology`), or hyphenated variant. Match by stem; handle underscore↔hyphen tolerantly.

### Implementation

**Step 3.1 — Create `scripts/refresh_ao_pm_wiki_pages.py`** (new file):

```python
"""Refresh wiki_pages rows for ao_pm from data/ao_pm/*.md.

Matches existing rows by slug (stem, underscore, or hyphen variant).
UPDATE only — does not INSERT or DELETE. Fail loud if an expected
filename has no matching row.

Usage: python3 scripts/refresh_ao_pm_wiki_pages.py
"""
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SOURCE_DIR = Path(__file__).resolve().parent.parent / "data" / "ao_pm"
PM_SLUG = "ao_pm"

# Expected filename → allowed slug variants (match in order).
# Populated after Step 0 inspection; adjust if Step 0 reveals different slugs.
FILE_TO_SLUGS = {
    "SCHEMA.md":                 ["SCHEMA", "schema", "ao_pm/schema"],
    "psychology.md":             ["psychology", "ao_pm/psychology"],
    "investment_channels.md":    ["investment_channels", "investment-channels",
                                  "ao_pm/investment_channels"],
    "financing_to_completion.md":["financing_to_completion", "financing-to-completion",
                                  "ao_pm/financing_to_completion"],
    "ftc-table-explanations.md": ["ftc-table-explanations", "ftc_table_explanations",
                                  "ao_pm/ftc-table-explanations"],
    "agenda.md":                 ["agenda", "ao_pm/agenda"],
    "sensitive_issues.md":       ["sensitive_issues", "sensitive-issues",
                                  "ao_pm/sensitive_issues"],
    "communication_rules.md":    ["communication_rules", "communication-rules",
                                  "ao_pm/communication_rules"],
}


def main():
    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    if not conn:
        raise RuntimeError("DB connection unavailable")
    try:
        cur = conn.cursor()

        # Snapshot existing slugs
        cur.execute(
            """
            SELECT slug FROM wiki_pages
            WHERE agent_owner = %s AND page_type = 'agent_knowledge'
            ORDER BY slug
            LIMIT 50
            """,
            (PM_SLUG,),
        )
        existing_slugs = {row[0] for row in cur.fetchall()}
        logger.info("Existing ao_pm wiki_pages slugs: %s", sorted(existing_slugs))

        updates = 0
        skipped = []
        for fname, slug_variants in FILE_TO_SLUGS.items():
            fpath = SOURCE_DIR / fname
            if not fpath.is_file():
                skipped.append(f"{fname} (source missing)")
                continue
            content = fpath.read_text(encoding="utf-8")
            target_slug = next((s for s in slug_variants if s in existing_slugs), None)
            if not target_slug:
                skipped.append(f"{fname} (no matching slug in wiki_pages: tried {slug_variants})")
                continue
            cur.execute(
                """
                UPDATE wiki_pages
                SET content = %s, updated_at = NOW()
                WHERE agent_owner = %s
                  AND page_type = 'agent_knowledge'
                  AND slug = %s
                """,
                (content, PM_SLUG, target_slug),
            )
            if cur.rowcount == 1:
                updates += 1
                logger.info("Updated %s → slug='%s' (%d chars)", fname, target_slug, len(content))
            else:
                skipped.append(f"{fname} (rowcount={cur.rowcount} for slug '{target_slug}')")

        conn.commit()
        logger.info("Refresh complete: %d UPDATEs, %d skipped", updates, len(skipped))
        if skipped:
            logger.warning("Skipped: %s", skipped)
            # Non-zero exit if any expected file didn't land
            sys.exit(2)
    except Exception as e:
        conn.rollback()
        logger.error("Refresh failed: %s", e)
        raise
    finally:
        cur.close()
        store._put_conn(conn)


if __name__ == "__main__":
    main()
```

**Step 3.2 — Adjust slug variants if Step 0 inspection showed different shapes.** If Step 0 returned slugs that aren't in the `FILE_TO_SLUGS` table, add them to the variant list and re-run.

**Step 3.3 — Run:**

```bash
python3 -c "import py_compile; py_compile.compile('scripts/refresh_ao_pm_wiki_pages.py', doraise=True)"
python3 scripts/refresh_ao_pm_wiki_pages.py
# expected: "Refresh complete: 8 UPDATEs, 0 skipped"
```

If the exit is non-zero (skipped > 0), investigate and fix before smoke test. Do NOT ship partial refresh and hope.

### Key Constraints
- UPDATE only. No INSERT/DELETE. If the row count isn't 8, something else is wrong — surface it.
- `LIMIT 50` on the discovery SELECT (bounded).
- `conn.rollback()` in except block.
- Exit code 2 when any expected file didn't match — CI-legible failure.

### Verification

```sql
SELECT slug, LENGTH(content) AS chars, updated_at
FROM wiki_pages
WHERE agent_owner = 'ao_pm' AND page_type = 'agent_knowledge'
ORDER BY slug
LIMIT 20;
-- expect: updated_at within last 5 min for all 8 rows; content sizes ≈ filesystem sizes
```

Compare sizes quickly:

```bash
for f in /Users/dimitry/Desktop/baker-code/data/ao_pm/*.md; do
  echo "$(wc -c < "$f") $(basename "$f")"
done
```

---

## Step 4 — Smoke test (Director-run, 10 min)

Director invokes AO PM via Scan / Cockpit with a concrete question that exercises dated recall. Example prompts (Director picks one or more):

- "Summarize what AO said about the 48/45 equity question, with dates."
- "What's the current state of the capital call? Give me dates of last 3 relevant exchanges."
- "Remind me what AO's position on Hagenauer acquisition has been, with source dates."

### Pass criteria

- Every AO quote / position reference has an inline `[YYYY-MM-DD]` or `approximately [month YYYY]`.
- No bare "AO said X previously" without timeline.
- Knowledge content matches what's currently in `data/ao_pm/*.md` (spot-check 1-2 facts Director knows should have updated recently).

### Fail → fallback

If smoke test fails on dated citations → re-check Step 2 verification SQL (addendum present, prompt length increased). Most likely cause: running service still has old prompt cached at invocation level — wait 1 invocation cycle and re-try.

If smoke test fails on stale content → re-run Step 3 with the Step 0 slug snapshot inspected manually.

Director reports pass/fail in chat. AI Head relays to B2 for ship report.

---

## Files Modified

- `scripts/insert_ao_pm_capability.py` — append date-tactical block to `AO_PM_SYSTEM_PROMPT` literal (one edit, ~8 lines added)
- `scripts/refresh_ao_pm_wiki_pages.py` — NEW (~90 lines)

## Do NOT Touch (Phase 1)

- `orchestrator/capability_runner.py` — NO changes tonight. `_resolve_view_dir` / sub-matter loader / PM_REGISTRY path-flip are all Phase 2.
- `PM_REGISTRY["ao_pm"]["view_dir"]` — stays `"data/ao_pm"` tonight.
- `baker-vault/wiki/matters/oskolkov/` — NO writes tonight. Vault migration is Phase 2.
- `data/ao_pm/*.md` — no content edits tonight. Refresh reads current content as-is.
- `wiki_pages` rows other than `agent_owner='ao_pm'`.
- Any `capability_sets` row other than slug `ao_pm`.
- `ao_pm_lessons.md`, Gold shells, interactions stub — Phase 2.
- Scheduler (`triggers/embedded_scheduler.py`) — Phase 2.

## Quality Checkpoints

1. Step 0 pre-flight SQL returns `wiki_context_enabled='true'` AND exactly 8 rows for `ao_pm`.
2. Routing diagnostic report written to `briefs/_reports/B2_AO_ROUTING_DIAGNOSTIC_20260422.md` before Step 2.
3. `python3 -c "import py_compile; py_compile.compile('scripts/insert_ao_pm_capability.py', doraise=True)"` passes.
4. `python3 -c "import py_compile; py_compile.compile('scripts/refresh_ao_pm_wiki_pages.py', doraise=True)"` passes.
5. `grep -c "ON DATES AND TIMESTAMPS" scripts/insert_ao_pm_capability.py` returns `1`.
6. Post-run SQL: `capability_sets.system_prompt` for `ao_pm` contains `'ON DATES AND TIMESTAMPS'`.
7. Post-run SQL: 8 `wiki_pages` rows for `ao_pm` with `updated_at` within the last 10 min.
8. Director smoke test passes on dated citations + fresh content.

## Rollback

- **System prompt addendum:** `UPDATE capability_sets SET system_prompt = substring(system_prompt FROM 1 FOR POSITION('## ON DATES AND TIMESTAMPS' IN system_prompt) - 1) WHERE slug = 'ao_pm'`. Alternatively, revert the insert script edit and re-run.
- **wiki_pages content:** no rollback needed — the script UPDATEs with whatever's currently in `data/ao_pm/*.md`. Reverting is the same operation if the source files change.

Both rollbacks are ≤ 30 seconds, zero deploy.

## Ship Report

Target: `briefs/_reports/B2_AO_PM_EXTENSION_1_20260422.md`

Must contain:
1. Step 0 pre-flight results (flag value, 8 slug list).
2. Step 1 routing diagnostic results (inbound vs fires delta; decomposer sample).
3. Step 2 verification SQL output.
4. Step 3 verification SQL output + size comparison.
5. Step 4 smoke test outcome (from Director chat).
6. **Phase 2 deferral list** — echo `BRIEF_AO_PM_EXTENSION_1_PHASE2.md` headline items so the ship report is a complete snapshot.
7. Any anomalies that should inform Phase 2 (e.g. if routing is broken and needs a fix before Phase 2 lands).

## Phase 2 pointer

Residual work staged in `briefs/BRIEF_AO_PM_EXTENSION_1_PHASE2.md`:
- Vault migration (8 files + 7 scaffolds + 3 Gold + `ao_pm_lessons.md` + `interactions/`)
- Runtime wiring (`_resolve_view_dir` + PM_REGISTRY path flip + sub-matter on-demand loader)
- vault→`wiki_pages` auto-ingest pipeline (replaces manual `refresh_ao_pm_wiki_pages.py`)
- Weekly lint job + scheduler wiring
- System prompt date-tactical already shipped in Phase 1 — do not re-apply.

Phase 2 is independent of Phase 1 runtime behavior. Ship when ready.

## Reference trail

- Research Agent escalation: 2026-04-22 evening (relayed by Director)
- Ratified architecture: `/Users/dimitry/baker-vault/_ops/ideas/2026-04-22-ao-pm-revision-v3.md`
- Charter: `/Users/dimitry/baker-vault/_ops/processes/ai-head-autonomy-charter.md`
