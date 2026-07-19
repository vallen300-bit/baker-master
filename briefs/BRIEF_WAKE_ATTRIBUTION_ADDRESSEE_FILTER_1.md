# BRIEF — WAKE_ATTRIBUTION_ADDRESSEE_FILTER_1 (diagnose-first)

- **Brief ID:** WAKE_ATTRIBUTION_ADDRESSEE_FILTER_1
- **Author:** AH2 (deputy) · **Origin:** lead dispatch #13490 (Director-ratified, wake-hardening lane)
- **Builder:** deputy-codex · **Reviewer/gate-router:** AH2 (deputy) · **Gate:** independent `codex` seat · **Deploy:** lead
- **Repo:** brisen-lab (server glance) + baker-master `scripts/cockpit_controller.py` (controller consumer)
- **Class:** diagnostic-first bugfix (Matt Pocock Diagnose gate — AC-1 diagnosis routes to lead BEFORE any code)
- **Priority:** wake-storm reliability; sequenced AFTER the pool fix (now deployed). Not incident-grade; matters for Monday full-autonomous fleet (spurious wakes = wasted seat context + alarm fatigue).
- **Harness-V2:** full blocks below.

## Context Contract (Harness V2)
- **Task class:** production bugfix — server-side count/wake logic; diagnostic-first, single small diff.
- **In scope:** add per-recipient `wake_obligation_count` (dispatch+obligation, non-status-relay); drive the server wake/re-wake decision off it; keep `unacked_count` unchanged for display; (can-wait) empty-`to_terminals` write reject.
- **Out of scope:** controller `cockpit_controller.py` edits (disjoint from Brief B+D); H3 cowork App-residency; H4 #13453/#13457 attribution.
- **Invariants:** REMOVE_WAKE_TOPIC_GATE_1 (no topic gate re-introduced); Director display unchanged; every real addressed dispatch still wakes; existing debounce/dedupe (`WAKE_DEDUPE_SECONDS`, `_WAKE_DEBOUNCE_S`) intact.
- **Done rubric / done-state:** see Done rubric section. **Gate plan:** see Gate plan section.

## Files to touch
- brisen-lab `bus.py` — `_build_terminals_response` (add `wake_obligation_count`); the server wake/re-wake decision (drive off it, per bus.py:105/872 `_is_delivery_tracked` lineage). Optional: write-time empty-`to_terminals` reject.
- brisen-lab `tests/` — regression tests (broadcast / status-relay / real-dispatch).
- Controller `cockpit_controller.py` = NOT touched (out of scope; disjoint from B+D). baker-master = none.

## Verification
- Unit/regression: AC-5 (a broadcast-to-seat, b heartbeat-status-relay-to-seat, c real-dispatch) + AC-7 (empty-`to_terminals` reject) run in `tests/`.
- Live-AC (AC-6, deputy runs on deploy): a seat whose only unacked are broadcast/status-relay shows `wake_obligation_count`=0 and stops re-nudging, checked against the live `/api/v2/terminals` glance; a real dispatch still increments + wakes.

## Problem (symptom)
The tmux-seat controller (`cockpit_controller.py`) wakes a seat when its per-seat `unacked_count` (from the glance `/api/v2/terminals`) is > 0, then nudges "check message #N". Some seats carry an `unacked_count` they can never clear → the controller re-nudges indefinitely → **wake storm / unclearable wake** (PINNED Case-2: baden-baden-desk wake-looped for #13453 as a non-addressee).

## Evidence (captured live 2026-07-19, this session — REPRODUCIBLE)
1. **Broadcasts count toward a seat's wake-driving `unacked_count`.** Live glance `/api/v2/terminals`:
   `cowork-librarian` `unacked_count=2` = msgs **#11801 / #11802 from b1, `kind=broadcast`, topic `fleet/librarian-wiring-probe`** — stuck since ~#118xx (weeks old). A broadcast is a fleet announcement with **no per-seat ack obligation**, yet it inflates the per-seat count that drives wakes.
2. **The glance count has NO kind filter.** `bus.py:3378` (`_build_terminals_response`, deployed = f950386):
   `COUNT(*) FILTER (WHERE acknowledged_at IS NULL) AS unacked_count` over `unnest(to_terminals)` — counts **every kind** (dispatch, broadcast, …). It IS `to_terminals`-addressed-filtered (`WHERE to_terminals && known_slugs … recipient = ANY(known_slugs)`), so the naive "add a to_terminals filter" is **already satisfied here** — the leak is the **missing kind filter**, not a missing address filter.
3. **Inconsistency with the existing escalation policy.** `bus.py:105` already states the system "never re-wakes / escalates a non-dispatch (E15 alarm-fatigue guard)." So the escalation layer treats non-dispatch as non-wake-worthy, but the **count that drives the controller wake counts all kinds** — the two disagree. Surfacing the conflict (Mnilax), not averaging it.
4. **`unacked_total` fleet metric = 2279** while deputy's addressed-unread = 0 — the fleet-wide unacked ledger is dominated by non-actionable / stuck rows, consistent with broadcasts + App-resident cowork-* accumulation.
5. **Ack-eligibility signal:** daemon lifecycle broadcasts (restart/forced-kill) returned **HTTP 403 on ack** by deputy this session — non-addressed broadcasts are not individually ackable, so if any such row is count-eligible for a seat it is **unclearable by that seat**.

## Root-cause HYPOTHESES (to confirm in AC-1 diagnosis — do NOT pre-commit a fix)
- **H1 (lead candidate):** the wake-driving `unacked_count` includes `kind=broadcast` (and possibly other non-dispatch kinds) that carry no per-seat ack obligation → count never reaches 0 → perpetual wake. **Strongest per live evidence (#1/#2/#3).**
- **H2:** a message is count-eligible (`X ∈ to_terminals`) but NOT ack-eligible for X (ack returns 403), i.e. a count/ack asymmetry independent of kind (evidence #5). Would make even a dispatch unclearable.
- **H3:** App-resident cowork-* seats (`cowork-librarian`, `cowork-movie-desk` unacked_count=5, `cowork-ao-desk`=2) accumulate real dispatches they cannot ack — a **separate, known issue** (route-actionables-to-terminal-agents), NOT this brief. Diagnosis must SEPARATE H3 from H1/H2 so we don't "fix" a symptom that is really the cowork-App-residency problem.
- **H4 (lead #13630, from cowork-ah1 #13622) — write-path retry drops the addressee:** during the outage window, empty-response POST **retries landed WITHOUT `to_terminals`** → an unroutable dispatch-intent message that no seat is the addressee of, yet which still increments glance counts / drives a wake. This is how the PINNED Case-2 dead-letters **#13453 / #13457** were born (both since re-posted clean as **#13620 / #13621**; stop-nudge on the originals stands). Distinct from H1 (a real broadcast with a valid multi-recipient array) — H4 is a *malformed* message with a missing/empty addressee. Diagnosis must distinguish an empty/NULL `to_terminals` (H4) from a populated broadcast array (H1).

## AC-1 — DIAGNOSIS (routes deputy → lead BEFORE any code)
Produce a report that, for every seat currently carrying `unacked_count > 0` in the live glance:
1. Splits each stuck row into: (a) `kind=broadcast`/non-dispatch, no per-seat obligation → H1; (b) dispatch, count-eligible but ack returns non-200 for the addressed seat → H2; (c) dispatch, genuinely unacked because the seat is App-resident/offline → H3 (out of scope, hand to the cowork-routing lane); (d) **dispatch-intent with empty/NULL `to_terminals`** (unroutable dead-letter) → H4. Report the count of currently-live rows with `to_terminals` empty/NULL that are not soft-deleted.
2. Confirms whether `kind=broadcast` messages are ack-eligible by an individual recipient at all (probe the ack endpoint for a broadcast row addressed to a terminal seat).
3. States which hypothesis dominates the fleet's current stuck-wake population, with message IDs.
4. Confirms the controller wake path: does `cockpit_controller.py` gate its wake on `unacked_count` alone, or does it already have any kind/dispatch filter (grep `unacked_count`, `_oldest_unacked`, `unacked_messages`, lines ~147/256/656-675)?

## ✅ MODEL LOCKED (lead #13672, 2026-07-19) — build to THIS
- **Option A, server-side only.** Add a per-recipient glance field **`wake_obligation_count`** = count of unacked rows where **`_is_delivery_tracked(kind, execute_obligation)` (bus.py:107) AND NOT `_is_status_relay(topic, body)` (bus.py:156)**. This closes H1 (broadcasts, kind≠dispatch) AND H1' (heartbeat status-relays). The server-side wake decision drives off `wake_obligation_count`.
- **`unacked_count` (all-kinds) is UNCHANGED** — Director dashboard display preserved.
- **Controller (`cockpit_controller.py`) is UNTOUCHED** this brief — stays disjoint from Brief B+D (which own that file). WAKE_ATTRIBUTION diff = brisen-lab `bus.py` (+ tests) only.
- **Empty-`to_terminals` reject** = keep as cheap server-side write-time hygiene IF it lands cleanly in the same small diff; else drop to a can-wait follow-up (lead #13672 — not a blocker).
- **H4 residual (non-blocking):** #13453/#13457 attribution re-routes to H2/H1' or the `unacked_total` aggregate, NOT per-seat wake driving (b4 fail-loud accepted). Not this brief's job to chase; if needed, a server-side query confirms their `to_terminals`.

## FIX DIRECTION (original — superseded by the LOCK above; kept for the hypothesis rationale)
Most likely (if H1 confirmed): align the **wake-driving** count with the dispatch-obligation principle already at `bus.py:105` — exclude `kind=broadcast` (and any non-actionable kind) from the count/list that drives controller wakes. Design choice to settle in the build:
- **Option A (server, preferred):** add a separate glance field `wake_obligation_count` = dispatch-only unacked, and drive the controller wake off THAT; keep `unacked_count` (all-kinds) for Director display so the dashboard total is unchanged.
- **Option B (controller):** `cockpit_controller.py` filters `unacked_messages` to actionable kinds before the wake decision (no server change; but every consumer must re-implement the filter — weaker).
- If H2 confirmed: fix the count/ack asymmetry (make the addressed seat able to ack, or exclude un-ackable rows from the count).
**If H4 confirmed (write-path addressee-drop):** two-sided — (server) **reject or quarantine at POST time any dispatch-intent message whose `to_terminals` is empty/NULL** (fail-loud 4xx, do NOT persist a wake-driving row with no addressee), AND exclude empty/NULL-`to_terminals` rows from the wake-driving count so existing dead-letters stop nudging; (client) the bus-post retry path must **resend the FULL payload including `to_terminals`** on retry — never a partial re-POST that drops the addressee. Confirm the exact retry site in `scripts/bus_post.sh` / the post helper during diagnosis.
Preserve: Director dashboard unacked display; the existing debounce/dedupe (`WAKE_DEDUPE_SECONDS`, `_WAKE_DEBOUNCE_S`); the "every addressed dispatch wakes" rule (REMOVE_WAKE_TOPIC_GATE_1 — do NOT re-introduce a topic gate).

## Acceptance criteria
- **AC-1:** diagnosis report (above) delivered deputy→lead; model + fix locked by lead before code. *(gate)*
- **AC-2:** the wake-driving count excludes non-actionable kinds per the locked model; a `kind=broadcast` addressed to a wakeable seat does NOT increment that seat's wake-driving count.
- **AC-3:** a genuine addressed **dispatch** still drives a wake exactly as today (no regression to the wake-on-dispatch contract).
- **AC-4:** Director dashboard `unacked_count` display behaviour is preserved (or explicitly re-approved if changed).
- **AC-5:** regression tests: (i) broadcast-to-seat → wake-driving count unchanged; (ii) dispatch-to-seat → count increments + wakes; (iii) the stuck cowork-librarian #11801/#11802 class no longer drives a wake.
- **AC-7 (H4):** a POST of a dispatch-intent message with empty/NULL `to_terminals` is rejected/quarantined at the server (fail-loud, no wake-driving row persisted); the client retry path resends the full payload incl. `to_terminals`; existing empty-addressee dead-letters (#13453/#13457 class) no longer drive a wake-driving count. Regression test: retry after an empty-response POST re-sends `to_terminals`.
- **AC-6:** live-AC on deploy: a seat with only broadcast/non-actionable/unroutable unacked shows a wake-driving count of 0 and stops re-nudging; deputy runs it.

## Done rubric
Not "tests pass" — answer: (1) which hypothesis was real (AC-1)? (2) does a broadcast still create an unclearable wake? (must be NO) (3) does a real dispatch still wake? (must be YES) (4) is the Director display unchanged or re-approved? (5) POST_DEPLOY live-AC verdict posted.

## Gate plan
TDD-first (AC-5 tests written first) → independent `codex` verify (BLOCKING, cite PASS id) → deputy cross-lane review → lead merge → lead deploy → deputy POST_DEPLOY live-AC (AC-6). Non-blocking on the ENFORCE ladder. Diagnose gate (AC-1) precedes all code.

## Open questions for lead
1. **Q1 — Option A vs B?** Recommendation: **A (server-side `wake_obligation_count`)** — single source of truth, every consumer benefits, Director display untouched. B re-implements the filter in each consumer.
2. **Q2 — scope of "non-actionable kinds":** exclude only `kind=broadcast`, or also lifecycle/heartbeat/canary? Recommendation: **start with `broadcast` + lifecycle; keep `dispatch` (and any explicit obligation kind) as the ONLY wake-driver**, env-listed so it's tunable without a redeploy. Confirm the kind taxonomy in AC-1.
3. **Q3 — H3 (cowork-* App-resident accumulation):** confirm it is handed to the cowork-routing lane, NOT folded here. Recommendation: **hand off** — it is an App-residency/ack-path issue, a different root cause.
