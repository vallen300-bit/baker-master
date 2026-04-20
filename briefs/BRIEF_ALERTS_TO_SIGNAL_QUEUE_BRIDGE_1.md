# BRIEF: ALERTS_TO_SIGNAL_QUEUE_BRIDGE_1 — Connect Baker's alert stream to Cortex T3's signal_queue

**Prepared by:** AI Head
**Date:** 2026-04-20
**Director-approved:** 2026-04-20 (plain English: taxonomy co-design + *"Agree, go ahead"*)
**Target reviewer:** B2
**Target implementer:** single B-code (likely B1 once free from SOT Phase B)
**Session evidence:** 2026-04-20 chat transcript + `feedback_bridge_day1_teaching.md` + `feedback_ai_head_plain_english_only.md`

## Context

Cortex T3 went live in shadow mode on 2026-04-20 (~04:00 UTC). Pipeline tick registered, scheduler running, sentinels polling, dashboard rendering clean empty-state. Director's "when will I see the first signal" check at ~08:00 UTC produced an investigation — AI Head traced the gap and found: **the Cortex T3 pipeline was built to process signals, but no code path creates `signal_queue` rows from raw sentinel data**. Zero rows in `signal_queue`. Zero pipeline log entries. Gate 1 (≥5-10 clean signals through Steps 1-7) will never move.

Meanwhile, Baker's legacy 5-step pipeline (Classify → Enrich → Decide → Draft → Store) is fully operational — 5,366 alerts over Baker's lifetime, 5 in the last 4 hours, Director's M365 email from this morning caught as alert #15485 at 08:15 UTC (2 minutes after it landed). Baker's brain is fine. The seam between Baker's output (`alerts` table) and Cortex T3's input (`signal_queue` table) was simply never built.

**This brief builds that seam — the bridge.** Not a new producer designed from scratch. A selector-and-mapper that reads new `alerts` rows, applies a four-axis filter (to keep signal dense), maps each kept alert into a `signal_queue` row, advances a watermark, and exits. Runs as an APScheduler job on Render alongside `kbl_pipeline_tick`.

**Director's co-designed filter taxonomy** (established in 2026-04-20 chat, recorded verbatim):

> Don't filter on tier alone. Filter on **three axes working together** — tier + sender + message type. That's exactly what a mature selector should do.

Formalized in this brief as the four-axis selector: priority Tier 1+2 OR matter_slug OR VIP sender OR allowlist message type. Plus a stop-list for the noise common-denominator (third-party events/offers/visits mis-tagged as Director commitments).

**Explicit scope limit:** ship imperfect. Let the feedback ledger teach the filter via real dismissals during a 2-3 day convergence window. `BAKER_PRIORITY_CLASSIFIER_TUNE_1` is a separate follow-up brief that fixes root causes upstream — not a prerequisite for this bridge.

## Estimated time: ~6-8h
## Complexity: Medium
## Prerequisites

- `signal_queue` table exists with 35 columns (verified 2026-04-20 — MIGRATION_RUNNER_1 applied all schema migrations at 00:38 UTC)
- `alerts` table live + producing (verified — 5,366 lifetime, most recent at 10:10 UTC today)
- `vip_contacts` table exists with `id`, `name`, `email`, `whatsapp_id`, `fireflies_speaker_label` (verified)
- `deadlines` table with `assigned_to` + `assigned_by` columns (verified — obligor signal exists; this brief does not use it but `BAKER_PRIORITY_CLASSIFIER_TUNE_1` will)
- `mcp__baker__baker_raw_query` + `baker_raw_write` operational (verified)
- Render + Mac Mini shadow-mode infrastructure operational

---

## Fix/Feature 1: `kbl_bridge_tick` — new APScheduler job that bridges new alerts → signal_queue

### Problem

Cortex T3 pipeline has zero input. `kbl_pipeline_tick` fires every 120s, claims `WHERE status='pending'` from `signal_queue`, finds nothing, exits. No Silver ever generated. Gate 1 (production flip readiness) cannot move without this bridge.

### Current State

**Writers to `signal_queue` in the codebase** (verified via `grep -rn "INSERT INTO signal_queue"` and tracing UPSERT patterns in kbl/):

- `kbl/steps/step1_triage.py` through `step7_commit.py` — pipeline steps that UPDATE existing signal_queue rows (no inserts)
- `kbl/resolvers/email.py`, `kbl/resolvers/whatsapp.py` — resolvers for signal-embedded references (no inserts)
- `kbl/layer0.py` — Layer 0 filter, operates on existing signals (no inserts)
- `memory/store_back.py:6338` — schema CREATE TABLE (DDL, no inserts)
- `tests/test_status_check_expand_migration.py` + `tests/test_step*.py` — test fixtures inserting for test setup (not production path)

**Zero production-path writers.** Confirmed.

**Registered APScheduler jobs** on Render (from `triggers/embedded_scheduler.py`):
- `email_poll`, `exchange_poll`, `bluewin_poll`
- `fireflies_scan`, `plaud_scan`
- `scheduler_heartbeat`, `memory_watchdog`
- `clickup_poll` (6 workspaces)
- `dropbox_poll`, `todoist_poll`, `rss_poll`, `slack_poll`
- `browser_check`
- `kbl_pipeline_tick` — every 120s, env-gated on `KBL_FLAGS_PIPELINE_ENABLED`

43 total scheduled jobs on Render (verified via `/health` earlier this session).

### Implementation

**Branch:** `alerts-to-signal-queue-bridge-1`. **Target repo:** `baker-master`. **Reviewer:** B2.

New module: `kbl/bridge/alerts_to_signal.py`.

Wire into scheduler: `triggers/embedded_scheduler.py` registers a new job `kbl_bridge_tick` at interval `BRIDGE_TICK_INTERVAL_SECONDS` (default 60s, clamped to ≥30s floor matching pipeline tick).

**The module exposes one function:**

```python
def run_bridge_tick(max_bridge_per_tick: int = 50) -> dict:
    """Read new alerts since last watermark, apply 4-axis filter +
    stop-list, map kept alerts to signal_queue rows, advance watermark.
    Returns counts dict: {read, kept, bridged, skipped_filter,
    skipped_stoplist, errors}.
    """
```

**Four-axis filter logic (pure function, unit-testable):**

```python
def should_bridge(alert: dict, vip_ids: set[str], vip_emails: set[str]) -> bool:
    """Return True if alert passes the 4-axis selector.

    Axes (inclusive OR — any one matching is sufficient):
      1. Priority tier 1 or 2
      2. matter_slug IS NOT NULL (non-empty)
      3. contact_id resolves to a VIP contact (or sender_email in vip_emails
         when contact_id is NULL)
      4. tags/structured_actions contain a whitelist type

    Returns False if NONE match OR if stop-list matches.
    """
    # Stop-list check runs FIRST so it overrides permissive axes.
    if _is_stoplist_noise(alert):
        return False

    if alert.get("tier", 3) <= 2:
        return True
    if alert.get("matter_slug"):
        return True
    if alert.get("contact_id") and str(alert["contact_id"]) in vip_ids:
        return True
    if _has_promote_type(alert):
        return True

    return False
```

**Promote-type allowlist** (from Director's ratified taxonomy 2026-04-20):

```python
PROMOTE_TYPES = {
    "commitment",          # "I will do X by Y"
    "deadline",            # legal/regulatory/financial hard date
    "appointment",         # scheduled events, prep reminders
    "meeting",
    "tax-opinion",         # KPMG, Russo, Constantinos
    "tax-document",
    "financial-report",    # balance sheets, drawdown requests
    "financial-document",
    "legal-document",      # court filings, contracts
    "dispute-update",      # Hagenauer / Cupial / Ofenheimer
    "contract-change",     # AO / TU / SW / HMA
    "investor-communication",
    "vip-message",
    "travel-info",         # flights, hotels, transfers (real-cost if missed)
}
```

These are matched against `alert.tags` (jsonb array) and a lightweight regex on `alert.title` for type-like keywords when tags are absent. Tag-match is strict (token present); title-match is advisory (informs `_has_promote_type` only if no tag signal).

**Stop-list (Director-ratified common denominator 2026-04-20):**

```python
STOPLIST_TITLE_PATTERNS = [
    r"\bcomplimentary\b",
    r"\bredeem\b",
    r"\b(?:sale|% off|% discount)\b",
    r"\bsotheby(?:'s)?\b",
    r"\bauction\b(?!.*brisen)",  # auction, unless Brisen-specific
    r"\bwill be available\b",    # Stan Manoukian pattern
    r"\bMedal Engraving\b",
    r"\bpreview ends\b",
    r"\bHotel Express Deals\b",
    r"\bForbes Under 30\b",
    r"\bwine o'clock\b",
    r"\bTAKEITOUTSIDE\b",        # promo code example; generalizes per batch
]
STOPLIST_SOURCES = {
    "dropbox_batch",       # file-arrival receipts
    "cadence_tracker",     # VIP silence re-fires after Director dismissal
    "sentinel_health",     # operational, not Silver-worthy
    "waha_silence",
    "waha_session",
}

def _is_stoplist_noise(alert: dict) -> bool:
    if alert.get("source") in STOPLIST_SOURCES:
        return True
    title = (alert.get("title") or "")
    for pattern in STOPLIST_TITLE_PATTERNS:
        if re.search(pattern, title, flags=re.IGNORECASE):
            return True
    return False
```

**Watermark persistence:**

New row in `trigger_watermarks` with `source='alerts_to_signal_bridge'`. Each tick:

```python
SELECT last_seen FROM trigger_watermarks WHERE source='alerts_to_signal_bridge'
-- On first run, returns nothing; treat as NOW() - INTERVAL '2 hours'
-- so we don't backfill 5,366 alerts.

SELECT id, tier, title, body, matter_slug, source, source_id, tags,
       structured_actions, contact_id, created_at
FROM alerts
WHERE created_at > :watermark
ORDER BY created_at ASC
LIMIT :max_bridge_per_tick
```

After successful bridge: `INSERT ... ON CONFLICT (source) DO UPDATE SET last_seen = MAX(batch.created_at), updated_at = NOW()`.

**Alert → signal_queue mapping:**

```python
def map_alert_to_signal(alert: dict) -> dict:
    """Project an alert row into signal_queue's shape.

    signal_queue columns we populate:
      - source: 'legacy_alert'
      - signal_type: derived from alert.source (alert_source → signal_type)
      - matter: alert.matter_slug (may be NULL — pipeline Step 1 can infer)
      - primary_matter: alert.matter_slug (Step 2 may refine)
      - summary: alert.title
      - triage_score: NULL (Step 1 computes)
      - vedana: NULL (Step 5 classifies)
      - hot_md_match: NULL (Step 1 computes)
      - priority: alert.tier (1/2/3 maps to priority int)
      - status: 'pending' (kbl_pipeline_tick claims from here)
      - stage: 'triage'
      - payload: full alert as jsonb (preserves source_id, tags,
        structured_actions, contact_id, body, created_at for Steps 2-6)
    Other columns NULL — filled by pipeline steps.
    """
```

**Error handling per lesson #17 — verify function signatures before writing code snippets:**

- `psycopg2` connection from `kbl/db.py::get_conn()` (verified — returns context-manager yielding a connection). All DB ops wrapped in try/except with `conn.rollback()` on error (lesson #2 pattern).
- Bridge fails loud on ANY insert error (raise; APScheduler logs + retries on next tick). Partial-batch rollback preserved.
- Watermark advances ONLY after full batch commits successfully. No half-advance.

**Cost gate interaction:**

Bridge does NOT invoke Opus. Pure DB → DB. Zero LLM cost. The `kbl_cost_ledger` remains untouched by this module. Opus cost happens downstream in Step 5.

**Rate consideration:** Baker produces ~47 alerts/day; 4-axis filter lets through ~42/day; stop-list removes another ~5-10/day. Bridge sees ~30-35/day passing into signal_queue. At 60s tick interval, each tick processes 0-3 alerts typically. Under spike (morning email burst), `max_bridge_per_tick=50` caps burst behavior safely.

### Key Constraints

- **DO NOT** modify any pipeline step (Steps 1-7). Bridge is a producer upstream of them.
- **DO NOT** touch `mac_mini_heartbeat` — that's a different subsystem.
- **DO NOT** write directly to `kbl_log` from the bridge unless an error rises to ERROR/CRITICAL per R1.S2 invariant.
- **DO NOT** invoke any LLM from the bridge. Pure filtering + mapping. Cost gate stays at zero on this path.
- **DO NOT** duplicate-bridge an alert. `source_id` in signal_queue.payload must include alert's source_id; bridge checks `WHERE NOT EXISTS (SELECT 1 FROM signal_queue WHERE payload->>'alert_source_id' = ...)` before insert. Belt-and-suspenders against watermark drift.
- **Stop-list is intentionally conservative.** Easier to widen via Director's real dismissals during burn-in than to have to undo false positives. Any pattern that could plausibly match a real Director commitment is OUT of the stop-list.
- **Observability invariant:** every tick logs one line to stdout with counts `{read, kept, bridged, skipped_filter, skipped_stoplist, errors}`. APScheduler captures to Render log stream. Director-facing dashboard widget (not built in this brief) can read from those logs later.

### Verification

**Unit tests — new file `tests/test_bridge_alerts_to_signal.py`:**

1. `should_bridge` returns True for each of the 4 axes independently (parametrize across 4 synthetic alerts).
2. `should_bridge` returns False when all 4 axes miss.
3. Stop-list overrides permissive axes: alert with matter_slug + stoplist title pattern → False.
4. Stop-list source (`dropbox_batch`) → False regardless of tier.
5. VIP lookup: alert with contact_id in vip_ids set → True.
6. Mapping: `map_alert_to_signal` produces row shape matching `signal_queue` column set exactly (no extra, no missing non-NULL-required columns).
7. Watermark advances only on successful batch commit (mock `conn.commit` raising → watermark unchanged).
8. Idempotency: running bridge twice on the same alert does NOT create duplicate `signal_queue` row (NOT EXISTS check).

**Integration test (gated on `TEST_DATABASE_URL` via existing `needs_live_pg` fixture from PR #23):**

Insert 10 fake alerts spanning all 4 filter axes + 3 stoplist cases. Run bridge tick. Verify:
- 7-8 land in signal_queue (depending on overlap)
- 3 stoplist cases do NOT land
- Watermark advances to MAX(created_at) of the batch
- Re-running bridge tick inserts 0 new rows (idempotent)

**Production smoke test (post-merge):**

```sql
-- Before:
SELECT COUNT(*) FROM signal_queue;  -- expect 0

-- After first kbl_bridge_tick fires:
SELECT COUNT(*) FROM signal_queue;  -- expect 5-35 (depending on alert rate)
SELECT source, status, COUNT(*) FROM signal_queue GROUP BY source, status;
-- Expect: source='legacy_alert', status='pending' (or 'routed_inbox'/'completed'
-- if kbl_pipeline_tick has already claimed them and processed).

-- After 2 hours:
SELECT COUNT(*) FROM signal_queue WHERE status='completed';
-- Expect: ≥ a handful. Gate 1 of production-flip is now moving.
```

### Trust markers (lesson #40 — "what in production would reveal a bug")

**Three failure modes and how we'd spot them:**

1. **Watermark jams** — bridge advances watermark but INSERT silently fails → next tick skips the alert → permanent miss. Spot: daily `SELECT MAX(created_at) FROM alerts` vs `SELECT last_seen FROM trigger_watermarks WHERE source='alerts_to_signal_bridge'`. Gap > 1h during a day with alert activity = alarm.

2. **Stop-list false positive** — a real Director commitment contains a stop-list keyword and never reaches Cortex. Spot: Day 1 teaching protocol — Director flags "where did X go?" on known-shipped alerts that didn't produce Silver. I batch-review and widen the stop-list to be less aggressive.

3. **Mapping shape drift** — `signal_queue.payload` missing a field that Step 2+ relies on. Spot: `kbl_log` errors during Step 2 resolver with "KeyError: 'source_id'" or similar. If this happens in production, bridge is producing structurally incomplete signals and all Silver from that window is contaminated.

**The meta-pattern (lesson #42):** this is the exact class of bug lesson #42 was coined for — a filter layer between producers and consumers that "works in tests" but has production-only edge cases. Trust markers force us to instrument those edges at deploy.

## Files Modified

**New:**
- `kbl/bridge/__init__.py`
- `kbl/bridge/alerts_to_signal.py` — main module (~250 LOC)
- `tests/test_bridge_alerts_to_signal.py` — unit tests (~200 LOC)

**Modified:**
- `triggers/embedded_scheduler.py` — register `kbl_bridge_tick` job (~20 LOC addition)
- `config/settings.py` — add `BRIDGE_TICK_INTERVAL_SECONDS` env var with default 60 (~3 LOC)

**Migrations:** none. `trigger_watermarks` row created on first run via existing UPSERT pattern.

## Do NOT Touch

- `kbl/pipeline_tick.py` or any of `kbl/steps/step*.py` — pipeline is correct; bridge lives upstream.
- `kbl/layer0.py` — Layer 0 filters signals, bridge produces them. Different layer.
- `memory/store_back.py` — store_back's signal_queue DDL is the source of truth for schema; don't re-create.
- Any `kbl/resolvers/*.py` — resolvers are Step 2 concerns, bridge is pre-Step 1.
- `alerts` table — read-only from the bridge. No UPDATE on alerts from this module.
- `baker_raw_write` MCP tool — used by AI Head and Director. Bridge writes via `kbl/db.py::get_conn()` directly, matching pipeline convention.

## Quality Checkpoints

1. **All tests green** — `pytest tests/test_bridge_alerts_to_signal.py -xvs` pre-merge.
2. **First production tick logs clean counts** — `{read: N, kept: M, bridged: M, skipped_filter: X, skipped_stoplist: Y, errors: 0}`.
3. **signal_queue grows and pipeline_tick picks up** — within 120s of first bridge tick, `SELECT COUNT(*) FROM signal_queue WHERE status IN ('triaging', 'extracting', 'committed')` shows non-zero.
4. **Watermark advances monotonically** — check 3× over 30 min post-deploy.
5. **No duplicate signals** — `SELECT payload->>'alert_source_id', COUNT(*) FROM signal_queue WHERE source='legacy_alert' GROUP BY 1 HAVING COUNT(*) > 1` returns zero rows.
6. **Stop-list + filter audit** — 1 hour post-first-tick, `SELECT tier, matter_slug, title FROM alerts WHERE created_at > NOW() - INTERVAL '2 hours' AND id NOT IN (select (payload->>'alert_id')::int from signal_queue WHERE source='legacy_alert')` — review the skipped set. Every row should match a filter axis miss OR a stoplist entry. Surprise skips = bug.

## Verification SQL

```sql
-- Bridge activity last hour
SELECT
  COUNT(*) FILTER (WHERE source='legacy_alert') AS bridged,
  COUNT(*) FILTER (WHERE source='legacy_alert' AND status='pending') AS pending,
  COUNT(*) FILTER (WHERE source='legacy_alert' AND status='completed') AS completed
FROM signal_queue
WHERE created_at > NOW() - INTERVAL '1 hour';

-- Watermark health
SELECT last_seen, NOW() - last_seen AS gap
FROM trigger_watermarks
WHERE source='alerts_to_signal_bridge';

-- Alerts produced vs bridged last 24h
SELECT
  (SELECT COUNT(*) FROM alerts WHERE created_at > NOW() - INTERVAL '24 hours') AS total_alerts,
  (SELECT COUNT(*) FROM signal_queue WHERE source='legacy_alert' AND created_at > NOW() - INTERVAL '24 hours') AS total_bridged,
  (SELECT ROUND(100.0 * (SELECT COUNT(*) FROM signal_queue WHERE source='legacy_alert' AND created_at > NOW() - INTERVAL '24 hours')
    / NULLIF((SELECT COUNT(*) FROM alerts WHERE created_at > NOW() - INTERVAL '24 hours'), 0), 1) AS bridged_pct;
-- Expected: bridged_pct ≈ 70-80% (~30-35 bridged per ~42 alerts).

-- Stop-list sample (what got filtered)
SELECT tier, title, matter_slug, source
FROM alerts
WHERE created_at > NOW() - INTERVAL '24 hours'
  AND id NOT IN (SELECT (payload->>'alert_id')::int FROM signal_queue WHERE source='legacy_alert' AND payload ? 'alert_id')
ORDER BY created_at DESC
LIMIT 25;
-- Director reviews this list during Day 1 teaching to confirm skips are correct.
```

## Day 1 Teaching Protocol (per `feedback_bridge_day1_teaching.md`)

**Ratified rule:** the bridge is not "done" when it merges. It's "done" when Director has reviewed 20-30 Silver files and the filter has been tuned at least once from that data.

**Protocol:**

1. **T+0 (bridge merges):** AI Head reports to Director the first Silver file the moment it's written to vault (Step 7). Target: within ~4-6 hours of merge, depending on alert rate.
2. **T+6h (first batch):** AI Head surfaces ~5-10 Silver files for Director review. Director flags each: `promote` / `dismiss-noise` / `correct-matter` / `correct-tier` / `wrong-obligor`.
3. **T+12h (batch 2):** AI Head aggregates Director's flags. Identifies patterns: "all 3 dismissals matched pattern X." Proposes stop-list additions or removals.
4. **T+18h (filter v1.1):** AI Head drafts a PR against `kbl/bridge/alerts_to_signal.py` with stop-list updates. B2 reviews. AI Head auto-merges on APPROVE.
5. **T+24h (batch 3):** repeat cycle. Each iteration tightens the filter from real data, not speculation.
6. **T+48-72h (convergence):** residual noise is down to items genuinely hard to mechanically detect. Director makes the call: ship as-is (accept residual noise, let feedback ledger work), OR greenlight `BAKER_PRIORITY_CLASSIFIER_TUNE_1` as the durable root-cause fix.

**This protocol is part of the bridge, not an optional post-script.** AI Head commits to surfacing batches and aggregating patterns on the stated cadence. Failure to do so re-opens the bridge brief — it isn't complete without active teaching.

## Follow-up brief (not this brief)

**`BAKER_PRIORITY_CLASSIFIER_TUNE_1`** — upstream classifier prompt tune. Scope revealed by exploration this session:

- `deadlines` table already has `assigned_to` + `assigned_by` columns (verified). Obligor signal exists; Baker's deadline_cadence just doesn't route on it.
- Three systematic classifier errors surfaced in 2026-04-20 chat: (a) under-tiering real-matter content as T3 (LCG-Aelio tax opinion), (b) over-tiering promo content as T1/T2 (Forbes ticket, Sotheby's), (c) under-tiering matter-important informational as T3 (MO Vienna press mentions, M365 updates).
- Estimated effort: 4-6h (half-day, not the weekend I originally estimated) once Baker's classifier prompt is located + the `assigned_to`/`assigned_by` signal is surfaced to the prompt.

Authoring blocked on 2-3 days of Day 1 teaching data from THIS bridge. Don't draft classifier-tune brief before convergence data is in hand.

## Dispatch plan

- **Single B-code implements the full brief in one PR.** Bridge is architecturally atomic — watermark + filter + mapper + scheduler registration all must land together.
- **Preferred implementer:** B1 (strongest on infrastructure modules this session) once free from SOT_OBSIDIAN_UNIFICATION_1 Phase B.
- **Reviewer:** B2.
- **Expected timeline:** 6-8h implementation + 1h B2 review + auto-merge.
- **Deployment:** Render auto-deploys on merge. `kbl_bridge_tick` fires within 2-4 min of live. First signal_queue row within ~60s after that. Director's first Silver file within ~5-10 min after signal lands (Steps 1-7 pipeline time).

## Lessons captured proactively (for `tasks/lessons.md` after merge + Day 1 teaching cycle)

Placeholders:

- **Lesson #46 — Bridges between two subsystems are their own failure class.** Watermark + mapping shape + idempotency must all be tested independently. Skipping any of the three leaves a time-bomb.
- **Lesson #47 — Stop-lists are brittle and belong at the filter edge, not the classifier.** Stop-lists catch observed noise cheaply but don't fix the classifier producing noise. Pair every stop-list with a scheduled root-cause brief (in this case, `BAKER_PRIORITY_CLASSIFIER_TUNE_1`).
- **Lesson #48 — Day 1 teaching is part of the feature, not a post-ship nicety.** A filter that "ships" but never gets tuned from real dismissals isn't done. Bake the teaching cadence into the brief itself, not a README.

---

*Brief ratified 2026-04-20 by Director's 4-axis filter co-design + stop-list agreement + Day 1 teaching rule ratification + explicit "go ahead" on authoring.*
*Written under /write-brief protocol steps 1-5. Step 6 (capture lessons) to execute after bridge is live + 2-3 day convergence window passes.*
