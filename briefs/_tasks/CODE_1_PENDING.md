# Code Brisen #1 — Pending Task

**From:** AI Head
**To:** Code Brisen #1 (fresh terminal tab)
**Task posted:** 2026-04-20 (midday, post-SOT-Phase-B ship)
**Status:** OPEN — ALERTS_TO_SIGNAL_QUEUE_BRIDGE_1 implementation

---

## Task: ALERTS_TO_SIGNAL_QUEUE_BRIDGE_1 — Implement the alerts → signal_queue bridge

Brief: `briefs/BRIEF_ALERTS_TO_SIGNAL_QUEUE_BRIDGE_1.md` at commit `d449b6c` in baker-master. Read end-to-end before starting — the brief is self-contained with all 4-axis filter logic, stop-list patterns, mapping shape, verification SQL, and Day 1 teaching protocol.

**Target PR:** against `baker-master`. Branch: `alerts-to-signal-queue-bridge-1`. Base: `main`. Reviewer: B2.

### Why this matters now

Cortex T3 shadow mode went live 2026-04-20 at ~04:00 UTC. Scheduler running, pipeline_tick registered, dashboard clean. But `signal_queue` has stayed empty ever since — no producer code path creates rows from raw sentinel data. `kbl_pipeline_tick` wakes every 120s, finds nothing, exits.

This brief closes the seam. **Gate 1 of production-flip (≥5-10 clean signals through Steps 1-7) cannot move until this ships.** It is the single highest-leverage piece of work in the Cortex T3 queue right now.

### Scope summary (full detail in brief)

- New module `kbl/bridge/alerts_to_signal.py` with `run_bridge_tick()` entrypoint
- Pure-function `should_bridge()` — 4-axis selector (tier + matter + VIP + promote-type) + stop-list
- Pure-function `map_alert_to_signal()` — project alerts row into signal_queue shape
- Watermark row in `trigger_watermarks` (`source='alerts_to_signal_bridge'`)
- APScheduler job `kbl_bridge_tick` registered in `triggers/embedded_scheduler.py` at 60s default (env: `BRIDGE_TICK_INTERVAL_SECONDS`)
- Unit tests `tests/test_bridge_alerts_to_signal.py` — 8 cases covering each axis, stop-list override, idempotency, watermark safety, mapping shape
- Integration test (TEST_DATABASE_URL-gated via existing `needs_live_pg` fixture)
- Zero LLM calls. Zero cost-gate interaction. Pure DB → DB.

### Hard constraints (from brief §Key Constraints)

- **DO NOT** modify `kbl/pipeline_tick.py` or any `kbl/steps/step*.py`. Pipeline is correct; bridge is upstream.
- **DO NOT** invoke any LLM from the bridge. Filter + map. Nothing else.
- **DO NOT** duplicate-bridge — `NOT EXISTS` check on `payload->>'alert_source_id'` belt-and-suspenders against watermark drift.
- **Watermark advances ONLY after full batch commits.** Partial-batch rollback mandatory.
- **Stop-list is conservative.** Any pattern that could plausibly match a real Director commitment stays OUT. Easier to widen from real dismissals than to undo a false positive.

### Acceptance criteria (from brief §Quality Checkpoints)

1. All unit tests green (`pytest tests/test_bridge_alerts_to_signal.py -xvs`)
2. First production tick logs `{read, kept, bridged, skipped_filter, skipped_stoplist, errors}` with `errors=0`
3. `SELECT COUNT(*) FROM signal_queue WHERE source='legacy_alert'` non-zero within 2 minutes of deploy
4. `kbl_pipeline_tick` picks up bridged signals within 120s (status flips from `pending` through pipeline stages)
5. No duplicate signals — verification SQL in brief
6. Watermark advances monotonically (3 checks over 30 min)

### Trust markers (brief §Trust markers)

Three failure modes. Code in a way each is spottable:

1. Watermark jam (silently skips alerts) — spot via daily `MAX(alerts.created_at)` vs `trigger_watermarks.last_seen` diff
2. Stop-list false positive (real commitment dropped) — Day 1 teaching catches it
3. Mapping shape drift (missing payload field breaks Step 2) — `kbl_log` errors surface immediately

### Day 1 teaching protocol

**The bridge is not done when it merges** — it's done after Director reviews 20-30 Silver files and the filter is tuned at least once from that data. See brief §Day 1 Teaching Protocol. AI Head owns the batch-review + stop-list-tuning cadence post-merge; your scope ends at merge.

### Output

Ship PR, ping B2 for review. AI Head auto-merges on APPROVE. Expected 6-8h.

**After merge:** you're off this work. SOT Phase D (MCP bridge for Cowork — brief §Fix/Feature 4) will need a sub-brief from AI Head first before it dispatches. You stand down until that sub-brief lands.
