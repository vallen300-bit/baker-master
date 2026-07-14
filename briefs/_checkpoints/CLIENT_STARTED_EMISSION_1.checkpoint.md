# CLIENT_STARTED_EMISSION_1 — build checkpoint

- brief_id: CLIENT_STARTED_EMISSION_1
- seat: B1
- attempt: 1
- branch: b1/client-started-emission-1 (off main @48e84ec7)
- status: IN_PROGRESS — spec locked, code not yet written
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

## What's left (the build — two repos)
- **Fix 1 (brisen-lab):** new `POST /msg/<id>/started` in bus.py/app.py, mirror the
  ack handler (bus.py:10). Resolve X-Terminal-Key→slug; 403 if slug ∉ to_terminals;
  409/not_dispatch unless `kind='dispatch' AND execute_obligation` (NOT execute_obligation
  alone — ratify_required also has it, bus.py:76-81/84-91); call mark_delivery_started_sync
  inside db_gate.db_call; idempotent (COALESCE); respect escalation guard (db.py:1190-1196);
  LIMIT + conn.rollback() on except. Tests = rubric 1-4.
- **Fix 2 (baker-master):** emit POST /msg/<id>/started on first NON-ACK kind=dispatch
  reply, in scripts/bus_post.sh (+ bus_post.py parity) + scripts/codex-bus-reply.sh +
  scripts/codexarch-bus-reply.sh. Match by --parent (primary) / thread / topic. Best-effort,
  404/5xx → log+continue, never alter the post's own exit code. NEVER on an ack post.
  NEVER in check_inbox.sh (READ-ONLY #557). Test = rubric 5.
- Suites green both repos (brisen-lab: no new fails vs 27-fail baseline).

## Key paths / refs
- brisen-lab endpoint template: ack handler bus.py:10; writer mark_delivery_started_sync db.py:1183;
  P5 filter kind=dispatch AND execute_obligation bus.py:84-91 / db.py:1316; escalation guard db.py:1190-1196.
- brisen-lab checkout: local ~/bm-b1/brisen-lab is STALE SCRATCH — fresh pull origin/main first.
- baker-master reply path: scripts/bus_post.sh (+.py), codex-bus-reply.sh, codexarch-bus-reply.sh.

## Next concrete step
Locate/refresh the brisen-lab checkout (fresh origin/main), then build Fix 1
(the /started endpoint + rubric 1-4 tests) TDD-first. Then Fix 2 client reply-path
emission + rubric 5. Gate chain: b1 self-verify → codex correctness (deputy conformance
to amended shape) → lead PASS → merge endpoint-then-client → deputy POST_DEPLOY_AC_VERDICT.
