# CLIENT_STARTED_EMISSION_1 — build checkpoint

- brief_id: CLIENT_STARTED_EMISSION_1
- seat: B1
- attempt: 1
- branch (baker-master): b1/client-started-emission-1 (off main @48e84ec7)
- branch (brisen-lab): b1/client-started-emission-1 (off main @33932d6) — Fix 1 landed @e822591
- status: IN_PROGRESS — spec locked; Fix-1 ENDPOINT written+compiles; Fix-1 TESTS + Fix-2 remain
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
Write Fix-1 rubric 1-4 tests in brisen-lab tests/ (mirror test_case_one_p5_delivery_confirmation.py),
run them + the suite. Then Fix 2 client reply-path emission + rubric 5. Gate chain: b1 self-verify →
codex correctness (deputy conformance to amended shape) → lead PASS → merge endpoint-then-client →
deputy POST_DEPLOY_AC_VERDICT.
