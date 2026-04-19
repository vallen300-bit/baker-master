# B2 MIGRATION_RUNNER_1 brief re-review (post-fold) — APPROVE

**Reviewer:** Code Brisen #2
**Date:** 2026-04-19 (evening)
**Target brief:** `briefs/_drafts/MIGRATION_RUNNER_1_BRIEF.md` @ v2 fold (head `a532a13`)
**Prior review:** `briefs/_reports/B2_migration_runner_brief_review_20260419.md` @ `4a2c6db` (REDIRECT R1+R2+R3, N1-N4)
**Task mailbox:** `briefs/_tasks/CODE_2_PENDING.md` @ `6594149`
**Verdict:** **APPROVE.** All 7 fold points land cleanly and in most places exceed what I asked for. B1 is cleared to implement.

---

## Fold-point audit — all 7 ✓

| Fold | Where in v2 brief | Status | Notes |
|------|---------------------|--------|-------|
| R1 advisory lock | §Hard-constraints #7 (L222-260) + Test #8 (L373-399) | ✓ | `pg_try_advisory_lock` + 30s timeout + graceful-degrade `return []` + unlock in `finally`. |
| R2 first-deploy | §First deploy behavior (L189-209) + Test #6 (L326-345) | ✓ | 11 files lex-sorted, idempotency invariant stated, Test #6 automates the dry-run. |
| R3 marker convention | §Hard-constraints #8 (L262-266) + Test #7 (L347-371) | ✓ | Grandfather set hardcoded with retirement comment; forward-compat CI gate. |
| N1 AST→refactor | §Scope.IN.3 (L113-132) + Test #5 (L304-324) | ✓ | `startup()` split into `_init_store` / `_run_migrations` / `_start_scheduler`; mock-based order assertion. |
| N2 `TEST_DATABASE_URL` | §Test expectations preamble (L272-280) | ✓ | `pytestmark = pytest.mark.skipif(...)` — matches `tests/test_migrations.py` pattern verbatim. |
| N3 `CONCURRENTLY` footgun | §Hard-constraints #4 corollary (L219) | ✓ | Explicitly names `CREATE INDEX CONCURRENTLY`, `VACUUM`, `ALTER TYPE … ADD VALUE` as non-transactional DDL; routes to out-of-band SQL. |
| N4 column-drift defense | §Scope.IN.2 (L75-92) | ✓ | `information_schema.columns` check post-`CREATE TABLE IF NOT EXISTS`; raises `MigrationError` on missing `{filename, applied_at, sha256}`. |

---

## R1 — deep spot-check (brief re-review focus)

**Lock scope ✓** — code snippet L252-255:

```python
try:
    # ... full apply loop here ...
finally:
    cur.execute("SELECT pg_advisory_unlock(%s)", (_MIGRATION_LOCK_KEY,))
```

Unlock in `finally` wraps the entire apply loop, not individual file applies. This is correct: the lock must persist across all per-file transactions, and `pg_try_advisory_lock` is session-level (not transaction-level) so it survives `COMMIT` boundaries. If any per-file apply raises, `finally` still releases. Good.

**Timeout + graceful degrade ✓** — L234-250:
- `pg_try_advisory_lock` polled every 500ms for up to 30s
- On timeout: `logger.warning(...)`, `return []` — no `MigrationError` raised
- Hard-constraint #5 L220 carves out the exception explicitly: "Exception: the advisory-lock `pg_try_advisory_lock` timeout path WARNs and returns gracefully (see #7); all other failures raise"

Rationale documented at L258: if the sibling crashes mid-apply without releasing, blocking wait deadlocks the blocked replica forever. Timeout + graceful exit means worst case "hole is at most one deploy cycle wide" — defensible trade.

**Lock key ✓** — `_MIGRATION_LOCK_KEY = 0x42BA4E00001` (decimal 4,578,801,451,009). Fits bigint signed range (max 9.2e18). Mnemonic "Baker migrations v1." No collision concern — no other code path in the repo uses `pg_advisory_lock` (verified by grep in v1 review context).

**Test #8 ✓** — sidecar `blocker` connection holds the lock with blocking `pg_advisory_lock`; monkey-patches `_LOCK_TIMEOUT_SECONDS` down to 2.0s for test speed; asserts empty-list return + no `schema_migrations` rows written under contention.

One small gap B1 will need to close at impl time (not a brief fold): the test monkey-patches `config.migration_runner._LOCK_TIMEOUT_SECONDS` but §Hard-constraint #7's code snippet hard-codes `30.0`. B1 must declare `_LOCK_TIMEOUT_SECONDS = 30.0` as a module constant and use it as `deadline = time.monotonic() + _LOCK_TIMEOUT_SECONDS` so the patch lands. Trivial; not brief-level. Mentioning here so the implementer-self-review catches it.

---

## R2 — deep spot-check

**11 files listed in correct lex order ✓** — L195-207. Ordering (which is literal runner-execution order since runner uses `sorted(glob('*.sql'))`):

1. `20260418_expand_signal_queue_status_check.sql`
2. `20260418_loop_infrastructure.sql`
3. `20260418_step1_signal_queue_columns.sql`
4. `20260418_step2_resolved_thread_paths.sql`
5. `20260418_step3_signal_queue_extracted_entities.sql`
6. `20260418_step4_signal_queue_step5_decision.sql`
7. `20260419_add_kbl_cost_ledger_and_kbl_log.sql` ← `add_` < `mac_` < `step5`
8. `20260419_mac_mini_heartbeat.sql`
9. `20260419_step5_signal_queue_opus_draft.sql`
10. `20260419_step6_kbl_cross_link_queue.sql` ← `kbl_` < `signal_` on `step6_` tiebreaker
11. `20260419_step6_signal_queue_final_markdown.sql`

I verified this is the actual lex order against `ls migrations/`. ✓ (My v1 review listed them in PR-landing order which was wrong; B3 correctly re-sorted to runner order.)

**Dry-run committed to test suite ✓** — Test #6 at L326-345 promotes the manual dry-run to a skipif-gated pytest. B1 runs it locally against a Neon throwaway branch pre-seeded to current-prod schema (no `schema_migrations` rows, all tables/columns present). Expected: 11 retroactive claims, 11 `schema_migrations` rows, exit 0. Any error = idempotency bug in one of the 11 files → blocks PR.

**Per-file idempotency tagging ✓** — each of the 11 list entries is annotated with the idempotency mechanism (`ADD COLUMN IF NOT EXISTS`, `DROP CONSTRAINT IF EXISTS ... ADD CONSTRAINT`, `CREATE TABLE IF NOT EXISTS`, `INSERT ON CONFLICT DO NOTHING`, etc.). Forward-invariant stated at L209. Good.

---

## R3 — deep spot-check

**Grandfather set hardcoded ✓** — Test #7 L354-358:

```python
_GRANDFATHERED = {
    # Remove no earlier than Phase 2 — rewrite these two with markers first.
    "20260419_mac_mini_heartbeat.sql",
    "20260419_add_kbl_cost_ledger_and_kbl_log.sql",
}
```

Explicit set (not regex) — no risk of accidentally grandfathering unrelated files. Retirement-date comment calls out Phase 2 as the rewrite trigger. ✓

**Forward-requirement ✓** — Test #7 glob's all `migrations/*.sql`, skips grandfathered, asserts `_UP_MARKER.search(content)` on rest. Fails CI on any new file lacking the marker. Regex is the exact same one used by `tests/test_migrations.py:35-38` so the convention stays DRY. ✓

**Runtime remains file-level ✓** — §Scope.IN.1 L61 explicitly states runner reads files whole (no UP/DOWN parse); §Hard-constraint #8 L266 reinforces "The runner itself remains file-level — no UP/DOWN parse at runtime."

---

## N1-N4 — spot-check

**N1 refactor path ✓** — §Scope.IN.3 shows the refactored `startup()`:

```python
async def startup():
    logger.info("Baker Dashboard starting...")
    _init_store()
    _run_migrations()
    _start_scheduler()
```

Test #5 uses `unittest.mock.patch` to stub all three, attaches to a manager mock, asserts `mock_calls == [call.init(), call.migrate(), call.start()]`. Survives black/ruff reformats. Good. The existing inline DDL at `outputs/dashboard.py:338-399` stays inside `_init_store()` for this PR — decomm is follow-up brief scope.

One sub-observation B1 will encounter: `_init_store()` currently returns nothing (calls `_get_store()` + does inline DDL in the try/except wrapper). The refactor should preserve the existing `try: … except Exception as e: logger.warning("... will retry")` swallow at `dashboard.py:400-401` — that warn-and-continue is correct for store pre-warm (Postgres cold-start) and semantically different from the migration runner's raise-loud behavior. Brief doesn't restate this but B1 will see it during impl; not a brief-level concern.

**N2 convention ✓** — L272-280. Drops `testing.postgresql` / `pg_fixtures` (not in `requirements.txt`), uses `TEST_DATABASE_URL` gate. Matches `tests/test_migrations.py:27-32` verbatim.

**N3 CONCURRENTLY ✓** — L219. Names the three specific DDL classes that break per-file BEGIN: `CREATE INDEX CONCURRENTLY`, `VACUUM`, `ALTER TYPE ... ADD VALUE` (pre-PG12). Routes them out-of-band. The corollary's last sentence ("runner doesn't enforce concurrency … but this brief flags the gotcha for the author-checklist in a future `docs/ops/migrations_conventions.md`") correctly scopes the enforcement to human discipline + future doc.

**N4 column-drift ✓** — L77-90. Query against `information_schema.columns` with `current_schema()` (not hard-coded `'public'`) so it works under non-default schemas. Expected set `{filename, applied_at, sha256}` computed as a set difference; error message names the missing columns explicitly. ✓

---

## CHANDA — correctly re-framed

Inv 9 framing at L426 now reads:
> "Inv 9 (extended by analogy): Mac Mini is the single AGENT writer for signals (literal Inv 9 per `memory/MEMORY.md` → `project_mac_mini_role.md`). By analogy, Render is the single SCHEMA writer for migrations. Mac Mini poller does not call the runner; the `pg_try_advisory_lock` additionally serializes within Render itself. Respected."

This correctly distinguishes literal Inv 9 from the analogical extension — which was the nit I flagged at v1 review bottom. ✓

---

## Timeline accuracy

v1 estimate: ~60-90 min. v2 estimate: ~110-130 min. Delta (+~40 min) is honestly tracked in §Timeline L431-438:
- +advisory lock impl ~10 min
- +dry-run audit ~15 min
- +Test #7 marker CI ~5 min
- +Test #8 advisory-lock contention ~10 min

Fair. B1 should plan for ~2h and finish slightly under.

---

## What's still right (rolled forward from v1)

All the v1-positive items remain intact:
- Module location `config/migration_runner.py` ✓
- Connection independence via `psycopg2.connect(DATABASE_URL)` mirroring `kbl/db.py` ✓
- Per-file transaction ✓
- sha256 mismatch → `MigrationError` + documented rollback via `DELETE FROM schema_migrations WHERE filename='…'` ✓
- Mac Mini poller opt-out ✓ (now with improved CHANDA framing)
- Inline DDL decomm = follow-up brief ✓
- Director-ratified ship-now path ✓

---

## No residual nits that block

Three polish items I noted during spot-check, none blocking and none worth a second REDIRECT:

1. **`_LOCK_TIMEOUT_SECONDS` module constant.** Test #8 monkey-patches it; §Hard-constraint #7's code snippet hard-codes `30.0`. B1 declares the constant at module top during impl. Implementer-self-review catch.
2. **`_init_store()` swallow semantics.** Preserve existing `try: … except: logger.warning(...)` around `_get_store()` call — store pre-warm is correctly warn-and-continue (Postgres cold-start), semantically different from `_run_migrations()` raise-loud. B1 sees this during refactor.
3. **§Hard-constraint #5 forward-refs #7** ("Exception: the advisory-lock path … (see #7)") — minor prose flow; reader hits the forward-ref before reaching §#7. Readable as-is.

None are brief-level. All can be handled by B1 during impl.

---

## Dispatch

**APPROVE.** All 7 fold points land cleanly: R1 advisory lock with proper try/finally scope + graceful-timeout + Test #8; R2 first-deploy behavior with lex-correct file list + automated dry-run Test #6; R3 grandfather set hardcoded + Test #7 marker CI gate; N1 startup refactor with mock-based order assertion; N2 `TEST_DATABASE_URL` convention; N3 CONCURRENTLY footgun named + routed out-of-band; N4 column-drift defense via `information_schema.columns`. CHANDA Inv 9 framing correctly analogical. Timeline honestly re-estimated at ~110-130 min.

**Post-approval path (per AI Head's dispatch):**
1. AI Head dispatches B1 for MIGRATION_RUNNER_1 impl PR (~110-130 min).
2. B1 runs Test #6 dry-run locally against a Neon throwaway branch pre-seeded to current-prod; audits 11 retroactive claims.
3. B1 opens PR on branch `migration-runner-1`; B2 reviews for impl-level fidelity (separate from this brief-level approve).
4. On B2 APPROVE + `MERGEABLE`: AI Head auto-merges. Next Render boot claims 11 retroactive migrations; all future PRs auto-apply.

Report: `briefs/_reports/B2_migration_runner_brief_rereview_20260419.md`. Closing terminal tab per directive.
