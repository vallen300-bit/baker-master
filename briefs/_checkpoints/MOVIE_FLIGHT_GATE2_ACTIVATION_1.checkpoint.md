# CHECKPOINT — MOVIE_FLIGHT_GATE2_ACTIVATION_1

attempt: 3
brief_id: MOVIE_FLIGHT_GATE2_ACTIVATION_1
brief: briefs/_tasks/MOVIE_FLIGHT_GATE2_ACTIVATION_1.md @main (560dcdb9)
branch: b4/movie-flight-gate2 (off main @253869c3)
dispatched_by: lead (bus topic baker-os-v2/movie-flight-gate2)
reply_target: lead
scope_confirmed: bus #8143 — option (a) CODE change (feature-build, ~6h, PR + codex G3 medium)
reason_for_checkpoint: context 45-50%; lead ordered checkpoint+respawn FIRST before build (#8143 step 1)

## WHAT'S DONE (diagnose gate 1 — CLOSED, lead scope-confirmed #8143)
- Full prod diagnosis posted to lead as bus #8142; lead ruled option (a) in #8143.
- Git-archaeology on BOX5_PARTICIPANT_FETCH_LANE_ENABLED (lead step 3): **never-enabled, shipped
  dark by design** — introduced by BOX5_GATE2_PARTICIPANT_FETCH_LANE_1 / PR #454 (commit 9d126ace)
  as "dark, additive"; no later on/off commit; Render env never set it. NOT a deliberate
  cost/noise-driven off. => flag-flip to ON is a legit first-activation, done AS PART OF THE PR
  (not a silent env change).

## KEY FINDINGS (prod ground truth — carry forward)
- project_registry: 3 active rows — ao/AO-OSK-001/ao-desk, aukera/BB-AUK-001/baden-baden-desk,
  movie/MO-VIE-001/movie-desk (37 participants, desk_code MOVIE). NO mo-vie-am / mo-vie-exit /
  oskolkov rows. Registry is keyed on SHORT slug. Lead #8143 step 5: registry stays as-is, NO new rows.
- Live env AIRPORT_TICKETING_KEYWORDS = aukera,annaberg,lilienmatt,merz,weippert,brandner,pohanis,
  dragovan,sardarov,skliar (no MOVIE term).
- Global routing env (email+WA tickets all carry these): desk=baden-baden-desk, matter=lilienmatt,
  flight=BB-AUK-001. Prod airport_tickets: 58 email + 121 WA all -> baden-baden-desk/BB-AUK-001/
  lilienmatt; ZERO email/WA ever -> ao-desk/AO-OSK-001. Only PLAUD does per-matter (5 AO plaud, 1 to ao-desk).
- BOX5_PARTICIPANT_FETCH_LANE_ENABLED unset on Render => OFF (participant widening dark).
- Render service id: srv-d6dgsbctgctc73f55730. Env READ: op item "API Render" field `credential`
  (32-char key) -> GET https://api.render.com/v1/services/<srv>/env-vars?limit=100.
  Env WRITE: MUST use tools/render_env_guard.safe_env_put (merge mode, single-key PUT) — NEVER raw
  PUT (catastrophic-wipe rule, .claude/rules/python-backend.md). Live flight probe: X-Baker-Key
  (fallback `bakerbhavanga` works) against baker-master.onrender.com/flight/MO-VIE-001.

## CONFIRMED DESIGN (lead #8143 — build to this)
Per-arrival routing for email + WA lanes (mirror the Plaud lane, which already works):
1. Turn participant lane ON (BOX5_PARTICIPANT_FETCH_LANE_ENABLED) as part of the PR.
2. Carry the registry matter_slug into email/WA tickets: add `matter_slug` to EmailArrival (and the
   WA arrival shape), resolved at the participant-fetch construction from the matched registry row.
3. Make build_email_ticket + the WA builder route via _desk_for_matter(matter_slug, conn) /
   _flight_for_matter(matter_slug, conn) + set suspected_matter_slug=matter_slug — EXACTLY like
   build_plaud_ticket (reference impl). Global env stays the FALLBACK for non-matched arrivals so
   BB-AUK-001 regression is byte-identical.
4. Registry: NO new rows (keyed on short slug movie/ao already).
5. Keyword list: proposed AFTER design lands, collision-checked, lead sign-off BEFORE any env flip.
   HARD: never bare `movie`; `rg7` collides with hagenauer-rg7. Candidates: "mandarin oriental",
   "riemergasse" (collision-check both). Note: this fix also revives PR #483 on email/WA for AO +
   every future flight (lead's rationale) — keep the change generic, not MOVIE-special-cased.
AC (unchanged): seeded MOVIE email/WA probe mints desk=movie-desk + suspected_flight=MO-VIE-001,
visible on movie-desk check-in; lilienmatt regression probe still baden-baden-desk (byte-identical).

## KEY CODE PATHS (orchestrator/airport_ticketing_bridge.py unless noted)
- EmailArrival dataclass ~175 (has participant_fetched:190; ADD matter_slug field here).
- build_email_ticket:671 — desk=_desk_slug():691, matter=_matter_slug():730, flight=_flight_name():731
  (these three lines are what to convert to per-arrival, with global fallback).
- WA builder ~892 (suspected_matter_slug=_matter_slug():898) — same conversion.
- build_plaud_ticket:792 — REFERENCE per-matter impl (_desk_for_matter:810, _flight_for_matter:842).
- _desk_for_matter:491 · _flight_for_matter:537 · desk_owner_for_matter kbl/project_registry_store.py:288.
- participant lane: _PARTICIPANT_LANE_ENV:105 · participant_lane_enabled():375 · email-arrival
  construction ~1671-1681 (participant_fetched set from participant_only_ids — ALSO resolve+carry
  matter_slug here from the participant's registry match).
- run_tick:2532 (email build call ~2675) · active_keywords:357 · _DEFAULT_KEYWORDS:58 · _KEYWORDS_ENV:49.
- Do NOT touch _keyword_ilike_where (match/miss parity, G3 #4957) — append config only. Do NOT touch
  AO flight rows/env or slugs.yml.
- Tests: tests/test_airport_ticketing_bridge*.py (existing bridge conventions; live-PG cases).

## RATIFIED DESIGN (Director ruling, relayed lead #8154) — BUILD TO THIS
Two-factor hybrid ("match the name PLUS the content, and ideally a project number"):
1. e.7/e.8 explicit-code + thread-continuity lanes UNTOUCHED — code always wins, strongest signal (#5035).
2. NEW resolver = identity AND content corroboration. For a participant-fetched email:
   - candidate set A = the active registry matters the SENDER is a participant in (sender->matter-set).
   - candidate set B = the matters whose CONTENT keywords match subject+full_body (needs a NEW
     keyword->matter map; today the keyword list is flat/global).
   - route to that matter's desk/flight AT MINT iff A ∩ B == exactly ONE matter. Handles multi-matter
     senders (Buchwalder+Riemergasse->MOVIE; Buchwalder+drawdown->AO).
3. No corroboration / conflict / multi-match -> safe-default desk-review, NEVER guess. #5035 core: never name alone.
4. Content haystack = subject + full_body (existing Gate-2). Attachment text: ingest does NOT extract it
   (email_attachments has only content_sha256 + no text col; full_body = body only) -> OUT of scope,
   note attachment-text extraction as a FOLLOW-UP (Director spec pt 4).
5. AC (amended): seeded probe = MOVIE participant + MOVIE keyword content -> desk=movie-desk +
   flight=MO-VIE-001 at mint; identity-only (no content corroboration) -> review lane by design;
   lilienmatt regression unchanged.
6. NEUTRAL REVIEW DESK (LEAD RULING #8160): uncorroborated / conflict / multi-match tickets mint
   proposed_desk_slug=`lead` + a NEW `review_reason` tag on the ticket, value in
   {identity_only, conflict, multi_match}, so lead reroutes one-glance. NO new agent/slug/pseudo-slug
   (bus recipient validation would 400 it). The GLOBAL env desk (baden-baden) stays the fallback ONLY
   for non-participant traffic (today's behavior, unchanged) — it is NOT the review destination. BB
   cockpit stays clean. NOTE: `lead` must be a valid bus recipient (it is) and resolve_owner_slug/
   RESERVED_RECIPIENTS must allow it as a proposed desk — verify at build (if `lead` is reserved,
   raise with lead for the exact review-desk slug).
7. Keyword list + keyword->matter map: **SIGNED OFF by lead #8165 (gate CLEARED). FROZEN spec:**
   - PART A — FETCH terms to APPEND to AIRPORT_TICKETING_KEYWORDS (env flip, at PR/deploy):
     'mandarin oriental', 'mohg', 'mo-vie', 'mo vienna'. EXCLUDE bare 'movie', 'rg7', 'riemergasse'.
   - PART B — CONTENT->MATTER map (factor B), MOVIE-ONLY this PR:
     movie (MO-VIE-001) <- {'mandarin oriental','mohg','mo-vie','mo vienna'} ; aukera (BB-AUK-001) <- {'aukera'}.
   - Q1 (CONFIRMED): the 7 surnames (merz/weippert/brandner/pohanis/dragovan/sardarov/skliar) stay FETCH-ONLY,
     EXCLUDED from the Part-B content map (identity never double-counts as content).
   - Q2 (RULED): DROP 'riemergasse' ENTIRELY for v1 — Moravcik & other construction names are in BOTH the
     MOVIE registry AND the hagenauer-rg7 dispute at Riemergasse 7, so identity-gating does NOT disambiguate
     building-address content (a Hagenauer-dispute mail from such a sender would misroute to MOVIE). Revisit
     only with live miss-data. Do NOT add riemergasse to Part A or Part B.
   - Q3 (RULED): MOVIE-only content map this PR; AO/BB content-term expansion = FOLLOW-UP brief (the resolver
     is generic, so ao/aukera inherit per-matter content routing for free once terms are added later).
   - Env flip still executes at PR/deploy time, documented (not silent).
8. Attachment-text extraction (LEAD RULING #8160): accepted OUT of scope; content = subject+full_body
   only; log attachment-text extraction as a named FOLLOW-UP in the ship report.

## (superseded) BUILD-TIME FINDING (attempt 2) — #5035 CONFLICT, escalated to lead, RESOLVED by #8154
Discovered on build entry (before writing code): email/WA per-matter routing ALREADY EXISTS
downstream in run_tick, but keyed on EXPLICIT PROJECT CODE / THREAD, not identity:
- (e.7) EXPLICIT-CODE ROUTED LANE (bridge:2895 → desk_owner=resolved["desk_owner"] :2938):
  a mail carrying exactly one registered ACTIVE project code reroutes to that matter's desk.
- (e.8) THREAD-CONTINUITY LANE (bridge:2973 → :3023): routes by prior code-routed thread when
  the mail carries NO explicit code; never overrides an explicit code.
- build_email_ticket (691/730/731) sets GLOBAL desk/matter/flight as the BASE; the (e.7)/(e.8)
  lanes reverse it when a code/thread signal exists. That's why prod shows all email→baden-baden
  (BB mails carry BB codes; AO mails carry no "AO-OSK-001" literal, so never reach ao-desk).
- Director ruling #5035 (comment bridge:1628-1635): the participant lane uses identity ONLY to
  FETCH — routing decided by project CODE, NEVER by which projects a sender belongs to. A sender
  in >1 active project sending a code-less mail is AMBIGUOUS → safe-default desk-review TICKET,
  never auto-picks a desk.
CONFLICT: lead #8143 design ("carry registry matter_slug into email/WA tickets + route via
_desk_for_matter") is IDENTITY-routing — it softens #5035 and overlaps (e.7)/(e.8). Do NOT build
identity-routing until lead reconciles. Options posted to lead (bus, this topic):
  Y (strict #5035): identity-only mails go to safe-default desk; MOVIE routes to movie-desk only
    via explicit MO-VIE-001 code / thread continuity. AC "mint desk=movie-desk" met only for
    code-carrying/seeded mails. Smallest change (participant lane ON + keyword fetch; routing
    already works via e.7/e.8). Honors Director #5035 verbatim.
  Z (bounded relax = lead #8143 intent, my lean): identity routes per-matter ONLY when sender is
    unambiguously in exactly ONE active matter; multi-matter sender → global (preserves #5035's
    core). Meets AC at mint for single-matter MOVIE participants. Needs sender→matter resolution
    in the participant lane + a sender-unambiguity guard; coexist with (not duplicate) e.7/e.8.
Escalation bus id: (see topic baker-os-v2/movie-flight-gate2). HOLDING for lead ruling Y vs Z.

## STATUS: keyword gate CLEARED (lead #8165). BUILD UNBLOCKED — fresh seat claims attempt 3->4.
All design + keyword decisions are FROZEN (see RATIFIED DESIGN pts 1-8 above). Nothing left to ask lead
before coding EXCEPT: verify `lead` is an allowed proposed_desk_slug (resolve_owner_slug/RESERVED_RECIPIENTS)
— if reserved, raise for the exact review-desk slug. First deliverable (keyword list+map) DONE + signed off;
skip it. Fresh seat: bump attempt 3->4 and go straight to the code layer below.

## NEXT CONCRETE STEP (successor starts HERE — design RATIFIED #8154, keywords SIGNED OFF #8165, build is large/multi-file)
Ratified two-factor design above. Build order (TDD-first, branch b4/movie-flight-gate2):
1. Keyword->matter map: extend the keyword config so each active keyword carries its matter/flight
   (aukera->BB-AUK-001, MOVIE terms->MO-VIE-001, AO surnames->AO-OSK-001, lilienmatt/annaberg->BB).
   Preserve _keyword_ilike_where match/miss PARITY (do NOT touch that predicate — G3 #4957); the map
   is a SEPARATE lookup layered on top. Content-match factor B = matters whose mapped keywords hit
   subject+full_body.
2. Sender->matter-set (factor A): from project_registry participants — which active matters list this
   sender (email) as a participant. (active_participant_values already builds the email allow-set:1525.)
3. Resolver: A ∩ B; route only if == 1 matter -> _desk_for_matter/_flight_for_matter for that matter.
   Add matter_slug to EmailArrival (default "") + WA arrival; populate from the resolver at fetch/build.
4. Neutral review desk = `lead` + `review_reason` tag {identity_only|conflict|multi_match} (LEAD #8160,
   design pt 6). NO new slug. Add `review_reason` to AirportTicket (default "", NOT in payload() unless
   the bus contract needs it — check) + the reserve_ticket/airport_tickets column if it must persist.
   Global env desk stays fallback for NON-participant traffic only.
5. Participant lane ON (env flip inside PR, documented). FIRST DELIVERABLE before ANY env flip: keyword
   list + keyword->matter map to lead, collision-checked, sign-off.
6. TDD tests: (a) MOVIE participant + "mandarin oriental"/"riemergasse" content -> movie-desk/MO-VIE-001;
   (b) multi-matter sender + MOVIE content -> MOVIE; + AO/drawdown content -> AO; (c) identity-only no
   content -> review lane; (d) lilienmatt keyword -> baden-baden (regression byte-identical); (e) e.7/e.8
   still win on explicit code. Live-PG cases per existing conventions (tests/test_airport_*).
7. pytest literal green -> PR base main -> codex G3 medium (gate/movie-flight-gate2) -> lead merge ->
   live probes (seeded MOVIE + lilienmatt regression) -> POST_DEPLOY_AC_VERDICT to lead.
SIZE NOTE: this is now a multi-file feature (new keyword->matter subsystem + resolver + neutral desk +
tests), > the original ~6h estimate. Predecessor did all diagnosis + design ratification; a FRESH seat
should carry the build with clean context. Do NOT redo diagnosis/design.

## (superseded) ORIGINAL/Y-vs-Z NEXT STEPS — replaced by the ratified two-factor build above

## ORIGINAL NEXT STEP (pre-#5035-finding — SUPERSEDED by the gate above)
TDD-first on branch b4/movie-flight-gate2:
1. Write failing tests: (a) MOVIE registered-participant email arrival -> ticket desk=movie-desk,
   suspected_flight=MO-VIE-001, suspected_matter=movie; (b) lilienmatt keyword email -> baden-baden-desk
   (regression, byte-identical); mirror both for WA.
2. Add matter_slug to EmailArrival + resolve it at participant-fetch construction (~1671).
3. Convert build_email_ticket (691/730/731) + WA builder (898) to per-arrival _desk_for_matter/
   _flight_for_matter/matter with global fallback. Keep the diff generic (benefits AO too).
4. Flip BOX5_PARTICIPANT_FETCH_LANE_ENABLED ON as part of the PR (document, not silent).
5. Run pytest (literal green), open PR base main, request codex G3 (medium) on
   gate/movie-flight-gate2, ship report -> lead.
6. AFTER design lands: propose collision-checked keyword list to lead; sign-off BEFORE env flip.
7. Then live probes (seeded MOVIE + lilienmatt regression) + POST_DEPLOY_AC_VERDICT to lead.
Gate plan: build -> PR -> codex G3 medium -> lead merge -> live probes -> POST_DEPLOY_AC_VERDICT.
