# BRIEF: WAKE_DISPOSITION_REWAKE_1 — structured wake disposition + re-wake-on-idle + receipt surface

> **STATUS: AUTHORED 2026-07-19 night (lead). DISPATCH BLOCKED until
> WAKE_FORCE_AUTHORITATIVE_READ_1 (B+D + scope-add) merges — same files, ordered
> to avoid conflicts. Dispatch target: deputy-codex (controller side) with b1
> cross-lane contract (listener side).**

dispatched_by: lead
assignee: deputy-codex (controller) + b1 (listener consumer, second phase)
effort: medium
repo: baker-master (scripts/cockpit_controller.py) + brisen-lab (tools/wake-listener/) — cross-repo, ordered
task_class: reliability-fix (closes two Director-visible wake gaps)
Harness-V2: STANDARD — codex gate per repo tip; no Director gate (Tier-A mechanics).

## Context Contract

Reader needs: this brief + `scripts/cockpit_controller.py` (wake endpoint +
glance path) + `tools/wake-listener/wake-listener.py` (dispatch/classify) +
bus threads gates/wake-force-authoritative-read-1 and #13728/#13580. No other
context required; do not load matter libraries.

- **Task class:** production reliability fix, cross-repo, ordered 2-phase.
- **Done-state class / rubric:** DONE = all 5 ACs below hold on LIVE probes
  (not compile-clean); each phase merged only on independent gate PASS on the
  exact pushed HEAD; controller re-synced to App Support + kickstarted.
- **Gate plan:** per-repo-tip independent cross-vendor gate (codex bus seat,
  or lead codex-verify CLI lane when the seat is down) → lead merges → live AC.

## Problem

Three accepted-but-open gaps from the 2026-07-19 wake arc, all sharing one root:
the controller's wake response conflates "I chose not to wake" with "I could not
confirm delivery", and a deliberate skip is never revisited.

1. **Quiet-uncertain drop (deep-verify #13580 + b1 #13728):** listener treats any
   HTTP 200 `{sent:false}` as authoritative; a `sent:false` meaning
   "delivery-uncertain / no telemetry" is indistinguishable from a deliberate
   busy-skip. Logged INFO only. Silent terminal wake drop.
2. **No re-wake after busy-skip (Director live repro 2026-07-19 ~22:42-44Z,
   wake_audit.log `skipped:"working"` × 2, source cockpit_click):** Director
   clicked b1 + codex cards; both skipped as "working"; nothing re-woke either
   seat when it idled; Director had to hand-paste the unacked bus. Obligations
   sit silent until a human intervenes.
3. **Deferred receipt contract (b1 #13670, deferral ruling #13713):** listener
   sends `X-Wake-Request-Id` but controller does not echo it into
   `wake_events`/audit, and no receipt-read endpoint exists — so the listener's
   ambiguous-reconcile-retry stays dormant (strict at-most-once only).

## Task — controller side (deputy-codex, phase 1)

1. **Structured disposition** in every wake response: replace the bare
   `sent:false` + free-string `skipped` with
   `disposition: "delivered" | "skipped" | "undelivered"` + `reason:<string>`.
   - `skipped` = deliberate no-wake (seat working, no obligation, debounce) —
     stays INFO, terminal state, no retry.
   - `undelivered` = controller could not confirm the nudge landed (no
     telemetry, stale glance, tmux write unverified) — the listener/cockpit must
     see this loudly.
   - Keep the legacy `sent` bool in the payload for old clients (derive:
     `sent = disposition=="delivered"`).
2. **Re-wake on idle transition:** when a wake is skipped `reason=working`,
   record the pending obligation (slug + msg_id); when the seat's state
   transitions working→idle (existing glance/telemetry poll) AND the obligation
   is still unacked server-side (`wake_obligation_count > 0`), fire ONE
   deferred wake. Debounce + per-message dedupe rules unchanged (no storm
   regression — dedupe merged @8d8a9413 must gate the deferred wake too).
3. **Receipt surface:** echo `X-Wake-Request-Id` into `wake_events`/audit rows;
   add a read endpoint `GET <receipt-url>/<request_id>` → `{"landed": bool}`
   (auth same as controller endpoints). Shape was pre-agreed in b1 #13670
   contract (a)+(b).
4. **Shared deadline (codex #13742 structural fix):** the wake endpoint must
   bound its OWN total handling time — enforce an internal cumulative deadline
   (env-tunable, default safely below the listener's budget) across glance +
   tmux writes + verification + recovery; on deadline breach return
   `disposition:"undelivered", reason:"controller-deadline"` instead of letting
   the client time out. Optionally honor an `X-Wake-Deadline-Ms` request header
   when lower. This replaces client-side worst-case guessing (interim additive
   budget shipped listener-side in WAKE_LISTENER_NO_LEGACY_FALLBACK_1 round 3).

## Task — listener side (b1, phase 2, after controller merges)

4. Consume `disposition`: `undelivered` → log LOUD (WARNING+) with request-id +
   reconcile via receipt endpoint, retry ONLY via controller when definitively
   not landed (existing at-most-once machinery). `skipped` stays INFO. Absent
   `disposition` field (old controller) → current behavior, no crash.
5. Set `WAKE_RECEIPT_URL` in the listener launchd env; enable the dormant
   reconcile-retry path.

## Files Modified

- Phase 1: `scripts/cockpit_controller.py` (baker-master) + its tests
  (`tests/test_cockpit_*.py`); wake_events/audit write path.
- Phase 2: `tools/wake-listener/wake-listener.py` (brisen-lab) + its tests;
  listener launchd env (`WAKE_RECEIPT_URL`).
- No other files without a flagged scope-add.

## Verification

- Unit: builder's scoped suites green py3.9+3.12 per repo; py_compile +
  diff-check clean; gate PASS on exact HEAD.
- Live: AC2 click-repro on a working seat (wake_audit.log evidence), AC3
  receipt probe `GET /api/wake-receipt/{rid}`, dedupe-guard probe (AC4) —
  all run post-deploy before DONE (Lesson #8: exercise the real flow).

## Constraints (hard)

- NO interim reason-string allowlist heuristics (ruling #13730 — the taxonomy is
  canonical from the controller, never guessed client-side).
- Per-message dedupe + 60s floor + typed repeat windows are invariants; the
  deferred re-wake goes through them, not around them.
- Field-absent fallbacks both directions — mixed-version fleet must not crash.
- Ordered merges: controller (phase 1) merges + deploys + App Support re-sync
  BEFORE listener (phase 2) branches.
- Codex gate on merged-tree per repo tip (Lesson #124), exact HEAD cited.

## Acceptance criteria

- AC1: disposition field live on all wake responses; legacy `sent` preserved.
- AC2: live repro of the Director scenario — click a working seat, seat idles,
  deferred wake fires once, obligation delivered, no duplicate (wake_audit.log
  evidence).
- AC3: undelivered path logs WARNING+ with request-id; receipt endpoint answers
  `{landed:bool}`; listener reconcile-retry proven in a live probe.
- AC4: dedupe/floor guards proven still active on the deferred-wake path.
- AC5: codex PASS both repo tips; ship reports to `briefs/_reports/`.

## Reply target

Bus-post all state changes (start, blocker, ship/gate request, merge) to `lead`
on topic `wake-disposition-rewake-1`. Reply-target = lead.
