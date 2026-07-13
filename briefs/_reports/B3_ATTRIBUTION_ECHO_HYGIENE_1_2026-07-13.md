# Ship report — ATTRIBUTION_ECHO_HYGIENE_1

- **Builder:** b3 (2026-07-13)
- **Dispatch:** lead #10757 + addendum #10770 (acked/claimed #10777). Effort: low-medium.
- **Repo/PR:** brisen-lab — [PR #135](https://github.com/vallen300-bit/brisen-lab/pull/135), branch `b3/attribution-echo-hygiene-1` off post-#134 `origin/main` @59103ae. ONE micro-PR, three items.
- **Gate:** G1 self-verify PASS → codex bus gate (`review/pr-135`, hard-refresh main) → lead merge.
- **Class:** backend-contract attribution hygiene. Pure server-side field stamping/echo; no schema change (all target columns already exist).

## What shipped (three surgical items)

### Item 1 — `execute_obligation` stored-echo on idempotent replay
Same bug class as the intent P1 codex #10742 fixed in #133: the dedup-hit response echoed `execute_obligation` re-derived from the current request's `kind`, not the stored row — a divergent-kind replay could report `False` for a stored obligation-bearing command. Added `execute_obligation` to the INSERT `RETURNING` + conflict re-`SELECT`; response echoes `row["execute_obligation"]`. `source` is safe as-is (`from_terminal` is part of the idempotency key scope → cannot diverge on a replay) — noted, not touched.

### Item 2 (b1 flag #10750) — client `ratify_decision` insert attribution
The client `ratify_decision` direct-insert (`_ratify_decision_inner`) omitted `source`/`unattributed` (and post-#133, `intent`). Now stamps per the client gate: `is_shared_key = sender_slug in _shared_key_slugs()`; `source = 'daemon' if is_shared_key else sender_slug`; `unattributed = is_shared_key`; `intent = _derive_intent('ratify_decision')` → `'event'`. Not hardcoded FALSE. The client shared-key gate is not weakened.

### Item 3 (b1 flag #10768) — daemon insert paths derive `intent`
`post_daemon_message._insert` + `emit_audit._do_insert` wrote `intent=NULL` post-#133. Now derive `intent` via `_derive_intent(kind)` like the client path — including `emit_audit`'s `escalate_to_aihead` `ratify_required` row (a command → `intent=command`).

## Invariants held
No `VALID_KINDS`/gate change; `_is_delivery_tracked` / `_is_assignment` untouched. The client shared-key gate is not weakened (a shared-key `ratify_decision` still lands `unattributed=TRUE`, proven by test).

## Tests (literal, isolated throwaway local PG)
`tests/test_attribution_echo_hygiene.py` — **5 passed**:
1. `execute_obligation` stored-echo on divergent-kind replay (dispatch→command under key, replay as ack → response + stored row stay `True`);
2. `ratify_decision` attributed per-seat (`source=lead`, `unattributed=False`, `intent=event`);
3. `ratify_decision` shared-key flagged (`source=daemon`, `unattributed=True`);
4. `post_daemon_message` derives `command`/`event`;
5. `emit_audit` derives `event` (audit row) + `command` (escalation `ratify_required` row).

**All 5 load-bearing** — verified each FAILS against `origin/main` `bus.py` and passes with the fix.

**Full suite: 26 failed / 626 passed / 1 skipped = zero new failures** vs the true post-#134 baseline (bus.py=origin/main, test file ignored). Proven by a deterministic failing-set diff: "in-mine-not-baseline" is empty; every one of the 26 is a pre-existing autowake / wake-topic-gate / identity module-global-state cross-file isolation failure. (An earlier run showed baseline 27 — that ±1 is the known flaky autowake nondeterminism; the same-session deterministic diff is the authoritative check.)

Isolation discipline: every run used a per-run `createdb -h /tmp` / `dropdb` throwaway local Postgres (never the shared Neon test DB).

## Note surfaced to lead
Item 2 also stamps `intent='event'` on the `ratify_decision` row (it was `intent=NULL` post-#133 — same gap class as item 3 but on this client path). Folded in because I was already editing that exact insert for attribution (full attribution of the row) — flagged in the claim/report so it can be split if lead prefers.
