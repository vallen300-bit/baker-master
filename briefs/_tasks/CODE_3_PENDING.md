---
status: PENDING
brief: briefs/BRIEF_DEADLINE_FEEDBACK_LOOP_1.md
brief_id: DEADLINE_FEEDBACK_LOOP_1
trigger_class: TIER_B_DB_MIGRATION_+_DASHBOARD_UI_+_ENDPOINT
dispatched_at: 2026-05-13
dispatched_by: ai-head-1 (AH1)
target: b3
mandatory_2nd_pass: true
security_review_required: true
effort_estimate: ~4h
predecessor:
  brief: briefs/BRIEF_DEADLINE_SIGNAL_HYGIENE_1.md
  pr: 202
  merge_commit: 6c31b057
  director_apply: 2ed9896 (Scope C 352/352 applied 2026-05-13)
ratified_spec: _ops/ideas/2026-05-13-smart-signal-classification.md
director_ratification: |
  2026-05-13 — "Rest is okay. All ratified." (4-phase sequencing Q1-Q4 + Gemini
  Flash/Pro stack swap on smart-signal-classification spec).
scope_summary:
  part_1: NEW migration 20260513b_deadline_feedback.sql (1 table + 3 indexes)
  part_2: NEW models/deadline_feedback.py + NEW endpoint POST /api/deadlines/{id}/feedback + NEW GET /api/slug-registry + AUGMENT existing /dismiss + /complete to write corpus rows
  part_3: 2 new buttons on deadline-card triage bar + XSS-safe DOM-constructed wrong-matter dropdown
  part_4: NEW tests/test_deadline_feedback.py (≥7 tests, mix of unit + live-PG)
followup_brief: SIGNAL_CLASSIFIER_TIER2_1 (gated on 2+ weeks click corpus from THIS brief)
ship_gate: literal pytest -v output paste + check_singletons PASS + py_compile on both modified .py files
bus_topic: ship/DEADLINE_FEEDBACK_LOOP_1
---

# CODE_3_PENDING — DEADLINE_FEEDBACK_LOOP_1

Read `briefs/BRIEF_DEADLINE_FEEDBACK_LOOP_1.md` for full spec.

## Confirmation phrase
`"B3 oriented. Read: CODE_3_PENDING.md, MEMORY.md."`

## Working dir
`~/bm-b3` — branch off `main` after `git pull --ff-only`. Suggested branch: `b3-deadline-feedback-loop`.

## What ships (single PR, 4 parts)

1. **Migration** — `migrations/20260513b_deadline_feedback.sql` (1 new table, 3 indexes). Verify post-deploy via `information_schema.columns`.
2. **Backend** — `models/deadline_feedback.py` (NEW), `outputs/dashboard.py` (1 new POST + 1 new GET + augment 2 existing POSTs). `Request` already imported at dashboard.py:21 (verified).
3. **Frontend** — `outputs/static/app.js` (2 button additions + 4 new functions, all XSS-safe via DOM construction, NO innerHTML on dynamic content); `outputs/static/index.html` cache bump `?v=112` → `?v=113`.
4. **Tests** — `tests/test_deadline_feedback.py` (NEW). At minimum: invalid-type rejection, unknown-slug normalize-to-None, round-trip insert, endpoint write, 400 on bad verb, backward-compat dismiss/complete corpus capture.

## What does NOT ship (AH1 owns / out of scope)

- Phase 3 Gemini classifier upgrade (`SIGNAL_CLASSIFIER_TIER2_1`) — separate brief, gated on 2+ weeks of click corpus from THIS brief
- Phase 4 multi-dim envelope JSONB column on deadlines / signal_queue — phase 4 brief, after phase 3 proves out
- Touching `_match_matter_slug()` / classifier code in `orchestrator/pipeline.py` — phase 3 territory
- Touching `outputs/static/mobile.html` / `mobile.js` — they don't render deadlines (verified clean grep)
- Touching `models/deadlines.py` table-creation bootstrap — migration owns the new table

## Hard constraints

- **No `innerHTML` on dynamic content.** Build the wrong-matter dropdown via `document.createElement` + `option.value` / `option.textContent` + `appendChild`. Static-ASCII button labels in `_landingTriageBar` can keep the existing string-concat pattern (consistent with surrounding code). See brief §Part 3 §XSS discipline.
- **`insert_feedback` is fault-tolerant.** Failures inside it return `None` + log; they MUST NOT raise to the calling endpoint. Augmented `/dismiss` and `/complete` must continue to flip status even if the feedback write fails (existing user-facing behavior preserved).
- **`conn.rollback()` in every except block** on DB code paths (Python backend rule).
- **`LIMIT` on every SELECT** including `get_recent_feedback` (Python backend rule — capped at 100 default).
- **Ship gate is literal `pytest -v` output.** No "pass by inspection" — REQUEST_CHANGES if claimed.

## 2nd-pass code-reviewer (MANDATORY)

This brief touches DB schema (migration trigger #2 per `/security-review` 2nd-pass protocol). After AH2 static + AH2 `/security-review` + picker-architect verdicts land, AH1 fires `feature-dev:code-reviewer` agent with the 6-line output contract. All 4 gates must clear before merge.

## Bus post on ship

```bash
BAKER_ROLE=b3 ~/Desktop/baker-code/scripts/bus_post.sh lead \
  "PR #<N> OPEN — DEADLINE_FEEDBACK_LOOP_1. Migration 20260513b_deadline_feedback applied via deploy. <K>/<K> tests PASS. check_singletons PASS. New endpoints registered: POST /api/deadlines/{id}/feedback + GET /api/slug-registry. /dismiss + /complete now write 'mute' / 'confirm' corpus rows (backward compat preserved)." \
  ship/DEADLINE_FEEDBACK_LOOP_1
```

## Verification SQL (post-deploy)

Run as part of ship-report — paste output back to lead:

```sql
SELECT column_name, data_type FROM information_schema.columns
WHERE table_name = 'deadline_feedback' ORDER BY ordinal_position;
-- Expect 9 rows.

SELECT feedback_type, COUNT(*) FROM deadline_feedback GROUP BY feedback_type;
-- Probably 0 rows pre-traffic. That's fine — confirms table exists + index works.
```

---

## UPDATE — 2026-05-13 — AH1 fix request (post-review chain)

**Status:** FIX_REQUESTED (re-open mailbox on PR branch `b3-deadline-feedback-loop`).
**Trigger:** Review chain on PR #203 cleared /security-review (NO_FINDINGS) but surfaced 2 HIGH findings — 1 from picker-architect, 1 from `feature-dev:code-reviewer`. Both legit + cross-confirmed. Fix loop before merge.

### Fix A (HIGH — operation-ordering gap on new `/feedback` endpoint)

**Where:** `outputs/dashboard.py` — new `deadline_feedback_api()` around lines 7242–7322 (post-merge ranges, find by function name).

**Defect:** `insert_feedback(...)` and `update_deadline(...)` execute in the SAME outer `try` block. The augmented `/dismiss` + `/complete` correctly wrap the feedback call in an **inner** `try/except` so a failure there cannot block the status flip. The new `/feedback` endpoint does NOT mirror that pattern — an unexpected raise from `insert_feedback` (despite its internal try/except) would be caught by the outer `except Exception`, return a 500, and **skip the status flip entirely**. Director clicks "Not a Deadline", sees an error, card stays visible, no corpus row written. Echoes PR #1 brisen-lab operation-ordering scar.

**Fix:** wrap the `insert_feedback(...)` call inside `deadline_feedback_api` in its own inner `try/except`, matching the pattern in `/dismiss` and `/complete`:

```python
fid = None
try:
    fid = insert_feedback(
        deadline_id=deadline_id,
        feedback_type=feedback_type,
        original_matter_slug=dl.get("matter_slug"),
        corrected_matter_slug=corrected_slug,
        original_description=dl.get("description") or "",
        original_source_type=dl.get("source_type"),
        director_note=None,
    )
except Exception as fe:
    logger.warning(f"deadline_feedback ({feedback_type}) write failed for {deadline_id}: {fe}")

# Side-effect status flip runs unconditionally — corpus write must NEVER block it.
if feedback_type == "confirm":
    update_deadline(...)
# ... etc
```

Brief's hard constraint: *"failures inside it return `None` + log; they MUST NOT raise to the calling endpoint."* Apply the same belt-and-suspenders here.

### Fix B (HIGH — observability gap on corpus-write degradation)

**Where:** `outputs/dashboard.py` — three call sites that write feedback rows: `/dismiss` (~line 6864), `/complete` (~line 6895), `/feedback` (new endpoint).

**Defect:** When `insert_feedback` returns `None` (degraded DB path) or its outer wrapper catches an exception, the failure is `logger.warning(...)` only. No counter, no metric, no `/api/health` signal. Phase 3 classifier upgrade `SIGNAL_CLASSIFIER_TIER2_1` is **gated on "2+ weeks of clicks land here"** — a silent regression (schema drift, connection pool exhaustion, migration unapplied) invalidates that corpus window with zero visibility to Director.

**Fix:** add a module-level counter that increments on every feedback-write failure path, exposed via the existing health surface. Two acceptable approaches — pick one:

1. **Counter on `models/deadline_feedback.py`** (preferred — single owner of the write):
   - Add module-level `_WRITE_FAILURES: int = 0` + `_LAST_FAILURE_AT: Optional[datetime] = None`.
   - Increment in the existing `except` blocks of `insert_feedback` (the `if feedback_type not in VALID_FEEDBACK_TYPES` branch, the `if not conn` branch, and the `except Exception as e` branch).
   - Export `get_write_failure_stats() -> dict` returning `{"count": _WRITE_FAILURES, "last_failure_at": _LAST_FAILURE_AT}`.
   - In `outputs/dashboard.py` `/api/health` endpoint (find existing function), add a `"deadline_feedback": {...}` key sourced from `get_write_failure_stats()`. Non-fatal — health stays "ok" even if counter > 0; surface is sufficient.

2. **Reuse existing metrics primitive** if there's already a `BAKER_METRICS` dict or similar in `outputs/dashboard.py` — increment `BAKER_METRICS["deadline_feedback_write_failures"]` instead. Grep first; only adopt if it exists.

Add **one** unit test: feedback write that goes through the degraded `if not conn` path increments the counter by exactly 1. Live-PG not required — monkeypatch `get_conn` to return `None` like the existing `test_insert_feedback_returns_none_on_no_connection`.

### Out of scope for this fix loop

Architect's 3 MED findings (slug-registry empty-on-error, `_activeSlugs` no-TTL, DB CHECK vs app whitelist duplication) and 1 LOW (helper extraction) are **NOT** part of this fix request. Capture as phase-3 follow-ups if needed.

### Re-ship gate

1. Re-run `pytest tests/test_deadline_feedback.py -v` — paste literal output, all prior-passing tests still pass + 1 new failure-counter test passes.
2. `bash scripts/check_singletons.sh` PASS.
3. `py_compile` clean on modified files.
4. Push to existing branch `b3-deadline-feedback-loop` (no new branch — same PR #203 picks up the new commit).
5. Bus-post on push:
   ```bash
   BAKER_ROLE=b3 ~/Desktop/baker-code/scripts/bus_post.sh lead \
     "PR #203 UPDATED — Fix A (inner try/except on /feedback) + Fix B (write-failure counter exposed via /api/health). <K>/<K> tests PASS." \
     fix/DEADLINE_FEEDBACK_LOOP_1
   ```
6. AH1 re-runs `feature-dev:code-reviewer` on the delta only, then merges.

### Why no Fix C/D/etc.

Auth, SQL parameterization, XSS discipline, migration safety, CSRF, type-match drift — all clean across three independent reviewers. Don't touch them.
