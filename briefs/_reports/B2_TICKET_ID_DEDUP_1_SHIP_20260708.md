# B2 SHIP — TICKET_ID_DEDUP_1 (A + B1) + BUS_WILDCARD_PENDING_FIX (#7335)

- **Dispatched by:** lead (#7327 re BB #7310; add-on #7335) — ruling #7342 = A + B1.
- **Date:** 2026-07-08
- **PRs:** baker-master #491 (A guard + B1 client + tests) · brisen-lab #105 (B1 daemon + #7335 + tests)
- **Branches:** both `b2/ticket-id-dedup-1`.

## Root cause (forensics, bus #7341 — accepted by lead)
The re-mint was **not** a disposed-dedup gap (the brief's premise). It was a
read-timeout blind-retry loop:
1. `post_ticket_to_bus` → `urllib` read timeout (`baker_actions.error_message` on every
   `bus_failed` = **"The read operation timed out"**).
2. `mark_ticket_failed` → `status='failed'`, `bus_message_id` NULL, `terminal_status` NULL;
   the arrival is not `done`, so `run_tick`'s contiguous watermark **freezes** at it.
3. `reserve_ticket`'s failed-retry path (`status='failed' AND bus_message_id IS NULL` →
   reset to `candidate` + reissue) re-POSTs every tick. A read-timeout is **ambiguous**
   (the daemon likely created the message), so each retry delivered a **duplicate** desk
   message (BB #7310).
4. The desk check-in could not land mid-storm: `_write_checkin` updates `WHERE status='sent'`,
   but the row flapped `candidate`↔`failed`. Both IDs only self-resolved once the daemon
   recovered (16dc → bus #7306; 638 → bus #7312, checked-in DUPLICATE).

The brief's disposed-dedup alone would not have stopped this (a disposed row already has
`bus_message_id` set, so the retry path can't fire on it). Lead ruled **A + B1**.

## What shipped (two repos, additive, deploy-order-independent)
**A — disposed guard** (`orchestrator/airport_ticketing_bridge.py`): `reserve_ticket` returns
a disposed no-op (no failed→candidate reset) when the row is disposed (`terminal_status` set
/ `check_in_at` / status in `rejected|checked_in|closed`); `issue_ticket` propagates
`reason='disposed'`; `run_tick` treats it as a deterministic done (advance cursor, never
re-post). Undisposed-failed posts still retry.

**B1 client** (same file): `post_ticket_to_bus` sends `idempotency_key = ticket_id`.

**B1 daemon** (`brisen-lab/bus.py` + `db.py`): `brisen_lab_msg.idempotency_key` column +
partial `UNIQUE (from_terminal, idempotency_key)`; `_insert()` does `ON CONFLICT DO NOTHING`
+ returns the original message on a key match; side effects (broadcast/wake +
`force_fresh_context`) fire only on a fresh insert (no double-wake). Keyless posts
byte-identical.

**#7335** (`brisen-lab/bus.py` `get_msg`): the UNREAD (pending) view matches named recipiency
only, so unackable `to_terminals=['*']` broadcasts drop out of pending; full-history keeps
the `'*'` OR. Read-side only; ack semantics + named behavior unchanged.

## Amended acceptance (lead #7342)
1. **Read-timeout + retry delivers exactly one desk message** — ✅ daemon dedups on
   `(from_terminal, idempotency_key)`: retry returns the original `message_id`, no new row,
   no re-broadcast. Test `test_idempotency_key_retry_returns_same_message`. Any number of
   client-side timeouts collapse onto the one message created by the first (delivered) POST.
2. **Disposed-id guard holds** — ✅ `test_reserve_ticket_disposed_row_never_reissues` across 5
   disposition shapes (no UPDATE runs); `test_issue_ticket_disposed_does_not_post`.
3. **Check-in lands post-fix (no candidate/failed flap)** — ✅ by mechanism: with B1 the
   retry POST returns 200 (dedup hit) → `mark_ticket_sent` → `status='sent'` → `_write_checkin`
   lands. Covered by the client-key test + daemon-dedup test; no single cross-repo end-to-end
   test (client retry loop + live daemon in one process) — called out honestly.
4. **Regression: daemon key-match + client retry path** — ✅ `test_no_idempotency_key_creates_
   distinct_rows`, `test_idempotency_key_scoped_per_sender`, `test_reserve_ticket_failed_but_
   undisposed_still_retries`, `test_post_ticket_to_bus_sends_ticket_id_as_idempotency_key`.

## Verification (literal pytest)
- baker-master `tests/test_ticket_id_dedup_1.py` + `tests/test_airport_ticketing_bridge.py`:
  **19 passed, 3 skipped** (live-PG skip without `TEST_DATABASE_URL`).
- Regression sweep (box5 runner / checkin / bus drain / nonmail / idempotency-race):
  **94 passed, 68 skipped, 1 failed** — the 1 failure `test_director_inbox_drain::test_12_
  director_key_cache_beats_op_ref_env` fails **identically on clean main** (my changes
  stashed) → pre-existing, env-dependent (op-ref key cache), NOT introduced here.
- brisen-lab suite collects clean (65 tests) with the edited `bus.py`/`db.py`.
- The 3 baker-master live-PG tests + the 4 brisen-lab daemon tests are `TEST_DATABASE_URL`-
  gated and run in CI (Neon branch); not runnable locally (no DSN).

## Notes for lead
- Both PRs need to deploy for the full B1 fix, but they're order-independent (additive).
- Pre-existing test failure above flagged separately — not a blocker for these PRs.
- Gate requested to codex on both PRs.
