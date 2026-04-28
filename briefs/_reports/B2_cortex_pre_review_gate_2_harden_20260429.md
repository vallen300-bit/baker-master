---
ship_report_for: briefs/BRIEF_CORTEX_PRE_REVIEW_GATE_2_HARDEN.md
predecessor_pr: 80
predecessor_report: briefs/_reports/B2_cortex_pre_review_gate_20260429.md
builder: b2
shipped_at: 2026-04-29T02:25:00Z
trigger_class: HIGH
branch: cortex-pre-review-gate-1 (continuation — same PR #80, new commit on top)
pr_url: https://github.com/vallen300-bit/baker-master/pull/80
review_required:
  - "AI Head A solo — /security-review re-run + sections C (URL endpoint) + E (Idempotency) recheck"
ship_gate_pass: true
---

# B2 Ship Report — CORTEX_PRE_REVIEW_GATE_2_HARDEN

## Two blockers closed

### Blocker 1 — TOCTOU race (security-review confidence 9, MEDIUM cost-loss)

`record_decision()` previously did an unconditional `INSERT`. Between the prior `already_decided()` read and that INSERT there was no DB-level guard. Race surface:
- iPhone double-tap on slow 4G (perceived non-response → user re-taps)
- Slack URL preview unfurl GET (closed via Blocker 2 below)
- Tab reload, browser back+forward, etc.

Result without fix: 2× $4 cycles + 2× competing matter-state writes.

**Fix:** `record_decision` now does a single atomic conditional INSERT and returns `bool`. The dashboard endpoint only schedules the BackgroundTask if `record_decision` returned `True` (i.e. THIS caller actually claimed the row).

```sql
INSERT INTO baker_actions (action_type, target_task_id, payload, trigger_source, success)
SELECT %s, %s, %s::jsonb, %s, %s
WHERE NOT EXISTS (
    SELECT 1 FROM baker_actions
    WHERE target_task_id = %s
      AND action_type IN ('cortex:gate:approved','cortex:gate:skipped')
)
RETURNING id
```

Postgres serializes concurrent attempts against the same `target_task_id` at row-lock level. The losing INSERT writes no row → `cur.fetchone()` returns `None` → return `False` → endpoint shows "Already decided" instead of firing.

### Blocker 2 — Slack URL unfurl side-fire on post (HIGH)

`outputs/slack_notifier.post_to_channel(channel, text)` did not pass `unfurl_links` / `unfurl_media`. Slack's default = unfurl ON. The `Slackbot-LinkExpanding` URL-preview fetcher GETs every URL in a posted message at post time. Our gate URL is a side-effecting GET — Slackbot's preview fetch alone would fire `record_decision` + cycle the moment we POST the DM, before the Director ever taps. Textbook fire-on-post bug (and a violation of HTTP semantics for GET).

**Fix:**
- `post_to_channel` extended with optional `unfurl_links: Optional[bool] = None` + `unfurl_media: Optional[bool] = None` kwargs. Default `None` preserves existing behavior for **all 4 existing callers** (audit_sentinel, ai_head_audit×2, wiki_lint, pm_state_write).
- `post_gate` explicitly passes `unfurl_links=False, unfurl_media=False`.

## Files modified

```
 outputs/dashboard.py                 |  +20  (claim-check + 'Already decided' branch)
 outputs/slack_notifier.py            |  +29  (optional unfurl_links/unfurl_media kwargs)
 triggers/cortex_pre_review_gate.py   |  +57  (atomic INSERT + return bool + json import + post_gate flags)
 tests/test_cortex_pre_review_gate.py | +134  (3 new tests; 1 prior test fixture updated)
 briefs/_reports/B2_cortex_pre_review_gate_2_harden_20260429.md   # this report
 briefs/_tasks/CODE_2_PENDING.md      # mailbox: OPEN→IN_PROGRESS, claimed_by:b2
```

## Files NOT touched (per brief)

- `orchestrator/cortex_runner.py`
- `kbl/bridge/alerts_to_signal.py`
- `triggers/cortex_pipeline.py` (gate fork already correct from PR #80)
- All other dashboard endpoints
- `audit_sentinel.py` / `ai_head_audit.py` / `wiki_lint.py` (post_to_channel callers — verified unaffected by their tests passing)

## Ship gate verification (Lesson #47 — no "by inspection")

### Syntax checks (3 files)

```
$ python3 -c "import py_compile; py_compile.compile('triggers/cortex_pre_review_gate.py', doraise=True)" && echo gate.py OK
gate.py OK
$ python3 -c "import py_compile; py_compile.compile('outputs/slack_notifier.py', doraise=True)" && echo slack_notifier.py OK
slack_notifier.py OK
$ python3 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True)" && echo dashboard.py OK
dashboard.py OK
```

### All 10 gate tests — literal stdout

```
$ pytest tests/test_cortex_pre_review_gate.py -v
collected 10 items

tests/test_cortex_pre_review_gate.py::test_sign_verify_roundtrip PASSED                          [ 10%]
tests/test_cortex_pre_review_gate.py::test_verify_expired PASSED                                 [ 20%]
tests/test_cortex_pre_review_gate.py::test_verify_bad_signature PASSED                           [ 30%]
tests/test_cortex_pre_review_gate.py::test_verify_unknown_action PASSED                          [ 40%]
tests/test_cortex_pre_review_gate.py::test_secret_unset_disables_gate PASSED                     [ 50%]
tests/test_cortex_pre_review_gate.py::test_already_decided_returns_prior PASSED                  [ 60%]
tests/test_cortex_pre_review_gate.py::test_gate_decide_endpoint_approve_flow PASSED              [ 70%]
tests/test_cortex_pre_review_gate.py::test_record_decision_claim_then_loser PASSED               [ 80%]
tests/test_cortex_pre_review_gate.py::test_gate_decide_endpoint_race_loser_does_not_fire_cycle PASSED [ 90%]
tests/test_cortex_pre_review_gate.py::test_post_gate_disables_slack_unfurl PASSED                [100%]

======================== 10 passed, 6 warnings in 1.42s ========================
```

7 prior tests still PASS + 3 new PASS = 10/10 literal.

### Regression — gate + alerts bridge + cortex runner + post_to_channel callers

```
$ pytest tests/test_cortex_pre_review_gate.py \
         tests/test_alerts_to_signal_cortex_dispatch.py \
         tests/test_cortex_runner_phase126.py \
         tests/test_pm_state_write.py \
         tests/test_audit_sentinel.py \
         tests/test_ai_head_weekly_audit.py \
         tests/test_autopoll_state.py
======================== 80 passed, 9 warnings in 1.39s ========================
```

(Brief listed `tests/test_cortex_pipeline.py` — that file does not exist in the tree; pipeline-shape coverage is at `test_alerts_to_signal_cortex_dispatch.py`. Coverage of all 4 existing `post_to_channel` callers confirmed via `grep -l post_to_channel tests/`.)

## Quality checkpoints (brief §"Quality Checkpoints")

| # | Checkpoint                                                                | Status |
|---|---------------------------------------------------------------------------|--------|
| 1 | py_compile clean on all 3 modified files                                  | ✅ PASS |
| 2 | `test_record_decision_claim_then_loser` PASS literal                      | ✅ PASS |
| 3 | `test_gate_decide_endpoint_race_loser_does_not_fire_cycle` PASS literal   | ✅ PASS |
| 4 | `test_post_gate_disables_slack_unfurl` PASS literal                       | ✅ PASS |
| 5 | All 7 prior gate tests still PASS literal                                 | ✅ PASS |
| 6 | Regression suite PASS literal                                             | ✅ PASS (80/80) |
| 7 | `post_to_channel` existing callers unaffected (default kwargs=None preserves prior signature) | ✅ PASS (test_audit_sentinel + test_ai_head_weekly_audit + test_pm_state_write + test_autopoll_state all green) |
| 8 | Branch is still `cortex-pre-review-gate-1`; same PR #80                   | ✅ PASS (force-push after rebase onto main with mailbox-conflict resolution) |

## Security surface review (B2 self-walkthrough — formal review = AI Head A solo)

| Check                                            | Implementation                                                              |
|--------------------------------------------------|-----------------------------------------------------------------------------|
| Atomic claim                                     | `INSERT … SELECT … WHERE NOT EXISTS … RETURNING id` — single Postgres stmt |
| Return-value contract                            | `record_decision -> bool` (True = claimed, False = lost / DB error)         |
| Endpoint check                                   | `if not claimed: return "Already decided"` BEFORE BackgroundTask scheduling |
| `RETURNING` parsing                              | `cur.fetchone()` returns `None` when WHERE NOT EXISTS suppresses the INSERT |
| `conn.rollback()` in except path                 | Present, wrapped in nested try/except so rollback failure doesn't mask original error |
| `json.dumps` for payload                         | Promoted to top-level import; matter_slug/action sanitized                  |
| Slack unfurl off                                 | `post_gate` passes `unfurl_links=False, unfurl_media=False`                 |
| `post_to_channel` backward compat                | New kwargs are keyword-only (`*`) + default `None` → existing positional calls unchanged |
| Existing callers verified                        | 4 callers (audit_sentinel, ai_head_audit×2, wiki_lint via tests, pm_state_write) — all tests still pass |

## Deviations from brief

**None of substance.** Two micro-adjustments worth noting:

1. **`json` promoted to top-level import.** Brief example used inline `import json` inside the function; I moved it to the module-top alongside `base64/hashlib/hmac/...` for consistency with the rest of the module. Behavior identical.
2. **Existing test 7 fixture updated.** The pre-existing `test_gate_decide_endpoint_approve_flow`'s `_fake_record` returned `None`; with the new return-value contract that would have failed (None → `not claimed` → "Already decided" branch). Updated `_fake_record` to `return True`. Surfaced inline in the test for clarity. (Required to keep the prior 7 tests green.)

## After patch ships — A executes (per brief §"After patch ships")

1. `/security-review` re-run on the updated diff (focus: section C URL endpoint + section E idempotency)
2. Section C + E recheck (B1 review still valid for the rest)
3. Squash-merge PR #80 with both commits (originals + harden)
4. Render env vars + redeploy + smoke per original brief §"After merge — A executes"

## Force-push note

After the Director's `git rebase main` resolved the mailbox conflict, the branch's commit hashes shifted (`6471b135` → `da04826b`, `90104277` → `f8f995fc`). The harden commit lands on top of the rebased base. `git push` will need `--force-with-lease` to update the remote PR-80 branch — this is expected for any post-rebase ship. No history loss; both originals are still in the rebased graph.

## Co-Authored-By

```
Co-authored-by: Code Brisen #2 <b2@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
