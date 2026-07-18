# BRISEN_LAB_E1_ACK_NO_OP_DIAGNOSE_1 — Step-1 diagnosis note (to lead; hard gate)

- **Brief:** `briefs/BRIEF_BRISEN_LAB_E1_ACK_NO_OP_DIAGNOSE_1.md` (deputy per lead #9454). Diagnosis-first — no fix until root cause confirmed + lead go.
- **Seat:** b4 · **Date:** 2026-07-12 · **Repo:** brisen-lab (`~/bm-b4-brisen-lab`, main @21a979b).

## Symptom (restated)
`POST /msg/<id>/ack` returns `{"ok":true}` yet `acknowledged_at` stays NULL → message resurfaces as unread → client re-acks. An `ok:true` that does not change state is a correctness lie.

## REPRODUCED (live)
Harness `/tmp/e1_repro.py`: post b4→b4 → single ack → read back via `GET /msg/b4` (list) AND `GET /event/<id>/full` (authoritative), N=40 sequential.
- **3 / 40 flaps (~7.5%)**: ack returned `{"ok":true}` but `/event/<id>/full` showed `acknowledged_at = NULL`.
  - `mid=9501`: ack `ok:true`, **list read `acked=true`** but **`/event` `acknowledged_at=NULL`** in the same cycle.
  - `mid=9545`, `9559`: ack `ok:true`, `/event acknowledged_at=NULL`.
- Co-occurring: **F-503 storm** — 3 `bus_busy_retry` + 6 read-timeouts during the run; total elapsed 998s (heavy pool contention). E1 and F-503 are interacting exactly as the brief predicted (F-503 amplifies E1's visible pain).

## Candidate causes — verdicts
| # | Cause | Verdict | Evidence |
|---|---|---|---|
| 1 | Read/write endpoint split / replica lag | **RULED OUT** | `db.py`: single `_pool`, single `_dsn()` (always rewrites Neon `-pooler.`→direct); no 2nd `psycopg2.connect`, no `_ro`/`readonly`/replica anywhere. Reads and writes share one direct-primary pool. |
| 2 | `UPDATE` affected-rows not checked (concurrent 0-row) | **RULED OUT (empirically)** | Concurrent double-ack burst (15×2): **0/15** left NULL. A single normal ack (production path) has no competing writer, so a 0-row race cannot leave NULL. |
| 4 | Snapshot staleness (REPEATABLE READ) | **RULED OUT** | No `set_session`/`isolation_level`/`REPEATABLE`/`SERIALIZABLE`; PG default READ COMMITTED (fresh snapshot per statement). |
| 3 | Half-open / recycled connection under Neon autosuspend + F-503 churn | **LEADING (unconfirmed sub-mode)** | The only remaining locus. `get_conn` trusts a "hot" conn (idle < threshold) and **skips the `SELECT 1` probe** (db.py:267); commit is at db.py:294. Flaps cluster with the connection-churn storm. |
| 5 | post-commit rollback in `broadcast_fn`/badge | RULED OUT | Both run AFTER `get_conn` has committed+putconn; cannot NULL a committed row. |

## Two open sub-modes under Cause 3 (need one more confirmation)
- **(3w) lost write** — the ack's `UPDATE`+`commit()` is acknowledged on a half-open/recycled pooled connection but not durable.
- **(3r) stale read** — the write IS durable, but an inbox read on a recycled connection serves a pre-ack snapshot, so the message shows unread and the client re-acks. The `mid=9501` split (**list `acked=true`** but **`/event` NULL** same cycle) is a data point toward a read-side inconsistency; it is not yet conclusive.

I could **not** disambiguate 3w vs 3r from the client side: a follow-up probe (re-read the same message 8× to see if `acknowledged_at` flips) was **defeated by the active F-503 storm** — 5/6 posts timed-out/503'd, the one ack itself 503'd (never `ok:true`). Continuing to hammer live only amplifies F-503.

## What confirms it definitively (cheap, server-side)
A ~5-line diagnostic instrument on the ack path, landed to prod, captures the smoking gun under real load without more client hammering:
1. Log `cur.rowcount` after the `UPDATE` on the `"ok"` branch.
2. In the SAME connection/txn, immediately re-`SELECT acknowledged_at` after the UPDATE and log whether it is non-NULL.
3. Log the checked-out conn's idle-age + whether it was probed (hot-trust path vs probed path).
This distinguishes "UPDATE matched 0 rows" (3-variant of 2), "committed but not durable" (3w), and "durable but read-stale" (3r).

## Fix shape (cause-agnostic — do NOT build until lead go)
Per brief §Step 2, the robust fix closes the correctness lie regardless of sub-mode: make ack **transactional + idempotent with an in-txn read-back guarantee** — after the `UPDATE`, assert `cur.rowcount == 1` AND re-`SELECT acknowledged_at` in the same txn; return `{"ok":true}` **only** if it is now non-NULL, else return a distinct `retry`/non-ok so the client knows the write did not land. If (3r) read-side is confirmed, additionally force a probe (never hot-trust) on the ack-sensitive read, or route acks+their confirming read to a freshly-probed connection. This also removes any interaction with F-503 blind-retries.

## Gate status
Holding at the Step-1 hard gate. Requesting lead go on ONE of:
(a) land the tiny server-side diagnostic instrument first to confirm 3w vs 3r under real load, then fix; or
(b) proceed straight to the cause-agnostic read-back-guarantee fix (closes the lie for both sub-modes) with the instrument folded in as belt-and-suspenders.
