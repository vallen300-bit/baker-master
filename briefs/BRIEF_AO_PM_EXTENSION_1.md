# BRIEF: AO_PM_EXTENSION_1 — Vault-canonical AO PM + learning loop + date-tactical addendum

## Context

Promotes ratified `_ops/ideas/2026-04-22-ao-pm-revision-v3.md` to implementation.

Current state: AO PM capability is live (8 view files in `data/ao_pm/`, PM_REGISTRY config, signal detector, state table). Gap audit (v3 Part A) identified four weaknesses: (A1) no learning loop beyond rejection corrections, (A2) no episodic memory, (A3) no substrate push for signal fires, (A4) view files live in Dropbox-shadowed `data/` instead of the vault (violates Dropbox-exit ratification 2026-04-19 and 3-layer SoT ratification 2026-04-22).

Director-ratified architectural decisions merged into this brief:
- **Option A (2026-04-22):** canonical L2 = `baker-vault/wiki/matters/oskolkov/`.
- **3-layer SoT split** (Postgres live / Obsidian distilled / Postgres raw-message) per `memory/project_ao_pm_three_layer_sot.md`.
- **AO date-tactical countermeasure** (v3 §C) — system prompt addendum.
- **Matter authorship principle** per `memory/project_matter_authorship_principle.md`.

**No tonight deadline.** Queue normally behind PR #40 (STEP6_VALIDATION_HOTFIX_1). Dispatch to B2 once free; no preempt.

### Research Agent finding (2026-04-22 evening)

`wiki_context_enabled=True` in prod and 8 `wiki_pages` rows already exist for `agent_owner='ao_pm'`. Runtime reads Postgres via `_load_wiki_context` at `orchestrator/capability_runner.py:844-859`, **not** the filesystem. Director confirmed: **Deliverable 2 (capability_runner `view_dir` flip) ships as hygiene regardless** — it keeps the filesystem fallback correct and keeps PM_REGISTRY honest. The vault → `wiki_pages` ingest script (part of Deliverable 2) is **mandatory** — without it, stale Postgres content wins over fresh vault reads and the whole migration is silent no-op.

## Estimated time: ~6h
## Complexity: Medium
## Prerequisites
- `BAKER_VAULT_PATH` env var set on Render (already set: `/opt/render/project/src/baker-vault-mirror` per handover 2026-04-21 evening). Local dev: `~/baker-vault`.
- Vault checkout on Render deploy target — confirmed via KBL-A deploy.
- `BRIEF_CAPABILITY_THREADS_1` is a soft prereq for full episodic memory. Brief stubs `interactions/` with a README; episodic population deferred until threads brief lands.
- `BRIEF_KBL_SEED_1` coordination: seed must include `oskolkov` in matter stub list. If seed hasn't run, this brief creates the folder skeleton directly (seed reconciles against populated folder — cleaner per v3 §Part G Q5).

## Scope — 5 deliverables

| # | Deliverable | Files touched |
|---|---|---|
| 1 | Vault migration: 8 `cp`/rename + 7 new files + 3 Gold shells + `ao_pm_lessons.md` + `interactions/` stub | `baker-vault/wiki/matters/oskolkov/**` |
| 2 | Runtime wiring: `_resolve_view_dir` helper, PM_REGISTRY path flip, sub-matter on-demand loader, vault→`wiki_pages` ingest script (mandatory one-shot after deploy) | `orchestrator/capability_runner.py`, `scripts/ingest_vault_matter.py` (new) |
| 3 | System prompt Part C date-tactical addendum | `scripts/insert_ao_pm_capability.py` (edit `AO_PM_SYSTEM_PROMPT` literal + rerun) |
| 4 | Learning loop scaffold: `ao_pm_lessons.md` with Worked / Didn't-work sections | `baker-vault/wiki/matters/oskolkov/ao_pm_lessons.md` (new, folded into D1 commit) |
| 5 | Weekly vault lint + scheduler wiring | `scripts/lint_ao_pm_vault.py` (new), `triggers/embedded_scheduler.py` (new job) |

Substrate Slack push (v3 §A3) and Anthropic Memory-tool pilot (§B2) stay out-of-scope — defer to a successor brief after substrate architecture lands.

---

## BLOCKING GATE — Pre-deploy staleness diagnostic (30 min)

**Runs before Deliverable 2 deploys.** Blocks the `view_dir` flip / ingest run until routing state is known. Deliverables 1, 3, 4 do not depend on this gate and can ship first.

### Queries (every SELECT bounded with LIMIT)

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

-- (C) ao_pm capability runs — last 21 days
SELECT COUNT(*) AS ao_pm_runs_21d
FROM capability_runs
WHERE capability_slug = 'ao_pm' AND created_at > NOW() - INTERVAL '21 days'
LIMIT 1;

-- (D) Decomposer spot-check (confirm ao_pm appears in chosen_slugs
--     for AO-laden inputs). If table name differs, grep orchestrator/ first.
SELECT created_at, input_text, chosen_slugs
FROM decomposer_decisions
WHERE input_text ILIKE '%oskolkov%' OR input_text ILIKE '%aelio%' OR input_text ILIKE '%andrey%'
ORDER BY created_at DESC
LIMIT 20;
```

Write the report to `briefs/_reports/B2_AO_ROUTING_DIAGNOSTIC_<YYYYMMDD>.md` with:
- All 4 query results.
- One of three diagnosis verdicts (below).
- One-sentence go/no-go recommendation on Deliverable 2.

### Decision tree

- **(A) or (B) > 0 AND (C) > 0, roughly aligned** → routing works (v3 case d). Proceed with Deliverable 2.
- **(A)+(B) > 0, (C) = 0** → routing broken (v3 case c). Ship Deliverables 1, 3, 4 only. Hold Deliverables 2 + 5 until a routing fix brief lands separately. File a one-line flag to AI Head with the delta.
- **(A)+(B) = 0** → quiet matter (v3 case a). Note and proceed with full deploy; Deliverable 2 unblocks future signals regardless.

---

## Deliverable 1 — Vault migration

### Problem
Eight AO PM view files live in `data/ao_pm/` under the repo root. Dropbox-shadowed legacy (Dropbox exit ratified 2026-04-19). 3-layer SoT names Obsidian `.md` as L2 primary (ratified 2026-04-22). Director edit authority requires Obsidian-native paths — `data/ao_pm/` is read-only from Obsidian's perspective.

### Current state
- `data/ao_pm/` contains 8 files: `SCHEMA.md`, `psychology.md`, `investment_channels.md`, `financing_to_completion.md`, `ftc-table-explanations.md`, `agenda.md`, `sensitive_issues.md`, `communication_rules.md`.
- `baker-vault/wiki/matters/oskolkov/` contains: `_index.md`, `cards/` (empty), `decisions/` (empty). Seed_migration (2026-04-14) pre-dated target layout in `_index.md`.
- `baker-vault` is a separate git repo at `/Users/dimitry/baker-vault/` (MacBook) mirrored at `/opt/render/project/src/baker-vault-mirror` (Render).

### Implementation

**Step 1.1 — Migrate 8 files** (run from `~/baker-vault/`, rename underscore → hyphen to match `_index.md` wikilinks):

```bash
cd ~/baker-vault
mkdir -p wiki/matters/oskolkov/sub-matters
mkdir -p wiki/matters/oskolkov/interactions

cp /Users/dimitry/Desktop/baker-code/data/ao_pm/SCHEMA.md                  wiki/matters/oskolkov/_schema-legacy.md
cp /Users/dimitry/Desktop/baker-code/data/ao_pm/psychology.md              wiki/matters/oskolkov/psychology.md
cp /Users/dimitry/Desktop/baker-code/data/ao_pm/investment_channels.md     wiki/matters/oskolkov/investment-channels.md
cp /Users/dimitry/Desktop/baker-code/data/ao_pm/financing_to_completion.md wiki/matters/oskolkov/financing-to-completion.md
cp /Users/dimitry/Desktop/baker-code/data/ao_pm/ftc-table-explanations.md  wiki/matters/oskolkov/ftc-table-explanations.md
cp /Users/dimitry/Desktop/baker-code/data/ao_pm/agenda.md                  wiki/matters/oskolkov/agenda.md
cp /Users/dimitry/Desktop/baker-code/data/ao_pm/sensitive_issues.md        wiki/matters/oskolkov/sensitive-issues.md
cp /Users/dimitry/Desktop/baker-code/data/ao_pm/communication_rules.md     wiki/matters/oskolkov/communication-rules.md
```

`SCHEMA.md` is absorbed into `_index.md` (Step 1.3) and kept as `_schema-legacy.md` during transition for reference; removed after verification.

**Step 1.2 — Frontmatter on each migrated file.** Template:

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

`live_state_refs` empty on first pass; populate during content audit. `owner` is `Director` except `financing-to-completion.md` and `ftc-table-explanations.md` → `Edita + Baker`.

**Step 1.3 — Update `_index.md`** — merge SCHEMA.md content into an "Architecture" section; refresh the "View Files" table to reflect the new filenames + new files.

**Step 1.4 — 7 new scaffold files**, each with frontmatter + top-of-file TODO:

- `_overview.md` — core entities (AO, Aelio, RG7, LCG) + counterparty orbit (Buchwalder, Pohanis, Ofenheimer)
- `red-flags.md` — active red flags (to be migrated from `pm_project_state.state_json.red_flags` on first audit)
- `financial-facts.md` — stable structural facts (TOTAL, two-channel architecture, % ranges)
- `sub-matters/rg7-equity.md`
- `sub-matters/capital-calls.md`
- `sub-matters/restructuring.md`
- `sub-matters/personal-loan.md`
- `sub-matters/fx-mayr.md`
- `sub-matters/tuscany.md`

Scaffold template:

```markdown
---
title: "<Human title>"
matter: oskolkov
type: distilled-knowledge
layer: 2
live_state_refs: []
owner: Director
last_audit: 2026-04-22
status: scaffold
---

# <Human title>

<!-- TODO: populate in content session. Scaffold per BRIEF_AO_PM_EXTENSION_1. -->

## Sources
- `pm_project_state.state_json.sub_matters.<slug>` (live counters)
- `email_messages` / `whatsapp_messages` WHERE matter='oskolkov-rg7'
```

**Step 1.5 — 3 Gold shells** + Deliverable 4 lessons scaffold:

- `gold.md` — frontmatter `status: empty`, `type: gold`
- `proposed-gold.md` — frontmatter `status: empty`, `type: proposed-gold`
- `ao_pm_lessons.md` — see Deliverable 4 below (folded into this commit)

**Step 1.6 — `interactions/` stub** — create `interactions/README.md`:

```markdown
# Interactions (Episodic Memory Stub)

**Status:** stub pending BRIEF_CAPABILITY_THREADS_1.

Format when threads ship: `YYYY-MM-DD-<source>.md` — one file per significant AO touchpoint.

Until threads: manual entries allowed. Do not auto-populate — wait for threads infra.
```

**Step 1.7 — Commit vault repo:**

```bash
cd ~/baker-vault
git add wiki/matters/oskolkov/
git commit -m "AO_PM_EXTENSION_1: migrate 8 files + 7 scaffolds + Gold shells + lessons + interactions stub"
```

Mirror to Render-side `baker-vault-mirror` via the existing sync mechanism. Verify with `ls /opt/render/project/src/baker-vault-mirror/wiki/matters/oskolkov` after next deploy.

**Step 1.8 — Do NOT delete `data/ao_pm/` yet.** Safety fallback until Deliverable 2 verified in production. Deletion belongs to post-D2 cleanup step.

### Verification

```bash
ls -la /Users/dimitry/baker-vault/wiki/matters/oskolkov/
ls -la /Users/dimitry/baker-vault/wiki/matters/oskolkov/sub-matters/
ls -la /Users/dimitry/baker-vault/wiki/matters/oskolkov/interactions/
grep -L "^---$" /Users/dimitry/baker-vault/wiki/matters/oskolkov/*.md
# Output: empty (all files have frontmatter)
```

---

## Deliverable 2 — Runtime wiring (`_resolve_view_dir` + ingest)

### Problem
`_load_pm_view_files()` at `orchestrator/capability_runner.py:1289` resolves `view_dir` relative to the baker-code repo root. Works for `data/ao_pm/` but breaks when we point at `wiki/matters/oskolkov` (that path lives in the vault repo, not baker-code).

Research Agent finding: `wiki_context_enabled=True` in prod means `_load_wiki_context` at line 1323 wins over `_load_pm_view_files`. The filesystem read is a fallback path today. Still: **view_dir flip is hygiene** (keeps PM_REGISTRY honest, keeps the fallback correct), and the **vault → `wiki_pages` ingest is mandatory** — without it, stale Postgres content wins and the migration is silent no-op.

### Current state
- `PM_REGISTRY["ao_pm"]["view_dir"] = "data/ao_pm"` at `orchestrator/capability_runner.py:48`.
- `_load_pm_view_files` (line 1289) resolves path as `os.path.dirname(os.path.dirname(__file__))` + `view_dir` → `baker-code/data/ao_pm/`.
- `_load_wiki_context` (line 1323) reads `wiki_pages` table — priority over filesystem when `wiki_context_enabled=True` (see line 844-859). Currently 8 rows exist for `agent_owner='ao_pm'`.
- `BAKER_VAULT_PATH` env: `/opt/render/project/src/baker-vault-mirror` (Render), `/Users/dimitry/baker-vault` (local).

### Implementation

**Step 2.1 — Add `_resolve_view_dir` helper** in `capability_runner.py` near the top of the `CapabilityRunner` class helpers (before `_load_pm_view_files`, ~line 1286):

```python
def _resolve_view_dir(self, view_dir_config: str) -> str:
    """Resolve PM view_dir config to an absolute filesystem path.

    If view_dir starts with 'wiki/', resolve against BAKER_VAULT_PATH env var.
    Otherwise resolve against baker-code repo root (legacy behavior).
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

**Step 2.2 — Replace line 1296 in `_load_pm_view_files`:**

```python
# BEFORE
view_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), config["view_dir"])
# AFTER
view_dir = self._resolve_view_dir(config["view_dir"])
```

**Step 2.3 — Update `PM_REGISTRY["ao_pm"]`** (line 45) + bump `PM_REGISTRY_VERSION` (line 42) from `1` to `2`:

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
            "ftc-table-explanations.md",    # NEW in order (was in folder but not listed)
            "agenda.md",
            "sensitive-issues.md",          # was: sensitive_issues.md
            "communication-rules.md",       # was: communication_rules.md
            "red-flags.md",
            "financial-facts.md",
        ],
        # … rest unchanged (state_label, contact_keywords, signal patterns, etc.)
        "extraction_view_files": [
            "psychology.md", "investment-channels.md",
            "financing-to-completion.md",
            "sensitive-issues.md", "communication-rules.md", "agenda.md",
        ],
    },
    # … "movie_am" unchanged
}
```

**Step 2.4 — Sub-matter on-demand loader** (v3 §X4). Append to `_load_pm_view_files` after the main loop:

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

Bounds context growth — parked sub-matters stay readable in Obsidian but don't bloat the prompt.

**Step 2.5 — `scripts/ingest_vault_matter.py`** (new, ~100 lines) — matter-generic, wipes existing `wiki_pages` rows for the PM slug and re-inserts from vault:

```python
"""Ingest a vault matter folder into wiki_pages.

Wipes existing rows for agent_owner=<pm_slug> and re-inserts from vault.
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

**Step 2.6 — One-shot ingest run** after deploy:

```bash
# Render: in a shell on the running service
python3 scripts/ingest_vault_matter.py oskolkov
# expected: Inserted ≥ 11 rows (top-level) + 6 (sub-matters)
```

### Key constraints
- **Ingest is mandatory, not optional.** Without it, `_load_wiki_context` keeps serving the stale 8 rows and the migration does nothing.
- If `BAKER_VAULT_PATH` is unset on Render, `_resolve_view_dir` falls back to legacy resolution (which will 404 because `data/ao_pm/` still exists as pre-cleanup safety net — but filesystem fallback is rarely hit when wiki_context is on). Verify env var before deploy.
- `_load_wiki_context` priority logic at line 844-859 is **not changed** — dual-run stays.
- `wiki_pages` DELETE is matter-scoped (`agent_owner = %s`) — bounded, not a full-table wipe. `conn.rollback()` in except.
- Sub-matter loader filename normalization: `_` → `-` to match vault convention.

### Verification
```bash
python3 -c "import py_compile; py_compile.compile('orchestrator/capability_runner.py', doraise=True)"
python3 -c "import py_compile; py_compile.compile('scripts/ingest_vault_matter.py', doraise=True)"

export BAKER_VAULT_PATH=/Users/dimitry/baker-vault
python3 -c "
from orchestrator.capability_runner import CapabilityRunner, PM_REGISTRY
r = CapabilityRunner.__new__(CapabilityRunner)
import os
path = r._resolve_view_dir(PM_REGISTRY['ao_pm']['view_dir'])
print('resolved=', path, 'exists=', os.path.isdir(path))
"
```
```sql
-- After ingest runs
SELECT slug, LENGTH(content) AS chars, updated_at
FROM wiki_pages WHERE agent_owner = 'ao_pm' AND page_type = 'agent_knowledge'
ORDER BY slug LIMIT 25;
-- expect: 11 top-level + 6 sub-matters = 17 rows, all updated_at within the last 5 min
```

---

## Deliverable 3 — System prompt Part C date-tactical addendum

### Problem
AO remembers precise dates but feigns date amnesia in negotiations (v3 §C1, Director-ratified 2026-04-22). AO PM output references AO statements without forcing dated citation — loses operational ammunition.

### Current state
- `capability_sets.system_prompt` for slug `ao_pm` set by `scripts/insert_ao_pm_capability.py:17` (`AO_PM_SYSTEM_PROMPT` literal).
- Script is idempotent — UPDATEs existing row when re-run (line 227-247).
- Current prompt lacks an "ON DATES AND TIMESTAMPS" section.

### Implementation

**Step 3.1 — Edit `scripts/insert_ao_pm_capability.py`.** Append this block to the `AO_PM_SYSTEM_PROMPT = """…"""` literal (before the closing triple-quote):

```
## ON DATES AND TIMESTAMPS — TACTICAL (MANDATORY)
AO remembers precise dates but feigns amnesia in negotiations. Your dated
recall is operational ammunition, not style.

- Cite every past AO statement with exact date inline: [YYYY-MM-DD]: "quote" (source).
- Never write "AO said X previously" — always dated.
- If date uncertain: "approximately [month YYYY]" — never omit timeline.
- This rule applies to emails, WhatsApp, meetings, calls, all sources.
```

**Step 3.2 — Idempotency check** — grep post-edit:

```bash
grep -c "ON DATES AND TIMESTAMPS" scripts/insert_ao_pm_capability.py
# expect: 1
```

The insert script sets `system_prompt` column to the entire literal each run (line 228-247), so re-runs won't duplicate as long as the literal contains exactly one copy.

**Step 3.3 — Run the insert script** against prod DB:

```bash
python3 -c "import py_compile; py_compile.compile('scripts/insert_ao_pm_capability.py', doraise=True)"
python3 scripts/insert_ao_pm_capability.py
# expected console: "ao_pm already exists — updating system_prompt and tools"
```

### Key constraints
- No separate update script — reuse `insert_ao_pm_capability.py` per the existing idempotency pattern.
- Append only. Do not restructure the existing prompt.

### Verification

```sql
SELECT POSITION('ON DATES AND TIMESTAMPS' IN system_prompt) > 0 AS addendum_present,
       LENGTH(system_prompt) AS prompt_len
FROM capability_sets WHERE slug = 'ao_pm' LIMIT 1;
-- expect: true, prompt_len increased by ~450 chars
```

Director-run smoke test (informal): AO scan with dated-recall question should surface `[YYYY-MM-DD]: "quote"` style citations.

---

## Deliverable 4 — Learning loop scaffold (`ao_pm_lessons.md`)

### Problem
v3 §A1: no process-learning loop for AO PM. `baker_corrections` (actual table name — v3 doc incorrectly says `capability_corrections`; verified `memory/store_back.py:508`) captures rejection-derived rules with 5-per-capability cap + 90-day expiry. Nothing captures positively-observed patterns; nothing consolidates Silver → Gold.

### Current state
- `baker_corrections` table exists, populated via `store.store_correction(...)` (`memory/store_back.py:537`), retrieved via `get_relevant_corrections(capability_slug, limit=3)` (line 584).
- No `ao_pm_lessons.md` exists.
- No promotion pipeline from Silver → `ao_pm_lessons.md` → `gold.md` wired. This brief lands the structure; promotion logic itself is enforced by Deliverable 5's lint.

### Implementation

**Fold into Deliverable 1's vault commit.** Create `baker-vault/wiki/matters/oskolkov/ao_pm_lessons.md`:

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

Consolidated process learnings for AO PM. Sits between Silver (`baker_corrections` rows) and Gold (`gold.md`).

**Promotion rule:** a `baker_corrections` row that fires 3+ times (via `retrieval_count`) is a candidate for promotion here. AI Head reviews weekly via lint output (`_lint-report.md`).

**Demotion rule:** a lesson not referenced in 60+ days is a candidate for retirement. Lint flags.

---

## Worked — why

(Empty — populate as patterns emerge.)

Format: `- [YYYY-MM-DD] Pattern X worked because Y. Source: <baker_task_id / decision link>`

---

## Didn't work — why

(Empty — populate as patterns emerge.)

Format: `- [YYYY-MM-DD] Pattern X failed because Y. Root cause: Z. Source: <baker_task_id / decision link>`

---

## Counterparty tactical

- [2026-04-22] Cite every past AO statement with exact date inline: `[YYYY-MM-DD]: "quote" (source)`. Reason: AO remembers precise dates but feigns amnesia in negotiations (v3 §C1, Director-ratified). Source: `_ops/ideas/2026-04-22-ao-pm-revision-v3.md` §C.

---

## Pending promotion to gold.md

(Empty — populated by AI Head review.)
```

### Key constraints
- Scaffold only. Population is a separate ongoing task.
- "Counterparty tactical" seed duplicates Deliverable 3's system-prompt injection intentionally — one is model-instruction, one is human-reference. Both are load-bearing.

### Verification
```bash
test -f /Users/dimitry/baker-vault/wiki/matters/oskolkov/ao_pm_lessons.md && head -5 $_
```

---

## Deliverable 5 — Weekly vault lint + scheduler wiring

### Problem
Layer 2 files drift against Layer 1 live counters over time (the reason the drift rule exists in the 3-layer SoT architecture). Wikilinks rot when files rename. `ao_pm_lessons.md` grows stale rules without pruning. Without lint, silent knowledge rot.

### Current state
- No matter-scoped lint exists.
- `triggers/embedded_scheduler.py:221` already registers a `wiki_lint` daily job using APScheduler `CronTrigger` (`_run_wiki_lint` helper at line 716). This brief piggybacks the same pattern for a separate weekly matter lint.

### Implementation

**Step 5.1 — `scripts/lint_ao_pm_vault.py`** (new, ~150 lines). Full script:

```python
"""Weekly lint for baker-vault/wiki/matters/oskolkov/.

Checks:
- Missing frontmatter fields (title/matter/type/layer).
- Broken wikilinks [[target]] pointing at missing files.
- Drift: live_state_refs listing pm_project_state keys that no longer exist.
- Stale baker_corrections rows for ao_pm not retrieved in 60+ days.
- Interactions files missing 4 required timestamps (source_at/ingest_at/recall_at/decision_at).

Output: wiki/matters/oskolkov/_lint-report.md (overwritten each run).
"""
import os
import re
import sys
import logging
from pathlib import Path
from datetime import datetime, timedelta, timezone

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MATTER_SLUG = "oskolkov"
REQUIRED_FRONTMATTER = {"title", "matter", "type", "layer"}


def main():
    vault_path = os.environ.get("BAKER_VAULT_PATH")
    if not vault_path:
        raise RuntimeError("BAKER_VAULT_PATH not set")
    matter_dir = Path(vault_path) / "wiki" / "matters" / MATTER_SLUG
    if not matter_dir.is_dir():
        raise RuntimeError(f"Matter dir not found: {matter_dir}")

    violations = []
    violations.extend(_check_frontmatter(matter_dir))
    violations.extend(_check_wikilinks(matter_dir))
    violations.extend(_check_drift(matter_dir))
    violations.extend(_check_stale_lessons(matter_dir))
    violations.extend(_check_interactions(matter_dir))

    report = _render_report(violations)
    report_path = matter_dir / "_lint-report.md"
    report_path.write_text(report, encoding="utf-8")
    logger.info("Wrote %s (%d violations)", report_path, len(violations))

    if violations:
        logger.warning("Lint violations: %d — see %s", len(violations), report_path)


def _check_frontmatter(matter_dir: Path) -> list:
    violations = []
    for md in matter_dir.rglob("*.md"):
        if md.name == "_lint-report.md":
            continue
        txt = md.read_text(encoding="utf-8")
        if not txt.startswith("---"):
            violations.append(f"Missing frontmatter: {md.relative_to(matter_dir)}")
            continue
        try:
            _, fm, _ = txt.split("---", 2)
        except ValueError:
            violations.append(f"Malformed frontmatter: {md.relative_to(matter_dir)}")
            continue
        fields = set()
        for line in fm.splitlines():
            if ":" in line and not line.startswith(" "):
                fields.add(line.split(":", 1)[0].strip())
        missing = REQUIRED_FRONTMATTER - fields
        if missing:
            violations.append(
                f"Missing frontmatter fields in {md.relative_to(matter_dir)}: {sorted(missing)}"
            )
    return violations


def _check_wikilinks(matter_dir: Path) -> list:
    violations = []
    existing = {p.stem for p in matter_dir.rglob("*.md")}
    sub_dir = matter_dir / "sub-matters"
    if sub_dir.is_dir():
        for p in sub_dir.glob("*.md"):
            existing.add(f"sub-matters/{p.stem}")
    for md in matter_dir.rglob("*.md"):
        txt = md.read_text(encoding="utf-8")
        for match in re.finditer(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", txt):
            target = match.group(1).strip()
            if target.startswith("#") or ("/" in target and not target.startswith("sub-matters/")):
                continue
            if target not in existing:
                violations.append(
                    f"Broken wikilink in {md.relative_to(matter_dir)}: [[{target}]]"
                )
    return violations


def _check_drift(matter_dir: Path) -> list:
    violations = []
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        state = store.get_pm_project_state("ao_pm") or {}
        state_keys = set((state.get("state_json") or {}).keys())
    except Exception as e:
        logger.warning("Drift check skipped: %s", e)
        return violations
    for md in matter_dir.rglob("*.md"):
        if md.name == "_lint-report.md":
            continue
        txt = md.read_text(encoding="utf-8")
        refs = re.search(r"live_state_refs:\s*\[([^\]]*)\]", txt)
        if not refs:
            continue
        items = [x.strip().strip('"').strip("'") for x in refs.group(1).split(",") if x.strip()]
        for ref in items:
            top = ref.split(".")[0]
            if top and top not in state_keys:
                violations.append(
                    f"Drift: {md.relative_to(matter_dir)} references {ref} — not in pm_project_state.state_json keys"
                )
    return violations


def _check_stale_lessons(matter_dir: Path) -> list:
    violations = []
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return violations
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT id, learned_rule FROM baker_corrections
                WHERE capability_slug = 'ao_pm' AND active = TRUE
                  AND (last_retrieved_at IS NULL OR last_retrieved_at < NOW() - INTERVAL '60 days')
                ORDER BY created_at ASC
                LIMIT 20
                """
            )
            for row_id, rule in cur.fetchall():
                violations.append(
                    f"Stale correction #{row_id} (ao_pm): {rule[:80]}… — retired-candidate"
                )
            cur.close()
        except Exception as e:
            conn.rollback()
            logger.warning("Stale-lessons check failed: %s", e)
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.warning("Stale-lessons outer error: %s", e)
    return violations


def _check_interactions(matter_dir: Path) -> list:
    violations = []
    interactions = matter_dir / "interactions"
    if not interactions.is_dir():
        return violations
    required_ts = {"source_at", "ingest_at", "recall_at", "decision_at"}
    for md in interactions.glob("*.md"):
        if md.name == "README.md":
            continue
        txt = md.read_text(encoding="utf-8")
        missing = [ts for ts in required_ts if ts not in txt]
        if missing:
            violations.append(
                f"Interaction missing timestamps {missing}: {md.relative_to(matter_dir)}"
            )
    return violations


def _render_report(violations: list) -> str:
    header = f"""---
title: AO PM Lint Report
matter: oskolkov
type: lint-report
generated_at: {datetime.now(timezone.utc).isoformat()}
violation_count: {len(violations)}
---

# AO PM Lint Report

Last run: `{datetime.now(timezone.utc).isoformat()}`
Violations: **{len(violations)}**

"""
    if not violations:
        return header + "All checks passed.\n"
    body = "\n".join(f"- {v}" for v in violations)
    return header + "## Violations\n\n" + body + "\n"


if __name__ == "__main__":
    main()
```

**Step 5.2 — Scheduler wiring** in `triggers/embedded_scheduler.py`. Piggyback the existing APScheduler pattern at line 221 (`wiki_lint`). Add alongside:

```python
# AO PM matter lint — weekly Sunday 06:00 UTC (BRIEF_AO_PM_EXTENSION_1 §5)
scheduler.add_job(
    _run_ao_pm_lint,
    CronTrigger(day_of_week="sun", hour=6, minute=0, timezone="UTC"),
    id="ao_pm_lint", name="ao_pm_lint",
    coalesce=True, max_instances=1, replace_existing=True,
)
logger.info("Registered: ao_pm_lint (Sunday 06:00 UTC)")
```

Helper near `_run_wiki_lint` (around line 716):

```python
def _run_ao_pm_lint():
    """BRIEF_AO_PM_EXTENSION_1: Run AO PM vault lint and log results."""
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

**Do NOT** wire lint into any startup hook — lint output is not load-bearing for the runtime loop. The daily `wiki_lint` at line 221 is a separate CORTEX-PHASE-3 job; leave it untouched.

Cadence: weekly Sunday 06:00 UTC (1h before daily briefing at 07:00 UTC).

### Key constraints
- Lint is log + file only. Substrate Slack push deferred (v3 §A3 out-of-scope).
- Every DB query has a `LIMIT` (see `_check_stale_lessons` → `LIMIT 20`).
- Every except block has `conn.rollback()`.
- Lint skips `_lint-report.md` to avoid feedback loops. Idempotent — overwrites each run.

### Verification
```bash
python3 -c "import py_compile; py_compile.compile('scripts/lint_ao_pm_vault.py', doraise=True)"
export BAKER_VAULT_PATH=/Users/dimitry/baker-vault
python3 scripts/lint_ao_pm_vault.py
head -20 /Users/dimitry/baker-vault/wiki/matters/oskolkov/_lint-report.md
```

Post-deploy scheduler verify:

```bash
# Render logs after next restart should show "Registered: ao_pm_lint (Sunday 06:00 UTC)"
```

---

## Files Modified

**baker-vault repo:**
- `wiki/matters/oskolkov/_index.md` — updated View Files table, absorbed SCHEMA.md
- `wiki/matters/oskolkov/{psychology,investment-channels,financing-to-completion,ftc-table-explanations,agenda,sensitive-issues,communication-rules}.md` — migrated + frontmatter
- `wiki/matters/oskolkov/_schema-legacy.md` — transitional (removed after verification)
- `wiki/matters/oskolkov/{_overview,red-flags,financial-facts}.md` — NEW scaffolds
- `wiki/matters/oskolkov/sub-matters/{rg7-equity,capital-calls,restructuring,personal-loan,fx-mayr,tuscany}.md` — 6 NEW scaffolds
- `wiki/matters/oskolkov/{gold,proposed-gold}.md` — NEW empty shells
- `wiki/matters/oskolkov/ao_pm_lessons.md` — NEW (Deliverable 4, folded into D1 commit)
- `wiki/matters/oskolkov/interactions/README.md` — NEW stub

**baker-code repo:**
- `orchestrator/capability_runner.py` — `_resolve_view_dir` (new), `_load_pm_view_files` call site, `PM_REGISTRY["ao_pm"]` config (view_dir + hyphenated file names + 3 new files), `PM_REGISTRY_VERSION` → 2, sub-matter on-demand loader
- `scripts/ingest_vault_matter.py` — NEW
- `scripts/insert_ao_pm_capability.py` — `AO_PM_SYSTEM_PROMPT` literal gets date-tactical addendum
- `scripts/lint_ao_pm_vault.py` — NEW
- `triggers/embedded_scheduler.py` — `ao_pm_lint` job + `_run_ao_pm_lint` helper
- `data/ao_pm/` — DELETED (post-D2 verification only)

## Do NOT Touch
- `orchestrator/pm_signal_detector.py` — signal detection already correct for AO PM
- `memory/store_back.py` `baker_corrections` / `pm_project_state` functions
- `PM_REGISTRY["movie_am"]` — MOVIE AM is a separate brief (v3 §X8)
- `capability_sets` rows for any slug other than `ao_pm`
- `_load_wiki_context` priority logic (line 844-859) — dual-run stays; ingest handles staleness
- `triggers/embedded_scheduler.py:221` `wiki_lint` job — separate CORTEX-PHASE-3 job
- Any `data/movie_am/` content
- `cortex_config.wiki_context_enabled` flag

## Quality Checkpoints
1. `python3 -c "import py_compile; py_compile.compile('orchestrator/capability_runner.py', doraise=True)"`
2. `python3 -c "import py_compile; py_compile.compile('scripts/ingest_vault_matter.py', doraise=True)"`
3. `python3 -c "import py_compile; py_compile.compile('scripts/insert_ao_pm_capability.py', doraise=True)"`
4. `python3 -c "import py_compile; py_compile.compile('scripts/lint_ao_pm_vault.py', doraise=True)"`
5. `grep -c "ON DATES AND TIMESTAMPS" scripts/insert_ao_pm_capability.py` → `1`
6. All top-level vault files + 6 sub-matter scaffolds + 3 Gold shells + lessons + `interactions/README.md` present
7. Every vault `.md` has valid frontmatter (fresh lint run: zero "Missing frontmatter" violations)
8. `_resolve_view_dir("wiki/matters/oskolkov")` on Render returns `/opt/render/project/src/baker-vault-mirror/wiki/matters/oskolkov`
9. `wiki_pages` row count for `agent_owner='ao_pm'` matches vault file count after ingest
10. `capability_sets.system_prompt` for `ao_pm` contains `'ON DATES AND TIMESTAMPS'`
11. Post-deploy AO PM invocation reads vault content (check logs for `## WIKI:` lines in prompt from `_load_wiki_context`; `## VIEW FILE:` lines in fallback)
12. Lint runs without crash and writes `_lint-report.md`
13. Scheduler registers `ao_pm_lint` (Sunday 06:00 UTC) in startup logs
14. Routing diagnostic report filed at `briefs/_reports/B2_AO_ROUTING_DIAGNOSTIC_<YYYYMMDD>.md` before Deliverable 2 deploys

## Verification SQL
```sql
-- wiki_pages refresh from vault
SELECT COUNT(*) AS rows, MAX(updated_at) AS last_update
FROM wiki_pages WHERE agent_owner = 'ao_pm' AND page_type = 'agent_knowledge' LIMIT 1;

-- System prompt addendum present
SELECT POSITION('ON DATES AND TIMESTAMPS' IN system_prompt) > 0 AS addendum_present,
       LENGTH(system_prompt) AS prompt_len
FROM capability_sets WHERE slug = 'ao_pm' LIMIT 1;

-- Post-deploy live state sanity
SELECT last_run_at, run_count,
       jsonb_array_length(COALESCE(state_json->'open_actions', '[]'::jsonb)) AS open_actions
FROM pm_project_state WHERE pm_slug = 'ao_pm' AND state_key = 'current' LIMIT 1;
```

## Deployment Order

1. Vault commit (Deliverables 1 + 4) — vault repo only, no baker-code deploy. Low blast radius.
2. Deliverable 3 (system prompt) — one-shot DB update. Safe anytime after D1. No code deploy needed.
3. **Blocking gate** — pre-deploy staleness diagnostic (30 min). Report filed before D2 proceeds.
4. Deliverable 2 (runtime wiring) — baker-code deploy. **Run `scripts/ingest_vault_matter.py oskolkov` once immediately after deploy** — mandatory (see Deliverable 2 constraints).
5. Deliverable 5 (lint + scheduler) — baker-code deploy. Non-load-bearing; lint runs next Sunday.
6. Delete `data/ao_pm/` only after Deliverable 2 Quality Checkpoint 11 passes on production.

## Rollback

Each deliverable is independently reversible:

1. **Vault content:** `git revert` the vault commit. Vault repo independent from baker-code.
2. **Runtime wiring:** revert `PM_REGISTRY["ao_pm"]["view_dir"]` to `"data/ao_pm"`, revert `view_file_order` to underscore names, revert `_resolve_view_dir` helper. `data/ao_pm/` still on disk (pre-cleanup) so legacy fallback resolves.
3. **System prompt:** `UPDATE capability_sets SET system_prompt = substring(system_prompt FROM 1 FOR POSITION('## ON DATES AND TIMESTAMPS' IN system_prompt) - 1) WHERE slug = 'ao_pm'`.
4. **Lessons file:** `git rm` in vault repo.
5. **Lint:** remove scheduler wiring; script is dormant when not invoked.
6. **`wiki_pages`:** re-running ingest against a reverted vault restores prior content — no manual rollback path needed.

## Ship Report

Target: `briefs/_reports/B2_AO_PM_EXTENSION_1_<YYYYMMDD>.md`

Must contain:
1. Pre-deploy staleness diagnostic result (decision-tree verdict).
2. Each deliverable: what shipped, verification SQL output, any anomalies.
3. Quality Checkpoint 1-14 pass/fail.
4. `data/ao_pm/` deletion timestamp (or a reason for deferring).
5. Any residual work recommended for a successor brief.

## Brief authoring notes

- **Table name correction** applied: v3 doc referenced `capability_corrections`, actual is `baker_corrections` (verified `memory/store_back.py:508`).
- **`data/ao_pm/` contains 8 files, not 7**: `ftc-table-explanations.md` exists on disk but was absent from PM_REGISTRY's `view_file_order`. Brief adds it to the order.
- **`wiki_pages` priority over filesystem** (v3 did not surface): `wiki_context_enabled=True` in prod + 8 `ao_pm` rows means the ingest step is mandatory. Without it, migration is silent no-op.
- **Scheduler wiring** uses APScheduler CronTrigger matching existing `wiki_lint` job in `triggers/embedded_scheduler.py:221` for consistency.
- **Substrate push + Memory-tool pilot** (v3 §A3 + §B2): deferred to a successor brief. Scope discipline per `/write-brief` Step 4.
- **No tonight deadline.** Queue normally behind PR #40 (STEP6_VALIDATION_HOTFIX_1). B2 dispatch once free; no preempt.

## Reference trail

- Ratified architecture: `/Users/dimitry/baker-vault/_ops/ideas/2026-04-22-ao-pm-revision-v3.md`
- Capability extension template: `/Users/dimitry/baker-vault/_ops/ideas/2026-04-22-capability-extension-template.md`
- 3-layer SoT: `memory/project_ao_pm_three_layer_sot.md`
- Authorship principle: `memory/project_matter_authorship_principle.md`
- AO date-tactical: `memory/people_ao_date_tactical.md`
- AI Head autonomy charter: `baker-vault/_ops/processes/ai-head-autonomy-charter.md`
