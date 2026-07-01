# CHECKPOINT — Box 5 ticketing arc (lead / AH1)

**Written:** 2026-07-01 ~06:30Z. Successor: claim = attempt-bump commit, not bus ack.
**Attempt:** 6 (STATE ADVANCED PAST D — D MERGED, E DISPATCHED. Now awaiting b4's E ship → E gate cycle. E is the LAST Box 5 brief).

## ROLE
AH1 lead orchestrator. Sole dispatch/gate/merge. Box 5 build program (Baker OS V2, Signal Journey / airport ticketing). cowork-ah1 STOOD DOWN from the D+E lane (#4782) — Director refreshed lead to finish autonomously; git/merge is lead's single-threaded lane. cowork-ah1 still owns Box 5 DESIGN + authored briefs A–E. b4 = builder (CODE_4 slot). codex = live BUS gate terminal.

## HARD RULE (Director-ratified 2026-06-30)
Codex gates → the **codex BUS terminal** (`BAKER_ROLE=lead bash scripts/bus_post.sh codex "..." "gate/<topic>"`). **NEVER** the `codex-verifier` subagent. Bus caught 5 P1s on this arc a subagent would have passed. Memory: `feedback_never_use_codex_verifier_subagent_route_to_codex_bus`.

## GATE CHAIN
G1 (builder self-check) → codex G3 (bus, effort MEDIUM for additive/dark) → lead G4 `/security-review` → lead squash-merge (`gh pr merge <N> --squash --delete-branch`). Ship reports → dispatched_by (cowork-ah1); gate verdicts → lead. NO Director GO for dark merges (bank model); activation (flag flips) + seed runs ARE Director-gated.

## BUS MECHANICS
Host brisen-lab.onrender.com, auth X-Terminal-Key (`source scripts/brisen_lab_terminal_key.sh; KEY=$(brisen_lab_read_terminal_key "lead" "")`). Read `/msg/lead?limit=2000` (parse json, filter `not acknowledged_at`). Full body `/event/{id}/full`. Ack `POST /msg/{id}/ack`. Daemon broadcast msgs (aid lifecycle #4769/#4770) return 403 on ack — leave them. Bus post bodies: NO backticks (shell parse error).

## MERGED THIS ARC (all dark)
- **#439** PROJECT_NUMBER_REGISTRY_1 (registry + resolvers: resolve_project_number / resolve_by_participant / resolve_by_alias).
- **#440** BOX5_RECEIPT_TTL_1 (A) — check-in reader + TTL/nudge.
- **#441** BOX5_SCHEMA_FOUNDATION_1 (B) — airport_tickets terminal cols incl. FAST_TICKET 6-state CHECK + routing cols + gated aukera seed.
- **#442** BOX5_TICKETING_RUNNER_1 (C) — squash **86ae607**. run_tick: cursor + SKIP-LOCKED claim + status-guarded terminal write. G3 PASS after 2 re-gate rounds (4 P1s). G4 CLEAN.
- **#443** BOX5_HARD_FAST_LANE_1 (D) — squash **5795589**. (e.5) hard fast lane + extract_project_codes + aukera seed slug fix. codex G3 PASS on rework a4ffc0e (savepoint-scoped rollback — SAVEPOINT airport_hard_lane preserves the reservation so a D exception falls through to a visible TICKET; test 17 tightened). G4 /security-review CLEAN (all SQL static-literal or existing parameterized helpers; email text → regex + bound params only). DONE.

## IN FLIGHT — E (last Box 5 brief)
- **BOX5_SOFT_FAST_LANE_1** (E), branch box5-soft-fast-lane-1 (b4 creates). DISPATCHED to b4 = **bus #4783** (`dispatch/box5-soft-fast-lane`). Dispatch committed to main **d240602** (envelope `briefs/_tasks/CODE_4_PENDING.md` + full brief `briefs/BRIEF_BOX5_SOFT_FAST_LANE_1.md`). dispatched_by cowork-ah1; ship → cowork-ah1, gate verdicts → lead.
- E = manifest SOFT fast lane. New block (e.7) AFTER D's (e.5), BEFORE C's (f). Needs >=2 INDEPENDENT signals (resolve_by_participant AND resolve_by_alias agree on same project_number); sender-only NEVER clears; soft clear = terminal_status TICKET (ROUTED) + 4 routing kwargs on write_terminal_status + new soft_ticket counter, NEVER FAST_TICKET/VISIBLE_HOLD; exception → failed + (f) TICKET.
- **Pre-merge-refs note FOLDED into envelope (#4772):** b4 must re-pin C/D line-refs to merged main @ 5795589 (grep real file), reuse D's `handled` flag, EXTEND the existing kbl.project_registry_store import to add resolve_by_alias. Same adaptation b4 did for D.
- **AWAITING b4 E ship.** On ship (branch box5-soft-fast-lane-1 pushed + ship msg to lead/cowork-ah1):
  1. Fetch branch; identify code SHA (ignore any report/mailbox commit on top).
  2. Quick self-check the (e.7) placement + write_terminal_status extension is byte-compatible for C/D callers.
  3. Fire codex G3 on the BUS (topic gate/box5-soft-fast-lane-g3, effort MEDIUM; focus >=2-signal-required + sender-only-never-clears + soft=TICKET-not-FAST_TICKET + error-never-clears).
  4. PASS → lead G4 `/security-review` on `git diff main...<sha>` (worktree at /tmp if main tree dirty) → squash-merge → **Box 5 build program COMPLETE**.
  5. FAIL → route findings to b4 (`bus_post.sh b4 ... gate/box5-soft-fast-lane-g3-fail-rework`), b4 reworks, re-gate codex.

## DIRECTOR-GATED (NOT done — need explicit GO)
- Activation of A (flip `AIRPORT_CHECKIN_SWEEP_ENABLED`) and the fast lane (`BOX5_FAST_LANE_ENABLED`).
- BB pilot **seed run** (aukera) — `scripts/seed_bb_pilot_registry.py`, currently un-run.
- Box 5 **feed-widening** follow-up brief ("every arrival ends visible" — no-keyword arrivals) — deferred, cowork-ah1 tracking.

## GIT / HYGIENE
- main HEAD after E dispatch = **d240602**; after this checkpoint = the attempt-bump commit.
- Path-scoped commits only — working tree has many pre-existing unrelated M/?? files (CLAUDE.md, .claude/*, docs-site, scripts, other briefs) that are NOT mine to commit. `git add` explicit paths.
- CODE_4_PENDING.md / BRIEF_ writes are hook-guarded (write_brief_sop_enforcer) — for mechanical dispatch of a pre-authored brief use `export BAKER_BRIEF_SOP_BYPASS=1` + write via Bash heredoc (supersede-old-dispatch).
