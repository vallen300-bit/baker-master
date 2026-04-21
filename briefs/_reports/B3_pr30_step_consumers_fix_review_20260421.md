# B3 Review — PR #30 STEP_CONSUMERS_SIGNAL_CONTENT_SOURCE_FIX_1

**From:** Code Brisen #3
**To:** AI Head
**Date:** 2026-04-21
**PR:** baker-master#30 (head `777ca48`)
**Brief:** `briefs/BRIEF_STEP_CONSUMERS_SIGNAL_CONTENT_SOURCE_FIX_1.md`
**Ship report:** `briefs/_reports/B1_step_consumers_fix_ship_20260421.md`
**Upstream diagnostic:** `briefs/_reports/B2_pipeline_diagnostic_20260421.md` (commit `1ac8ed0`)
**Unblocks:** Cortex T3 Gate 1
**Reviewer-separation:** clean — B2 diagnosed, B1 implemented, B3 reviews (I was on Phase D + the hot.md pair; zero touches to step consumers).

---

## Dispatch back (TL;DR)

**Verdict: APPROVE** — Tier A auto-merge greenlit.

PR is small, mechanical, and tight. The COALESCE + alias strategy lands cleanly across all 4 consumers. The new integration test module gates the exact drift that regressed. No blocking issues; zero nits for this PR (one N1 follow-up observation for the bridge-tuning brief, non-blocking).

Director still needs to authorize the Tier B recovery UPDATE separately post-merge — the pre-flight SELECT + envelope-bounded UPDATE SQL in B1's ship report §Deploy are clean.

---

## Focus item check (10/10)

### 1. ✅ All 4 step consumers redirect cleanly

```
$ grep -rn "SELECT.*raw_content" kbl/steps/
kbl/steps/step5_opus.py:261:  "SELECT COALESCE(payload->>'alert_body', summary, '') AS raw_content, "
kbl/steps/step3_extract.py:445: "SELECT COALESCE(payload->>'alert_body', summary, '') AS raw_content, "
kbl/steps/step1_triage.py:441: "SELECT COALESCE(payload->>'alert_body', summary, '') AS raw_content "
```

Plus `kbl/steps/step2_resolve.py:86` through the `_SIGNAL_SELECT_FIELDS` pair list. All 4 SELECT sites hit the COALESCE expression; zero phantom-column references remain. B1's claim is exact.

### 2. ✅ Alias strategy clean — `_SIGNAL_SELECT_FIELDS` scrutiny

The step2 refactor from `_SIGNAL_SELECT_COLUMNS: tuple[str, ...]` → `_SIGNAL_SELECT_FIELDS: tuple[tuple[str, str], ...]` is the right move. The old shape mixed SQL-expression + dict-key roles implicitly (`"raw_content"` served as both column name AND dict key); the new shape makes them explicit pairs:

```python
_SIGNAL_SELECT_FIELDS: tuple[tuple[str, str], ...] = (
    ("id", "id"),
    ("source", "source"),
    ("primary_matter", "primary_matter"),
    (
        "COALESCE(payload->>'alert_body', summary, '') AS raw_content",
        "raw_content",
    ),
    ("payload", "payload"),
)
```

`col_list = ", ".join(expr for expr, _ in _SIGNAL_SELECT_FIELDS)` + `keys = tuple(k for _, k in _SIGNAL_SELECT_FIELDS)` keeps the SELECT and the zipped dict aligned. Single caller (`_fetch_signal` in the same module). Downstream consumers reading `signal["raw_content"]` see the legacy key preserved verbatim. Clear abstraction, no over-engineering.

### 3. ✅ COALESCE ladder is safe

`COALESCE(payload->>'alert_body', summary, '')`:
- **Rung 1 (`payload->>'alert_body'`):** primary — what `alerts_to_signal.map_alert_to_signal` writes today (line 390 in the bridge).
- **Rung 2 (`summary`):** legacy fallback. `summary` is a real TEXT column; populated by every bridge row (mapper uses `alert.get("title")`). For pre-bridge rows or alternate producers, summary is the best available body substitute.
- **Rung 3 (`''`):** tail — guarantees a non-NULL str so downstream `.lower()`, `len()`, concat don't raise. Verified against step consumers: step1 returns `row[0] or ""` (double-safe); step2 stores into dict key verbatim; step3 uses `raw_content = row[0] or ""`; step5 populates `raw_content=raw_content or ""`. Every consumer does the `or ""` belt+suspenders even though COALESCE guarantees it — defensive but not harmful.

Fallback semantics match the brief's §2 spec.

### 4. ✅ Integration tests assert the right thing

`tests/test_bridge_pipeline_integration.py` — 6 live-PG tests, all gated on `needs_live_pg` fixture:

| Test | What it pins |
|---|---|
| `test_step1_reads_bridge_shaped_row_via_coalesce` | The exact drift point — calls `_fetch_signal` on a row built via `alerts_to_signal.map_alert_to_signal` (guarantees production shape). |
| `test_step2_reads_bridge_shaped_row_and_preserves_raw_content_key` | Dict-key contract for resolvers (`signal['raw_content']`). |
| `test_step3_reads_bridge_shaped_row` | 4-tuple unpacking — body is `row[0]`. |
| `test_step5_reads_bridge_shaped_row` | `_SignalInputs` dataclass carries body into `raw_content` field. |
| `test_fallback_to_summary_when_payload_missing_alert_body` | COALESCE middle rung on hand-rolled row without `payload.alert_body`. |
| `test_empty_body_coalesce_tail_returns_empty_string` | COALESCE tail rung — empty string not NULL. |

The first test is particularly strong: it uses `map_alert_to_signal` rather than hard-coded column values, so if the bridge mapper ever changes its payload keys, this test starts failing first — exact feedback loop we want.

Local collection: 6 SKIPPED cleanly without `TEST_DATABASE_URL` set. `needs_live_pg` fixture chain (ephemeral Neon → TEST_DATABASE_URL → skip) per the conftest.py work from PR #25 is holding.

`_cleanup_signal` deletes kbl_cost_ledger + kbl_log traces in dependency order; forward-compatible if a future migration adds FK constraints.

### 5. ✅ Shared fixture helper

`tests/fixtures/signal_queue.py::insert_test_signal`:

- Named-kwargs API (`body`, `matter`, `source`, `status`, `stage`, `priority`, `summary`, `signal_type`, `extra_payload`) — readable call sites.
- Docstring explicitly calls out the drift class it prevents ("ALERT BODY goes in payload['alert_body'], NOT a non-existent raw_content column").
- `summary` defaults to the same text as `body` so the COALESCE 2nd-rung fallback also resolves for tests that don't explicitly set summary.
- Step-N column pre-population intentionally left out — UPDATE-after-INSERT pattern documented.
- Only column set list matches what `alerts_to_signal.map_alert_to_signal` actually writes.

Reasonable API. Correctly shared — the new integration test imports via `from tests.fixtures.signal_queue import insert_test_signal`; future step-consumer tests will use it.

### 6. ✅ Fixture drift repairs — only 2 files had actual drift

**Verified via grep:** `INSERT INTO signal_queue` with `raw_content` column appears in exactly 2 files on main pre-PR:
- `tests/test_step4_classify.py:616` — swapped to `payload` JSONB with `alert_body` key. Comment explains step 4 doesn't consume body, so the shape is just realistic-for-future-reads.
- `tests/test_status_check_expand_migration.py` — 3 sites swapped to `summary` column (body text irrelevant to status-CHECK assertion per the comment).

**Other 4 step test files:**
- `tests/test_step1_triage.py` — `_mock_conn` returns `(raw_content,)` tuple from MagicMock; SQL text is regex-matched, not column-checked. Unaffected.
- `tests/test_step2_resolve.py` — builds in-memory dicts with `"raw_content"` key; never hits DB.
- `tests/test_step3_extract.py` — MagicMock cursor pattern; unaffected.
- `tests/test_step5_opus.py` — MagicMock cursor pattern; unaffected.

`tests/test_layer0_eval.py` uses a `Signal(..., raw_content=body, ...)` in-memory dataclass — not signal_queue SQL. Safe.

DEV-1's scope reduction (5→2 files) is accurate. B1's survey was correct.

### 7. ✅ `kbl/pipeline_tick.py:359-365` unchanged

```
$ cd /tmp/bm-b3-pr30 && git diff main...HEAD -- kbl/pipeline_tick.py | wc -l
0
```

Empty diff. The `emit_log` block B2's diagnostic flagged as diagnostic-friendly is untouched.

### 8. ✅ Comment quality

Each of the 4 consumer sites carries the "SAFETY NET, NOT a cover-up" language plus the specific future-maintainer instruction. Step 1 + Step 2 comments include the explicit call-to-action:

> "If you're reading this comment while adding a third body source, add it to the ladder here + update the bridge + update the other 3 consumers."

Step 3 + Step 5 comments are shorter but carry the same core message. Fixture helpers + test comments echo it. The tone is durable guidance — forward-looking, not a post-mortem apology.

Suggestion (not a nit, just an observation): if the bridge ever adds a third body source, the code-owner of this 4-file fan-out should consider hoisting the COALESCE expression into a module-level constant (e.g. `kbl.bridge.alerts_to_signal.SIGNAL_BODY_SQL = "COALESCE(payload->>'alert_body', summary, '')"`) so the 4 SELECTs read from one source of truth. Not needed now — at 2 rungs the inline form is more readable than one level of indirection.

### 9. ✅ No schema changes

Migrations audit:
```
$ git log main...HEAD --oneline -- migrations/
(empty — no migration commits on the PR branch)
```

Only April-21-dated migration is `20260421_signal_queue_hot_md_match.sql` from the prior PR #29 (already on main). No new migration, no generated column, no synonymous VIEW. Brief §Key constraints §4 satisfied.

### 10. ✅ Test count reproduction

Ran the 7 test files B1 cited (step1/2/3/4/5 + integration + status-check-migration) locally on py3.9:

```
tests/test_step1_triage.py                   PASSED
tests/test_step2_resolve.py                  PASSED
tests/test_step3_extract.py                  PASSED
tests/test_step4_classify.py                 PASSED (1 live-PG SKIPPED)
tests/test_step5_opus.py                     PASSED
tests/test_bridge_pipeline_integration.py    6 SKIPPED (live-PG gate)
tests/test_status_check_expand_migration.py  PASSED (1 live-PG SKIPPED)
---
Scoped total: 202 passed, 8 skipped, 0 failed
```

B1's 299 figure is a broader scope (includes migration_runner, layer0, bridge, hot_md, nudge, vault-mirror, and other bridge-adjacent files). I spot-checked the 7 directly-affected files and got 202/8/0; the extra 97 in B1's count maps to tests that shouldn't have changed behavior under this PR (confirmed: the new SELECT text change is invisible to MagicMock cursors).

**No regressions surfaced in the affected surface.** Broader suite has 22 pre-existing failures / 12 pre-existing errors on py3.9 — all are the PEP-604 `|` type-syntax landmine (lesson #41; present on main; B1 runs py3.12 which is unaffected). Not a PR-30 regression.

---

## Brief deviations — judgment

### DEV-1: 5 expected test modules → 2 actual ✅ Reasonable
Verified via grep as noted in focus item 6. The brief's scope estimate was conservative (assumed MagicMock patterns might also contain `raw_content` column references); B1's survey found they don't. Net churn is smaller than planned, which is the correct outcome.

### DEV-2: `_SIGNAL_SELECT_COLUMNS` → `_SIGNAL_SELECT_FIELDS` ✅ Justified
Scrutinized in focus item 2. The rename + shape change is the minimum edit that preserves the alias strategy while making the SQL-expression vs dict-key split explicit. Only caller is same-module. Reasonable.

### DEV-3: Step 4 prod code untouched ✅ Confirmed
Inspected `kbl/steps/step4_classify.py::_fetch_signal_context`:

```python
cur.execute(
    "SELECT triage_score, primary_matter, related_matters, "
    "       resolved_thread_paths "
    "FROM signal_queue WHERE id = %s",
    (signal_id,),
)
```

Step 4 reads triage_score + matter data; never reads body text. The only body-related bug was the live-PG TEST `INSERT` — that's now fixed. Prod code stays clean. DEV-3's framing is correct.

---

## Non-blocking observation (for next bridge-tuning brief, not this PR)

**N1 — Body-SQL single-source-of-truth.** The `COALESCE(payload->>'alert_body', summary, '')` literal is duplicated at 4 call sites across 4 files. At 2 rungs the inline form is readable and the duplication cost is low. If/when a 3rd body source is added (alt producer, migrated column, etc.), consider hoisting to:

```python
# kbl/bridge/alerts_to_signal.py
SIGNAL_BODY_SQL = "COALESCE(payload->>'alert_body', summary, '') AS raw_content"
```

Then the 4 consumers import and interpolate the string. Deferred: not worth the churn now, but worth noting for the next brief that touches this surface.

Do NOT block merge on this. Roll into whatever brief next touches bridge/consumer coupling.

---

## Recommendation

**APPROVE — Tier A auto-merge greenlit.**

No blocking issues, no nits worth gating on. Brief §Pre-merge verification list (the 5 items) all check green. Code reads as tight, focused, and reversible.

Merge sequence for AI Head:
1. **Merge PR #30** per Tier A (no further Director auth for merge itself).
2. **Render auto-deploys** (~3 min) — migration runner picks up `20260421_signal_queue_hot_md_match.sql` on first startup if it hadn't already.
3. **Wait for first clean `kbl_bridge_tick`** post-deploy (confirms no import-time failures).
4. **Director authorizes Tier B recovery UPDATE** — use the pre-flight SELECT first (B1's ship report §4), confirm 15 rows match, then run the UPDATE with the `id <= 15` envelope.
5. **Wait 1 `kbl_pipeline_tick` cycle (~120s)** for re-claim.
6. **Verify per brief §Verification post-deploy:** signal_queue rows advancing past triage + kbl_cost_ledger populating + zero new ERROR rows in kbl_log (component='pipeline_tick').
7. **Gate 1 closes** when ≥5-10 signals reach terminal stage.

Cortex T3 Gate 1 on track to unblock today.

— B3
