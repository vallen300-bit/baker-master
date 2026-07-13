# CHECKPOINT — CASE_ONE_P3_CONTRACT_IDENTITY_1

attempt: 2
seat: b3 (fresh successor seat — claimed arc 2026-07-13, build in progress)
branch: b3/case-one-p3-contract-identity-1
created: 2026-07-13

## Brief id
CASE_ONE_P3_CONTRACT_IDENTITY_1 — brief `briefs/BRIEF_CASE_ONE_P3_CONTRACT_IDENTITY_1.md` @39bba3e4 on main (deputy-authored, lead-review PASS). Dispatch: lead bus #10023. Effort: HIGH.

## What's done (attempt:2 — fresh b3 successor, BUILD COMPLETE, gates pending)
Full P3 built + G1 self-verify PASS. Two PRs open (must merge together):
- brisen-lab PR #124 (server daemon) — branch b3/case-one-p3-contract-identity-1, commit 6669136.
- baker-master PR #545 (MCP fleet client) — branch b3/case-one-p3-contract-identity-1, commit d162c77e.
All 5 pieces (P3.1-P3.4 + both riders + a 3rd transition gate) implemented, all DEFAULT-OFF.
Tests: 15 new vs real local Postgres, all green. Full brisen-lab suite 27 failed/526 passed —
the 27 fail identically on clean main (pre-existing autowake/identity env failures, no CI); 0 regressions.
Ship report posted to lead: bus #10028. b3 inbox: 0 unread.

## What's left
G2 deputy cross-lane review + non-author test-run vs real pg → lead independent Claude-side review → lead merges BOTH PRs (codex suspended #9711).

## TWO LEAD RIDERS (BINDING — from dispatch #10023, capture in case not verbatim in brief)
(a) **TRANSITION MODE** — removing content-hash dedup + requiring an envelope id must NOT break legacy clients mid-rollout. The server ACCEPTS legacy un-id'd posts during transition (synthesize the id server-side + mark `legacy=true`); hard-require the id ONLY AFTER fleet clients ship.
(b) **STAGED shared-key kill** — do NOT hard-refuse the shared Baker-MCP key until every app-seat poster has a per-seat key. Interim: map the shared key to `daemon` + flag as unattributed; kill switch via env var.

## Gate plan
Two-gate: deputy review + non-author test-run (against real Postgres) → lead merges.

## Key paths / commits
- Brief: `briefs/BRIEF_CASE_ONE_P3_CONTRACT_IDENTITY_1.md` @39bba3e4 (main).
- Likely repos: brisen-lab (bus daemon — envelope id, dedup, key attribution) + baker-master (client posters / bus_post). Confirm from brief.
- No work commits yet.

## Next concrete step (fresh seat / on request_changes)
Build is DONE + shipped. If a gate returns request_changes: address all points → NEW commit (never amend)
on the same branch in BOTH worktrees (~/bm-b3-brisen-lab for server, ~/bm-b3 for client) → push → reply on
the ship thread (bus #10028) to lead. Local test DB: create a throwaway `createdb` on local pg 5432 and set
TEST_DATABASE_URL (shared Neon test DB corrupts under concurrent TRUNCATE — do NOT use it). Env gates to know:
BRISEN_LAB_REQUIRE_ENVELOPE_ID / BRISEN_LAB_SHARED_KEY_KILL / BRISEN_LAB_ENFORCE_BODY_MIN (all default-off).

## Claim discipline
The successor claims this arc by the `attempt:`-bump commit on THIS checkpoint, NOT by a bus ack. If `attempt` is already bumped by another session, stand down. At `attempt >= 3`, stop resuming and escalate to lead with this path + last error.
