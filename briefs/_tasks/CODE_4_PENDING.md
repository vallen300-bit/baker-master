---
status: SHIPPED_AWAITING_GATES
pr: 444
head_sha: 1fac01d
shipped_at: 2026-07-01
brief_id: BOX5_SOFT_FAST_LANE_1
to: b4
from: lead
dispatched_by: cowork-ah1
dispatched_at: 2026-07-01
branch: box5-soft-fast-lane-1
ship_note: "1fac01d (PR #444) — soft fast lane block (e.7) between D's (e.5) and C's (f), reusing D's handled flag. >=2 independent signals (resolve_by_participant AND resolve_by_alias agree on exactly 1 project: len(p_nums & a_nums)==1); sender-only/alias-only/conflict/no-match -> (f) TICKET; clean clear -> routed terminal_status=TICKET + matter_slug/desk_owner/manifest_match_signals/confidence=0.60, NEVER FAST_TICKET, new soft_ticket counter. SAVEPOINT airport_soft_lane (same reliability fix D needed): soft-lane throw rolls back only E's partial work, preserves issue_ticket reservation, failed++, (f) TICKET — plain rollback would strand (D's P1 class); test 23 proves it non-vacuously. write_terminal_status extended with 4 optional routing kwargs (dynamic SET, byte-identical SQL for C/D kwarg-less callers). 100 GREEN live-PG16: 27 box5 (20 C/D no-regression + 7 E) + 21 registry + 52 airport. py_compile clean. VISIBLE_HOLD grep=1 (BRIEF-B pre-existing comment; E writes 0). Ships DARK behind BOX5_FAST_LANE_ENABLED; no seed change. Ship report -> cowork-ah1; gate verdicts -> lead. Awaiting codex G3."
test_placement_note: "Soft-lane run_tick tests live in tests/test_box5_ticketing_runner.py (tests 19-25) where the runner/hard_lane harness + _seed_email/_terminal live — NOT tests/test_project_registry.py as the pre-merge brief said. Same adaptation class as the line-refs; envelope gate_plan already lists test_box5_ticketing_runner.py for the soft-lane matrix."
base_note: branch off main @ 5795589 or later. Contains BOTH C (#442, squash 86ae607) AND D (#443, squash 5795589) merged — write_terminal_status / _claim_for_terminal / fast_lane_enabled / extract_project_codes / resolve_by_participant / resolve_by_alias / resolve_project_number and D's (e.5) hard-lane FAST_TICKET block ALL live on main. Verify with grep before editing.
reply_target: cowork-ah1 (bus) for ship report; gate verdicts to lead
effort: medium (builder — one surgical branch composing two existing #439 resolvers + a 4-kwarg extension to write_terminal_status; cost is the >=2-signal / sender-only-forbidden / conflict / error test matrix, NOT new infra). codex G3 effort medium (focus: >=2-INDEPENDENT-signals-required, sender-only-NEVER-clears, error-never-clears-routes-to-TICKET, soft-clear-is-TICKET-not-FAST_TICKET; NOT xhigh).
task_class: ADDITIVE decision logic + OPTIONAL signature extension. One new precedence tier — block (e.7) — in C's run_tick, positioned AFTER D's (e.5) hard-lane arm and BEFORE C's (f) safe-default TICKET; four OPTIONAL routing kwargs (matter_slug/desk_owner/manifest_match_signals/confidence, default None, appended to the guarded UPDATE SET clause only when provided — byte-compatible for C's and D's existing callers); one new soft_ticket counter + stats key. NO net-new registry helper (composes the two existing #439 resolvers). NO schema migration, NO new job/lock/table (routing columns already merged in #441).
gate_plan: G1 builder self-test (pytest test_project_registry.py + test_box5_ticketing_runner.py incl. new soft-lane matrix + no-regression on C/D; py_compile changed files) -> codex G3 (bus, effort medium) -> lead G4 /security-review -> lead squash-merge. Ships DARK behind BOX5_FAST_LANE_ENABLED (default false). SEED STAYS UN-RUN (Director GO); this brief adds NO seed change.
full_brief: briefs/BRIEF_BOX5_SOFT_FAST_LANE_1.md
prev_merged: C (BOX5_TICKETING_RUNNER_1) MERGED PR #442 squash 86ae607 (G3 PASS after 2 re-gate rounds, 4 P1s fixed; G4 CLEAN). D (BOX5_HARD_FAST_LANE_1) MERGED PR #443 squash 5795589 (G3 PASS after 1 re-gate — savepoint-strand P1 fixed; G4 CLEAN). E is the LAST Box 5 brief.
---

# BOX5_SOFT_FAST_LANE_1 — manifest soft fast lane (Build Order 7, the LAST Box 5 brief)

## Read this first — PRE-MERGE LINE-REFS ADAPTATION (MANDATORY, same as you did for D)
Complete copy-pasteable impl in **briefs/BRIEF_BOX5_SOFT_FAST_LANE_1.md** (on main, committed alongside this envelope). Implement the DESIGN exactly — brief authored + verifier-checked by cowork-ah1; do NOT redesign.

**CRITICAL: the brief's C/D coordinates are PRE-MERGE draft snapshots.** Every reference to scratchpad/brief_c_draft.md / scratchpad/brief_d_draft.md line numbers, and every airport_ticketing_bridge.py:NNN line-ref (e.g. :780, :57, :298, :227, :274), points at pre-merge drafts — C evolved through 4 P1 re-gate fixes and D through 1, so those line numbers are STALE. **Re-pin ALL insertion coordinates + helper signatures to the MERGED code on main @ 5795589 by grepping the real file** — exactly the adaptation you did correctly for D. Grep for:
- D's (e.5) hard-lane arm — the "if fast_lane and row_id:" / "SAVEPOINT airport_hard_lane" region. **E's block (e.7) goes AFTER this arm's whole if/try and BEFORE C's "# (f) SAFE DEFAULT" block.** Both D and E fall through to (f) on a non-clear.
- C's "# (f) SAFE DEFAULT — TICKET" block and the "if not handled:" guard D introduced — reuse that handled flag (E sets handled = True on a clean soft clear so (f) does not double-write).
- The write_terminal_status( signature (extend with the 4 optional kwargs, appended to the SET clause only when non-None).
- _claim_for_terminal, the fast_lane local, the stats dict (add 'soft_ticket': soft_ticket), and the existing "from kbl.project_registry_store import (...)" block D added — EXTEND that import to add resolve_by_alias (do NOT add a second import block).

## Context (one paragraph)
Box 5 Build Order 7 — the MANIFEST SOFT FAST LANE. Insert block (e.7) between D's (e.5) hard lane and C's (f) safe-default TICKET. Because both D and E clear via handled/continue, E executes ONLY when the hard lane did NOT clear (number missing/unregistered/inactive/conflicting, or sender not participant-bound). Requires >=2 INDEPENDENT signals — resolve_by_participant('email', sender) AND resolve_by_alias(subject+' '+body) agreeing on the SAME project_number (agree = participant_pns & alias_pns; len(agree)==1). Sender-only NEVER clears. Weak/conflicting -> terminal_status='TICKET' (a ROUTED ticket via the new routing kwargs), NEVER FAST_TICKET (reserved for D's authoritative hard lane), NEVER VISIBLE_HOLD. Manifest-check exception NEVER auto-clears (#blocker D3) -> safe-default TICKET + count failed; distinguish threw from no-match.

## Scope (locked — do NOT exceed)
- >=2 independent signals mandatory; sender-only / one-signal / conflict / no-match / exception all -> (f) TICKET.
- Soft clear writes terminal_status='TICKET' (ROUTED) with the routing columns, NOT FAST_TICKET; increments a NEW soft_ticket counter (not defaulted_ticket, not fast_ticket).
- Entire branch gated "if fast_lane and row_id:" reusing C's pre-computed fast_lane local — do NOT re-read the env.
- routing kwargs appended INSIDE the same status-guarded UPDATE (WHERE id=%s AND terminal_status IS NULL) — never written outside the guard.
- NO VISIBLE_HOLD (grep count stays 0). NO new table/schema/job/lock. NO seed change. Resolvers are read-only + swallow their own exceptions to [].

## Acceptance criteria — machine-checkable (full 10-item rubric verbatim in full_brief)
- Runs only after hard lane misses + flag on; flag false -> C's TICKET default covers everything.
- >=2 agreeing signals required (len(participant_pns & alias_pns)==1); one-signal / sender-only -> TICKET, soft_ticket NOT incremented.
- Competing active manifest conflict -> TICKET (never a wrong routed clear).
- Soft clear -> terminal_status='TICKET' (ROUTED) + routing columns + soft_ticket++; NEVER FAST_TICKET, NEVER VISIBLE_HOLD.
- write_terminal_status extension is byte-compatible: C's and D's existing callers (no kwargs) produce identical SQL.
- Manifest exception -> failed++ + fall through to (f) TICKET, never a soft clear.

## Done rubric
Build-done = PR merged + all 10 rubric items green. Ships DARK (BOX5_FAST_LANE_ENABLED off). NO activation, NO seed run — later Director GOs. E is the last Box 5 brief; on merge the Box 5 build program is complete.

## Context-economy (HARD — no auto-compaction)
Read ONLY the files in the brief's Context Contract. Output to /tmp; tails only. Context >70%: commit, push, bus handoff, STOP. Reliability reminder: C needed 4 P1 re-gate fixes and D needed 1 (savepoint-strand) before shipping clean. Write the soft-lane test matrix FIRST and make it assert the real fall-throughs — sender-only->TICKET, one-signal->TICKET, conflict->TICKET, resolver-throws->TICKET+failed — not just the happy-path >=2-signal clear. Assert the write_terminal_status extension leaves C's/D's existing callers byte-identical.
