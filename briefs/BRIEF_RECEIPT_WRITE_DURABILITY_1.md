# BRIEF: RECEIPT_WRITE_DURABILITY_1 — durable delivery-receipt write under F-503 + created_at-anchored epoch/obligation filter (finding-3 leak fix)

> Case One reliability-hardening. Authored by deputy (AH2, standing bus-health owner) from the
> authoring queue lead greenlit at **#11158** (item 2 of 2; FLEET_DEPLOY_PARITY_1 is item 1).
> Two surgical brisen-lab fixes: **(R1)** make the delivery-receipt write survive the F-503
> recycled-connection churn so a drained message reliably pins `delivered_at` (closes the
> **#557 delivered_at-NULL receipt-drop gap** — #557 was client-read-only and did NOT cover this,
> verdict #11062); **(R2)** anchor the epoch/obligation filter on the message's own `created_at`,
> not the receipt's drain-time `posted_at`, so backfilled receipts can no longer leak pre-cutoff
> messages past the epoch (**finding-3**, codex-arch #11125; the 7 IDs that leaked at the item-A
> epoch flip — verdict #11157). **TO LEAD FOR REVIEW BEFORE WORKER DISPATCH.** Codex seats lifted
> (#9711) → cross-vendor codex correctness gate available; #9255 independent-verdict-before-merge holds.

dispatched_by: lead (pending review)
assigned_to: <builder — lead assigns after review>
task_class: backend-delivery correctness (brisen-lab `db.py` receipt-write durability + `semantic_delivery_evaluator.py` epoch-filter anchor; NO new table, NO new endpoint, NO baker-master, NO host-side launchd)
Harness-V2: Context Contract + done rubric + gate plan inline.
effort: medium (R1) + low (R2)

## Context

**Context Contract.** Repo: **brisen-lab** only — `db.py` (the receipt write `record_delivery_receipts_sync`, db.py:1079, + the pool recycle machinery it rides), `semantic_delivery_evaluator.py` (the three epoch-anchored queries at :379/:403/:434), and `tests_unit/test_semantic_delivery_evaluator.py` + `tests/test_case_one_p5_delivery_confirmation.py` (existing suites). **NO baker-master, NO host-side scripts, NO new migration** (the receipt table already has every column both fixes need — `brisen_lab_delivery_receipt` + the `brisen_lab_msg m` join is already in every query). **No new service, no schema change** — R1 hardens an existing write, R2 changes a WHERE-clause anchor column.

**Relevant vault rails:** bus-and-lanes (delivery-receipt is the P4/P5 delivery fact), verification-surfaces (`semantic_delivery_evaluator` / `/api/semantic_delivery` / `arm_semantic_poll` consume these counts), memory-and-lessons (F-503 = DB_CONN_HARDEN Fix-3 firing at pool maxconn=10 under fleet burst; E1 ack-no-op recycled-conn class). **Ignore rails:** standing-contract, skills-and-playbooks, loop-runner.

### SCOPE DEDUPE (MANDATORY — lead #9563 discipline). Already shipped / owned elsewhere; do NOT re-cover:
- **F-503 bounded-acquire pool fix (brisen-lab #118) — SHIPPED.** That bounded the *acquire* side (a per-request deadline across the recycle loop → `BusPoolExhausted`/503 instead of a hang). R1 is a DIFFERENT layer: the durability of THIS specific write when the acquired connection is recycled/transient mid-write. Do NOT re-touch the pool sizing or the acquire deadline — build on top of them.
- **PR #557 — SHIPPED, but client-read-only (verdict #11062).** It does NOT cover the delivered_at-NULL receipt-drop this brief closes. Do NOT re-diagnose #557; R1 is the server-side write-durability #557 left open.
- **Receipt table / P5 state machine (db.py:679-704) — SHIPPED.** R1 does NOT touch `delivery_state`/`sla_state`/`escalated_at` (the wake→ack→started machine); it hardens ONLY the `delivered_at` pin (the orthogonal P4 "was drained" fact, per the db.py:1089-1093 comment). R2 does NOT touch the receipt row at all — only the evaluator's read filter.
- **Epoch resolver env override (`resolve_receipt_epoch`, semantic_delivery_evaluator.py:301) — SHIPPED + live** (`BRISEN_LAB_RECEIPT_EPOCH=2026-07-14T08:00:00Z`). R2 does NOT change how the epoch is resolved; it changes which column each *consuming query* compares against that epoch.

## Problem

**R1 — a drained message can silently fail to pin `delivered_at` under F-503, so it reads undelivered forever (#557 gap).** `record_delivery_receipts_sync` (db.py:1079) is the P4 drain write: when a recipient's inbox drain returns a message, it `INSERT … delivered_at=NOW() … ON CONFLICT DO UPDATE SET delivered_at=COALESCE(existing, NOW())`. It is called from `bus.py:2421` via `db_gate.db_call(...)`. The write is already idempotent, but it rides the F-503-prone pool (`get_conn()`, maxconn=10): under fleet burst a recycled/stale connection can drop the write (the E1 recycled-conn class) or the acquire can raise `BusPoolExhausted`. When that happens **after the reader already received the message**, the message was delivered but `delivered_at` stays NULL — indistinguishable from a genuinely-undelivered leg. This is the #557 gap and it directly inflates `post_epoch_undelivered` (the count the ARM semantic alarm fires on).

**R2 — the epoch/obligation filter anchors on the receipt's drain-time `posted_at`, so backfilled receipts leak pre-cutoff messages (finding-3).** All three anchored queries in `gather_db_evidence` filter `AND r.posted_at >= %s` (semantic_delivery_evaluator.py:379, 403, 434). But `posted_at` defaults to `NOW()` **at row-creation time** (db.py:684), and for a message whose receipt is minted by the DRAIN path (`record_delivery_receipts_sync`) rather than pre-created at dispatch, that `NOW()` is **drain time**, not message time. So a message *created before* the epoch cutoff but *drained after* it has `posted_at ≥ epoch` and **leaks past the filter**. This is exactly what happened at the item-A epoch flip: 7 pre-cutoff messages (ids **10380, 10503, 10970, 10988, 10990, 10996, 10999**, all <11000) leaked past the 08:00Z cutoff via backfilled receipts (verdict #11157). The `brisen_lab_msg m` table — which carries the message's *own* `created_at` — is **already JOINed** in every one of these queries, so the correct anchor is one column away.

## Fix

### R1 — Durable receipt write: bounded idempotent retry on the recycled-conn/transient class
Wrap the `record_delivery_receipts_sync` write in a bounded retry over the F-503/E1 transient class only (`psycopg2.OperationalError`, `InterfaceError`, connection-closed, `PoolError`/`BusPoolExhausted`) — the write is ALREADY `ON CONFLICT` idempotent, so a retry is safe by construction (a repeated drain never double-writes; `delivered_at` pins first). Bounded: small fixed attempts (e.g. 3) with a short backoff, well inside the existing per-request deadline #118 established — never an unbounded loop that re-enters the exhausted pool. On a `conn.rollback()` per attempt (dirty-connection hygiene — the recurring pool-poisoning lesson). If all attempts exhaust, **fail loud**: log a structured `receipt_write_dropped msg_ids=[…] recipient=… reason=…` line (a real drop is now visible, not silent) — do NOT swallow it. Consider (builder's call, note it in the ship report) whether the drain caller (`bus.py:2421`) should treat an exhausted receipt-write as a soft signal so the next drain re-attempts (the ON CONFLICT makes re-drain self-healing) — but the reader still gets the message regardless; R1's job is that `delivered_at` reliably lands, and a genuine drop is loud. Keep the write on the SYNC path it's on (called under `db_call`); do NOT restructure it to async.

### R2 — Anchor the epoch/obligation filter on `m.created_at`, not `r.posted_at`
In the three `gather_db_evidence` queries (semantic_delivery_evaluator.py:379, 403, 434), change `AND r.posted_at >= %s` → `AND m.created_at >= %s` (the `brisen_lab_msg m` join is already present in each — confirm all three before editing; if any query lacks the join, add `JOIN brisen_lab_msg m ON m.id = r.msg_id`, do NOT invent a column). `m.created_at` is the message's own authoritative creation time (db.py: `created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()` on `brisen_lab_msg`), so the epoch cutoff now excludes every pre-cutoff message regardless of when its receipt row was minted — closing the backfill leak for ALL rows, not just the 7 observed. **Align the fallback epoch (`resolve_receipt_epoch`, :319 `SELECT MIN(posted_at)`):** either switch it to `MIN(m.created_at)` over tracked messages for consistency, OR leave it and add a one-line comment stating the env override is authoritative in production (the fallback only fires on an unset env — currently never). Builder picks; state which in the ship report (Mnilax: surface the choice, don't average it).

## Files Modified
- `db.py` — R1: bounded idempotent retry + rollback-per-attempt + fail-loud drop log around the `record_delivery_receipts_sync` write (db.py:1079-1099). No signature change (callers `bus.py:2421` + tests unaffected).
- `semantic_delivery_evaluator.py` — R2: three anchor swaps `r.posted_at >= %s` → `m.created_at >= %s` (:379/:403/:434); optional `resolve_receipt_epoch` fallback alignment (:319) with a decision note.
- `tests_unit/test_semantic_delivery_evaluator.py` — R2 regression: seed a message with `m.created_at < epoch` but a receipt `posted_at ≥ epoch` (the backfill shape) → assert it is EXCLUDED from `post_epoch_undelivered` / `obligations_open_past_slo` (this test fails today, passes after R2 — the honest vertical proof); replay the 7-ID shape.
- `tests/test_case_one_p5_delivery_confirmation.py` — R1: a receipt write that raises the transient class on attempt 1 and succeeds on retry pins `delivered_at` exactly once (idempotent); an all-attempts-exhausted write emits the fail-loud drop log and does NOT crash the drain.

## Do NOT Touch
- The P5 `delivery_state`/`sla_state`/`escalated_at` state machine + its indexes — R1 hardens only the `delivered_at` pin (orthogonal per db.py:1089-1093). Do NOT stamp or advance the state machine from the drain write.
- The F-503 pool sizing (`_POOL_MAXCONN=10`), the acquire deadline, or `BusPoolExhausted` semantics (#118) — R1 builds on them; retry is bounded to stay inside the request deadline, never re-enters an exhausted pool unboundedly.
- The epoch resolver's env-override precedence (`resolve_receipt_epoch`) — R2 changes only the *comparison column* in the consuming queries, not epoch resolution.
- `record_delivery_receipts_sync`'s idempotent `ON CONFLICT` contract — the retry depends on it; do NOT change the upsert to a plain INSERT.
- baker-master, host-side scripts, any new migration — out of scope (Context Contract).

## Engineering Craft Gates
- **Diagnose:** applies. Feedback loop = the two hermetic suites against a throwaway Postgres (`createdb` / `TEST_DATABASE_URL` / `dropdb`), the pattern the P5/BTUNE suites already use. R2 reproduction: seed the backfill shape (message `created_at < epoch`, receipt `posted_at ≥ epoch`) → today it counts in `post_epoch_undelivered` (the leak), after R2 it is excluded. R1 reproduction: inject a transient-class raise into the write on attempt 1. Hypotheses, ranked: R2 — (1) the filter compares `r.posted_at` which is drain-time for backfilled receipts [confirmed by read: :379 + db.py:684 default]; R1 — (1) the receipt write has no retry and rides the F-503 pool so a recycled conn drops it silently [confirmed: db.py:1079-1099 no retry, `get_conn()`]. Probe/regression: the two new tests above, each failing pre-fix.
- **Prototype:** N/A — both fixes are deterministic on a known-defect query/write; no UI/state-model uncertainty.
- **TDD/verification:** applies. Public seams = `gather_db_evidence` returned counts (R2) and `record_delivery_receipts_sync`'s effect on `delivered_at` + its drop-log (R1). Write the R2 backfill-exclusion test first (fails today, passes after the anchor swap) — the honest vertical proof. Do NOT bulk-write tests before the anchor swap exists.

## Verification
1. **R2 finding-3 (the item-A repro):** seed a message with `created_at = epoch − 1h` whose receipt row has `posted_at = epoch + 1h`, past-SLA, `delivered_at IS NULL` → after R2 it is **excluded** from `post_epoch_undelivered` and `obligations_open_past_slo` (before R2 it counts — the leak). Replay all 7 leaked IDs' shape → all excluded. A genuinely post-epoch undelivered leg still counts (no over-correction).
2. **R1 durability:** a receipt write that raises `OperationalError`/`InterfaceError`/`PoolError` on attempt 1 then succeeds → `delivered_at` pinned exactly once (idempotent; a second drain does not move it). All-attempts-exhausted → a structured `receipt_write_dropped` log line is emitted (fail-loud) and the drain does NOT crash; a subsequent successful drain self-heals the pin (ON CONFLICT). `conn.rollback()` runs on each failed attempt (no pool poisoning).
3. **No regression:** existing `test_case_one_p5_delivery_confirmation.py` + `test_semantic_delivery_evaluator.py` pass unchanged; `/api/semantic_delivery` still returns the same counts for post-epoch data (only pre-epoch backfilled rows change — they stop leaking).
4. **Live AC (deputy, bus-health owner):** post-deploy, `/api/semantic_delivery` `undelivered_post_epoch` should not regain the pre-cutoff leak (the 7-ID class stays out); a real drained message on a live lane reliably shows `delivered_at` set. Emit `POST_DEPLOY_AC_VERDICT v1`. Note: item-A already ran the epoch flip switch-OFF at count 17/1 — R2 makes that count structurally correct (independent of drain timing) rather than epoch-value-dependent.

## Quality Checkpoints / Acceptance criteria
- **done rubric:** (1) `record_delivery_receipts_sync` retries the recycled-conn/transient class bounded + idempotent (ON CONFLICT preserved), rollback-per-attempt, fail-loud structured drop log on exhaustion, no crash to the drain, no signature change; (2) the three `gather_db_evidence` epoch filters anchor on `m.created_at` (join confirmed/added), closing the backfill leak for all rows; (3) `resolve_receipt_epoch` fallback decision stated (aligned or documented-as-inert); (4) R1 + R2 regression tests each fail pre-fix / pass post-fix, existing suites green; (5) live AC + `POST_DEPLOY_AC_VERDICT v1`, the 7-ID leak class provably gone.
- **done-state class:** production delivery-correctness → live AC required (a receipt-write that silently drops or an epoch filter that leaks both feed the ARM semantic alarm — a wrong count here is either a false-page or a false-green).
- **gate plan:** deputy authors → **lead reviews BEFORE worker dispatch** → builder implements → **independent verdict BEFORE merge** (codex correctness, cross-vendor; codex seats lifted #9711; or a Claude-side B-code line-review; #9255 holds) → lead merges → deploy → **deputy verifies live as bus-health owner** + posts `POST_DEPLOY_AC_VERDICT v1`. **Deploy note (item-A lesson):** a Render env change does NOT auto-deploy; a code change to db.py/evaluator DOES trigger a build — confirm the build actually deployed before running live AC (the ~25-min item-A stall). This is exactly the class FLEET_DEPLOY_PARITY_1 makes machine-checkable.
- **Harness-V2:** Context Contract + done rubric + gate plan covered inline.

## Dedupe / cross-links
- **finding-3** (codex-arch #11125) — R2 is its fix; anchor on `m.created_at` not drain-time `r.posted_at`. Root evidence: `briefs/_reports/A_CLEAR_AUDIT_2026-07-14.md` §POST_DEPLOY_AC (the 7 leaked IDs), verdict #11157/#11158.
- **#557 gap** (verdict #11062) — R1 is the server-side write-durability #557's client-read-only fix left open (delivered_at-NULL receipt drops).
- **F-503 / #118 / E1** — R1 sits on top of the bounded-acquire pool fix; it is the write-level durability for the recycled-conn class #118 bounded at the acquire level.
- **Companion (item 1 of the queue):** `FLEET_DEPLOY_PARITY_1` — host-side launchd deploy-parity (distinct object: shell/launchd installer `--check` + manifest, not the bus receipt path). Sequenced before this one per #11158.
- **Lessons applied:** "no rollback in except" → rollback-per-attempt (R1); "unbounded queries / silent failure accumulation" → bounded retry + fail-loud drop log; "column name guessing" → `m.created_at` verified against the `brisen_lab_msg` schema before the swap.
