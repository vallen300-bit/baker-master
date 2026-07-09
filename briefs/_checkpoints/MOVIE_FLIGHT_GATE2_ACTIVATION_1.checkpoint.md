# CHECKPOINT — MOVIE_FLIGHT_GATE2_ACTIVATION_1

attempt: 2
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

## BUILD-TIME FINDING (attempt 2) — #5035 CONFLICT, escalated to lead, HOLDING
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

## NEXT CONCRETE STEP (successor starts HERE — GATED on lead #5035 ruling)
BLOCKED pending lead's Y-vs-Z ruling on the #5035 reconciliation (above). Do NOT write routing
code until it lands. Once lead rules:
- If Z: add matter_slug to EmailArrival; in the participant lane (~1637) resolve the sender's
  matter via a NEW unambiguous-sender lookup (sender in exactly 1 active registry matter, else
  ""); build_email_ticket + WA builder route via _desk_for_matter/_flight_for_matter/matter with
  global fallback when matter_slug=="" ; keep (e.7)/(e.8) intact (they still win on explicit code).
- If Y: no build_email_ticket routing change — just flip participant lane ON + add MOVIE keywords
  so MOVIE mails FETCH + TICKET to safe-default desk; movie-desk claims; code/thread lanes route
  code-carrying mails. Rework AC wording with lead (mint-desk only for code/thread mails).
Then TDD tests, PR base main, codex G3 medium, lead merge, live probes, POST_DEPLOY_AC_VERDICT.
Keyword list still needs lead sign-off before any env flip (never bare movie; rg7 collides).

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
