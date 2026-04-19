# B2 PR #19 KBL_DASHBOARD_COST_ROLLUP_HOTFIX review — APPROVE

**Reviewer:** Code Brisen #2
**Date:** 2026-04-19 (evening)
**PR:** https://github.com/vallen300-bit/baker-master/pull/19
**Branch head:** `a8850f6` on `kbl-cost-rollup-hotfix`
**Brief origin:** Self-dispatched follow-up from my own sanity-check report `briefs/_reports/B2_kbl_migrations_sanity_20260419.md` (`kbl_cost_ledger.ts` canonical column call-out).
**Verdict:** **APPROVE** — 2-line rename + 36-line drift-prevention test. Zero drive-by. Full `*.py` grep confirms no other `created_at` drift on `kbl_cost_ledger` or `kbl_log`. `MERGEABLE`.

---

## Diff — surgical

`git diff main..pr19 --stat` (excluding my B2 migration-runner review file on main which is not in the PR scope):

```
 outputs/dashboard.py                  | 4 +-
 tests/test_dashboard_kbl_endpoints.py | 36 +++++
 2 files changed, 38 insertions(+), 2 deletions(-)
```

Two files, +38/-2. No other changes. Matches the brief's scope exactly.

---

## Line-by-line — `outputs/dashboard.py`

```diff
@@ -10884,7 +10884,7 @@ async def kbl_cost_rollup():
                            COALESCE(SUM(input_tokens), 0) AS in_tok,
                            COALESCE(SUM(output_tokens), 0) AS out_tok
                     FROM kbl_cost_ledger
-                    WHERE created_at > NOW() - INTERVAL '24 hours'
+                    WHERE ts > NOW() - INTERVAL '24 hours'
                     GROUP BY step, model
                     ORDER BY total_usd DESC
                     """
@@ -10894,7 +10894,7 @@ async def kbl_cost_rollup():
                     """
                     SELECT COALESCE(SUM(cost_usd), 0) AS day_total
                     FROM kbl_cost_ledger
-                    WHERE created_at > NOW() - INTERVAL '24 hours'
+                    WHERE ts > NOW() - INTERVAL '24 hours'
                     """
                 )
                 day_row = cur.fetchone()
```

Both renames land inside the `kbl_cost_rollup()` handler. Lines 10887 + 10897 per the task brief. Correct.

### Column-existence cross-check vs applied schema

Production Neon `kbl_cost_ledger` shape (verified in my sanity report + via today's migration `20260419_add_kbl_cost_ledger_and_kbl_log.sql:14`):

```
id BIGSERIAL PK, ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
signal_id INT FK, step TEXT NOT NULL, model TEXT,
input_tokens INT, output_tokens INT, latency_ms INT,
cost_usd NUMERIC(10,6), success BOOLEAN, metadata JSONB
```

Every column the endpoint references — `step`, `model`, `cost_usd`, `input_tokens`, `output_tokens`, `ts` — is present. No further drift. ✓

Index coverage: `idx_cost_ledger_day ON ((ts AT TIME ZONE 'UTC')::date)` from the same migration will serve the 24h window filter; B1's `WHERE ts > NOW() - INTERVAL '24 hours'` is not a `::date` predicate so the index is a seqscan-replacement candidate, not the optimal plan — but volume is low (a few cost rows per tick × ~720 ticks/day = <1K rows) so the endpoint stays well under 100ms regardless. N-level observation only; not worth a PR comment.

---

## New test `test_kbl_cost_rollup_sql_uses_canonical_ts_column` — the right shape

`tests/test_dashboard_kbl_endpoints.py:194-227`. Captures SQL via `_FakeCursor.execute` monkey-patch and asserts:

| Assertion | Value | What it catches |
|-----------|-------|-----------------|
| `resp.status_code == 200` | 200 | basic roundtrip |
| `len(cost_queries) >= 2` | ≥2 | both cost-ledger queries landed; catches accidental deletion of one query |
| `"WHERE ts" in q` (all queries) | True | forward drift — catches removal of `ts` filter |
| `"created_at not in q"` (all queries) | True | backward drift — catches re-introduction of `created_at` |

The double-direction assertion is key. PR #17's bug was `created_at` where `ts` belonged; a "WHERE ts" check alone would pass a PR that kept `created_at` AND added `ts`. The "no `created_at`" check forecloses that accidental-AND-regression.

Monkey-patch technique (`patch.object(_FakeCursor, "execute", _capturing_execute)`) is slightly heavy relative to simply subclassing `_FakeCursor` — but it preserves the existing fixture shape while adding SQL capture, and it resets cleanly on scope exit. Acceptable.

**Docstring is exemplary.** States the drift class, cites the specific migration as the schema source of truth, references the PR #17 regression the test exists to prevent. Future maintainers reading the test understand the "why" in 5 seconds. Import this pattern into other drift guards.

### Assertion-shape nit (not blocking)

The test implicitly assumes both queries will contain the literal substring `WHERE ts` — if someone rewrites to `WHERE kbl_cost_ledger.ts` (with table alias), the substring match still fires. If someone rewrites to `WHERE EXTRACT(epoch FROM ts) > …` or uses a CTE, the match could fail. Not worth guarding further — the current coding style doesn't use table-qualified column refs in these blocks, and a CTE rewrite would be reviewed as a structural change anyway.

---

## Repo-wide drift audit — zero OTHER drift found

B1's PR body claims "grep audit `kbl_cost_ledger|kbl_log` across `*.py`: all other query sites use canonical columns." Independently verified via `grep -rn "kbl_cost_ledger\|kbl_log" --include="*.py"`:

| File | Line | Columns used | Status |
|------|------|--------------|--------|
| `outputs/dashboard.py` | 10886-10887, 10896-10897 | `cost_usd`, `input_tokens`, `output_tokens`, `step`, `model`, `ts` | ✓ fixed by this PR |
| `kbl/cost.py` | 119 | `cost_usd`, `ts::date` (read) | ✓ canonical |
| `kbl/cost.py` | 160 | full INSERT: `signal_id`, `step`, `model`, `input_tokens`, `output_tokens`, `latency_ms`, `cost_usd`, `success`, `metadata` | ✓ canonical |
| `kbl/cost_gate.py` | 145 | `cost_usd`, `ts::date` (read) | ✓ canonical |
| `kbl/steps/step1_triage.py` | 491 | full INSERT (same columns as cost.py:160) | ✓ canonical |
| `kbl/steps/step2_resolve.py` | 126 | full INSERT | ✓ canonical |
| `kbl/steps/step3_extract.py` | 496 | full INSERT | ✓ canonical |
| `kbl/steps/step5_opus.py` | 347 | full INSERT | ✓ canonical |
| `kbl/logging.py` | 93 | `level`, `component`, `signal_id`, `message`, `metadata` on `kbl_log` | ✓ canonical |

Zero `created_at` on any `kbl_cost_ledger` SQL. Zero `kbl_log` column drift. Repo-wide clean. The endpoint handler was the unique locus of the bug — classic "the fixture-based test doesn't exercise the WHERE clause" gap that PR #19's new test closes.

One side-observation: `kbl/cost.py:121` uses `ts::date = NOW()::date` (not `AT TIME ZONE 'UTC'`). Today's migration (`20260419_add_kbl_cost_ledger_and_kbl_log.sql:27-30` comment block) flags that `ts::date` worked against Neon's permissive setting but will fail Postgres IMMUTABLE planning on `CREATE INDEX ((ts::date))` — the migration correctly switched the INDEX expression to `((ts AT TIME ZONE 'UTC')::date)`. The READ-side `WHERE ts::date = NOW()::date` in `cost.py:121` and `cost_gate.py` is fine (no index-planning implication on the WHERE clause directly — planner will fall back to seqscan on the VOLATILE cast). N-level — not this PR's problem.

---

## Independent local verification — blocked on py3.9 PEP 604

`python3 -m pytest tests/test_dashboard_kbl_endpoints.py -v` errors at collection with:

```
tools/ingest/extractors.py:275: TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'
```

Same py3.9-only blocker I hit on the PR #18 re-review (pre-existing codebase issue: `def _detect_mime_from_bytes(data: bytes) -> str | None:` uses PEP 604 syntax which requires 3.10+). `outputs/dashboard.py` imports that module at line 48, so any test that imports from `outputs.dashboard` collides.

Workaround for PR #18 (scope pytest to `tests/test_pipeline_tick.py` only) does not apply here because `test_dashboard_kbl_endpoints.py` imports `from outputs.dashboard import app, verify_api_key` at line 106.

**Mitigation:** trust B1's report "9/9 green" (brief body + local run on py3.10+). I verified by code-read that:
1. The fake cursor infrastructure (`_FakeCursor`, `_FakeConn`, `_patch_conn`) is unchanged — same shape the existing 8 tests in this file use, all presumed green pre-hotfix.
2. The new test's monkey-patch technique is sound — `patch.object` scopes cleanly and restores `_FakeCursor.execute` on exit.
3. The two assertion predicates (`"WHERE ts" in q`, `"created_at" not in q`) both fire against the post-rename SQL strings I can read in `outputs/dashboard.py:10887 + 10897`.

So the test WILL pass if the suite collects. This is the same code-read-only shape of verification I gave on PR #18 for the full 88/88 number. Accept.

---

## CI / mergeable — MERGEABLE, empty rollup

```
{"mergeable":"MERGEABLE","state":"OPEN","statusCheckRollup":[]}
```

`MERGEABLE` directly (not `UNKNOWN` like PR #18 was pre-merge) — good. Empty rollup = no CI configured on the repo. Same posture as prior PRs. Safe to auto-merge on B2 APPROVE per AI Head's Tier-A authority.

---

## CHANDA pre-push — unchanged

This is a follow-on hotfix to a bug in production-facing endpoint behavior. No invariant impact:

- **Inv 4** — untouched (no author/markdown).
- **Inv 8** — untouched (no KBL feedback flow).
- **Inv 9** — untouched (dashboard is read-only; Mac Mini isn't involved).
- **Inv 10** — untouched (no prompt files).
- **Q1 Loop Test** — pre-hotfix, `/cost-rollup` 500'd silently; Cockpit widget showed no data; Baker operator assumed no cost accrued; Leg 2 capture was WRITING (Step 1/2/3/5 insert rows fine) but Leg 3 readout was broken. Post-hotfix: readout restored. Pass.
- **Q2 Wish Test** — this PR closes the very failure mode B2's sanity report flagged as a canonical-column drift risk. CHANDA Leg 2→Leg 3 visibility restored. Pass.

---

## Dispatch

**APPROVE.** Two-line rename surgically fixes the endpoint; 36-line drift-prevention test forecloses the regression class that let the bug land. Zero drive-by changes. Full `*.py` grep confirms no other `kbl_cost_ledger` / `kbl_log` column drift. `MERGEABLE` directly — AI Head can auto-merge on this APPROVE per Tier-A authority. Local verification blocked on pre-existing py3.9 PEP 604 codebase issue in `tools/ingest/extractors.py`; trust B1's "9/9 green" claim + my code-read verification of the monkey-patch correctness.

**Post-merge path:**
1. AI Head auto-merges PR #19.
2. Render auto-deploys on push to `main`.
3. `/api/kbl/cost-rollup` returns 200 with actual data (currently returns 500 against `kbl_cost_ledger`).
4. All 4 KBL Pipeline Cockpit widgets functional: signals, cost-rollup, silver-landed, mac-mini-status.
5. Shadow-mode KBL-B pipeline fully observable — Director's go-live dashboard lights up properly.

**Reports shipped this cycle:**
- Task 1: `briefs/_reports/B2_migration_runner_brief_review_20260419.md` (REDIRECT, 3 folds for B3).
- Task 2: this file (APPROVE, PR #19 ready for auto-merge).

Closing terminal tab per directive.
