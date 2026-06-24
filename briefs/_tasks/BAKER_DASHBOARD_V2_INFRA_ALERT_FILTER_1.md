# Baker Dashboard V2 — Infra-Alert Filter 1

Status: PRE-AUTHORIZED / DISPATCHABLE (fire AFTER full verifier drain — do not bridge mid-run)
Date: 2026-06-24
Recommended owner: B3 (built the V2 pipeline activation; owns this code)
Coordinator: AH1 (lead)
Parent brief: `briefs/_tasks/BAKER_DASHBOARD_V2_NOISY_COCKPIT_CONSOLIDATED_1.md`
Harness-V2: applies

## Bottom line

The V2 candidate bridge sends *every* pending alert into the Director's trusted Today feed — including the system's own infra-health alerts (scheduler-stale, sentinel-watchdog, WAHA-session). Those get verified and shown as trusted cards. A shared noise filter already exists in the codebase but the V2 bridge never calls it. Wire it in + add the one missing source.

## Context Contract

- **Surface:** `orchestrator/candidate_ingest.py` (V2 candidate producer) — bridges `alerts` + `deadlines` rows into `signal_candidates`, which the verifier promotes to `verified_items` (the Today feed).
- **Observed (live, 2026-06-24):** of the first 18 trusted `verified_items`, ~7 are infra-health noise. 6 are `Scheduler job 'X' is stale` cards — a source §A-LEAD-0621b already diagnosed as a **cosmetic false alarm** (per-instance advisory-lock artifact, scheduler is alive).
- **Pending-alert source census (live):** `scheduler_job_liveness` = 39, `sentinel_health` = 8, `waha_session` = 1 — all infra, all currently eligible to bridge.
- **Existing asset (REUSE, do not duplicate):** `kbl/bridge/alerts_to_signal.py` already defines `STOPLIST_SOURCES` (frozenset) + `_is_stoplist_noise(alert: dict) -> bool` (source-set check first, then title-regex for marketing/auction/retail noise). The V2 bridge in `orchestrator/candidate_ingest.py` does **not** import or use it.
- **Director-plain why:** so the dashboard stops showing the Director the system talking to itself — every card left is money, legal, or people.

## Task class

Bug / quality fix (noise leak). Deterministic code filter — **no LLM**, no new model calls, no new endpoints, no migration, no new table.

## Engineering Craft Gates

- **Diagnose (applies):** Repro = `SELECT count(*) FROM verified_items WHERE matter_slug='system' OR source_type='alerts' AND <infra source>`. Feedback loop = re-run `bridge_pending_alerts()` after fix, confirm 0 new infra candidates. Hypothesis (confirmed): V2 bridge has no stoplist; root cause is a missing reuse, not a new algorithm.
- **Prototype (N/A):** no UX or state-shape uncertainty — exact filter key (`source`) is known.
- **TDD (applies):** add one vertical unit test on `bridge_alert_to_candidate()` — an infra-source alert returns `created=False`; a real matter alert returns `created=True`. Test the public chokepoint, not internals.

## Implementation

### Fix 1 — add the one missing infra source to the shared stoplist
`kbl/bridge/alerts_to_signal.py`, in `STOPLIST_SOURCES`:

```python
STOPLIST_SOURCES = frozenset(
    [
        "dropbox_batch",
        "cadence_tracker",
        "sentinel_health",
        "waha_silence",
        "waha_session",
        "scheduler_job_liveness",   # NEW: scheduler-liveness = cosmetic false alarm (§A-LEAD-0621b); System Health console (PR #417) is its home, not the Director Today feed
    ]
)
```

### Fix 2 — apply the shared filter in the V2 alert bridge
`orchestrator/candidate_ingest.py`:

(a) The batch SELECT in `bridge_pending_alerts()` (line ~384) does not fetch `source`. Add it:

```python
cur.execute(
    """
    SELECT id, title, body, matter_slug, structured_actions, source
    FROM alerts
    WHERE status = 'pending'
    ORDER BY id DESC
    LIMIT %s
    """,
    (limit,),
)
```

(b) In `bridge_alert_to_candidate(alert: dict)` (line 329), short-circuit before `create_candidate`:

```python
def bridge_alert_to_candidate(alert: dict) -> dict:
    """Bridge one pending ``alerts`` row to a candidate (AC3.1). Idempotent."""
    # Infra-health + marketing/auction noise never reaches the Director Today feed.
    # Reuse the single shared noise definition (DRY — same filter as the V1 signal bridge).
    from kbl.bridge.alerts_to_signal import _is_stoplist_noise
    if _is_stoplist_noise(alert):
        return {"ok": True, "created": False, "skipped_reason": "stoplist_noise"}
    alert_id = alert.get("id")
    # ... unchanged below ...
```

The existing `bridge_pending_alerts` loop already counts a non-`created` result as `skipped` — no loop change needed.

### Fix 3 — one-time cleanup of already-trusted infra cards (ops step, AH1-run AFTER deploy)
The filter is forward-looking; the ~7 infra cards already in `verified_items` persist. AH1 runs ONE dismissal pass post-deploy (not in code, not a migration). Candidate query for AH1 to review-then-dismiss:

```sql
-- REVIEW first (read-only); AH1 confirms set before any state change
SELECT id, matter_slug, source_type, left(claim,70) AS claim
FROM verified_items
WHERE matter_slug = 'system'
   OR claim ILIKE 'Scheduler job %is stale%'
   OR claim ILIKE 'SENTINEL WATCHDOG%'
   OR claim ILIKE 'WAHA SESSION%'
ORDER BY id;
```

## Key Constraints

- **Reuse, do not duplicate.** No new denylist constant in `candidate_ingest.py`. One noise definition, both bridges.
- **Cross-surface effect is INTENDED + must be verified.** Adding `scheduler_job_liveness` to `STOPLIST_SOURCES` also changes the existing `alerts_to_signal.py` consumer. That consumer SHOULD also drop scheduler noise (§0621b confirms cosmetic) — confirm its behavior is unchanged except for the now-filtered infra source. Surface, don't hide, this in the gate request.
- **`conn.rollback()`** already present in the except block — keep it.
- **No model calls.** If anyone proposes an LLM relevance classifier here, reject — this is deterministic.
- **Deadlines path untouched.** `bridge_deadline_to_candidate` is not in scope (deadlines are matter-real).
- **Do not run the bridge mid-drain.** Fire only after the verifier queue is empty so the cleanup pass catches the full infra set in one go.

## Verification

1. **Unit test (new):** `bridge_alert_to_candidate({"id": 1, "source": "scheduler_job_liveness", "title": "SCHEDULER JOB STALE: x"})` → `created is False`, `skipped_reason == "stoplist_noise"`. A matter alert (`source="pipeline"`, real title) → `created is True`.
2. **Existing V1 consumer regression:** run the `alerts_to_signal.py` test suite (or its `_is_stoplist_noise` tests) — green, with scheduler source now also filtered.
3. **Live (post-deploy, AH1):** re-run `bridge_pending_alerts()` → result `bridged` excludes all 48 infra alerts; `SELECT count(*) FROM signal_candidates WHERE raw_source_table='alerts' AND status='awaiting_verification'` shows no infra rows added.
4. **Done = the Today feed contains zero `matter_slug='system'` / scheduler-stale / watchdog / WAHA cards after the Fix-3 cleanup.**

## Files Modified
- `kbl/bridge/alerts_to_signal.py` — add `scheduler_job_liveness` to `STOPLIST_SOURCES`.
- `orchestrator/candidate_ingest.py` — fetch `source` in batch SELECT; apply `_is_stoplist_noise` in `bridge_alert_to_candidate`.
- `tests/` — new unit test for the bridge chokepoint.

## Do NOT Touch
- `bridge_deadline_to_candidate` / deadlines path — matter-real, in scope of selection-engine not this filter.
- `candidate_verifier.py` — the verifier is correct; the leak is upstream at the bridge.
- `outputs/dashboard.py` routes — no route change.
- Any migration file — no schema change.

## Gate plan
1. **G2 (deputy-codex):** runtime correctness + the cross-surface blast-radius (V1 consumer unchanged). Watch for: import cycle (`candidate_ingest` → `alerts_to_signal`), `source`-missing KeyError on alerts with null source.
2. **G3 (deputy):** independent threat/AC pass.
3. **G4 (AH1 /security-review):** low surface (read-path filter, no new external endpoint, no auth change) — expect clean.
4. **POST_DEPLOY_AC_VERDICT v1** on the bus; then AH1 runs Fix-3 cleanup + confirms the feed.

## Done rubric (answer these in the ship report — not "tests passed")
1. Is `scheduler_job_liveness` in `STOPLIST_SOURCES` and is `_is_stoplist_noise` called in the V2 alert bridge? (yes/no + diff)
2. Does the new unit test prove infra-skip + matter-bridge? (paste assertion)
3. Re-run bridge: how many infra candidates created? (must be 0)
4. Is the V1 `alerts_to_signal` consumer behavior confirmed unchanged except the intended scheduler filter? (how verified)
5. Post Fix-3: how many `system`/scheduler/watchdog/WAHA cards remain in the Today feed? (must be 0)
