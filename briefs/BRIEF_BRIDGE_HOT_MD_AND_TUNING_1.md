# BRIEF: BRIDGE_HOT_MD_AND_TUNING_1

**Parent brief:** ALERTS_TO_SIGNAL_QUEUE_BRIDGE_1 (Day 1 teaching feedback + hot.md axis)
**Status:** RATIFIED 2026-04-20 by Director
**Estimated effort:** 4-5h implementation + review cycle
**Assignee:** B1 (primary — bridge codepath + new scheduler job)
**Reviewer:** B3 (familiar with bridge internals from the Phase D review that just cleared)
**PR pair:** baker-master (code) + baker-vault (initial hot.md scaffold + OPERATING.md for AI Dennis context)

---

## Why

Day 1 teaching produced the first actionable feedback from the bridge:

- **Precision ran at 40%** (4/10 correct promotes, 5/10 noise, 1/10 duplicate) on Batch #1.
- **Root cause of the noise is matter-mis-tagging upstream** (classifier over-matches RSS articles to Brisen matters — e.g. "cigar market" → Austrian Tax, "phone scams" → Vienna Financing). Fully fixing it is `BAKER_PRIORITY_CLASSIFIER_TUNE_1` territory, still parked waiting for 2-3 days of dismissal data.
- **Root cause of the dup is a bridge idempotency race** — two ticks processed the same alert 625ms apart; the `NOT EXISTS (alert_id OR alert_source_id)` guard passed both times because no advisory lock serialized the read-insert cycle.
- **Meanwhile, Director's actual weekly priorities don't have a mechanism to push signals through.** Matter-tag axis is too noisy to double down on; we need a strict-signal Director-curated axis.

This brief bundles all four fixes into one codepath because they all touch `kbl/bridge/alerts_to_signal.py`.

---

## Fix / Feature

### 1. hot.md integration — 5th axis in `should_bridge()`

**File:** `kbl/bridge/alerts_to_signal.py::should_bridge()`

Add a 5th axis evaluated alongside priority-tier / matter / VIP / promote-type:

- **Axis 5: `hot_md_match`** — alert content (title + body, case-insensitive) matches any non-empty, non-comment line in `_ops/hot.md`. If match → promote + record the matched line to new column `signal_queue.hot_md_match` (TEXT).

**Semantics:** any single axis true → promote (OR-gate, unchanged). Stop-list still overrides permissive axes (unchanged).

**Why 5th axis:** Director-curated. Strict signal. Gives Director a weekly lever without code changes.

**hot.md parse rules:**
- Lines starting with `#` → comment, ignore.
- Empty lines → ignore.
- Leading `-` or `*` (bullet markers) stripped.
- Each remaining line is one pattern. Case-insensitive substring match against `alert.title || ' ' || alert.body`.
- Pattern length < 4 chars → ignored (prevents "RE" matching every real-estate email).

### 2. hot.md file scaffold (baker-vault PR)

**Path:** `baker-vault/_ops/hot.md`

**Contents** (initial seed — Director overwrites weekly):

```
# Hot.md — Director's current-week priorities
# Baker's bridge uses this to boost signals. Update every Saturday morning
# (Baker will nudge you via WhatsApp). One priority per line, plain English,
# 4+ character phrases. Comments (lines starting with #) are ignored.
#
# Format examples:
#   Hagenauer                            (matter keyword)
#   Oskolkov                             (person)
#   final account                        (multi-word phrase, case-insensitive)
#   SNB                                  (specific institution/acronym)
#
# DO NOT put personal secrets here. This file sits in baker-vault (read-only
# on Render via the Phase D MCP bridge); Cowork AI Dennis can read it too.

# Active priorities (week of YYYY-MM-DD):
# (blank — overwrite with this week's focus)
```

### 3. Stop-list patterns from Batch #1

**File:** `kbl/bridge/alerts_to_signal.py` (stop-list constant).

Add to existing stop-list (Director-ratified, each tied to a Day 1 dismissal):

| Pattern | Reason (Director's flag) |
|---|---|
| `cigar market` / `luxury cigar` | Batch #1 #9: Austrian Tax & Corporate mis-match |
| `phone scam` / `phone scams` / ` scam ` / ` scams ` | Batch #1 #10: Financing mis-match |
| `fuel price` / `fuel tax` | Batch #1 #5 + #7: energy policy noise |
| `energy policy` | Batch #1 #7: Austrian Tax & Corporate mis-match |
| `retail market update` / retail-chain turnover (TK Maxx / Adler patterns) | Batch #1 #6: German Property Tax mis-match |

Each pattern goes in with a comment citing the dismissal ID — audit trail for the stop-list's growth.

### 4. Idempotency race fix

**File:** `kbl/bridge/alerts_to_signal.py::run_bridge_tick()`.

Today: two ticks 625ms apart both read `alerts WHERE created_at > watermark`, both pass `NOT EXISTS` check, both INSERT. Same alert → duplicate rows.

**Fix:** wrap the tick's read-filter-insert cycle in a Postgres advisory lock:

```
SELECT pg_try_advisory_lock(:lock_key)  -- lock_key = hash('alerts_to_signal_bridge')
-- if lock not acquired: skip this tick, log and exit
-- if acquired: do work, then pg_advisory_unlock at end
```

Alternative (if advisory lock has operational drawbacks): APScheduler `max_instances=1` + `coalesce=True` on the `kbl_bridge_tick` job. Simpler but relies on APScheduler hygiene; advisory lock is DB-enforced.

**Recommendation in brief:** advisory lock. Survives scheduler restarts mid-tick; survives multi-pod deploys if we ever scale Render horizontally.

**Test:** simulate concurrent tick invocation via `asyncio.gather(tick, tick)` on TEST_DATABASE_URL — second tick must no-op, not insert duplicates.

### 5. Saturday morning hot.md nudge

**File:** `triggers/embedded_scheduler.py` — new APScheduler job.

- Job name: `hot_md_weekly_nudge`
- Cron: `0 6 * * SAT` (06:00 UTC = 07:00 CET / 08:00 CEST, Saturday) — Geneva morning
- Action: send WhatsApp message to Director **using the existing helper `outputs/whatsapp_sender.py`** — do NOT introduce a parallel WAHA call pattern. Message body:
  ```
  Saturday hot.md refresh.
  Edit baker-vault/_ops/hot.md with this week's focus areas. Baker syncs within 5 min; matches boost signal priority through the bridge.
  ```
  Keep it short, action-oriented, substrate-voice. No pleasantries, no "good morning" — per §9 operating rule #4 ("alerts are rare and earned, not chatty").
- No confirmation required; fire-and-forget. If WAHA is down, log + swallow (substrate-push contract: don't block on delivery).

Env var: `HOT_MD_NUDGE_ENABLED` (default `true` — allows quick disable without redeploy).

**Forward integration (documented, NOT in scope for this brief):** once `BRIEF_MORNING_DIGEST_FANOUT_1` ships post-Cortex-3T, this standalone scheduler job retires and the hot.md reminder becomes a section inside Saturday's morning digest. Per §9 operating rule #3 ("morning digest is the single highest-leverage artefact"), substrate pushes consolidate there rather than proliferate as separate cron jobs. Until then, the standalone job is the pragmatic near-term vehicle — WAHA is the only substrate fanout channel live today.

---

## Schema changes

**New column:** `signal_queue.hot_md_match TEXT NULL` — stores the matched hot.md line when axis 5 fired (NULL if other axis fired). Allows downstream analytics ("which hot.md entries are actually firing?").

Migration: `migrations/20260420_signal_queue_hot_md_match.sql`. Applied by `MIGRATION_RUNNER_1` on deploy.

---

## Tests

- `tests/test_bridge_hot_md.py`:
  - Empty hot.md → axis 5 never fires.
  - hot.md with `Hagenauer` + alert "Email about Hagenauer settlement" → match; `hot_md_match` = `Hagenauer`.
  - Short pattern (`RE`) → ignored, no false-positive.
  - Comment line (`# focus this week`) → ignored.
  - Bullet-stripped (`- SNB`) → matched as `SNB`.
- `tests/test_bridge_idempotency_race.py`:
  - Two concurrent ticks → one inserts, one no-ops (via advisory lock).
- `tests/test_bridge_stop_list_additions.py`:
  - Each new stop-list pattern tested against a realistic mock alert from Batch #1.
- `tests/test_hot_md_weekly_nudge.py`:
  - Saturday 06:00 UTC trigger → WhatsApp send called with expected body.
  - WAHA down → log + swallow, no exception propagates.

---

## Pre-merge verification (new — per lesson from Phase D review)

Before B3 merges, B1 must demonstrate via the ship report:

1. `migrations/` file applied cleanly in a fresh TEST_DATABASE_URL (no `column already exists` errors).
2. Local dry-run of bridge tick against staging alerts with a sample `_ops/hot.md` → expected promote pattern, `hot_md_match` column populated.
3. Advisory lock proven via concurrent-tick test.
4. `hot_md_weekly_nudge` job shows up in APScheduler registry with correct cron string.

(Template proposal: AI Head adds a §Pre-merge verification to the brief template per B3's N3 nit from Phase D.)

---

## Key constraints

- **hot.md is Director-curated, never classifier-written.** No code path writes to `_ops/hot.md`. The Saturday nudge prompts Director to edit; Baker never edits itself.
- **Stop-list additions are additive only.** Never remove an existing stop-list pattern in this PR; that's a separate Director-gated decision.
- **Advisory lock key must be stable.** Use `hashtext('alerts_to_signal_bridge')` or a hardcoded int constant; do NOT compute from a mutable string.
- **Short-pattern floor.** Enforce 4-char minimum on hot.md entries to prevent catastrophic match cascades ("EU" → everything).

---

## Out of scope

- Multi-tier hot.md (T1/T2/T3 within hot.md itself). Today: one tier, binary match.
- Regex-support in hot.md. Substring only. Regex is a separate brief if ever needed.
- Historical backfill of `hot_md_match` for the 10 Batch #1 rows — they stay NULL; new signals going forward get populated.
- Classifier-tune fixes (`BAKER_PRIORITY_CLASSIFIER_TUNE_1`) — still waiting on more dismissal data.

---

## Verification (post-deploy)

1. Add a line to `_ops/hot.md`: `test-hot-md-axis`
2. Wait 5 min for vault mirror to pick it up
3. Check `mcp__baker__baker_vault_read({path: "_ops/hot.md"})` from any session — content reflects the edit
4. Monitor `signal_queue` for the next bridge tick with an alert matching `test-hot-md-axis` → should promote with `hot_md_match='test-hot-md-axis'`

---

## Day 2 teaching protocol

- Immediately after merge, AI Head surfaces Batch #2 (pre-flagged — Director confirms/overrides only) per the new workflow.
- Director's edits of `_ops/hot.md` get committed to baker-vault by AI Head (Tier B — small doc edits authorized per routine).
- Within 5 min of each edit, bridge sees new patterns.
