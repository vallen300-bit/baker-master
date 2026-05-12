# BRIEF: APSCHEDULER_VAULT_SCANNER_V1 — daily vault-task + deadline scanner, consolidated Slack DM

## Context

Three-tier scheduled-tasks architecture (Director-ratified 2026-05-13). Brief 2 of 3:
- **Brief 1** — vault soft-task schema (BRIEF_VAULT_TASKS_SCHEMA_V1, b2)
- **Brief 2 — THIS** — APScheduler vault scanner (b3)
- **Brief 3** — Baker deadline-system audit (BRIEF_HARD_DEADLINE_AUDIT_V1, b4)

The scanner is the "messenger" piece: it reads vault tasks (Brief 1's output) + Baker's deadline table, and pushes ONE consolidated Slack DM per day. It also generates per-desk `today-YYYY-MM-DD.md` + `upcoming-deadlines.md` mirror files inside the vault, so desks see their own state at session start without an API call.

Architecture doc: `https://brisen-docs.onrender.com/architecture/scheduled-tasks-architecture.html`.

## Estimated time: ~4h
## Complexity: Medium
## Prerequisites: BRIEF_VAULT_TASKS_SCHEMA_V1 merged (so the scanner has at least one valid task to scan).

---

## Pattern (mandatory before any code)

Mirror the existing APScheduler patterns in `triggers/embedded_scheduler.py`:
- Cross-process singleton lock via `triggers/scheduler_lease.py` (jobs run on lock-holder replica only — vault_mirror scar 2026-05-12)
- Job registration in `_register_jobs(scheduler)`
- CronTrigger with explicit `timezone="UTC"`
- Env-gated enable: `VAULT_SCANNER_ENABLED` (default true; set false to kill switch)
- Job id: `vault_scanner_daily`, name: `Vault task + deadline scanner (06:00 UTC daily)`
- Wrapper function `_vault_scanner_job()` at module bottom, follows hot_md_weekly_nudge pattern (lines 1095-1121)

**Singleton scope:** APScheduler job runs only on the lock-holder replica. Non-lock replica skips silently. This matches the vault_mirror sync_tick pattern post-PR #195.

---

## Part 1: Cron + idempotent restart catch-up

### Job

```python
scheduler.add_job(
    _vault_scanner_job,
    trigger=CronTrigger(hour=6, minute=0, timezone="UTC"),
    id="vault_scanner_daily",
    name="Vault task + deadline scanner (06:00 UTC daily)",
    replace_existing=True,
    coalesce=True,       # if Render was down at 06:00, fire once on next tick window
    misfire_grace_time=3600,   # tolerate up to 1h late
)
```

### Idempotency marker (catch-up on restart)

APScheduler's `misfire_grace_time` covers ~1h late. But Render auto-deploys on push to main can take longer, and Render's free tier can sleep for minutes. So also add **explicit catch-up on startup**:

In `_register_jobs`, after registering the scanner, run:

```python
from datetime import datetime, timezone, time
import os
_now = datetime.now(timezone.utc)
_today = _now.date()
_marker_path = os.path.expanduser(
    f"~/baker-vault/_ops/agents/_scanner-state/last-run-{_today.isoformat()}.marker"
)
# Run once on startup if 06:00 UTC has passed today and no marker exists
if _now.time() >= time(6, 0) and not os.path.exists(_marker_path):
    logger.info("vault_scanner: catch-up run on startup (no marker for %s)", _today)
    try:
        _vault_scanner_job()
    except Exception:
        logger.exception("vault_scanner: catch-up run failed")
```

**Marker file format:** `~/baker-vault/_ops/agents/_scanner-state/last-run-YYYY-MM-DD.marker` — empty file, mtime is the timestamp. Create `_scanner-state/` directory inside the scanner if missing.

**Why a file, not a DB row:** the vault is the source of truth for this. Avoids a new table. Markers older than 7 days are pruned at the top of each scan run (sweep `_scanner-state/` glob).

---

## Part 2: Scanner logic (the actual job)

`_vault_scanner_job()` does five things, in this order:

### 1. Discover desks

```python
vault_root = os.path.expanduser("~/baker-vault")
agents_dir = os.path.join(vault_root, "_ops", "agents")
desks = sorted([
    d for d in os.listdir(agents_dir)
    if os.path.isdir(os.path.join(agents_dir, d, "tasks", "active"))
])
```

Skip desks without a `tasks/active/` subdir (they don't participate yet). v1 expects only `movie-desk` to match.

### 2. Per-desk: scan vault tasks

For each desk, walk `tasks/active/*.md`:
- Parse frontmatter (PyYAML)
- Bucket each task into: `overdue` (`due < today`), `due_today` (`due == today`), `due_soon` (today < due <= today+7), `blocked`, `no_due` (no `due` field)
- Skip files with malformed/missing frontmatter; log warning but do NOT crash the scan

### 3. Per-desk: scan deadlines table

Query Baker DB:

```sql
SELECT id, description, due_date, priority, severity, matter_slug, assigned_to,
       last_reminded_at, reminder_stage, is_critical
FROM deadlines
WHERE status = 'active'
  AND assigned_to = %s          -- matches desk slug
  AND (due_date IS NULL OR due_date <= NOW() + INTERVAL '30 days')
ORDER BY due_date NULLS LAST, priority
```

Bucket: `overdue / due_today / due_this_week / due_this_month`.

**Mapping rule:** `assigned_to` matches the desk's directory name (e.g., `movie-desk`). For v1 only the MOHG residence-fee deferral test case will hit this query — register it under `assigned_to='movie-desk'` (handled by Brief 3).

### 4. Per-desk: write vault mirror files

For each desk that has any non-empty bucket, write TWO files (overwrite):

**A. `~/baker-vault/_ops/agents/<desk>/today-YYYY-MM-DD.md`**

```markdown
---
generated_at: 2026-05-13T06:00:00Z
generated_by: vault_scanner_daily
desk: movie-desk
---

# Today — movie-desk — 2026-05-13

## Overdue tasks (N)
- [<task-slug>](tasks/active/2026-05-13-mohg-debrief.md) — <title> — due <date> — <priority>

## Due today (N)
- ...

## Due this week (N)
- ...

## Blocked (N)
- <task> — blocked_by: <other-task>

## Hard deadlines — overdue (N)
- <id>: <description> — due <date> — <priority>

## Hard deadlines — due this week (N)
- ...
```

Empty sections OK; sections with N=0 should be omitted entirely. Don't write the file at all if all buckets empty.

**B. `~/baker-vault/_ops/agents/<desk>/today.md`** — copy of A (for desks that prefer a stable filename).

**C. `~/baker-vault/_ops/agents/<desk>/upcoming-deadlines.md`** — read-only mirror of THIS desk's hard deadlines for the next 30 days. Regenerated every scan. Frontmatter:

```yaml
---
generated_at: <ISO>
generated_by: vault_scanner_daily
desk: <desk>
warning: GENERATED FILE — do not edit by hand; changes are overwritten on next scan
---
```

### 5. Send ONE consolidated Slack DM

Per AH1 engineering eval (Director-ratified): one DM at 06:00 UTC with desk-grouped sections. Per-desk DM ONLY for urgent items (defined below).

**Slack push primitive:** Use the existing Slack MCP / push wrapper. Find the pattern from the weekly self-audit / hot_md_nudge — likely a `slack_send` or similar helper in `triggers/` or `tools/`. If no clean wrapper exists, use the MCP tool `mcp__claude_ai_Slack__slack_send_message` to Director's DM channel (resolve from preferences).

**Recipient:** Director's personal Slack DM. Channel ID lookup pattern: existing weekly-audit job uses an env var or hardcoded channel — mirror that.

**Format:**

```
Daily digest — 2026-05-13 06:00 UTC

🟠 movie-desk
  Overdue: <count>
  Due today: <count>
  Due this week: <count>
  Hard deadlines overdue: <count>
  Hard deadlines this week: <count>

🟢 ao-desk
  (nothing today)

...

Full per-desk view: ~/baker-vault/_ops/agents/<desk>/today-2026-05-13.md
```

Per-desk emoji: 🟢 empty / 🟡 some items / 🟠 overdue or blocked / 🔴 critical or >7 overdue.

**Urgent ping rule:** If ANY desk has `is_critical=true` deadline overdue OR task priority `critical` overdue OR a `blocked_by` chain resolved (the blocker just closed today), ALSO send a separate per-desk DM with the specifics. Threshold conservative — start strict, loosen with experience.

**Rate cap:** Max 1 consolidated DM/day + 1 per-desk urgent DM per desk per day. Hard cap; counter resets at midnight UTC.

---

## Part 3: Marker file + atomic commit

At the END of a successful scan run:

1. Write the marker file `~/baker-vault/_ops/agents/_scanner-state/last-run-YYYY-MM-DD.marker` (empty file, mtime = now).
2. **DO NOT** commit to baker-vault from the scanner. The generated files (`today-*.md`, `upcoming-deadlines.md`) are agent-managed and not committed by the scanner itself — vault_mirror's sync_thread + Mac Mini single-writer handle persistence.
3. **However**: add the generated files to `.gitignore` in `_ops/agents/<desk>/`? No — Director wants them queryable in git history (audit trail of what was surfaced each day). Let Mac Mini's normal commit cycle pick them up.

If you find that Mac Mini doesn't auto-commit scanner output, raise this as a follow-up — DO NOT add commit logic to the scanner in v1.

---

## Part 4: schedule-registry.yml entry

Add the scanner as the FIRST entry in `baker-vault/_ops/processes/schedule-registry.yml` (placeholder created by Brief 1):

```yaml
jobs:
  - name: vault_scanner_daily
    cron: "0 6 * * *"
    timezone: UTC
    target_agent: lead
    payload:
      description: "Vault soft-task + hard-deadline daily scan"
      output_paths:
        - "_ops/agents/<desk>/today-<date>.md"
        - "_ops/agents/<desk>/today.md"
        - "_ops/agents/<desk>/upcoming-deadlines.md"
      slack_dm: true
      slack_dm_rate_cap: "1/day consolidated + 1/day/desk urgent"
    enabled: true
    registered_in: triggers/embedded_scheduler.py
    brief: BRIEF_APSCHEDULER_VAULT_SCANNER_V1
```

This is documentation of the scheduler state. Runtime still uses the Python code in `embedded_scheduler.py`. Reconciliation between YAML and runtime is v2.

---

## Files to modify / create

**baker-master (this brief's primary repo):**
- `triggers/embedded_scheduler.py` — register `vault_scanner_daily` job + add startup catch-up logic + `_vault_scanner_job()` wrapper at module bottom
- `triggers/vault_scanner.py` — NEW module with the scan logic (frontmatter parse, bucketing, file write, Slack push)
- `tests/test_vault_scanner.py` — NEW
- `requirements.txt` — add `PyYAML` if not already present (verify first: grep + skip if there)

**baker-vault (small touches, can be a separate vault commit):**
- `_ops/processes/schedule-registry.yml` — add the entry above

**Do NOT touch:**
- `outputs/dashboard.py` (no FastAPI route changes for v1)
- Existing scheduler jobs
- `models/deadlines.py` (Brief 3 audits, does not modify)
- vault_mirror (orthogonal lane)

---

## Hard rules — Python backend

Per `/Users/dimitry/bm-aihead1/.claude/rules/python-backend.md`:
- `conn.rollback()` in except blocks before any new query
- Always LIMIT unbounded SQL queries (the deadline query has implicit limit via WHERE; explicit LIMIT 500 added as belt+suspenders)
- Fault-tolerant: wrap DB + filesystem + Slack calls in try/except; scanner MUST NOT crash a Render service on a malformed task file
- Render env vars: use MCP merge mode for `VAULT_SCANNER_ENABLED` add (out of scope for this brief — AH1 will set it post-merge)

Singleton pattern: any new use of `SentinelStoreBack` or `SentinelRetriever` MUST go through `._get_global_instance()`. Pre-push hook `scripts/check_singletons.sh` will catch violations.

---

## Test plan

`tests/test_vault_scanner.py` must include LITERAL tests (no "by inspection"):

1. **Empty vault** — no desks have `tasks/active/`: scanner returns silently, no files written, no Slack DM sent (cap not consumed).
2. **MOHG task only** — parse frontmatter, write today file, send 1 consolidated DM (mock the Slack call).
3. **Malformed frontmatter** — task file with bad YAML: scanner logs warning, skips file, continues with remaining files.
4. **Overdue critical** — task with `priority: critical` and `due` in the past: triggers per-desk urgent DM (in addition to consolidated).
5. **Rate cap** — second scan in same UTC day does NOT send another consolidated DM (cap respected).
6. **Marker file** — after successful scan, marker file exists with today's date; old markers (>7d) pruned.
7. **Idempotent restart** — call scanner twice in same call window: second call respects rate cap.
8. **DB unavailable** — `get_conn()` returns None: scanner logs warning, still processes vault tasks, writes today files WITHOUT deadline sections, sends DM (degraded but not dead).

---

## Ship gate

1. Literal output of `pytest tests/test_vault_scanner.py -v` GREEN. All 8 tests pass.
2. Pre-push hook `scripts/check_singletons.sh` passes.
3. PR description includes the literal pytest output (no "by inspection" — Lesson #8).
4. **Mandatory 2nd-pass code-reviewer agent** triggered (SKILL.md §Code-reviewer 2nd-pass Protocol — fires here because this PR touches: external surface = Slack push primitive, scheduler ordering = job registration + startup catch-up race).

---

## /security-review — MANDATORY

This PR triggers `/security-review` per SKILL.md §Security Review Protocol:
- Touches external surface (Slack DM push)
- Touches scheduler primitives (startup catch-up + rate cap state)
- Reads vault files (path traversal: validate `desk` name against `[a-z0-9-]+` before joining paths)
- DB read (parameterized; no string formatting)

Path traversal hardening: when iterating `os.listdir(agents_dir)`, validate each entry matches `^[a-z0-9-]+$` and is a direct subdirectory (no symlink follow). Reject + log anything else.

---

## Risks + past lessons applied

- **Lesson #52 (singleton-pattern CI guard):** any new global instance MUST use `._get_global_instance()`. None expected in this brief but enforced by hook.
- **Lesson #8 (compile-clean ≠ done):** literal pytest output required.
- **Lesson #7 (baker-vault shared-FS race):** scanner WRITES today files but does NOT commit. Mac Mini commits via its existing cycle. No new race introduced.
- **Lesson #25 (singleton-locked scheduler):** the singleton lock pattern is already in `scheduler_lease.py`; the new job participates automatically by being registered in `_register_jobs`.
- **vault_mirror scar (2026-05-12):** the marker file approach + APScheduler `coalesce=True` + `misfire_grace_time=3600` make this robust to single-replica restart, multi-replica drift, and Render free-tier sleep.

---

## Out of scope (defer to v2)

- DataView-rendered today files (plugin-free v1)
- Per-task `recurrence` field handling (registry-only in v1)
- Backfilling closed tasks into a separate history report
- Cortex Backlog migration from ClickUp (separate brief)
- AID / B-code per-desk DM routing (Director Slack only in v1)
- WhatsApp fallback (Slack only in v1)
- Reconciling YAML registry vs runtime APScheduler state (v2 will likely make the YAML authoritative + APScheduler reads it at startup)

---

## Director ratification anchor

Director "go" 2026-05-13 (this session) post AH1 engineering eval. Specifically ratified:
- One consolidated DM with desk sections (NOT N per-desk DMs)
- Urgent per-desk DM only on critical-priority overdue or blocker-cleared
- 06:00 UTC fire time
- Dated today files (audit trail) + stable `today.md` copy
- Idempotent startup catch-up
- Singleton-replica execution via existing `scheduler_lease.py`

---

## Dispatch coordination

- Builder: **b3**
- Branch: `b3/apscheduler-vault-scanner-1`
- Coordinates with Brief 1 (b2): merge order matters — Brief 1 must merge BEFORE this brief's scanner can run successfully (no `tasks/active/` to scan otherwise). If b3 lands first, gate behind `VAULT_SCANNER_ENABLED=false` Render env until Brief 1 lands.
- Coordinates with Brief 3 (b4): no hard dependency; Brief 3 registers ONE deadline that this scanner picks up. If Brief 3 lands first, scanner just sees zero deadlines on first run — fine.
