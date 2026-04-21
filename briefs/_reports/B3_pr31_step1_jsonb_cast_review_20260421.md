---
role: B3
kind: review
brief: step1_triage_jsonb_cast_fix
pr: https://github.com/vallen300-bit/baker-master/pull/31
branch: step1-triage-jsonb-cast-fix-1
base: main
commits: [13fcacb, ea97ad5]
ship_report: briefs/_reports/B2_step1_triage_jsonb_cast_fix_20260421.md
verdict: APPROVE
tier: A
date: 2026-04-21
tags: [step1-triage, jsonb, psycopg2, schema-drift, cortex-t3-gate1, review]
---

# B3 — review of PR #31 `STEP1_TRIAGE_JSONB_CAST_FIX_1`

**Verdict: APPROVE.** Tier A auto-merge greenlit. Zero blocking issues, zero gating nits. B2's deviation is the only route that actually works against live PG and aligns with three existing sibling-writer patterns in the same codebase.

---

## Focus items — 5/5 green

### 1. ✅ Fix is minimal and surgical; mirrors proven sibling pattern

`kbl/steps/step1_triage.py:_write_triage_result` now uses `related_matters = %s::jsonb` + `json.dumps(list(result.related_matters))`. Verified against the three in-codebase precedents:

| Site | SQL side | Python side |
|---|---|---|
| `kbl/steps/step2_resolve.py:126` | `resolved_thread_paths = %s::jsonb` | `json.dumps(list(paths))` |
| `kbl/steps/step3_extract.py:486` | `extracted_entities = %s::jsonb` | `json.dumps(entities.to_dict())` |
| `kbl/bridge/alerts_to_signal.py:499` | `payload = ... %s::jsonb` | `json.dumps(signal_row["payload"])` |
| **`kbl/steps/step1_triage.py:467` (this PR)** | **`related_matters = %s::jsonb`** | **`json.dumps(list(result.related_matters))`** |

Pattern match is exact. No novel abstraction introduced; this is the boring, load-bearing thing you want on a Gate 1 blocker fix.

The 8-line comment block above `_write_triage_result` explicitly cross-references the two sibling lines for future maintainers — same comment-quality bar the raw_content fix hit (PR #30). Good.

### 2. ✅ Brief-vs-ship deviation — accept B2's reading

B2 shipped `%s::jsonb` **plus** `json.dumps(...)` where the brief asked only for `%s::jsonb` on the SQL side with the raw Python list unchanged on the Python side. The brief, as literally written, would not have worked.

Mechanism (confirmed):
- psycopg2 adapts a Python `list` to Postgres `ARRAY[...]` (i.e. `text[]`).
- PG does NOT support an implicit cast from `text[]` to `jsonb`. `SELECT ARRAY['a','b']::jsonb;` raises `cannot cast type text[] to jsonb`.
- PG DOES support TEXT→JSONB. That's the route all three sibling writers already use.

So the brief's literal instruction was wrong on a mechanical detail. B2 caught it empirically, shipped the working pattern that's already deployed in three adjacent files, and flagged the deviation prominently in the ship report for reviewer verification. This is the right call by a wide margin.

**Alternative considered (and rejected):** `psycopg2.extras.Json(...)` adapter. It works, but it would be the only site in the codebase using that wrapper — every other JSONB writer uses the `json.dumps + %s::jsonb` idiom. Introducing a novel adapter pattern on a Gate 1 blocker fix is strictly worse than matching sibling style. No change requested.

### 3. ✅ Regression tests — round-trip + cleanup both solid

Both new tests (`test_step1_triage.py:762-916`) do genuine PG round-trips:

- Connect to `needs_live_pg` URL (skips cleanly if no `TEST_DATABASE_URL` or `ephemeral_neon_db`).
- INSERT a signal_queue row via the shared `tests/fixtures/signal_queue.insert_test_signal` helper (same helper introduced by PR #30's STEP_CONSUMERS fix — consistent use).
- Call `_write_triage_result` with a `TriageResult`.
- Re-SELECT using `jsonb_typeof(related_matters)` + `jsonb_array_length(related_matters)` — these two PG functions specifically fail on non-JSONB columns, so they're the correct assertion shape.
- Assert round-trip values match.

Cleanup in `finally` is robust:
```python
cur.execute("DELETE FROM kbl_cost_ledger WHERE signal_id = %s", (signal_id,))
cur.execute("DELETE FROM kbl_log WHERE signal_id = %s", (signal_id,))
cur.execute("DELETE FROM signal_queue WHERE id = %s", (signal_id,))
conn.commit()
conn.close()
```

Deletes FK-dependent children first (kbl_cost_ledger, kbl_log) then the parent row. `conn.close()` reached via `finally` even on mid-test assertion failure. No leaked rows in shared test DB.

**Empty-list edge case** (`related_matters=()`) is separately pinned — correct call. Gemma triage outputs empty related_matters in the majority case, so this is the hot path, not the tail.

Local smoke (py3.9 with pytest): `tests/test_step1_triage.py` → **51 passed, 2 skipped**. The 2 skipped are exactly the new live-PG gates; they SKIP cleanly on the `needs_live_pg` fixture when no Neon branch / `TEST_DATABASE_URL` is set. Works as designed.

### 4. ✅ JSONB audit — step1 was the only missing offender

Reproduced B2's audit independently. Grep pattern: `UPDATE signal_queue|INSERT INTO signal_queue` across `kbl/` + `tests/`. Then for each hit, inspected the column list vs. `information_schema.columns` JSONB columns.

Signal_queue JSONB columns (4 total):
- `payload` — written only at `kbl/bridge/alerts_to_signal.py:499` — has `%s::jsonb` + `json.dumps`. ✓
- `related_matters` — written only at `kbl/steps/step1_triage.py:467` — **was missing cast, now fixed**. ✓
- `resolved_thread_paths` — written only at `kbl/steps/step2_resolve.py:126` — has cast + dumps. ✓
- `extracted_entities` — written only at `kbl/steps/step3_extract.py:486` — has cast + dumps. ✓

Steps 4–7 do not write any JSONB column on signal_queue:
- Step 4 (`step4_classify._write_decision`): writes `step_5_decision` (text), `cross_link_hint` (bool), `status` (text). Read-only against JSONB.
- Step 5 (`step5_opus._write_draft`): writes `opus_draft_markdown` (text), `status`. Read-only against JSONB.
- Step 6 (`step6_finalize._write_finalized`): writes `final_markdown` (text), `target_vault_path` (text), `status`, `finalize_retry_count` (int). No JSONB.
- Step 7 (`step7_commit._write_commit`): writes `status`, `committed_at`, `commit_sha` (text), NULL-outs `opus_draft_markdown` + `final_markdown` (both text). No JSONB.

**No further offenders exist.** Audit complete.

### 5. ✅ No schema changes

`git diff main...HEAD -- migrations/` is empty (0 lines). Per brief constraint.

---

## Judgment on the N2 follow-up (B2's proposal)

**B2 proposes `STEP_WRITERS_JSONB_SHAPE_AUDIT_1`** — extend the round-trip integration pattern to all step writers + add a CI grep rule for `%s::jsonb` without a paired `json.dumps` in the same `cur.execute` block.

**Recommendation: draft this as a dedicated brief post-Gate-1.**

Rationale:
- Today produced **three** adjacent bugs from the same root-cause family (silent schema/code drift): hot_md_match BOOLEAN/TEXT, step-consumers raw_content, step1 related_matters text[]/JSONB. All three stalled rows at `status='processing'` because `pipeline_tick.claim_one_signal` commits the claim *before* the step runs. Every future write-side-type drift will produce the same terminal strand.
- The *first* two bugs (hot_md_match + raw_content) were caught and fixed today; the *third* (this PR) was caught only because AI Head pushed the recovery UPDATE and noticed the next batch of rows re-stranding. That's operator-loop debugging, not CI.
- A simple grep gate (`grep -n "%s::jsonb" kbl/*.py kbl/steps/*.py | while read; do verify same line or same cur.execute has json.dumps`) would have caught this one pre-merge, in <1 second of CI.
- Round-trip integration tests per step writer would catch the class B of bug (driver adaptation drift) that the grep rule misses — e.g. if a future dev uses a custom psycopg2 adapter or a different serializer.
- Both mechanisms are cheap to build and kill an entire bug class. Net-positive.

**Not blocking this PR.** Drafting it post-Gate-1 is the right sequence — don't expand scope on the fix that unblocks the pipeline. But it's the right next brief once signals are flowing.

Worth noting: B2's side observations N1 (stale `TEXT[]` docstring at `step4_classify.py:181`) and N3 (terminal-flip-on-DatatypeMismatch mitigation OR reaper-tick for stuck-at-processing rows) are both worth capturing, but less urgent than N2. N3 in particular is the permanent mitigation for this entire bug class — cheaper than round-tripping every writer, arguably more important for Gate 2+. Suggest both go into the next bridge-tuning brief's non-blocking list.

---

## Non-blocking observations

None on this PR. B2's ship report already captured everything worth capturing, and the N2/N3 follow-ups above are parked as explicit next-brief candidates, not redlines on this one.

---

## Recommendation

**Tier A auto-merge OK.**

Post-merge sequence (standing Tier A for AI Head per memory/actions_log.md):
1. Merge PR #31 to main.
2. Render auto-deploys (~3 min).
3. Run Tier A recovery UPDATE (shape from B2's ship report §Recovery):
   ```sql
   UPDATE signal_queue
      SET status='pending', started_at=NULL
    WHERE stage='triage'
      AND status='processing'
      AND started_at IS NOT NULL
      AND triage_summary IS NULL;
   ```
4. Watch `signal_queue` for first end-to-end flow through Step 1 → Step 2 (first JSONB round-trip on real data validates the fix in prod).
5. If any row strands again past Step 1: halt, diagnose, escalate to Director with the stranded-row state dump.

**Gate 1 status expectation:** with this fix + today's hot_md_match fix + raw_content fix, the three known code-level blockers between healthy infra and end-to-end signal flow are cleared. Gate 1 closes on ≥5–10 signals reaching a terminal stage (`opus_done`, `paused_cost_cap`, `routed_inbox`, `committed_to_vault`) within the next 24–48 hours of production tick activity.

---

## Environment notes

- Review done on worktree `/tmp/bm-b3-pr31` against `origin/step1-triage-jsonb-cast-fix-1@ea97ad5`.
- Local py3.9 + fallback pytest: 51 passed, 2 skipped (the 2 new live-PG gates, as designed).
- Worktree cleanup: `git worktree remove /tmp/bm-b3-pr31 --force` on tab close per §8.

Tab quitting per §8.

— B3
