# BRIEF: WAKE_RESPAWN_BACKLOG_DRAIN_1 — respawned seats must drain unacked backlog; kill the stale-glance wake skip

- **Priority:** P1 (Director-dispatched 2026-07-19 morning, from overnight fleet smoke findings 1+2)
- **Executor:** deputy-codex
- **Complexity:** Medium
- **Estimated time:** ~3h
- **Evidence base:** `briefs/_reports/FLEET_WAKE_SMOKE_2026-07-19.md` rows 1-2; bus #13038-40 (forced-kills), #13112/#13113 (movie-desk refresh)

## Harness V2

- **Context Contract:** inputs = this brief + `briefs/_reports/FLEET_WAKE_SMOKE_2026-07-19.md` + `scripts/cockpit_controller.py` + brisen-lab lifecycle/respawn + snapshot modules; no other repos/libraries. Worker refresh at 50% context.
- **Task class:** production implementation (local controller + brisen-lab service), P1.
- **Done rubric / done-state class:** class GATED-MERGE — done only when (a) Diagnose verdict posted with evidence, (b) all three fixes implemented with new regression tests green + full cockpit suites green, (c) live probes A+B pass, (d) codex gate PASS on exact pushed HEAD(s). Compile-clean ≠ done (Lesson #8).
- **Gate plan:** codex seat gate, topic `gates/wake-respawn-backlog-drain-1`, exact-HEAD verify in clean worktree; lead merges/deploys/re-syncs after PASS.

## Context

Overnight smoke (28 seats): two related wake-loss classes.

**Class A — respawn eats the queued wake.** Daemon forced-kill/refresh (`lifecycle/forced-kill`, `director_refresh_agent`) restarts a seat; the wake for its unacked backlog fired BEFORE/DURING the kill. Fresh session comes up at an empty prompt, never told it has backlog. Observed: movie-desk, researcher (fresh sessions, ctx `--`, $0.000, unacked smoke sitting in mailbox).

**Class B — stale glance blocks re-wake.** `POST /api/sessions/{slug}/wake` skipped `"no unacked"` for movie-desk, origination-desk, publisher, researcher, russo-ai while a direct authenticated `GET /msg/{slug}` (limit=5) showed multiple unacked rows (e.g. movie-desk #13092 + 4 lifecycle msgs). Controller's mailbox state = `LabGlance.read()` → lab `terminals` snapshot, cached `lab_cache_seconds` (scripts/cockpit_controller.py ~940-978). Either the lab snapshot's `unacked_count` lags reality by many minutes, or the glance cache did. Wake decisions built on that number silently no-op.

## Engineering Craft Gates

- **Diagnose (applies, MANDATORY FIRST):** find where the lab snapshot computes `unacked_count` per terminal (brisen-lab repo) and establish why it read 0 for the five seats at ~2026-07-18T23:45Z-00:15Z while `/msg/{slug}` showed unacked rows. Ranked hypotheses: (1) lab snapshot caches per-terminal aggregates on an interval / materialized row not refreshed on insert; (2) snapshot counts only messages newer than a watermark that the forced-kill reset; (3) controller `lab_cache_seconds` too long + burst timing. Probe: insert a test message to a quiet seat, time how long until snapshot `unacked_count` increments. The fix target follows the evidence — do not guess.
- **Prototype:** N/A — seams are known; behavior is deterministic.
- **TDD (applies):** regression tests first at both seams (below) before implementation.

## Fix 1 — lab-side: respawn completion fires a backlog wake

In brisen-lab lifecycle respawn path (forced-kill / `director_refresh_agent` flow that emitted #13112/#13113): after the seat's replacement session registers (or after the respawn completes), if the seat has unacked messages (authoritative DB query, LIMIT 50), enqueue a normal wake for the oldest unacked message via the existing wake path. The lab owns the authoritative mailbox — no glance involved. Respect existing autowake master/disabled-slug gates. Test: simulated respawn with 1 unacked row → exactly one wake event recorded; zero unacked → no wake.

## Fix 2 — controller-side: glance-doubt fallback on wake skip

In `scripts/cockpit_controller.py` wake handler (skip point returning `"no unacked"` ~line 613-616 / 785-787): before returning the skip, force a glance refresh (bypass cache: add a `force_refresh()` or expire `_expires_at`) and re-check once. If the lab snapshot itself is the stale layer (per Diagnose), fix there and keep this fallback as belt-and-suspenders. The just-merged per-message dedupe + 60s seat floor (main @8d8a9413) already bound the blast radius of extra wakes — do not weaken them. Test: stale-cache scenario (mock glance returning 0, fresh returning 1) → wake fires after refresh.

## Fix 3 — controller-side: periodic backlog sweep (self-heal)

Background task in the controller (asyncio loop, every `COCKPIT_BACKLOG_SWEEP_SECONDS`, default 600, env-tunable, 0=off): for each manifest seat with `session_up`, not `is_working`, `unacked_count > 0` and oldest unacked age > sweep interval → call the existing internal wake path (same guards/dedupe/floor; audit `skipped="sweep"` vs sent). This catches any future wake-loss class without manual lead nudging. All lab/HTTP calls wrapped try/except; a sweep-cycle failure logs and continues (never crashes the controller).

## Key Constraints

- Do NOT touch verified-submit, park recovery, untagged-human guards, dedupe windows, or seat floor semantics (codex PASS #13117 scope).
- No new secrets; reuse existing controller settings pattern.
- Lab-side change must not wake `BRISEN_LAB_AUTOWAKE_DISABLED_SLUGS` members or fire when `master_enabled` false.

## Verification

1. Full cockpit suites green: `pytest tests/test_cockpit_wake.py tests/test_cockpit_controller.py -q` + new tests.
2. Live probe A (respawn): refresh-cycle a quiet seat carrying 1 unacked test msg → seat wakes and acks without manual nudge.
3. Live probe B (sweep): leave a test msg unacked on an idle seat > sweep interval → sweep wakes it; audit row shows the sweep source.
4. `py_compile` + `git diff --check` clean.

## Files Modified
- `scripts/cockpit_controller.py` (+ tests) — fixes 2, 3
- brisen-lab lifecycle/respawn module per Diagnose — fix 1 (separate PR, name it in the report)

## Do NOT Touch
- `scripts/cockpit_bridge_agent.py`, bridge/lab proxy routes — unrelated (COCKPIT_IN_LAB_BRIDGE_1 scope).
- Wake dedupe/floor constants — just shipped, live.

## Gate + Done

Codex gate on exact pushed HEAD(s), topic `gates/wake-respawn-backlog-drain-1`. No merge/deploy — lead owns those. Post-merge lead re-syncs `~/Library/Application Support/baker/cockpit/` + restarts controller.
