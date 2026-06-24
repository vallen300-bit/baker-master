# B3 Ship Report — BAKER_DASHBOARD_V2_INFRA_ALERT_FILTER_1

- **Brief:** `briefs/_tasks/BAKER_DASHBOARD_V2_INFRA_ALERT_FILTER_1.md`
- **PR:** #419 — `b3/baker-dashboard-v2-infra-alert-filter-1` → `main`
- **Commit:** c9da449
- **Dispatched by:** lead (verbal fire 2026-06-24; brief was PRE-AUTHORIZED / DISPATCHABLE, recommended owner B3)
- **Task class:** Bug / quality fix (noise leak). Deterministic filter — no LLM, no endpoint, no migration.

## Done rubric (answers, not "tests passed")

1. **Is `scheduler_job_liveness` in `STOPLIST_SOURCES` and is `_is_stoplist_noise` called in the V2 alert bridge? (yes/no + diff)**
   Yes / Yes.
   - `kbl/bridge/alerts_to_signal.py`: `scheduler_job_liveness` added to `STOPLIST_SOURCES`.
   - `orchestrator/candidate_ingest.py`: `bridge_alert_to_candidate` now imports `_is_stoplist_noise` (function-local) and short-circuits before `create_candidate`, returning `{"ok": True, "created": False, "skipped_reason": "stoplist_noise"}`. SELECT in `bridge_pending_alerts` now fetches `source`.

2. **Does the new unit test prove infra-skip + matter-bridge? (paste assertion)**
   Yes — `tests/test_candidate_ingest.py`:
   - `test_bridge_alert_skips_infra_stoplist_noise`: `create_candidate` monkeypatched to `pytest.fail` (proves no DB / no call); asserts `created is False` and `skipped_reason == "stoplist_noise"` for `source="scheduler_job_liveness"`.
   - `test_bridge_alert_bridges_real_matter_alert`: `source="pipeline"`, real title → `created is True`, `raw_source_table == "alerts"`, `raw_source_id == "42"`.

3. **Re-run bridge: how many infra candidates created? (must be 0)**
   Not run live (no DB in clone; the live re-run is the post-deploy AH1 step, and the brief bars running the bridge mid-drain). Unit-level proof stands: any alert whose `source` ∈ `STOPLIST_SOURCES` returns `created=False` before `create_candidate`. Census in the brief (scheduler_job_liveness=39, sentinel_health=8, waha_session=1 = 48 infra alerts) → all now short-circuit.

4. **Is the V1 `alerts_to_signal` consumer behavior confirmed unchanged except the intended scheduler filter? (how verified)**
   Verified by green regression: `tests/test_bridge_alerts_to_signal.py` + `tests/test_alerts_to_signal_cortex_dispatch.py` pass with the new source added. No existing V1 test expected `scheduler_job_liveness` to bridge, so the only behavior change is the intended drop of scheduler noise (cosmetic, §0621b). The V1 consumer reaches `_is_stoplist_noise` first in `should_bridge` (line 336), so scheduler alerts now return `should_bridge=False`.

5. **Post Fix-3: how many `system`/scheduler/watchdog/WAHA cards remain in the Today feed? (must be 0)**
   Pending — Fix-3 is the AH1-run post-deploy dismissal pass (read-then-dismiss, not code). This PR is forward-looking; it does not retroactively dismiss the ~7 cards already in `verified_items`.

## Verification (literal pytest)

```
python3.12 -m pytest tests/test_candidate_ingest.py
  -> 20 passed, 13 skipped

python3.12 -m pytest tests/test_bridge_alerts_to_signal.py \
  tests/test_alerts_to_signal_cortex_dispatch.py \
  tests/test_dashboard_v2_workers.py tests/test_bridge_pipeline_integration.py
  -> 66 passed, 6 skipped
```

## Files modified
- `kbl/bridge/alerts_to_signal.py` — `+scheduler_job_liveness` in `STOPLIST_SOURCES`.
- `orchestrator/candidate_ingest.py` — fetch `source` in batch SELECT; apply `_is_stoplist_noise` short-circuit in `bridge_alert_to_candidate`.
- `tests/test_candidate_ingest.py` — 2 new chokepoint tests.

## Gate plan (from brief)
G2 deputy-codex (runtime + cross-surface blast radius) → G3 deputy (threat/AC) → G4 AH1 `/security-review` + merge → POST_DEPLOY_AC_VERDICT v1, then AH1 runs Fix-3 cleanup.

## Notes for lead
- No `source`-null KeyError risk: `_is_stoplist_noise` uses `alert.get("source")` and `.get("title") or ""`.
- No import cycle: `alerts_to_signal` does not import `candidate_ingest`; the import is function-local regardless.
- Live re-run + Fix-3 cleanup gated on verifier-queue drain per brief — that timing is AH1's to fire.
