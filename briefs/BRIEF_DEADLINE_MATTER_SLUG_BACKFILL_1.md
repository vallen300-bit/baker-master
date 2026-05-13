---
brief_id: DEADLINE_MATTER_SLUG_BACKFILL_1
brief_version: 1.0
author: AH1
target: b3
dispatched: 2026-05-13
trigger_class: TIER_B_BACKFILL_+_WRITE_PATH_CLOSURE
mandatory_2nd_pass: false
security_review_required: false
effort_estimate: ~3h
complexity: Medium
predecessor: DEADLINE_ASSIGNED_TO_BACKFILL_1 (PR #199 merged 7e07516)
---

# BRIEF: DEADLINE_MATTER_SLUG_BACKFILL_1 — wire classifier into bypassed write-paths + one-shot backfill

## Context

Director-ratified 2026-05-13 "keep off, build a matter slug" — the scanner kill-switch (`VAULT_SCANNER_ENABLED=false`) stays in place until this brief lands. Predecessor brief DEADLINE_ASSIGNED_TO_BACKFILL_1 (b3, PR #199) surfaced that **all 69 active deadlines have NULL `matter_slug`**, which is why the desk-attribution backfill yielded M=0/A=0/U=69 — the upstream slug column it depends on is empty.

Root cause: the `_match_matter_slug()` classifier at `orchestrator/pipeline.py:27` already exists and is wired into 4 ingest triggers (email / fireflies / dropbox / calendar). But 3 other write-paths bypass it entirely. New deadlines from those paths land with NULL `matter_slug`, and no retroactive backfill has ever run.

This brief closes both gaps: forward-fix the bypassed paths (Scope A), then one-shot retroactive backfill (Scope B). Scanner re-enable is gated on Director ratification of the Scope-B apply.

## Estimated time: ~3h
## Complexity: Medium
## Prerequisites
- `BAKER_VAULT_PATH` env var set (existing — no change)
- Predecessor PR #199 merged (✅ — `7e07516`)
- Scanner stays OFF (✅ — flipped 2026-05-13 post your dispatch)

---

## Scope A — Wire `_match_matter_slug()` into 3 bypassed write-paths

### Problem
3 of 5 deadline-insert call sites do not call the classifier:
1. `triggers/clickup_trigger.py:548-551` — direct INSERT, no matter_slug in column list
2. `baker_mcp/baker_mcp_server.py:1660-1670` — `baker_add_deadline` MCP tool routes to `cortex_create_deadline()` which routes to `insert_deadline()`, neither accepts the param
3. `models/deadlines.insert_deadline()` (line 265) — no `matter_slug` param in signature

Already-wired paths to leave alone:
- `triggers/email_trigger.py:510-524`
- `triggers/fireflies_trigger.py:132-135`
- `triggers/dropbox_trigger.py:417`
- `triggers/calendar_trigger.py:637`
- `orchestrator/deadline_manager.py` recurring respawn (inherits parent)
- `outputs/dashboard.py` commitment migration (explicit `c.matter_slug`)

### Implementation

**A1. `models/deadlines.py:265` — add `matter_slug` param to `insert_deadline()`.**

Add to signature (with default None — backward compatible for callers we're not touching):
```python
def insert_deadline(
    description: str,
    due_date: datetime,
    source_type: str,
    confidence: str,
    priority: str = "normal",
    source_id: str = None,
    source_snippet: str = None,
    status: str = None,
    matter_slug: str = None,  # NEW
) -> Optional[int]:
```

Update INSERT at line 289-296:
```python
cur.execute("""
    INSERT INTO deadlines
        (description, due_date, source_type, source_id, source_snippet,
         confidence, priority, status, matter_slug)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    RETURNING id
""", (description, due_date, source_type, source_id,
      source_snippet or "", confidence, priority, status, matter_slug))
```

**A2. `models/cortex.py:455` — propagate `matter_slug` through `cortex_create_deadline()`.**

Add to signature:
```python
def cortex_create_deadline(
    description: str,
    due_date,
    source_type: str,
    source_agent: str,
    confidence: str = "medium",
    priority: str = "normal",
    source_id: str = None,
    source_snippet: str = None,
    matter_slug: str = None,  # NEW
) -> Optional[int]:
```

Pass through at line 487-495:
```python
dl_id = insert_deadline(
    description=description,
    due_date=due_date,
    source_type=source_type,
    confidence=confidence,
    priority=priority,
    source_id=source_id,
    source_snippet=source_snippet,
    matter_slug=matter_slug,  # NEW
)
```

**A3. `baker_mcp/baker_mcp_server.py:1660` — `baker_add_deadline` MCP tool: compute slug before call.**

Before the `cortex_create_deadline(...)` call (line ~1660), insert:
```python
# Compute matter_slug from description + source_snippet via classifier
from orchestrator.pipeline import _match_matter_slug
from kbl import slug_registry
from memory.store_back import SentinelStoreBack
_store = SentinelStoreBack._get_global_instance()
_matter_name = _match_matter_slug(description, source_snippet or "", _store)
_matter_slug = slug_registry.normalize(_matter_name)  # may be None if no match or unmappable
```

Then pass `matter_slug=_matter_slug` into `cortex_create_deadline(...)`.

**Singleton-pattern requirement:** Use `SentinelStoreBack._get_global_instance()` — NEVER bare `SentinelStoreBack()`. The `check_singletons.sh` pre-push hook will block bare instantiation.

**A4. `triggers/clickup_trigger.py:548-551` — direct INSERT path: compute + add column.**

Before the INSERT (line ~547), compute:
```python
from orchestrator.pipeline import _match_matter_slug
from kbl import slug_registry
_matter_name = _match_matter_slug(description, source_tag or "", store)
_matter_slug = slug_registry.normalize(_matter_name)
```

Update the INSERT at line 548-551:
```python
cur.execute("""
    INSERT INTO deadlines (description, due_date, priority, source_snippet, source_type, source_id, status, confidence, matter_slug)
    VALUES (%s, %s, %s, %s, %s, %s, 'active', 'high', %s)
""", (description, due_date, 'normal', source_tag, 'clickup', f"clickup:{task_id}", _matter_slug))
```

Note `store` is already in scope at that call site (look upstream in the same function — it's the `SentinelStoreBack` instance the trigger receives).

### Tests (Scope A)
- `tests/test_deadline_matter_slug_writepath.py` (new) — 4 tests minimum:
  1. `insert_deadline(matter_slug='cupial')` round-trip — DB row has `matter_slug='cupial'`
  2. `insert_deadline()` without matter_slug — DB row has NULL `matter_slug` (backward compat)
  3. `cortex_create_deadline(matter_slug='hagenauer')` — propagates through to DB
  4. `_match_matter_slug` returns `'Cupial'` → `slug_registry.normalize('Cupial')` returns `'cupial'` (integration shape)

---

## Scope B — One-shot backfill script: `scripts/backfill_matter_slug.py`

### Problem
69 active deadlines have NULL `matter_slug`. Many likely have enough text in `description + source_snippet` for the classifier to score a match against the active matter_registry.

### Pattern reuse
Mirror `scripts/backfill_assigned_to.py` (b3's prior backfill from PR #199):
- **Dry-run-by-default**: no args = dry-run mode, writes proposal to `/tmp/backfill_matter_slug_proposal_<UTC-ts>.md`
- **`--apply <ratified.md>` writes**: 3 safety rails (file <24h old, every row has non-empty proposed slug, `BAKER_BACKFILL_DRY_RUN_ONLY=1` env override)
- **M/A/U bucketing** in dry-run output (M=matched, A=ambiguous-multiple-candidates, U=unmatched). For matter_slug specifically: M = classifier scored ≥1 + slug resolved to canonical, U = classifier returned None OR slug_registry.normalize returned None.
- **Idempotent**: WHERE clause must include `matter_slug IS NULL` so re-running over a partially-applied set is safe.

### Per-row savepoint fix (predecessor v2_followup)
b3 flagged in CODE_3_PENDING.md frontmatter: *"`_apply_updates` per-row rollback can silently drop earlier successful UPDATEs on mid-batch error"*. Fix in this brief:

```python
# Inside the apply loop, after acquiring cursor:
for row in proposed_updates:
    cur.execute("SAVEPOINT row_sp")
    try:
        cur.execute(
            "UPDATE deadlines SET matter_slug = %s WHERE id = %s AND matter_slug IS NULL",
            (row["proposed_slug"], row["deadline_id"]),
        )
        cur.execute("RELEASE SAVEPOINT row_sp")
        applied += 1
    except Exception as e:
        cur.execute("ROLLBACK TO SAVEPOINT row_sp")
        failed.append({"id": row["deadline_id"], "error": str(e)})
        # continue loop — prior successful UPDATEs are preserved
conn.commit()
```

### Dry-run query (the SELECT)
```sql
SELECT id, description, source_snippet, source_type
FROM deadlines
WHERE status IN ('active', 'pending_confirm')
  AND matter_slug IS NULL
LIMIT 500;  -- belt-and-suspenders; actual count ~69 per b3's audit
```

### Classifier invocation in the backfill
```python
from orchestrator.pipeline import _match_matter_slug
from kbl import slug_registry
from memory.store_back import SentinelStoreBack

store = SentinelStoreBack._get_global_instance()

# Inside the per-row loop:
matter_name = _match_matter_slug(
    description or "",
    source_snippet or "",
    store,
)
proposed_slug = slug_registry.normalize(matter_name)  # None if no match or unmappable
```

### Tests (Scope B) — minimum 4
1. Dry-run with 0 NULL rows → empty proposal, exit 0, no DB writes
2. Dry-run with mixed match/no-match → proposal file written, M+U buckets correctly populated, no DB writes
3. `--apply <ratified.md>` happy path → matched rows updated, NULL rows untouched, idempotent on re-run
4. `--apply` with one bad row (forced bad slug to violate FK if added later, or a unique constraint violation) → other rows still committed via savepoint pattern

---

## Part H — Invocation-path audit (capability-extension-template §H)

Per SKILL.md Rule 10 (Amendment H). Required because this brief modifies write-paths into a column read by Pattern-2 surfaces (deadlines drives the daily DM, cockpit cards, and is consumed by `ao_pm` + `movie_am` capability sets via `update_pm_project_state(...)`).

**H1 — Enumerate invocation paths (write-side):**
| # | Door | File | Pre-fix matter_slug | Post-fix matter_slug |
|---|---|---|---|---|
| 1 | Email ingest | `triggers/email_trigger.py:510` | ✅ wired | ✅ unchanged |
| 2 | Fireflies ingest | `triggers/fireflies_trigger.py:132` | ✅ wired | ✅ unchanged |
| 3 | Dropbox ingest | `triggers/dropbox_trigger.py:417` | ✅ wired | ✅ unchanged |
| 4 | Calendar ingest | `triggers/calendar_trigger.py:637` | ✅ wired | ✅ unchanged |
| 5 | ClickUp ingest | `triggers/clickup_trigger.py:548` | ❌ NULL | ✅ fixed (Scope A4) |
| 6 | MCP `baker_add_deadline` | `baker_mcp/baker_mcp_server.py:1660` | ❌ NULL | ✅ fixed (Scope A3) |
| 7 | `insert_deadline()` helper | `models/deadlines.py:265` | ❌ no param | ✅ fixed (Scope A1) |
| 8 | `cortex_create_deadline()` | `models/cortex.py:455` | ❌ no param | ✅ fixed (Scope A2) |
| 9 | Dashboard commitment migration | `outputs/dashboard.py:5301` | ✅ explicit `c.matter_slug` | ✅ unchanged |
| 10 | Recurring respawn | `orchestrator/deadline_manager.py:1098` | ✅ inherits parent | ✅ unchanged |

**H2 — Write-path closure verification:** post-fix, every door either calls `_match_matter_slug(...)` (or accepts an explicit slug from upstream context) OR is intentionally read-only at this layer. Doors 9-10 are pass-through (no new classification needed).

**H3 — Read-path completeness:** `matter_slug` is read by (a) the desk-attribution backfill (predecessor), (b) PM-capability scope filters (`update_pm_project_state`), (c) cockpit/DM grouping. No read-path changes needed — those already SELECT the column.

**H4 — `mutation_source` tag:** Scope B `--apply` writes a row to `baker_actions` with `mutation_source='backfill_matter_slug'` for audit trail.

**H5 — Cross-surface continuity test:** after Scope B apply, run b3's predecessor backfill (`scripts/backfill_assigned_to.py`) in dry-run mode. M-bucket should now be non-zero — confirms the chain works end-to-end.

---

## Files Modified
- `models/deadlines.py` — add `matter_slug` param to `insert_deadline()` + INSERT column
- `models/cortex.py` — add `matter_slug` param to `cortex_create_deadline()` (pass-through)
- `baker_mcp/baker_mcp_server.py` — compute slug via classifier before MCP tool's `cortex_create_deadline()` call
- `triggers/clickup_trigger.py` — compute + add to direct INSERT
- `scripts/backfill_matter_slug.py` — NEW (mirror `backfill_assigned_to.py` shape with savepoint pattern)
- `tests/test_deadline_matter_slug_writepath.py` — NEW (≥4 tests Scope A)
- `tests/test_backfill_matter_slug.py` — NEW (≥4 tests Scope B)

## Do NOT Touch
- `orchestrator/pipeline.py:27-92` — classifier itself; only call it
- `triggers/email_trigger.py`, `fireflies_trigger.py`, `dropbox_trigger.py`, `calendar_trigger.py` — already correctly wired
- `orchestrator/deadline_manager.py` — recurring respawn already inherits parent
- `outputs/dashboard.py` commitment migration — already explicit
- DDL — `matter_slug` column already exists (TEXT, nullable). Do NOT touch `ALTER TABLE deadlines`.
- `scripts/backfill_assigned_to.py` — predecessor; leave as-is (do not retroactively patch its savepoint bug; this brief's script is the corrected pattern going forward)
- `baker-vault/slugs.yml` — separate-repo PR only (we only READ via slug_registry)

## Key Constraints

1. **Singleton hook (`scripts/check_singletons.sh`):** all instantiation of `SentinelStoreBack` must go through `._get_global_instance()`. The pre-push hook will block bare `SentinelStoreBack()`.
2. **Backward-compatible param default:** `matter_slug: str = None`. Existing callers (email_trigger / fireflies_trigger / etc.) must continue to work unchanged — they already compute their own slug locally and pass via kwarg.
3. **Classifier graceful-None:** `_match_matter_slug()` returns None on no match — that's expected and must NOT raise. `slug_registry.normalize(None)` returns None — also expected.
4. **`slug_registry.normalize` may return None for matter_names not in slugs.yml:** the classifier reads `matter_registry` (Postgres table) which can drift from `slugs.yml`. When normalize returns None, the row gets a NULL `matter_slug` — correct fail-soft behavior, not an error.
5. **Backfill idempotency:** WHERE clause must include `matter_slug IS NULL`. Never overwrite.
6. **3 safety rails on `--apply`** (copy b3's pattern verbatim from `backfill_assigned_to.py`):
   - Ratified mapping file <24h old (mtime check)
   - Every row has non-empty proposed slug (no partials in the apply set)
   - `BAKER_BACKFILL_DRY_RUN_ONLY=1` env-var override blocks `--apply` entirely
7. **No external surface changed.** No `/security-review` trigger (no auth, no new endpoints, no PII, no new external API call).
8. **PostgreSQL except blocks** must have `conn.rollback()` per project rule.

## Verification

### Ship gate
Literal `pytest tests/test_deadline_matter_slug_writepath.py tests/test_backfill_matter_slug.py -v` output PASTED in ship report. No "by inspection".

### Quality checkpoints
1. `pytest` green (paste full output in ship report)
2. `bash scripts/check_singletons.sh` PASS
3. Dry-run executed: `python3 scripts/backfill_matter_slug.py` produces a proposal file at `/tmp/backfill_matter_slug_proposal_<ts>.md` — committed as `briefs/_reports/B3_backfill_matter_slug_<ts>.md` for audit
4. Dry-run proposal includes M/A/U bucket counts and the list of (id, description-truncated, proposed_slug-or-NONE) tuples
5. No DDL touched (verify: `git diff --stat migrations/` shows no changes)
6. Scope-A unit test `test_insert_deadline_matter_slug_roundtrip` passes against live PG (or skip on missing `TEST_DATABASE_URL`)

### Verification SQL (post-apply, run by AH1 after Director ratifies)
```sql
-- Before apply (run in dry-run phase to confirm scope)
SELECT count(*) FROM deadlines
WHERE status IN ('active', 'pending_confirm') AND matter_slug IS NULL;
-- Expected: 69 ± small drift from new ingest

-- After apply
SELECT count(*) AS still_null FROM deadlines
WHERE status IN ('active', 'pending_confirm') AND matter_slug IS NULL;
-- Expected: < pre-apply count (delta = M-bucket size)

SELECT matter_slug, count(*) FROM deadlines
WHERE status IN ('active', 'pending_confirm')
GROUP BY matter_slug ORDER BY count(*) DESC;
-- Expected: matched slugs (cupial / hagenauer / movie / etc.) appear with non-zero counts
```

### Director ratification gate
**Do NOT execute `--apply`.** AH1 will:
1. Read your dry-run proposal file (committed to `briefs/_reports/`)
2. Surface the M-bucket sample (up to 20 rows: deadline description + proposed slug) to Director
3. On Director ratification of the M-bucket sample, AH1 executes `--apply <ratified_proposal.md>` from a freshly-pulled checkout (post-merge `git pull --rebase origin main` immediately before script run per SKILL.md Rule 9)
4. On clean apply, AH1 flips `VAULT_SCANNER_ENABLED=true` on Render + posts a deploy

---

## Bus posting (per `_ops/processes/agent-bus-posting-contract.md`)

Bus-post to `lead` on ship with topic `ship/DEADLINE_MATTER_SLUG_BACKFILL_1`. Include: PR number, test counts, dry-run bucket counts (M/A/U), and link to committed proposal file. Confirmation phrase: `B3 oriented. Read: CODE_3_PENDING.md, MEMORY.md.` at session start (per repo CLAUDE.md).

## Mailbox hygiene
On PR merge, AH1 will transition `briefs/_tasks/CODE_3_PENDING.md` → frontmatter `status: COMPLETE` (per b3's predecessor pattern). b3 does NOT touch the mailbox file post-ship.

---

## Lesson application from predecessor (carry-forward)
- ✅ Dry-run-by-default + 3 safety rails on `--apply` (b3's pattern from PR #199)
- ✅ Per-row savepoint pattern (b3's v2_followup flagged the bug; this brief's apply uses SAVEPOINT/RELEASE/ROLLBACK TO)
- ✅ Director ratification gate between dry-run and apply (DO NOT execute `--apply` autonomously)
- ✅ Singleton hook compliance (`SentinelStoreBack._get_global_instance()` only)
- ✅ Vault append on success (deadline-system-contract-v1.md v1.6 execution log — staged for CHANDA Inv 9 commit by Mac-Mini, NOT by b3)
