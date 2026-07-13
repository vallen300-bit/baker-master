# CHECKPOINT — CASE_ONE_P4_ENFORCEMENT_OBSERVABILITY_1

attempt: 2
seat: b3 (fresh successor — claimed the pre-build checkpoint per lead #10036 >=35%-context rider)
branch: b3/case-one-p4-enforcement-observability-1 (created off origin/main @fdd4a4e5, baker-master) + matching branch off origin/main in ~/bm-b3-brisen-lab
created: 2026-07-13
updated: 2026-07-13 (attempt-2 claim by fresh seat)

## Brief id
CASE_ONE_P4_ENFORCEMENT_OBSERVABILITY_1 — brief `briefs/BRIEF_CASE_ONE_P4_ENFORCEMENT_OBSERVABILITY_1.md` @381ebedb on main. Dispatch: lead bus #10036 (acked by prior seat). Effort: HIGH. Final Case-One phase. P3 fully merged (fdd4a4e5, PRs #124 brisen-lab + #545 baker-master).

## Claim
attempt:1 was the prior seat's pre-build checkpoint (respawn requested). This attempt:2 commit is the fresh-seat claim per checkpoint claim-discipline. Bus #10036 confirms riders; no newer b3-addressed message supersedes.

## What's done
- Bus checked: P4 dispatch #10036 confirmed, riders verbatim-matched.
- Brief read in full from origin/main.
- P4 branch created off origin/main; this claim commit.

## What's left
Entire P4 build — five pieces + two binding riders:
- **P4.1 (E3):** session-start freshness re-assertion hook (+ mid-session cadence); worker-side GO-reroute gate in bus-post path (reroute Director-addressed GO/confirm on already-dispatched job_ref to superior `reports_to`; fail-loud/logged).
- **P4.2 (E15):** dispatch-warning ONLY on `kind=assignment`; symptoms-only actionable alerts; demote 503/`bus_busy_retry` flood to a rate metric.
- **P4.3 (E20):** W3C `traceparent` on P3 envelope; delivery_receipt table/endpoint; dead_letter table; recipient-scope `GET /artifact/{ref}` (rider 2).
- **P4.4 (ownership C):** extend `/bus-health` (#119-#122); engine-room delivery-health page (Pattern C/D); deputy (AH2) named owner.
- **P4.5 (#9986):** `<alias>.current` symlink in band dir, maintained by P2 emitter.

## TWO LEAD RIDERS (BINDING — dispatch #10036)
(1) **GO-reroute gate CONSERVATIVE** — fires ONLY on GO/confirm about an ALREADY-DISPATCHED `job_ref`. NEVER `ratify_required`/Tier-B/Tier-C (those go to Director). Log + cc lead on every reroute. ENV KILL SWITCH. False-positive tests MANDATORY.
(2) **recipient-scope `GET /artifact/{ref}`** — P3 shipped it any-authenticated-seat readable; P4 tightens to recipient-scope (only a recipient of a message carrying that `artifact_ref`, or Director). Scope check + 403 test for non-recipient.

## Repos / context contract
- baker-master `~/bm-b3`: session-start hook, GO-reroute gate in bus-post path, band emitter symlink.
- brisen-lab `~/bm-b3-brisen-lab`: `bus.py` (traceparent, receipts, dead-letter, intent-filter alert predicate, recipient-scope /artifact), `db.py`+bootstrap ALTER, `/bus-health` extension.
- Dashboard: delivery-health engine-room page.
- Builds ON P1/P2/P3 — do NOT redo (see brief SCOPE DEDUPE).

## Gate plan
Two-gate: G1 self-verify → independent Claude-side review by lead (codex suspended #9711) → lead merges. Live drill AC + `POST_DEPLOY_AC_VERDICT v1`; deputy assumes named bus-health-owner sweep.

## Test-DB note
Local Postgres localhost:5432. Isolated throwaway DB (`createdb`), `TEST_DATABASE_URL=postgresql://localhost:5432/<db>`, run, `dropdb`. NOT shared Neon test DB. brisen-lab conftest `fresh_db`/`client` fixtures + `X-Terminal-Key: <slug>-key`; shared-key slug set via `BRISEN_LAB_SHARED_KEY_SLUGS`. Baseline dirty count = 27 pre-existing autowake/identity env failures — diff against that.

## Next concrete step
Explore brisen-lab bus.py envelope + /artifact + /bus-health; baker-master bus_post.sh path + session-start hook + P2 band emitter. Then build P4.3 (schema+receipts+dead-letter+traceparent) first as the observability spine, then P4.2 alerting, P4.1 enforcement, P4.4 dashboard, P4.5 symlink.

## Claim discipline
Successor claims by the `attempt:`-bump commit on THIS checkpoint. If `attempt` already bumped by another session, stand down. At `attempt >= 3`, stop resuming + escalate to lead with this path + last error.
