# BRIEF: HARD_DEADLINE_AUDIT_V1 — audit baker_add_deadline cadence + register MOVIE Desk test case

## Context

Three-tier scheduled-tasks architecture (Director-ratified 2026-05-13). Brief 3 of 3:
- **Brief 1** — vault soft-task schema (BRIEF_VAULT_TASKS_SCHEMA_V1, b2)
- **Brief 2** — APScheduler vault scanner (BRIEF_APSCHEDULER_VAULT_SCANNER_V1, b3) — consumes the deadline state Brief 3 audits
- **Brief 3 — THIS** — deadline-system audit + first registration

This brief has TWO independent parts:
1. **Audit** — document the existing `baker_add_deadline` lifecycle: nudge cadence, escalation, Slack/WhatsApp routing, state machine. Output is a markdown doc, not code.
2. **Register one test case** — the 31.12.2026 residence-fee deferral as MOVIE Desk's first hard deadline. This validates the audited cadence works end-to-end.

Architecture doc: `https://brisen-docs.onrender.com/architecture/scheduled-tasks-architecture.html`.

## Estimated time: ~2h
## Complexity: Low
## Prerequisites: None. Read access to baker-master `models/deadlines.py` + grep across baker-master.

---

## Part 1: Audit the existing deadline system

Read + grep across baker-master to produce a single canonical doc:

**Output file:** `baker-vault/_ops/processes/deadline-system-contract-v1.md`

The doc must answer EXACTLY these questions, with `file:line` citations to verify (per Brief Authoring Standards rule 7 — open each file at the cited line):

### Q1 — Schema (what fields exist today)

Document the live schema of the `deadlines` table. Source: `models/deadlines.py` lines ~77-106 + any post-2026-04-29 ALTER. Include for each column:
- name + type + default + nullable
- which migration / commit introduced it (grep migrations + git blame)

Expected columns at audit time:
`id, description, due_date, source_type, source_id, source_snippet, confidence, priority, status, dismissed_reason, last_reminded_at, reminder_stage, created_at, updated_at, severity, assigned_to, assigned_by, matter_slug, obligation_type, is_critical, critical_flagged_at`.

### Q2 — Lifecycle (status state machine)

`status` column transitions. Grep the codebase for all places that UPDATE `deadlines.status`. Likely states: `active`, `dismissed`, `completed`, `superseded`. Document each:
- Trigger (what code path causes the transition)
- Pre-conditions
- Side-effects (does Slack/WhatsApp fire on transition?)

### Q3 — Nudge cadence (THE CRITICAL ANSWER)

`last_reminded_at` and `reminder_stage` columns exist — so there IS a nudge state machine somewhere. Find it.

Grep for: `last_reminded_at`, `reminder_stage`, `deadline.*remind`, `deadline_nudge`, `deadline_alert`. Likely lives in `triggers/embedded_scheduler.py` or a dedicated `triggers/deadline_*.py` file.

Document for each nudge stage:
- Lead-time before `due_date` (e.g., T-30 days, T-7, T-1, T-0, T+1)
- Cadence between nudges within a stage
- Which channel (Slack DM / WhatsApp / Cockpit card / email)
- Escalation rules (does priority + severity + is_critical change the cadence?)

**If no nudge state machine exists** (columns are vestigial): say so explicitly. Surface as a v2 follow-up brief.

### Q4 — Push channel routing

Where do deadline nudges land?
- Slack DM to Director — channel ID, message format
- WhatsApp — only for `priority=critical` or `is_critical=true`?
- Cockpit card surface — is there a "Critical today" / "Due this week" widget?

Cite file:line for each. Expected source: `triggers/whatsapp_*.py`, `tools/slack_*.py`, `outputs/dashboard.py` routes.

### Q5 — Assignment + matter routing

`assigned_to` + `matter_slug` columns. Document:
- How `assigned_to` is set (which call paths populate it; default value)
- Which agent reads `assigned_to` to filter "their" deadlines (the new vault_scanner from Brief 2 will, but does anything else today?)
- `matter_slug` validation: enforced anywhere, or free-text?

### Q6 — Slack DM format + frequency cap

Quote the exact format of a current deadline-nudge Slack DM (if any). If multiple stages, one example per stage.

Is there a rate cap on how many nudges per day land in Director's DM? Where is it enforced?

### Q7 — Gaps + recommendations

Author's section. Based on the audit, list:
- Gaps between today's behavior and what Brief 2's vault scanner expects (e.g., if `assigned_to` is rarely populated, the scanner's per-desk query returns nothing — flag this)
- Any nudge stages that are missing (e.g., no T-30 escalation)
- Whether the system is robust to `due_date IS NULL` (soft commitments with no specific date — schema allows null per migration on line ~102)

Each gap gets a one-sentence proposed fix + estimated effort. NOT a v2 brief — just a list AH1 can size later.

---

## Part 2: Register the MOVIE Desk test case

After Part 1's doc is committed, register ONE hard deadline via `baker_add_deadline`:

**Deadline:** 31.12.2026 residence fee deferral year-end (MOVIE Desk test case per Director ratification).

### How to register

Use the Baker MCP tool `baker_add_deadline` from a Cowork session OR via the HTTP MCP endpoint. Schema (from `baker_mcp_server.py:431-444`):

```python
baker_add_deadline(
    description="MOVIE Desk — residence fee deferral year-end deadline",
    due_date="2026-12-31",
    priority="high",
    source_snippet="MOVIE Desk MOHG prep + scheduled-tasks v1 test case "
                   "(Director ratified 2026-05-13 — first hard deadline in "
                   "scheduled-tasks-architecture v1).",
    confidence="high",
)
```

**Then immediately follow up with a direct SQL UPDATE** to populate fields the MCP tool doesn't accept (`assigned_to`, `matter_slug`, `severity`):

```sql
UPDATE deadlines
SET assigned_to = 'movie-desk',
    matter_slug = 'mo-vie',
    severity = 'firm'
WHERE id = <returned-id-from-baker_add_deadline>;
```

Capture the returned `id` from the MCP call + paste both the MCP response and the UPDATE confirmation in the ship report.

**Do NOT** extend the MCP tool signature to accept `assigned_to` / `matter_slug` in v1 — that's a separate brief if Director wants it (likely v2).

### Verification

After registration:

```sql
SELECT id, description, due_date, priority, severity, status, assigned_to, matter_slug
FROM deadlines
WHERE description LIKE '%residence fee%';
```

Must return exactly one row with all fields populated as above. Paste literal output in ship report.

---

## Files to modify / create

**baker-vault:**
- `_ops/processes/deadline-system-contract-v1.md` — NEW (the Part 1 audit doc)

**baker-master:**
- None. (No code change in v1; Part 2 is a runtime DB write via MCP.)

**Baker DB:**
- Insert + update one row in `deadlines` table (Part 2). Idempotency: if a row with the same description already exists, do NOT insert a second — update the existing row's fields if any are missing.

---

## Test plan

This brief has no pytest target (audit + DB write only). Verification gates instead:

1. **Audit completeness:** doc answers all 7 questions in Part 1 with file:line citations. AH1 spot-checks 3 citations at random (opens the file at the line; must match doc claim).
2. **Registration confirmed:** SELECT query above returns exactly one row with all fields populated.
3. **Idempotent re-run:** running the registration sequence a second time does NOT insert a duplicate.

---

## Ship gate

1. `_ops/processes/deadline-system-contract-v1.md` committed + pushed to baker-vault main.
2. SELECT verification output pasted literally in ship report.
3. AH1 (this lane) verifies 3 random citations against source files; failure → REQUEST_CHANGES.

---

## Risks + past lessons applied

- **Lesson #7 (brief file:line citation verification):** every cite in the audit doc MUST point at the actual line. Brief-document line ≠ source line — open each file at line N to confirm before writing.
- **Lesson #18 (matter_slug validation):** `mo-vie` must exist in `baker-vault/slugs.yml`. Verify before the UPDATE — if not present, surface to AH1; do not silently create.
- **Lesson #8 (no by-inspection ship):** literal SELECT output required, not "row was inserted as expected."

---

## Out of scope (defer to v2)

- Extending `baker_add_deadline` MCP signature with `assigned_to` / `matter_slug` / `severity`
- Building new nudge stages if Q3 audit finds gaps (only document; don't implement in v1)
- Migrating any other deadlines from any other source (only the one test case)
- Replacing the existing nudge channel (WhatsApp / Slack) — audit-and-document only

---

## Director ratification anchor

Director "go" 2026-05-13 (this session). Specifically:
- 31.12.2026 residence-fee deferral named explicitly by MOVIE Desk + endorsed by Director as v1 test case.
- Audit-then-act sequence: AH1 engineering eval recommended "audit existing cadence + write a deadline-nudge contract doc; if it lacks per-tier escalation, brief a fix" — Director's "go" greenlights the audit + registration only; any cadence-fix is a separate brief, not folded into v1.

---

## Dispatch coordination

- Auditor + registrar: **b4**
- Branch: `b4/hard-deadline-audit-1` (for the vault doc commit only; no baker-master branch needed)
- Independent of Brief 1 + Brief 2 timing. Brief 2's scanner will pick up the test deadline whenever it runs after Brief 3 lands.

---

## UPDATE — 2026-05-13 — architecture-review amendment (Director-ratified this session)

One amendment, folded post-architecture-review. Adds ~15 min to audit effort (~2h → ~2.25h). Closes a HIGH-severity coupling concern.

### Amendment — Q5 must surface `assigned_to` population rate as a percent + v1.5 backfill trigger

The audit's Q5 ("Assignment + matter routing") originally asked "how is `assigned_to` set" + "which agent reads it." Director-ratified amendment makes the QUANTITATIVE answer mandatory.

**Required output for Q5:**

```
- Total active deadlines (status='active'): N
- Deadlines with assigned_to populated (non-null, non-empty): X (P%)
- Deadlines without assigned_to: Y (Q%)
- Deadlines with matter_slug populated: M (R%)
- Top-5 most common assigned_to values (count): ...
- Top-5 most common matter_slug values (count): ...
```

Run literally — paste the SQL and the literal output rows. Brief Authoring Standards rule 7 applies (cite the query).

```sql
SELECT
    COUNT(*) FILTER (WHERE status = 'active') AS total_active,
    COUNT(*) FILTER (WHERE status = 'active' AND assigned_to IS NOT NULL AND assigned_to != '') AS with_assignee,
    COUNT(*) FILTER (WHERE status = 'active' AND (assigned_to IS NULL OR assigned_to = '')) AS without_assignee,
    COUNT(*) FILTER (WHERE status = 'active' AND matter_slug IS NOT NULL AND matter_slug != '') AS with_matter_slug
FROM deadlines;
```

Compute P, Q, R as percentages of total_active.

### v1.5 backfill trigger

After registering the test deadline (Part 2), if **P < 50%** (less than half of active deadlines have `assigned_to` populated):

1. **Do NOT** attempt to backfill within this brief — out of scope.
2. **DO** add a clearly-marked v1.5 follow-up entry at the END of the audit doc:

```markdown
## v1.5 FOLLOW-UP — `assigned_to` backfill required

Population rate at audit time (2026-05-13): X / N = P%.

Threshold P < 50% triggers immediate v1.5 work BEFORE vault_scanner_daily
fleet-wide rollout. Otherwise the scanner's per-desk query under-reports
desk deadlines while real ones live in the `_unassigned` synthetic bucket.

Proposed v1.5 brief: `BRIEF_DEADLINE_ASSIGNED_TO_BACKFILL_1`. Scope:
- Heuristic backfill from `matter_slug` → desk via `_desk-matter-map.yml`
- Manual review queue for deadlines with neither `assigned_to` NOR `matter_slug`
- Director ratification of the desk assignments before bulk UPDATE

Surface to AH1 immediately on audit completion if triggered.
```

If **P >= 50%**, note "v1.5 backfill not triggered — population rate adequate" and proceed without the addendum.

This makes the audit actionable instead of merely descriptive.

### Ratification anchor

Director "ratified" 2026-05-13 (this session) post AH1 architecture-review verdict "accept-with-changes." Concern #1 (`assigned_to` population gap → scanner silent under-reporting) closed by (a) scanner-side `_unassigned` bucket in Brief 2 Amendment E, AND (b) this brief's quantitative-output requirement + v1.5 backfill trigger.
