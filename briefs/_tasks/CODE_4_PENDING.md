---
status: SHIPPED_AWAITING_GATES
pr: 442
head_sha: 8a168eb
shipped_at: 2026-07-01
brief_id: BOX5_TICKETING_RUNNER_1
to: b4
from: lead
dispatched_by: cowork-ah1
dispatched_at: 2026-07-01
branch: box5-ticketing-runner-1
reply_target: cowork-ah1 (bus) for ship report; gate verdicts to lead
effort: medium-high (builder — concurrency/idempotency/error-routing); codex G3 effort medium (focus the reliability matrix, NOT xhigh)
task_class: EXTEND existing airport_ticketing run_tick (per-source cursor + FOR UPDATE SKIP LOCKED claim + status-guarded single terminal write); ships DARK behind 2 kill-switches
gate_plan: G1 builder self-check incl. the 8-case idempotency/concurrency/error-routing test matrix (write FIRST) -> codex G3 (bus, effort medium, focus reliability) -> lead G4 /security-review -> lead merge. Dark ship, no activation. C MUST merge before D/E dispatch (they plug into C's classify hook in the same file).
full_brief: briefs/BRIEF_BOX5_TICKETING_RUNNER_1.md
---

# BOX5_TICKETING_RUNNER_1 — extend run_tick into the Box 5 ticketing runner (Build Order 5)

## Read this first
Complete copy-pasteable impl in **`briefs/BRIEF_BOX5_TICKETING_RUNNER_1.md`** (492 lines, on main, committed alongside). Implement exactly. Brief authored + verifier-checked by cowork-ah1; do not redesign. Prereqs all merged: #439 registry, #440 receipt/TTL, #441 terminal schema.

## Context (one paragraph)
Box 5 Build Order 5 — the runner. EXTEND the EXISTING `airport_ticketing` run_tick (NO new scheduler/lease/cursor table; single-replica still inherited from lease 8800100). Adds: per-source cursor via existing `trigger_watermarks` (key `airport_ticketing:email`, replaces today's constant 48h re-scan); `FOR UPDATE SKIP LOCKED` row claim (intra-tick safety); a status-guarded SINGLE terminal write (`UPDATE ... WHERE id=%s AND terminal_status IS NULL` — the ONLY terminal-write path, so re-run = 0 rows, no double-write); deterministic clears ONLY (DUPLICATE via dedup_key, REJECT_NOISE via automated-sender/no-keyword), everything else → TICKET (full desk review). NO project-number lane (D), NO manifest lane (E), NO VISIBLE_HOLD.

## Scope (locked — do NOT exceed)
- Extend run_tick in `orchestrator/airport_ticketing_bridge.py`. Writes terminal_status/terminal_reason/processed_at/terminal_outcome_written_at/raw_source_*.
- Kill-switches: master = existing `AIRPORT_TICKETING_BRIDGE_ENABLED` (dark); NEW `BOX5_FAST_LANE_ENABLED` (default false) → routes everything to safe-default TICKET while still clearing backlog (freeze a misroute by flag flip, no deploy).
- Errors NEVER auto-clear (a throw must be distinguishable from a no-match; error → leave terminal_status NULL + count).
- Per-tick stats + stuck-arrivals gauge (terminal_status IS NULL AND source_received_at < NOW()-30min).
- Additive/extend only; do NOT add D's project-number lane or E's manifest lane. Parameterized SQL, LIMIT on selects, rollback in except.

## Acceptance criteria
- AC1: `py_compile` clean; `bash scripts/check_singletons.sh` OK.
- AC2: the 8-case test matrix (idempotency, concurrency/SKIP LOCKED, error-routing, cursor advance, dedup, noise-reject, safe-default-TICKET, stuck-gauge) — all pass (live-PG auto-skip without TEST_DATABASE_URL; CI live).
- AC3: re-run over an already-terminal row = 0 rows updated (status-guarded single write proven).
- AC4: `BOX5_FAST_LANE_ENABLED=false` → every arrival → TICKET (no deterministic clearing); flag true → DUPLICATE/REJECT_NOISE clear deterministically.
- AC5: a raised exception in classify leaves terminal_status NULL (NOT cleared) + increments the error count.

## Done rubric
Build-done = PR merged + AC1-AC5 green. Ships DARK (master flag off). NO activation this build — that's a later Director GO. C must merge before D/E dispatch.

## Context-economy (HARD — no auto-compaction)
- Read ONLY the files in the brief's Context Contract. Output to /tmp; tails only. Context >70%: commit, push, bus handoff, STOP. Reminder: a prior Box-5 job (PR #440) passed the builder's own self-check but codex caught 2 P1 crash-path bugs — write the reliability test matrix FIRST and make it assert real crash/concurrency/error paths, not happy-path.
