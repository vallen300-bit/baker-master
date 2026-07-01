# CHECKPOINT — Box 5 ticketing arc (lead / AH1)

**Written:** 2026-07-01 ~06:05Z · context rollover at ~86%. Successor: claim = attempt-bump commit, not bus ack.
**Attempt:** 5 (rollover ~92%; STATE ADVANCED — D G3 round-1 FAILED, rework routed to b4 #4777; now awaiting b4 re-ship → re-fire codex G3. Fresh respawn #4778.).

## ROLE
AH1 lead orchestrator. Sole dispatch/gate/merge. Box 5 build program (Baker OS V2, Signal Journey / airport ticketing). cowork-ah1 = parallel AH1, authors Box 5 briefs A–E, owns Box 5 DESIGN. b4 = builder (CODE_4 slot). codex = live BUS gate terminal.

## HARD RULE (Director-ratified 2026-06-30)
Codex gates → the **codex BUS terminal** (`BAKER_ROLE=lead bash scripts/bus_post.sh codex "..." "gate/<topic>"`). **NEVER** the `codex-verifier` subagent. Bus caught 4 P1s on this arc a subagent would have passed. Memory: `feedback_never_use_codex_verifier_subagent_route_to_codex_bus`.

## GATE CHAIN
G1 (builder self-check) → codex G3 (bus, effort MEDIUM for additive/dark) → lead G4 `/security-review` → lead squash-merge (`gh pr merge <N> --squash --delete-branch`). Ship reports → dispatched_by (cowork-ah1); gate verdicts → lead. NO Director GO needed for dark merges (bank model); activation (flag flips) + seed runs ARE Director-gated.

## BUS MECHANICS
Host brisen-lab.onrender.com, auth X-Terminal-Key (`source scripts/brisen_lab_terminal_key.sh; KEY=$(brisen_lab_read_terminal_key "lead" "")`). Read `/msg/lead?limit=2000` (parse `json.loads(...,strict=False)`, filter `not acknowledged_at`). Full body `/event/{id}/full`. Ack `POST /msg/{id}/ack`. Daemon broadcast msgs return 403 on ack (not party — leave them).

## MERGED THIS SESSION
- **#439** PROJECT_NUMBER_REGISTRY_1 (registry + resolvers). MERGED earlier.
- **#440** BOX5_RECEIPT_TTL_1 (check-in reader + TTL/nudge), dark. MERGED.
- **#441** BOX5_SCHEMA_FOUNDATION_1 (airport_tickets terminal cols incl. FAST_TICKET 6-state CHECK + gated aukera seed). MERGED.
- **#442** BOX5_TICKETING_RUNNER_1 (C) — squash **86ae607**. codex G3 PASS after 2 re-gate rounds (4 P1s fixed: cursor-strand-under-cap, bus-fail/failure-strand, dead no-keyword REJECT_NOISE branch, blank-cursor 24h-fallback). lead G4 CLEAN. Dark behind AIRPORT_TICKETING_BRIDGE_ENABLED.

## IN FLIGHT — D (PR #443)
- **BOX5_HARD_FAST_LANE_1** (D), branch box5-hard-fast-lane-1, **code SHA 39671d6** (docs commit 6bb7ff2 on top — ignore for gate). b4 shipped; adapted correctly to merged C.
- **codex G3 round 1 = FAIL** (#4776, acked). 9/10 rubric PASS; 1 P1: hard-lane exception does `conn.rollback()` which destroys the reserved row → fallback `_claim_for_terminal` finds nothing → lease_skipped → NO terminal TICKET (arrival stranded; violates blocker-D3). Test at test_box5_ticketing_runner.py:508 accepted None, masking it.
- **Rework routed to b4 = bus #4777** (`gate/box5-hard-fast-lane-g3-fail-rework`): don't roll back the reservation; scope rollback to failed D work so fallback writes TICKET; fix the test to assert a real TICKET write (not None). **AWAITING b4 re-ship → re-fire codex G3.**
- NEXT ON VERDICT:
  - PASS → lead G4 `/security-review` on `git diff main...39671d6` (verify all SQL parameterized, no injection/secret/exec; D is additive decision logic + pure regex helper + seed literal edits). Then squash-merge #443. Then dispatch E.
  - FAIL → route findings to b4 (`bus_post.sh b4 ... gate/box5-hard-fast-lane-g3-fail-rework`), b4 reworks, re-gate codex. (D safety rubric = 10 items; the risk edges are: regex-only-never-clears, >1-code conflict→TICKET, binding mandatory, error-never-FAST_TICKET, VISIBLE_HOLD count 0, seed aukera both sites + un-run.)

## QUEUED — E (last Box 5 brief)
- **BOX5_SOFT_FAST_LANE_1** (E), staged `~/baker-vault/_ops/briefs/BRIEF_BOX5_SOFT_FAST_LANE_1.md`. dispatched_by cowork-ah1. Depends on **D MERGED** (edits C run_tick, sits AFTER D hard lane, BEFORE C safe-default; extends write_terminal_status with 4 OPTIONAL routing kwargs).
- **cowork-ah1 heads-up #4772 (acked):** E brief refs `brief_c_draft.md`/`brief_d_draft.md` = PRE-MERGE snapshots. At dispatch, add a one-line envelope note: **builder must re-pin insertion coordinates + helper signatures to the MERGED C+D code, NOT the draft line-refs** (same adaptation b4 did for D). E DESIGN is correct; no brief rework.
- DISPATCH E steps (after #443 merges): `tail -n +N` strip any preamble → copy vault brief to `briefs/BRIEF_BOX5_SOFT_FAST_LANE_1.md` → Write `briefs/_tasks/CODE_4_PENDING.md` envelope (model on this arc's D envelope + the pre-merge-refs note) → path-scoped commit `git add briefs/BRIEF_... briefs/_tasks/CODE_4_PENDING.md` + push → bus wake b4 (`dispatch/box5-soft-fast-lane`) + notify cowork-ah1.

## DIRECTOR-GATED (NOT done — need explicit GO)
- Activation of A (flip `AIRPORT_CHECKIN_SWEEP_ENABLED`).
- BB pilot **seed run** (aukera) — `scripts/seed_bb_pilot_registry.py`, currently un-run.
- Box 5 **feed-widening** follow-up brief ("every arrival ends visible" — no-keyword arrivals) — deferred, cowork-ah1 tracking.

## GIT / HYGIENE
- main HEAD after D dispatch = **8296616**; after this checkpoint = the attempt-bump commit.
- Path-scoped commits only — the working tree has many pre-existing unrelated M/?? files (CLAUDE.md, .claude/*, docs-site, scripts) that are NOT mine to commit. `git add` explicit paths.
- Bus post bodies: **NO backticks** (shell command-substitution parse error) — use plain words.
