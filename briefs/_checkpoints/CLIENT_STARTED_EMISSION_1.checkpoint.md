# CLIENT_STARTED_EMISSION_1 — build checkpoint

- brief_id: CLIENT_STARTED_EMISSION_1
- seat: B1
- attempt: 2 (fresh seat resume 2026-07-14, prior seat silent ~80min per lead #11201)
- branch (baker-master): b1/client-started-emission-1 (off main @48e84ec7)
- branch (brisen-lab): b1/client-started-emission-1 (off main @33932d6) — Fix 1 landed @e822591
- status: CLOSED — codex PASS #11229 after 4 clean gate rounds; both PRs MERGED by lead (#11231): brisen-lab #143 @3cd2aa1 + baker-master #561 @fecbbba. Seat RELEASED. Remaining downstream (NOT b1): Render deploy of both → deputy POST_DEPLOY_AC_VERDICT (a real dispatch reply shows started_at within seconds; prod POST /msg/<id>/started flips 405→200). Prior rounds: #11214/#11216 folds (Director-bypass, already_started, emit_started.py parent-or-thread, TOTAL guard) + #11225 (kind=='dispatch' gate) — all landed.
  Folds: (a) Director-bypass removed on /started (strict recipient membership, codex #11216); (b) already_started contract — mark_delivery_started_sync returns started/already_started/escalated, route echoes {ok,state}, at-least-once client + server-COALESCE single authority (lead #11215); (c) NEW scripts/emit_started.py single control point, PARENT OR THREAD match (topic dropped, collision hazard), TOTAL best-effort guard incl generic OSError; (d) brief amended. Counts: P5 endpoint 25 pass; full brisen-lab 27 fail (=baseline wake/identity env) /677 pass; test_bus_post.py 55 pass.
- dispatched_by: lead (#11095), G0 ruling #11121 (OPTION A first-action)

## Ratified shape (LOCKED — do not relitigate)
G0 resolved to **first-action**, NOT pickup (codex #11107 upheld; lead #11121;
#11076 pickup SUPERSEDED). `started` is the TERMINAL delivery state
(mark_delivery_started_sync → delivery_state=started + sla_state=delivered,
brisen-lab db.py:1192-1200), so pickup would mark abandoned-after-pickup as
delivered. Option B (new schema) rejected. No post-started E22 timer here
(separate companion). Full amended spec: briefs/BRIEF_CLIENT_STARTED_EMISSION_1.md
@27857c18.

## What's done
- Brief amended to first-action + committed @27857c18 (header, semantic-choice,
  Fix1 kind=dispatch gate, Fix2 reply-path rewrite, rubric 4+5, Files/Do-Not-Touch/Routing).

## Fix 1 ENDPOINT DONE — brisen-lab @e822591 (branch b1/client-started-emission-1)
- `_started_validate_sync(msg_id, slug, is_director)` added after `_ack_core_sync` (bus.py:833)
  → returns not_found/forbidden/not_dispatch/ok; uses existing `_is_delivery_tracked` (bus.py:107
  = kind=='dispatch' and execute_obligation) — the exact codex gate, already in the codebase.
- `POST /msg/{id}/started` route (bus.py:2648) mirrors /ack (bus.py:2564): freeze gate +
  authz(AUTH_ONLY); 404 / 403 not_recipient / 409 not_dispatch; ok → db_call(mark_delivery_started_sync).
- bus.py compiles clean. mark_delivery_started_sync (db.py:1183) UNCHANGED (COALESCE +
  escalated_at-IS-NULL guard). Already imported in bus.py — no import change.

## What's left
- **Fix 1 TESTS (rubric 1-4)** — mirror harness in `tests/test_case_one_p5_delivery_confirmation.py`
  (694 lines; codex cited 271-277 for started-not-ack). Write: (1) recipient POST /started sets
  started_at (delivery_state='started', sla_state='delivered'), idempotent 2nd call; (2) non-recipient
  → 403; (3) POST after escalated_at set does NOT un-escalate (sla_state stays 'undelivered'); (4)
  non-dispatch → 409 covering BOTH event-kind AND ratify_required (execute_obligation=true, kind!=dispatch).
  Run: no new fails vs the 27-fail brisen-lab baseline.
- **Fix 2 (baker-master)** — emit POST /msg/<id>/started on first NON-ACK kind=dispatch reply, in
  scripts/bus_post.sh (+ bus_post.py parity) + scripts/codex-bus-reply.sh + scripts/codexarch-bus-reply.sh.
  Match by --parent (primary) / thread / topic. Endpoint is the authoritative gate (optimistic client fire OK).
  Best-effort: 404/5xx → log+continue, NEVER alter the post's exit code. NEVER on an ack post. NEVER in
  check_inbox.sh (READ-ONLY #557). Test = rubric 5.

## Key refs (confirmed this session)
- brisen-lab: ack route bus.py:2564 (template); _ack_core_sync bus.py:773; _is_delivery_tracked bus.py:107;
  EXECUTE_OBLIGATION_KINDS={'dispatch','ratify_required'} bus.py:81; mark_delivery_started_sync db.py:1183
  (guard db.py:1190-1196/1209); detect_delivery_started_sync db.py:1269 (fallback). db_gate.db_call pattern.
- brisen-lab checkout ~/bm-b1/brisen-lab now ON b1/client-started-emission-1 @e822591 (refreshed to main @33932d6 first).
- baker-master reply path: scripts/bus_post.sh (+.py), codex-bus-reply.sh, codexarch-bus-reply.sh.

## Next concrete step
Build DONE both sides + PRs open (brisen-lab #143 endpoint+tests @HEAD; baker-master #561
client emission+tests @HEAD). Await codex correctness review, then lead PASS. On merge:
land endpoint #143 FIRST, then client #561 (early client fire needs a gate to hit). After
deploy, deputy runs POST_DEPLOY_AC_VERDICT. Successor: nothing to build — respond to review
findings only (hot-fix loop = NEW commit, never amend). Local test DB used: /tmp pg
bm_b1_started_test (live-PG); full p5 23 pass, full brisen-lab suite 26 fail = wake-daemon
env baseline (≤27), test_bus_post.py 50 pass.
