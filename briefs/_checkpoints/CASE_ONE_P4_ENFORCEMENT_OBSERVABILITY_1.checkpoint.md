# CHECKPOINT — CASE_ONE_P4_ENFORCEMENT_OBSERVABILITY_1

attempt: 1
seat: b3 (pre-build checkpoint — respawn requested per lead's >=35%-context rider, dispatch #10036)
branch: b3/case-one-p4-enforcement-observability-1 (NOT yet created — successor creates off main)
created: 2026-07-13

## Brief id
CASE_ONE_P4_ENFORCEMENT_OBSERVABILITY_1 — brief `briefs/BRIEF_CASE_ONE_P4_ENFORCEMENT_OBSERVABILITY_1.md` @381ebedb, now on main (merged; P3 also fully merged at fdd4a4e5 — both P3 PRs #124 brisen-lab + #545 baker-master landed). Dispatch: lead bus #10036 (acked). Effort: HIGH. Final Case-One phase.

## Why checkpoint-not-build
Same discipline as the P3 arc: this b3 seat is deep in context after building + shipping P3 this session. Lead's dispatch #10036 rider: "If context >=35% checkpoint first." P4 is high-effort mixed-repo — starting it in a deep context risks a mid-build hard block. Fresh seat builds.

## What's done
Nothing built. Pre-build checkpoint only. P3 (which P4 consumes: typed envelope, `kind`, server identity, claim-check `/artifact`) is MERGED to main.

## What's left
The entire P4 build. Read the brief @ its path on main first. Five pieces:
- **P4.1 structural behavioral enforcement (E3):** session-start freshness re-assertion hook (+ mid-session cadence); worker-side GO-reroute gate in the bus-post path that reroutes a Director-addressed GO/confirm/permission to the superior (`reports_to` in `agent_registry.yml`), fail-loud/logged.
- **P4.2 intent-granular symptoms-only alerting (E15):** dispatch-warning fires ONLY on `kind=assignment` (job-ref-required), never reply/fyi; symptoms-only + actionable-only alerts; demote 503/`bus_busy_retry` flood to a rate metric, not per-event alarms.
- **P4.3 observability (E20):** W3C `traceparent` on the P3 envelope (trace spans message→tool→cost, OTel GenAI conventions); delivery-receipt table/endpoint (a `0-unacked` false-clean becomes detectable — order with no receipt past SLA is flagged); dead-letter table for failed-delivery/failed-P3-validation msgs (reason recorded, never silent-dropped).
- **P4.4 delivery-health dashboard + owner (ownership C):** engine-room register (Pattern C/D, NOT Director-facing) — undelivered-past-SLA, dead-letter depth, dedup-reject rate, 503 rate, missed-heartbeat seats, per-seat delivery/ack latency. Named standing owner = deputy (AH2). EXTEND the shipped bus-health surface (#119-#122), do NOT fork it.
- **P4.5 micro:** stable `<alias>.current` symlink in the band dir, maintained by the P2 emitter, for a seat to self-read its own band file (#9986).

## TWO LEAD RIDERS (BINDING — from dispatch #10036)
(1) **GO-reroute gate CONSERVATIVE** — the reroute fires ONLY on a GO/confirm about an ALREADY-DISPATCHED `job_ref`. NEVER intercept/reroute `ratify_required` / Tier-B / Tier-C (those legitimately go to Director). Log + cc lead on every reroute. Provide an ENV KILL SWITCH for the gate. **False-positive tests MANDATORY** (a ratify_required / Tier-B message must NOT be rerouted; a genuine Director business question must NOT be rerouted).
(2) **NEW small AC — recipient-scope `GET /artifact/{ref}`** (P3 Finding A fast-follow): P3 shipped `/artifact/{ref}` as any-authenticated-seat readable (content-addressed by unguessable uuid). P4 tightens it to recipient-scope — only a seat that is a recipient of a message carrying that `artifact_ref` (or Director) may fetch it. Add the scope check + a test that a non-recipient seat gets 403.

## Repos / context contract
- Fleet harness (baker-master `~/bm-b3` + hooks): session-start hook, GO-reroute gate in bus-post path, band emitter symlink.
- brisen-lab (`~/bm-b3-brisen-lab`, separate repo/worktree): `bus.py` (traceparent, receipts, dead-letter, intent-filtered alert predicate, recipient-scope /artifact tighten), `db.py`+bootstrap ALTER (delivery_receipt + dead_letter tables), `/bus-health` metrics endpoint extension.
- Dashboard: delivery-health engine-room page.
- Builds ON P1/P2/P3 — do NOT redo them (see brief SCOPE DEDUPE).

## Gate plan
Two-gate: G1 self-verify → G2 deputy cross-lane + independent Claude-side review by lead before merge (codex suspended #9711) → lead merges. Live drill AC + `POST_DEPLOY_AC_VERDICT v1` post-deploy; deputy assumes named bus-health-owner sweep.

## Test-DB note (from P3 build)
Local Postgres runs at localhost:5432. Create an isolated throwaway DB (`createdb`), set `TEST_DATABASE_URL=postgresql://localhost:5432/<db>`, run, then `dropdb`. Do NOT use the shared Neon test DB (concurrent TRUNCATE corrupts row-count tests). brisen-lab conftest `fresh_db`/`client` fixtures + `X-Terminal-Key: <slug>-key` post pattern; shared-key slug set via `BRISEN_LAB_SHARED_KEY_SLUGS` env (read live). Full suite baseline on clean main = 27 failed/526-with-P3 passed (27 are pre-existing autowake/identity env failures, no CI) — diff against that, don't chase the 27.

## Next concrete step (fresh seat)
1. `git pull` main; read `briefs/BRIEF_CASE_ONE_P4_ENFORCEMENT_OBSERVABILITY_1.md` in full.
2. Bump `attempt:` in THIS checkpoint + commit (that commit is the claim — not a bus ack).
3. `git checkout -b b3/case-one-p4-enforcement-observability-1` off main (baker-master) AND a matching branch off origin/main in `~/bm-b3-brisen-lab`.
4. Implement the 5 pieces + BOTH riders above. Conservative GO-reroute with env kill switch + mandatory false-positive tests. Recipient-scope the /artifact endpoint + test.
5. Tests vs real local pg (isolated DB). Two-gate → lead merges. Post context % with ship.

## Claim discipline
Successor claims by the `attempt:`-bump commit on THIS checkpoint, NOT a bus ack. If `attempt` already bumped by another session, stand down. At `attempt >= 3`, stop resuming + escalate to lead with this path + last error.
