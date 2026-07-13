# CHECKPOINT — CASE_ONE_P3_CONTRACT_IDENTITY_1

attempt: 1
seat: b3 (pre-build checkpoint — respawn requested per lead's >=35%-context rider, dispatch #10023)
branch: b3/case-one-p3-contract-identity-1
created: 2026-07-13

## Brief id
CASE_ONE_P3_CONTRACT_IDENTITY_1 — brief `briefs/BRIEF_CASE_ONE_P3_CONTRACT_IDENTITY_1.md` @39bba3e4 on main (deputy-authored, lead-review PASS). Dispatch: lead bus #10023. Effort: HIGH.

## What's done
Nothing built. This is a pre-build checkpoint. The dispatching seat (b3) was deep in session (P0 + ITEM-10 arcs) and lead's dispatch #10023 said: "if >=35% context, checkpoint+respawn FIRST, build on fresh seat." Checkpointed instead of starting the high-effort build in a deep context.

## What's left
The entire build. Per the brief (read it @39bba3e4 first — `git pull` main).

## TWO LEAD RIDERS (BINDING — from dispatch #10023, capture in case not verbatim in brief)
(a) **TRANSITION MODE** — removing content-hash dedup + requiring an envelope id must NOT break legacy clients mid-rollout. The server ACCEPTS legacy un-id'd posts during transition (synthesize the id server-side + mark `legacy=true`); hard-require the id ONLY AFTER fleet clients ship.
(b) **STAGED shared-key kill** — do NOT hard-refuse the shared Baker-MCP key until every app-seat poster has a per-seat key. Interim: map the shared key to `daemon` + flag as unattributed; kill switch via env var.

## Gate plan
Two-gate: deputy review + non-author test-run (against real Postgres) → lead merges.

## Key paths / commits
- Brief: `briefs/BRIEF_CASE_ONE_P3_CONTRACT_IDENTITY_1.md` @39bba3e4 (main).
- Likely repos: brisen-lab (bus daemon — envelope id, dedup, key attribution) + baker-master (client posters / bus_post). Confirm from brief.
- No work commits yet.

## Next concrete step (fresh seat)
1. `git pull` main; read the brief @39bba3e4 in full.
2. Bump `attempt:` in this checkpoint + commit (that commit is the claim — not a bus ack).
3. Implement per the brief + the two binding riders above; keep dedup-removal + id-requirement behind the TRANSITION MODE (accept legacy, synthesize server-side, hard-require only post-fleet-ship); keep the shared-key kill STAGED with an env kill switch.
4. Tests against real pg (non-author test-run is a gate). Two-gate → lead merges. Post context % with ship.

## Claim discipline
The successor claims this arc by the `attempt:`-bump commit on THIS checkpoint, NOT by a bus ack. If `attempt` is already bumped by another session, stand down. At `attempt >= 3`, stop resuming and escalate to lead with this path + last error.
