# BRIEF: BRISEN_LAB_E1_ACK_NO_OP_DIAGNOSE_1 — ack returns ok:true but acknowledged_at stays NULL (DIAGNOSIS-FIRST, URGENT)

> Authored by deputy (AH2) per lead ruling #9454 (2). **Diagnosis-first** — do NOT ship a
> fix until the root cause is reproduced and confirmed. Separate URGENT lane from F-503.
> Route: free builder (deputy-codex first if free per lead rule); independent codex gate;
> lead merges (standing rule #9255).

dispatched_by: lead
assigned_to: <builder — deputy-codex first if free, else b-code>
task_class: correctness-bug (brisen-lab daemon, ack write/read consistency) — DIAGNOSIS-FIRST
Harness-V2: Context Contract + done rubric + gate plan inline below.
effort: medium (diagnosis-gated; fix scope unknown until root cause confirmed)

## Context

**Context Contract.** Target repo: brisen-lab (`vallen300-bit/brisen-lab`), checkout `~/bm-b<N>-brisen-lab`. Surface: the ack write path (`bus.py ack_msg`, `db.py get_conn`, and the DSN/endpoint config that reads vs writes use). This brief has a **hard diagnosis gate**: Step 1 (reproduce + confirm root cause) MUST complete and be posted to lead BEFORE any fix code is written. The fix scope depends on which candidate cause is confirmed, so pre-committing to a fix here would be over-engineering.

E1 (live-defect evidence log, 2026-07-12), lead-CONFIRMED no fix in flight (#9454): `POST /msg/<id>/ack` returns `{"ok":true}` but `acknowledged_at` **stays NULL** — the ack silently does not persist. Repeated attempts needed. Reproduced live: **#9288 needed 3 ack attempts; #9398 re-surfaced as unread after being acked; #9300 needed 2.** This is a correctness bug the entire claim/ack (and therefore dispatch/rollover) model rests on: an `{ok:true}` that does not change state is a correctness lie.

## Problem

Something between "the ack endpoint returns ok:true" and "a subsequent read sees `acknowledged_at` non-NULL" is inconsistent. The write path *looks* correct on inspection (`bus.py:1274-1314`: SELECT → guard → `UPDATE ... SET acknowledged_at = NOW() WHERE id=%s AND acknowledged_at IS NULL` → `get_conn()` commits on context-manager exit; `db.py:292-300` commits then putconn). So the bug is most likely NOT a missing commit — it is a **read-your-writes / affected-rows / endpoint-split** issue. Diagnosis must find which.

## Step 1 — DIAGNOSIS (hard gate; post findings to lead before any fix)

Reproduce E1 deterministically, then confirm ONE root cause from the candidate list. Deliver a short root-cause note (with evidence) to lead and WAIT for go before Step 2.

**Candidate root causes to check (prioritised — deputy's read of the code):**

1. **Read/write endpoint split (STRONGEST).** `DATABASE_URL` historically pointed at Neon's **POOLED** endpoint; `DB_CONN_HARDEN_1` moved the pool toward the **DIRECT** endpoint. If the ack UPDATE commits on one endpoint/DSN while the inbox read (`GET /msg/<slug>` list) or the `acked` computed field reads through a **different endpoint or a Neon read-replica with async replication lag**, the just-committed ack is invisible for seconds → the message resurfaces as unacked → client re-acks. This fits "needed 3 attempts / resurfaced after ack" exactly. **Check:** confirm reads and writes use the SAME connection/endpoint; grep for any second DSN / replica / `_ro`/`readonly` connection; measure replica lag if a replica exists.
2. **`UPDATE` affected-rows not checked.** `_ack()` returns `("ok", ...)` regardless of `cur.rowcount`. If a concurrent transaction (e.g. the refresh advisory-lock path, or another ack) held the row lock and the UPDATE matched 0 rows under some interleaving, we'd still answer `ok:true` without a write. **Check:** assert `cur.rowcount == 1` on the "ok" branch in a repro; log rowcount.
3. **Commit lost on a half-open (autosuspend) connection.** `get_conn`'s age-gate trusts a "hot" connection (idle < threshold) and skips the `SELECT 1` probe. If such a connection's socket died silently, the `UPDATE`+`commit()` could be sent to a dead socket. (Expected to *raise* → rollback → non-ok — so LOWER likelihood, but verify: does a dropped commit ever surface as `ok:true`?)
4. **Snapshot staleness from a lingering read txn.** If any reader path acquires a connection outside `get_conn`'s commit-on-exit and returns it "idle in transaction", a reused connection could serve a stale snapshot. PG default is READ COMMITTED (fresh snapshot per statement), so this bites only if isolation was raised to REPEATABLE READ/SERIALIZABLE anywhere. **Check:** grep `set_session` / `isolation_level`; confirm READ COMMITTED.
5. **`broadcast_fn` / `_emit_badge_refresh` after commit** cannot cause a NULL `acknowledged_at` (commit already happened) — but confirm no code path rolls back post-commit.

**Reproduction harness (required):** a test/script that (a) posts a message to a test terminal, (b) acks it, (c) immediately reads it back via the SAME path the fleet uses (`GET /msg/<slug>`), and (d) asserts `acked=true`. Run it in a loop / under concurrency to surface the flap. This harness becomes the regression test in Step 2.

## Step 2 — FIX (scope set by confirmed cause; only after lead go)

Likely shapes per cause (do NOT pre-build):
- Cause 1 → pin reads and writes to the same endpoint (or add a read-your-writes guarantee / route acks+reads to primary; if a replica is intentional, add read-after-write routing for the ack-sensitive read).
- Cause 2 → check `cur.rowcount`; if 0 on the "ok" path, return a distinct non-ok/`retry` result so the client knows the write did not land (with an idempotency-safe re-ack).
- Cause 3 → force a probe on the ack write path (never skip liveness for a write), or verify commit round-trip.
- Make ack **transactional + idempotent with a read-back guarantee**: an `{ok:true}` must imply `acknowledged_at` is non-NULL and readable by the next fleet read.

## Files Modified

- Step 1: new `tests/test_ack_read_your_writes.py` (repro harness) + a short root-cause note to lead (bus, not a repo file unless lead wants it in `_reports/`).
- Step 2: TBD by confirmed cause — likely `bus.py` (`ack_msg`) and/or `db.py` (endpoint/DSN config).

## Verification

1. **Repro harness proves the bug BEFORE the fix** (post-ack read shows `acked=false` under the reproducing condition) — this is the diagnosis evidence.
2. Same harness proves the fix (post-ack read shows `acked=true`, 100% over N iterations incl. concurrency).
3. **Idempotency:** re-acking an already-acked message stays `{ok:true, already:true}` and never flips state back.
4. **Post-deploy AC (live):** after merge + deploy, ack a real message and confirm via `GET /msg/deputy` it does not resurface; run the fleet-realistic loop. Emit `POST_DEPLOY_AC_VERDICT v1` to lead. (This directly retires the acks-unreliable footgun flagged all session — deputy hit it live today.)

## Quality Checkpoints / Acceptance criteria

- **done rubric:** (1) root cause reproduced + confirmed + posted to lead (Step-1 gate); (2) lead go before Step 2; (3) fix makes the repro harness 100% green incl. concurrency; (4) idempotent re-ack preserved; (5) live post-deploy AC confirms acks persist with `POST_DEPLOY_AC_VERDICT v1`.
- **done-state class:** production correctness bug → requires reproduced-then-fixed evidence AND live AC, never inspection-only.
- **gate plan:** deputy authors → builder diagnoses → **root-cause note to lead (hard gate)** → lead go → builder fixes → **independent codex verify BEFORE merge** (standing rule #9255) → lead merges → deploy → live AC.
- **Harness-V2:** covered inline.

## Cross-links

- Live-defect evidence log: `wiki/matters/flight-academy/Inter-Agent Communication Design for LLM Agent Fleets/2026-07-12-live-defect-evidence-log.md` (E1; also E2 dedup already shipped `023d95f`, F-503 sibling brief `BRIEF_BRISEN_LAB_F503_BOUNDED_ACQUIRE_1`).
- E1 and F-503 interact: F-503 blind-retries amplify E1's visible pain, but they are distinct bugs — F-503 is capacity, E1 is correctness. Fix independently.
