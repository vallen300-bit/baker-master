---
status: SHIPPED_AWAITING_GATES
pr: 443
head_sha: 39671d6
shipped_at: 2026-07-01
brief_id: BOX5_HARD_FAST_LANE_1
to: b4
from: lead
dispatched_by: cowork-ah1
dispatched_at: 2026-07-01
branch: box5-hard-fast-lane-1
ship_note: "39671d6 — hard fast lane between C's (e)/(f); adapted to C's MERGED done/contiguous structure (tuple _claim, bus_failed pre-handled). 10/10 rubric green. 21 registry + 20 box5 (14 C no-regression + 6 D) + 39 airport tests GREEN live-PG. Dark behind BOX5_FAST_LANE_ENABLED; seed aukera-corrected but un-run. Flags: VISIBLE_HOLD grep=1 is BRIEF-B pre-existing comment (D writes 0); hard-lane error = retry-next-tick per shared-txn rollback. Ship report -> cowork-ah1; awaiting codex G3."
base_note: branch off main @ 86ae607 or later (contains C's #442 merge — write_terminal_status/_claim_for_terminal/fast_lane_enabled all live)
reply_target: cowork-ah1 (bus) for ship report; gate verdicts to lead
effort: medium (builder — surgical branch + pure helper; cost is the binding/conflict/error test matrix); codex G3 effort medium (focus regex-only-never-clears + binding-mandatory + error-never-FAST_TICKET, NOT xhigh)
task_class: ADDITIVE decision logic + net-new pure helper + seed slug fix. One new precedence tier in C's run_tick between (e) DUPLICATE and (f) safe-default TICKET; one net-new pure-regex extract_project_codes() in kbl/project_registry_store.py (reuse _NUMBER_RE, NO DB); one new fast_ticket counter + stats key; two one-line aukera seed corrections (+ 1 breaking test assertion). No schema migration, no new job/lock/table.
gate_plan: G1 builder self-test (pytest test_project_registry.py incl. new pure-regex + flipped seed assertion + test_box5_ticketing_runner.py no-regression; py_compile both files) -> codex G3 (bus, effort medium) -> lead G4 /security-review -> lead merge. Ships DARK behind BOX5_FAST_LANE_ENABLED (default false). SEED STAYS UN-RUN until Director GO — D corrects the slug literal only; running scripts/seed_bb_pilot_registry.py is a separate gated step.
full_brief: briefs/BRIEF_BOX5_HARD_FAST_LANE_1.md
prev_merged: BOX5_TICKETING_RUNNER_1 (C) MERGED as PR #442 (squash 86ae607); G3 PASS after 2 re-gate rounds (4 P1s caught+fixed), G4 /security-review CLEAN.
---

# BOX5_HARD_FAST_LANE_1 — project-number hard fast lane (Build Order 6)

## Read this first
Complete copy-pasteable impl in **`briefs/BRIEF_BOX5_HARD_FAST_LANE_1.md`** (on main, committed alongside). Implement exactly. Brief authored + verifier-checked by cowork-ah1; do not redesign. **C (#442) is MERGED** — its helpers exist on main (verified: write_terminal_status / _claim_for_terminal / fast_lane_enabled all present). Prereqs #439 (resolvers), #440 (receipt/TTL), #441 (FAST_TICKET in the 6-state CHECK) all merged. Locate C's actual `(e)`/`(f)` blocks in the MERGED `orchestrator/airport_ticketing_bridge.py` (the brief's `brief_c_draft.md` line refs were the pre-merge draft — grep the real file).

## Context (one paragraph)
Box 5 Build Order 6 — the PROJECT-NUMBER HARD FAST LANE. Insert a new precedence tier BETWEEN C's `(e)` DUPLICATE clear and C's `(f)` safe-default TICKET. On a clean clear write `terminal_status='FAST_TICKET'` via C's `write_terminal_status`; on ANY miss/conflict/exception fall through to C's unchanged TICKET path. Consumes #439 registry: `resolve_project_number(text)` (active-filtered, deterministic single-return) + `resolve_by_participant('email', sender)`. Net-new pure `extract_project_codes(text)` (reuse `_NUMBER_RE`, no DB) runs FIRST: >1 distinct code → cross-matter CONFLICT → TICKET (never fast-board); exactly 1 → resolve; 0 → no code. Also folds the Director-ratified **aukera** seed correction (both hardcoded `annaberg` seed sites → `aukera`; seed stays gated/un-run).

## Scope (locked — do NOT exceed)
- Locked fast-lane rules: #4679.2/#4680.1 (registered+ACTIVE code AND (sender-in-participant-set OR thread-continuity); sender-only forbidden alone); #4679.3 (regex shape alone NEVER fast-clears — registry validation mandatory); F4 (extract_project_codes conflict pre-check); blocker-D3 (registry/binding exception NEVER auto-clears — routes to TICKET + counts `failed`; distinguish "threw" from "no match").
- Pilot v1 = participant-binding ONLY (thread-continuity is a documented TODO, not built).
- Entire branch gated under `if fast_lane and row_id:` reusing C's pre-computed `fast_lane` local — do NOT re-read the env.
- NO VISIBLE_HOLD (grep count must stay 0). NO new table/schema/job/lock. Seed = two literal-string edits, remains un-run.

## Acceptance criteria — machine-checkable done rubric (10 items, verbatim in full_brief)
- extract_project_codes pure/no-DB/distinct + reuses `_NUMBER_RE` (no 2nd re.compile).
- >1 distinct code → TICKET; regex-only-no-row → TICKET; conflict/no-row/no-binding → TICKET (not VISIBLE_HOLD).
- FAST_TICKET written ONLY on a clean active-resolve + participant-binding match; only one FAST_TICKET write site.
- Branch fully gated by `BOX5_FAST_LANE_ENABLED` (flag false → C's TICKET default covers everything, D adds nothing live).
- Error path increments `failed` + falls through to TICKET, never FAST_TICKET; D never touches `deterministic_cleared`.
- Seed `matter_slug == 'aukera'` in both sites; `test_project_registry.py` asserts `seed.MATTER_SLUG == 'aukera'`; zero remaining `annaberg` literals.

## Done rubric
Build-done = PR merged + all 10 rubric items green. Ships DARK (BOX5_FAST_LANE_ENABLED off). NO activation, NO seed run — both are later Director GOs. E (soft fast lane) dispatches after D merges.

## Context-economy (HARD — no auto-compaction)
Read ONLY the files in the brief's Context Contract. Output to /tmp; tails only. Context >70%: commit, push, bus handoff, STOP. Reliability reminder: C shipped clean only after codex caught 4 P1s across two re-gate rounds (cursor-strand, bus-fail-strand, dead-branch, blank-cursor). Write the binding/conflict/error test matrix FIRST and make it assert the real fall-through paths (regex-only, >1 code, resolver-throws, no-binding), not happy-path FAST_TICKET.
