---
status: IN_PROGRESS
brief: briefs/BRIEF_CORTEX_PRE_REVIEW_GATE_2_HARDEN.md
trigger_class: HIGH
dispatched_at: 2026-04-29T01:55:00Z
dispatched_by: ai-head-a
director_authorization: "A" (gate path) — A surfaced 2 blockers from /security-review + post-review analysis: (1) TOCTOU race in idempotency, (2) Slack unfurler GETs signed URLs on post → side-fire without Director tap
predecessor_pr: 80
predecessor_state: "PR #80 B1 PASS 10/10 + 7/7 tests + regression 35/35. /security-review found 1 MEDIUM (race, conf 9). A-additional finding: Slack auto-unfurl will GET the signed Yes/Skip URLs and fire record_decision + cycle without Director tapping — fire-on-post bug."
goal: "Two surgical patches on top of cortex-pre-review-gate-1 branch, then re-clear /security-review and merge: (1) atomic conditional INSERT in record_decision, return bool, endpoint only fires BackgroundTask if claimed; (2) extend post_to_channel with unfurl_links/unfurl_media kwargs and have post_gate pass False/False."
scope_summary:
  - "MOD triggers/cortex_pre_review_gate.py — record_decision returns bool, atomic INSERT WHERE NOT EXISTS, post_gate passes unfurl flags"
  - "MOD outputs/slack_notifier.py — post_to_channel optional unfurl_links/unfurl_media kwargs (default None preserves existing callers)"
  - "MOD outputs/dashboard.py — gate endpoint checks record_decision return; lost-race → 'Already decided' page"
  - "MOD tests/test_cortex_pre_review_gate.py — 3 new tests: claim/loser, race-loser-no-fire, post_gate-disables-unfurl"
files_modified:
  - triggers/cortex_pre_review_gate.py
  - outputs/slack_notifier.py
  - outputs/dashboard.py
  - tests/test_cortex_pre_review_gate.py (append 3 tests)
files_not_to_touch:
  - orchestrator/cortex_runner.py
  - kbl/bridge/alerts_to_signal.py
  - triggers/cortex_pipeline.py (gate fork already correct from PR #80)
  - audit_sentinel.py / ai_head_audit.py / wiki_lint.py (existing post_to_channel callers must stay unaffected — verify by their tests post-patch)
b1_review_required: false
b1_review_reason: "B1 already PASS 10/10 on PR #80 structural. Patches are surgical hardening of areas A is re-reviewing (sections C + E). A solo /security-review re-run sufficient."
builder: b2
reviewer: ai-head-a (solo /security-review re-run + section C + E recheck)
claimed_at: 2026-04-29T02:00:00Z
claimed_by: b2
last_heartbeat: 2026-04-29T02:00:00Z
blocker_question: null
ship_report: briefs/_reports/B2_cortex_pre_review_gate_2_harden_20260429.md
autopoll_eligible: false
---

# CODE_2_PENDING — B2: CORTEX_PRE_REVIEW_GATE_2_HARDEN — 2026-04-29

**Dispatcher:** AI Head A (sole orchestrator)
**Working dir:** `~/bm-b2/01_build`, branch `cortex-pre-review-gate-1` (continuation of PR #80)
**Trigger class:** HIGH (still — hardening on external API + auth path)

## Read full brief

`briefs/BRIEF_CORTEX_PRE_REVIEW_GATE_2_HARDEN.md` — full spec, copy-pasteable code, 3 new tests.

## Two blockers being closed

**Blocker 1 (security-review confidence 9, MEDIUM):** TOCTOU race — `already_decided` then `record_decision` is not atomic; double-tap or unfurl GET → 2× $4 cycles.

**Blocker 2 (A finding, HIGH):** `outputs/slack_notifier.post_to_channel` doesn't pass `unfurl_links: false` — Slack's URL preview fetcher (`Slackbot-LinkExpanding`) GETs every URL in the message → would auto-fire `?action=approve` the moment we POST the gate DM.

Both must close before merge.

## Execution

```bash
cd ~/bm-b2/01_build
git checkout cortex-pre-review-gate-1 && git pull -q

# Read brief
cat briefs/BRIEF_CORTEX_PRE_REVIEW_GATE_2_HARDEN.md | less

# Implement Fix 1: triggers/cortex_pre_review_gate.py
#   - record_decision returns bool
#   - atomic INSERT ... WHERE NOT EXISTS ... RETURNING id
#   - import json (if not already)
# Implement Fix 1 (cont): outputs/dashboard.py
#   - claimed = record_decision(...); if not claimed: return "Already decided" 200; else schedule task
# Implement Fix 2: outputs/slack_notifier.py
#   - post_to_channel adds optional unfurl_links / unfurl_media kwargs
# Implement Fix 2 (cont): triggers/cortex_pre_review_gate.py
#   - post_gate passes unfurl_links=False, unfurl_media=False
# Tests: append 3 to tests/test_cortex_pre_review_gate.py
#   - test_record_decision_claim_then_loser
#   - test_gate_decide_endpoint_race_loser_does_not_fire_cycle
#   - test_post_gate_disables_slack_unfurl

# Syntax check
python3 -c "import py_compile; py_compile.compile('triggers/cortex_pre_review_gate.py', doraise=True)"
python3 -c "import py_compile; py_compile.compile('outputs/slack_notifier.py', doraise=True)"
python3 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True)"

# All gate tests must PASS literally (existing 7 + 3 new = 10)
pytest tests/test_cortex_pre_review_gate.py -v

# Regression: gate + cortex pipeline + alerts bridge + phase126 + post_to_channel callers if their tests exist
pytest tests/test_cortex_pre_review_gate.py tests/test_cortex_pipeline.py tests/test_alerts_to_signal_cortex_dispatch.py tests/test_cortex_runner_phase126.py tests/test_pm_state_write.py -v

# Commit + push (same PR #80; new commit on top)
git add triggers/cortex_pre_review_gate.py outputs/slack_notifier.py outputs/dashboard.py tests/test_cortex_pre_review_gate.py briefs/BRIEF_CORTEX_PRE_REVIEW_GATE_2_HARDEN.md briefs/_tasks/CODE_2_PENDING.md
git commit -m "fix(cortex): close TOCTOU race + Slack unfurl side-fire on gate

Two blockers from A's /security-review on PR #80:

1. TOCTOU race in record_decision (sec-review conf 9): no DB-level
   atomicity between already_decided() check and INSERT. Replace with
   single conditional INSERT WHERE NOT EXISTS — atomic at row-lock.
   record_decision now returns bool (claimed/lost). Endpoint only fires
   BackgroundTask when claimed=True.

2. Slack unfurl fires gate URLs server-side on post (HIGH): Slackbot's
   link preview fetcher GETs every URL in a posted message; our gate
   endpoint is a side-effecting GET. Without unfurl_links=false, posting
   the DM would auto-trigger record_decision + cycle BEFORE Director
   ever tapped. Extend post_to_channel with unfurl_links/unfurl_media
   kwargs (default None preserves existing callers); post_gate now
   passes False/False.

3 new tests; existing 7 still pass; regression suite still passes.

Brief: briefs/BRIEF_CORTEX_PRE_REVIEW_GATE_2_HARDEN.md
Continuation of PR #80, no new branch.

Co-authored-by: Code Brisen #2 <b2@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"

git push origin cortex-pre-review-gate-1
```

(No new PR — same #80; the new commit appends.)

## Pass criteria

- 10 gate tests PASS literally
- Regression PASS literally
- py_compile clean on all 3 modified files
- `post_to_channel` callers (audit_sentinel, ai_head_audit, wiki_lint) unaffected — their tests still pass
- Single new commit on `cortex-pre-review-gate-1` branch

## STOP criteria

- Any test fails → STOP, surface
- `post_to_channel` default behavior changes for existing callers (i.e. unfurl_links param is required, not optional) → STOP
- Atomic INSERT pattern is wrong (e.g. uses `ON CONFLICT` against an index that doesn't exist) → STOP, surface
- conn.rollback() missing in any except block → STOP

## Output

Append to `briefs/_reports/B2_cortex_pre_review_gate_20260429.md` OR create new `briefs/_reports/B2_cortex_pre_review_gate_2_harden_20260429.md` with: new commit SHA on PR #80 + literal test stdout (10 gate + regression) + py_compile output + summary of file deltas.

## After patch ships — A executes

1. /security-review re-run on updated PR #80 diff (post-hardening) — must clear
2. Solo recheck of B1 sections C + E (URL endpoint + Idempotency) — should now be clean
3. Squash-merge PR #80
4. Render env vars (`CORTEX_GATE_SECRET` 48-char + `CORTEX_GATE_ENABLED=true`) + redeploy
5. Smoke (per original brief §"After merge — A executes")

## Co-Authored-By

```
Co-authored-by: Code Brisen #2 <b2@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
