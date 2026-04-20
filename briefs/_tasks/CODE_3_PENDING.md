# Code Brisen #3 — Pending Task

**From:** AI Head
**To:** Code Brisen #3 (fresh terminal tab)
**Task posted:** 2026-04-20 (afternoon, post-bridge-ship)
**Status:** OPEN — Bridge review (reassigned from B2)

---

## Task: Review PR #27 (baker-master) — ALERTS_TO_SIGNAL_QUEUE_BRIDGE_1

You accepted this review per your standing-down note ("bridge-review reroute if B2 is bottlenecked"). B2 is taking Phase B; you take bridge. Parallelizing doubles Gate 1 throughput.

**PR:** https://github.com/vallen300-bit/baker-master/pull/27
**Branch:** `alerts-to-signal-queue-bridge-1`
**Head commit:** `b18226e`
**Shipped by:** B1
**Scope:** Pure DB→DB bridge — `kbl/bridge/alerts_to_signal.py` (~330 LOC) + `kbl_bridge_tick` scheduler job + 38-case test suite

Brief reference: `briefs/BRIEF_ALERTS_TO_SIGNAL_QUEUE_BRIDGE_1.md` at commit `d449b6c`. Read brief end-to-end before reviewing — the 4-axis filter + stop-list logic is the load-bearing part.

---

## B1's three flagged deviations (you decide — each defensible, but reviewer call)

1. **Priority as TEXT (`urgent`/`normal`/`low`), not int.** Justification: `signal_queue.priority` column is TEXT; ORDER BY DESC on TEXT lex order happens to give `urgent > normal > low` alphabetically. Risk: adding a 4th priority later ("critical") could break ordering if inserted mid-lex. Check: does mapping doc this assumption? Is there a unit test proving ORDER BY lex matches intended severity order for the 3 current values?

2. **Auction stop-list split out of regex alternation.** Justification: Python `re` can't express brief's "Brisen anywhere in vicinity" pattern with fixed-width lookbehind alone. B1 split into two patterns. Check: does the split preserve brief's negative-lookaround semantics? Unit tests cover both paths?

3. **Skipped `config/settings.py` modification.** Justification: matched existing inline-read pattern used by `KBL_PIPELINE_TICK_INTERVAL_SECONDS`. Check: is `BRIDGE_TICK_INTERVAL_SECONDS` read with same `os.getenv(..., default)` shape + 30s floor enforced? Consistency with sibling scheduler jobs?

All three are architectural judgment calls, not errors. Brief ratification authorized reasonable deviation with paper trail. Your call.

## Verdict focus (beyond deviations)

- `should_bridge()` pure function: 4 axes evaluated independently + stop-list overrides permissive axes?
- `map_alert_to_signal()`: mapping shape matches signal_queue schema exactly (no extra/missing columns)?
- Watermark row: `source='alerts_to_signal_bridge'`? Rollback-safe (watermark updated ONLY after successful INSERT)?
- Idempotency: rerunning bridge tick with no new alerts is a no-op? Test exists?
- 38 tests: every axis covered + all 13 stop-list patterns + mapping shape + idempotency + watermark rollback?

**Reviewer-separation:** B1 implemented. You shipped unrelated helper v2 in parallel. Clean to review.

Report to `briefs/_reports/B3_pr27_bridge_review_20260420.md` in baker-master. APPROVE / REDIRECT / REQUEST_CHANGES. AI Head auto-merges on APPROVE per Tier A.

## After this

If APPROVE + merge: Day 1 teaching fires. AI Head takes it from there — you stand down for SOT Phase C (gated on Phase B merge).
If REDIRECT/REQUEST_CHANGES: B1 recalled.

Close tab after report shipped.
