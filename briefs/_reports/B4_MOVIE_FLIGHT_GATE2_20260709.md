# B4 Ship Report — MOVIE_FLIGHT_GATE2_ACTIVATION_1

- **Brief:** `briefs/_tasks/MOVIE_FLIGHT_GATE2_ACTIVATION_1.md` @560dcdb9
- **Dispatch:** bus #8136 (from `lead`); diagnose→design ratified across #8142–#8169 (Director two-factor #8154, keyword sign-off #8165, build-A ruling #8169)
- **Branch:** `b4/movie-flight-gate2` (off main @253869c3)
- **PR:** #<pending> → base `main`
- **Date:** 2026-07-09
- **Task class:** feature-build (production routing logic), Tier-B. No migrations, no auth surface. Env changes = post-deploy operator step (below).

## Harness-V2
Task class = feature-build · done-state = **deployed-live-probe-verified** (merged ≠ done; env flip + both live probes + POST_DEPLOY_AC_VERDICT required after merge) · done rubric = §Quality Checkpoints + §Live AC below · gate plan: build → PR → codex G3 (medium, `gate/movie-flight-gate2`) → lead merge → env flip → live probes → POST_DEPLOY_AC_VERDICT.

## What this does (Director-ratified two-factor routing, #8154)
Before: email + WA airport tickets always route to the **global** desk/flight (`baden-baden-desk`/`BB-AUK-001`/`lilienmatt`); per-matter routing existed only on the Plaud lane. So MOVIE arrivals never reached movie-desk/MO-VIE-001.

Now: for a fetched email/WA arrival, resolve the matter by **identity AND content corroboration** —
`factor A` (sender's registered-matter set) `∩` `factor B` (content keyword→matter map). Route to that matter's desk/flight **at mint** iff the intersection is exactly ONE matter. No corroboration / conflict / multi-match on a participant-fetched arrival → neutral **review lane `desk=lead` + `review_reason`** (not the global BB desk — keeps the BB cockpit clean, lead #8160). Keyword-lane / unregistered senders keep today's global behavior (lilienmatt regression byte-identical). The `(e.7)/(e.8)` explicit-code + thread lanes are **untouched** and still win downstream — code stays the strongest signal (#5035 honored: identity never routes alone, content never routes alone).

## Files modified
- `orchestrator/airport_ticketing_bridge.py`
  - `KEYWORD_MATTER_MAP` (MOVIE terms + `aukera`→matter; `riemergasse`/`rg7` deliberately absent per lead #8165 Q2), `_REVIEW_DESK='lead'`, review_reason constants.
  - `_content_matter_set` (factor B, pure), `_two_factor_matter` (resolver, pure), `_sender_matter_set` (factor A, shared-conn registry read, channel-scoped).
  - `AirportTicket.review_reason` field (default `""`; **not** in `payload()` → AIRPORT_TICKET v1 bus contract byte-identical; surfaced in `why_ticketed` for one-glance reroute).
  - `build_email_ticket` + `build_whatsapp_ticket` wired to the resolver (`+conn`), with global fallback. `run_tick` passes `conn`.
- `tests/test_movie_flight_gate2.py` — new, **33 tests** (pure resolver + factor A fake-conn + email/WA wiring).

## Slices (TDD, commit+push+checkpoint per slice — lead #8169 guardrail)
1. Pure resolver core (map + factor B + `_two_factor_matter`) — `2e3a8d52`.
2. Factor A `_sender_matter_set` (registry participants → matters) — `cf18725f`.
3. `build_email_ticket` wiring + `AirportTicket.review_reason` + `run_tick` conn — `11248f87`.
4. `build_whatsapp_ticket` parity — `bade90d1`.
5. This report + PR (env plumbing documented as post-deploy operator step).

## Quality Checkpoints (literal)
1. **Compile — PASS.** `py_compile` clean on `airport_ticketing_bridge.py`.
2. **Tests — PASS.** `test_movie_flight_gate2.py` = **33 passed**. Full airport surface (movie + ticketing_bridge + nonmail_signals + box5_runner + boarding_flow + checkin_reader + lounge_writer + terminal_columns) = **108 passed, 112 skipped** (skips = live-PG, auto-skip without `TEST_DATABASE_URL`), **0 failures**. No pre-existing airport test changed status.
3. **Byte-identical regression — PASS.** `conn=None` and keyword-lane/unregistered paths route exactly as before (existing `test_build_email_ticket_contract_is_candidate_not_judgment` still green; new `test_wire_lilienmatt_keyword_regression_stays_baden_baden` asserts baden-baden).
4. **Singleton guard — PASS.** `bash scripts/check_singletons.sh` → OK.
5. **`git diff --check main...HEAD` — PASS** (clean).
6. **Parity/no-touch — PASS.** `_keyword_ilike_where` untouched (G3 #4957 match/miss parity intact); `(e.7)/(e.8)` code/thread lanes untouched; no AO row/env change; `slugs.yml` untouched; `payload()` unchanged (AIRPORT_TICKET v1 stable).

## Post-deploy operator step (env — AFTER merge+deploy, NEVER before)
Both via `tools.render_env_guard.safe_env_put` (merge-mode single-key PUT — never raw PUT; catastrophic-wipe rule). Order matters: **deploy this code FIRST**, then flip — flipping before deploy would mint participant tickets to the OLD global desk (BB pollution).
1. `BOX5_PARTICIPANT_FETCH_LANE_ENABLED=true` — turns on the participant fetch lane (dark since PR #454); required for MOVIE participant mails to reach Gate-2. **Required for the AC probe.**
2. `AIRPORT_TICKETING_KEYWORDS` append `mandarin oriental,mohg,mo-vie,mo vienna` (keep existing terms) — reachability for MOVIE mails from non-participant senders.
After setting: verify ALL expected keys via Render API GET (don't assume). Open Q for lead: do you run the flip, or authorize me to `safe_env_put` at the post-deploy AC stage?

## Live AC (the done gate — run after merge+deploy+flip)
- **Probe (corroboration):** a MOVIE participant email/WA whose content carries a MOVIE keyword → ticket `desk=movie-desk`, `suspected_flight=MO-VIE-001`, visible on movie-desk check-in.
- **Probe (review lane):** a MOVIE participant identity-only mail (no MOVIE content) → `desk=lead` + `review_reason=identity_only` (NOT baden-baden).
- **Regression:** a lilienmatt arrival → `baden-baden-desk` unchanged.
- Then `POST_DEPLOY_AC_VERDICT v1` to lead, topic `baker-os-v2/movie-flight-gate2`.

## Follow-ups (named, out of scope this PR)
- **Attachment-text corroboration** — ingest does not extract attachment text (`email_attachments` has only `content_sha256`); Director ruled OUT of scope (#8154 pt 4). Follow-up if miss-data shows need.
- **AO/BB content-term expansion** — resolver is matter-generic; adding AO/BB terms to `KEYWORD_MATTER_MAP` gives them per-matter content routing for free (lead #8165 Q3). Separate brief.
- **`review_reason` persistence** — carried on the ticket + bus (`why_ticketed`), not yet an `airport_tickets` column; lead #8160 "work-queue V2 formalizes later."
- **WA sender-format verify** — confirm the stored WA participant `value` on the movie row matches `arrival.sender` format at live probe; if not, per-matter WA is inert-but-safe (global fallback, no misroute) pending a normalization follow-up.
