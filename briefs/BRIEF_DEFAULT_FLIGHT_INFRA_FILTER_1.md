# BRIEF: DEFAULT_FLIGHT_INFRA_FILTER_1 — stop self-originated infra/ops mail minting as real-matter (aukera-annaberg) tickets

> Case One reliability-hardening / ticketing correctness. Authored by deputy (AH2) from lead dispatch
> **#11221** (priority-bumped as authoring-queue brief #3) + lead review-gate **#11250** (items 1+2
> reviewed, #3 unblocked). Third occurrence (#11218): an **`[ARM OUT-OF-BAND RECOVERY/ALARM]` email
> from the Director's OWN mailbox** was minted as an **aukera-annaberg-financing** ticket via the
> participant-identity fetch lane + the default-flight fallback — "keyword fix can't touch this path"
> (the existing `_SKIP_EMAIL_SENDER_PATTERNS` cut is sender-pattern on the keyword lane; this leaks on
> the participant-identity lane and the `_flight_name()` fallback). Prior in the same family: BB-AUK-001
> mis-routes #10554/#10597/#10653 + b1's #10236 (default-fallback family, WA/email paths).
> **TO LEAD FOR REVIEW BEFORE WORKER DISPATCH.** Codex seats lifted (#9711) → cross-vendor codex
> correctness gate available; #9255 independent-verdict-before-merge holds.

dispatched_by: lead (pending review — #11221 priority-bump, #11250 unblock)
assigned_to: <builder — lead assigns after review>
task_class: ticketing-bridge routing correctness (baker-master `orchestrator/airport_ticketing_bridge.py` — an upstream infra-mail suppressor + a neutral review-flight for un-corroborated arrivals; + `tests/test_airport_*.py`. NO brisen-lab, NO dashboard.py route, NO DB migration, NO bus schema)
Harness-V2: Context Contract + done rubric + gate plan inline.
effort: medium

## Context

**Context Contract.** Repo: **baker-master** only — `orchestrator/airport_ticketing_bridge.py` (the email-ticket mint path `build_email_ticket` :896, the automated-arrival gate `_is_automated_email_arrival` :861, the review-lane branch :933-940, the flight resolvers `_flight_name` :758 / `_flight_for_matter` :762 / `_DEFAULT_FLIGHT` :61) + `tests/test_airport_*.py` (+ `tests/test_box5_participant_fetch_lane.py`). **NO dashboard.py, NO brisen-lab, NO migration, NO bus schema.** Two surgical changes: (Fix 1) an infra-ops-mail suppressor upstream of mint; (Fix 2) a neutral review-flight so an un-corroborated arrival never inherits a real matter's flight tag. Follows the existing `_SKIP_EMAIL_SENDER_PATTERNS` (`mio@observer.at`, bb-desk #8413) surgical-cut precedent + the `_NOISE_DESK="unrouted"` neutral-bucket precedent.

**Relevant vault rails:** bus-and-lanes (airport ticketing = the arrivals→ticket mint that feeds desk flights), verification-surfaces (`tests/test_airport_*`), memory-and-lessons ("noisy alert source in dashboard card" / "silent failure accumulation" — an infra alarm mis-filed as a matter ticket is the ticketing analog). **Ignore rails:** standing-contract, skills-and-playbooks, loop-runner.

### Root diagnosis (read the code before writing — two defects feed #11218):
1. **No infra-mail filter reaches the participant-identity lane.** `_is_automated_email_arrival` (:861) drops an arrival only if its **sender** matches `_SKIP_EMAIL_SENDER_PATTERNS` (`noreply@`, `@clickup.com`, `mio@observer.at`, …). The ARM out-of-band mail is sent from the Director's own mailbox via Outlook (`dvallen@brisengroup.com` — a Brisen-controlled OUTBOUND address, `_BRISEN_OUTBOUND_DOMAINS` :157), so it matches NO skip pattern → it is NOT automated by this predicate → it proceeds to mint. The exact subjects (from `scripts/arm_alarm_check.sh:321/345/373`): `"[ARM OUT-OF-BAND ALARM] …"`, `"[ARM OUT-OF-BAND ALARM STILL-FAILING] …"`, `"[ARM OUT-OF-BAND RECOVERY] …"`.
2. **The review lane's flight IS a real matter.** For a participant-fetched arrival with no content corroboration, `_two_factor_matter` (:630) returns `(None, review_reason="identity_only")`, so `build_email_ticket` takes the review branch (:933-940): `desk_slug = _REVIEW_DESK (lead)` — correct — but **`suspected_flight = _flight_name()`** (:940), and `_flight_name()` returns `AIRPORT_TICKETING_FLIGHT` env **defaulting to `_DEFAULT_FLIGHT = "aukera-annaberg-financing"`** (:61/:758). So the ticket's desk is lead-review but its **flight tag is a live matter** — that is the "default-flight fallback" #11218 named: it surfaces in the aukera-annaberg cockpit even though it went to the review desk.

### SCOPE DEDUPE (MANDATORY — lead #9563). Already shipped / owned elsewhere; do NOT re-cover:
- **`_SKIP_EMAIL_SENDER_PATTERNS` + `_is_automated_email_arrival` (:136/:861) — SHIPPED.** Fix 1 EXTENDS the automated-arrival gate with an infra predicate; it does NOT rewrite the sender-skip list (that stays for pure `noreply@` traffic). The reason the skip list "can't touch this path": the ARM sender is the Director, not a `noreply@`.
- **BOX5_GATE2 participant-identity fetch lane (:96-107, `participant_fetched`) — SHIPPED.** Do NOT change fetch; the fix is at MINT (suppress infra) + at the review-flight tag, both downstream of fetch.
- **Two-factor resolver + review lane (`_two_factor_matter` :630, review branch :933) — SHIPPED** (MOVIE_FLIGHT_GATE2, lead #8154/#8160). Fix 2 changes ONLY the `suspected_flight` value on the review branch (real matter → neutral bucket); it does NOT change desk routing (stays `_REVIEW_DESK`=lead) or the resolver.
- **`_flight_name()` / `AIRPORT_TICKETING_FLIGHT` (:758) — SHIPPED + operator-set.** Fix 2 does NOT repurpose the operator's active-flight env — the keyword-lane else branch (:945) legitimately uses it for real keyword traffic. Fix 2 introduces a SEPARATE neutral constant used only on the review branch.

## Problem

An internal ops alarm is not matter correspondence, yet it is minted as a real-matter (aukera-annaberg-financing) ticket — three times now (#11218, BB-AUK-001 #10554/#10597/#10653), each disposed by hand. Two independent gaps let it through: (1) nothing upstream of mint recognizes self-originated infra mail as non-matter, and (2) the fallback flight for any un-corroborated arrival is literally a live matter, so even the review lane mis-tags. Fix either and #11218 stops; fix both and the whole class stops (defense-in-depth: Fix 1 zero-noise-drops the known infra senders/subjects, Fix 2 guarantees anything that slips lands in a neutral review bucket, never a bogus matter).

## Fix (two changes, layered)

### Fix 1 — Infra-ops-mail suppressor UPSTREAM of mint (lead's primary ask)
Add a predicate `_is_infra_ops_mail(arrival) -> bool` and call it in `build_email_ticket` right beside the existing automated-arrival gate (:903), returning `None` (drop-logged via the existing `_DROP_LOG_SAVEPOINT`/drop path — a suppressed infra mail is logged, not silently vanished — fail-loud). Predicate = **self-originated AND infra-subject**, both required (so a counterparty email that merely quotes "[ARM…" is untouched):
- **Self-originated:** sender address/domain ∈ the Brisen-controlled set — reuse `_BRISEN_OUTBOUND_DOMAINS` (`brisengroup.com`) ∪ `_BRISEN_OUTBOUND_ADDRESSES` (:157/:164). (These already model "our own mail"; do not fork a second allowlist.)
- **Infra-subject:** subject matches (case-insensitive substring) an extensible marker tuple `_INFRA_SUBJECT_MARKERS`, seeded from the REAL ARM subjects + generic ops markers: `("[arm ", "out-of-band alarm", "out-of-band recovery", "still-failing", "watchdog", "canary", "fire-drill")`, env-overridable/extendable via `AIRPORT_INFRA_SUBJECT_MARKERS` (comma-split, lower-cased, unioned — mirrors the `_BRISEN_OUTBOUND_DOMAINS` env-read pattern). Read once at module import (rarely-changing, like the outbound allowlist).
This is the surgical zero-noise cut for the known class — mirrors the `mio@observer.at` precedent but sender-scoped-to-ours + subject-gated so it can only ever suppress OUR OWN ops mail.

### Fix 2 — Neutral review-flight so an un-corroborated arrival never inherits a real matter (lead's "review lane that is NOT a real matter flight")
Add a module constant `_REVIEW_FLIGHT = "unrouted-review"` (a neutral non-matter flight label, sibling to `_NOISE_DESK = "unrouted"` :299). On the review branch of `build_email_ticket` (:933-940) change **`suspected_flight = _flight_name()` → `suspected_flight = _REVIEW_FLIGHT`**. Apply the same to the sibling participant-review branches at :1166/:1170 (confirm each is the review-lane, not a corroborated-matter, branch before editing). Leave the corroborated-matter branch (:928-932, real two-factor match) and the keyword-lane else branch (:941-945, operator active-flight) on their current resolvers — those carry real matter signal / operator intent. Net: a ticket that reaches the review desk (lead) now also carries a review-bucket flight tag, so it can NEVER surface in a live matter's cockpit. This is the defense-in-depth net for any infra sender/subject Fix 1 did not enumerate.

## Files Modified
- `orchestrator/airport_ticketing_bridge.py`:
  - `_INFRA_SUBJECT_MARKERS` (new module tuple + `AIRPORT_INFRA_SUBJECT_MARKERS` env union, import-time) near `_SKIP_EMAIL_SENDER_PATTERNS` (:136).
  - `_is_infra_ops_mail(arrival)` (new predicate; reuses `_BRISEN_OUTBOUND_DOMAINS`/`_BRISEN_OUTBOUND_ADDRESSES`) near `_is_automated_email_arrival` (:861).
  - `build_email_ticket` (:903): `if _is_infra_ops_mail(arrival): <drop-log>; return None` beside the existing automated-arrival gate.
  - `_REVIEW_FLIGHT = "unrouted-review"` constant (near `_NOISE_DESK` :299); swap `suspected_flight = _flight_name()` → `_REVIEW_FLIGHT` on the review branch(es) :940 (+ :1166/:1170 if review-lane).
- `tests/test_airport_*.py` (+ `test_box5_participant_fetch_lane.py`): infra-suppress + review-flight cases (below).

## Do NOT Touch
- `_SKIP_EMAIL_SENDER_PATTERNS` entries / `_is_automated_email_arrival` existing behavior — extend, do not rewrite (pure `noreply@` traffic still drops there).
- The participant-identity FETCH lane (BOX5_GATE2) — fetch is correct; the fix is at mint + flight-tag, downstream.
- `_two_factor_matter` resolver logic + the desk routing (`_REVIEW_DESK`=lead) — unchanged; only the review branch's `suspected_flight` value changes.
- `_flight_name()` / `AIRPORT_TICKETING_FLIGHT` env / `_DEFAULT_FLIGHT` and the keyword-lane else branch (:941-945) — the operator's active-flight for real keyword traffic; do NOT repurpose it (that would move ALL keyword traffic off the active flight — wrong blast radius). Fix 2 adds a separate constant instead.
- dashboard.py, brisen-lab, migrations, bus schema — out of scope.

## Engineering Craft Gates
- **Diagnose:** applies. Feedback loop = `pytest tests/test_airport_*.py` (DB-free unit path: `conn=None` makes factor-A empty, exactly the participant-identity shape). Reproduction of #11218: build an `EmailArrival{sender="dvallen@brisengroup.com", subject="[ARM OUT-OF-BAND RECOVERY] report:stale on host", participant_fetched=True}` and run `build_email_ticket` → today it returns a ticket with `suspected_flight="aukera-annaberg-financing"` (the bug). Hypotheses, ranked: (1) `_is_automated_email_arrival` misses it because the sender isn't `noreply@` [confirmed: :861-865]; (2) the review branch tags `_flight_name()`=aukera [confirmed: :940 + :758 + :61]. Probe/regression: the two tests below, each failing pre-fix.
- **Prototype:** N/A — the mint path + review lane already exist; this is a deterministic predicate + a constant swap, no UI/state uncertainty.
- **TDD/verification:** applies. Public seam = `build_email_ticket`'s return (None vs a ticket) + `ticket.suspected_flight`. Write the Fix-1 infra-suppress test first (fails today: returns a ticket; passes after: returns None). Do NOT bulk-write before the predicate exists.

## Verification
1. **Fix 1 (infra suppress):** `build_email_ticket(EmailArrival{sender=dvallen@brisengroup.com, subject="[ARM OUT-OF-BAND RECOVERY] …", participant_fetched=True})` → returns `None`, and a drop-log line records the infra suppression (fail-loud, not silent). Repeat for `"[ARM OUT-OF-BAND ALARM] …"` and `"… STILL-FAILING …"`. **Negatives (must still ticket):** a real counterparty email whose subject quotes "[ARM…" from a NON-Brisen sender → NOT suppressed (self-originated gate holds); a genuine Director email about a matter (no infra marker) → NOT suppressed. Env extension `AIRPORT_INFRA_SUBJECT_MARKERS="deploy-alert"` adds a marker without code change.
2. **Fix 2 (neutral review-flight):** a participant-fetched arrival that does NOT corroborate a matter (e.g. Director sender, no keyword) → ticket `desk_slug`=lead (review, unchanged) AND `suspected_flight == "unrouted-review"` (NOT `aukera-annaberg-financing`). A corroborated two-factor match → still that matter's real flight (unchanged). A keyword-lane unregistered sender → still `_flight_name()` (unchanged).
3. **#11218 end-to-end:** the exact ARM recovery email → Fix 1 suppresses it (no ticket at all); if `AIRPORT_INFRA_SUBJECT_MARKERS` were cleared so Fix 1 is bypassed, Fix 2 still lands it on `unrouted-review`, never aukera-annaberg (defense-in-depth proven).
4. **Cockpit tolerance:** confirm a `suspected_flight="unrouted-review"` ticket renders / groups without error in the review surface (a free-text flight tag the cockpit already treats as metadata; builder confirms no registry-flight assumption breaks — if the flight list is registry-gated, note it and route the review bucket accordingly).
5. **No regression:** existing `tests/test_airport_*.py` + `test_box5_participant_fetch_lane.py` pass unchanged (keyword-lane + corroborated-matter + WA identity paths untouched).

## Quality Checkpoints / Acceptance criteria
- **done rubric:** (1) `_is_infra_ops_mail` suppresses self-originated (Brisen-controlled sender) + infra-subject mail upstream of mint with a drop-log, env-extensible markers, and does NOT touch counterparty or non-infra Director mail; (2) `_REVIEW_FLIGHT="unrouted-review"` replaces `_flight_name()` on the review branch(es) so an un-corroborated arrival never carries a live-matter flight tag, with desk routing + corroborated-matter + keyword-lane branches unchanged; (3) #11218 stops under Fix 1 alone AND under Fix 2 alone (defense-in-depth, both tested); (4) cockpit renders the review-bucket flight without error; (5) full airport test suite green, zero regression on keyword/corroborated/WA paths.
- **done-state class:** routing correctness → unit-test-provable (DB-free `conn=None` path is the exact repro); a live post-deploy spot-check that the next ARM alarm email does not mint a matter ticket (deputy folds into the bus-health/Monday audit). No live drill blocker, but confirm the deploy actually shipped (item-A lesson: a code change to `orchestrator/` DOES trigger a Render build — verify the build deployed before declaring the ARM class closed).
- **gate plan:** deputy authors → **lead reviews BEFORE worker dispatch** → builder implements → **independent verdict BEFORE merge** (codex correctness, cross-vendor #9711; or a Claude-side B-code line-review; #9255 holds) → lead merges → Render deploy → spot-check the next infra alarm email does not mint a matter ticket.
- **Harness-V2:** Context Contract + done rubric + gate plan covered inline.

## Dedupe / cross-links
- **#11218** (third occurrence) + **BB-AUK-001 mis-routes #10554/#10597/#10653** (canary + fire-drill emails from Director's mailbox minted as aukera-annaberg under the default-flight env) + **b1 #10236** (same default-fallback family, WA path) — this brief closes the email side of the class; the WA side is governed by the separate `_wa_identity_*` suppression (do not re-cover).
- **Spec direction (lead #11221):** "infra-sender/subject filter UPSTREAM of mint (ARM/watchdog/canary subjects + self-originated ops mail), OR default unmatched infra → a review lane that is NOT a real matter flight." Fix 1 = the upstream filter; Fix 2 = the not-a-real-matter review flight. Implemented BOTH (defense-in-depth) rather than either/or — the OR would fix #11218, both fix the class (Mnilax: surfaced the choice; both is strictly stronger and low-blast-radius).
- **Deferred (flagged, NOT in this brief):** whether `_DEFAULT_FLIGHT`/`AIRPORT_TICKETING_FLIGHT` should itself be a neutral label rather than a live matter is a broader operator-policy question (it drives keyword-lane traffic too); Fix 2 sidesteps it with a review-only constant. If lead wants the global default neutralized, that is a separate change with fleet-wide blast radius — spin `AIRPORT_DEFAULT_FLIGHT_NEUTRALIZE_1`.
- **Lessons applied:** "noisy alert source" (tight filters, exclude ops/error traffic from matter surfaces); "fault-tolerant writes" (predicate is pure, drop is logged); "verify the deploy shipped" (item-A).
