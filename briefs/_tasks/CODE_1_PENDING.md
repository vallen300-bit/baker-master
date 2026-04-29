# CODE_1 — B1: PR #81 STRUCTURAL REVIEW (CORTEX_SLACK_INTERACTIVITY_1)

**Status:** OPEN
**Dispatched:** 2026-04-29T~05:30Z
**Dispatched by:** ai-head-a (sole orchestrator)
**Director authorization:** RA-24 trigger class (external API + Slack HMAC auth surface + dispatches Gold-writing handlers)
**Builder under review:** b2 (≠ b1 ✓)
**Trigger class:** HIGH
**PR:** https://github.com/vallen300-bit/baker-master/pull/81
**Branch:** `cortex-slack-interactivity-1`
**Brief:** `briefs/BRIEF_CORTEX_SLACK_INTERACTIVITY_1.md`
**B2 ship report:** `briefs/_reports/B2_cortex_slack_interactivity_20260429.md`

## What B2 shipped

`POST /webhook/slack/interactive` — wires the 4 proposal-card buttons (Approve / Edit / Refresh / Reject) on AO proposal cards to existing Phase 5 handlers in `orchestrator/cortex_phase5_act.py`. Pure plumbing: no handler modifications, no new auth scheme beyond Slack v0 HMAC.

Files modified:
- NEW `triggers/slack_interactivity.py` (+352 LOC)
- MOD `outputs/dashboard.py` (+3 LOC: router import + include)
- NEW `tests/test_cortex_slack_interactivity.py` (+360 LOC, 8 tests)

Files NOT touched (per brief): `orchestrator/cortex_phase5_act.py`, `orchestrator/cortex_phase4_proposal.py`, `triggers/slack_events.py`.

## Execution

```bash
cd ~/bm-b1/01_build
git fetch origin && git checkout cortex-slack-interactivity-1 && git pull -q
git log --oneline main..HEAD   # expect: bf3d2c8d + 96c2e56b

# 1) Re-run ship gate locally on PR head (Lesson #48)
pytest tests/test_cortex_slack_interactivity.py -v
pytest tests/test_cortex_slack_interactivity.py tests/test_cortex_phase5_act.py tests/test_cortex_phase5_idempotency.py tests/test_cortex_pre_review_gate.py
python3 -c "import py_compile; py_compile.compile('triggers/slack_interactivity.py', doraise=True)"
python3 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True)"

# 2) Walk the 10 sections below — verdict per section
# 3) Confirm scope (only the 5 listed files in PR)
gh pr view 81 --json files --jq '.files[].path'
```

## Review sections (10) — verdict per section + evidence (file:line) + literal stdout

### A — HMAC correctness
- v0 scheme: signature base = `"v0:" + timestamp + ":" + body`
- HMAC-SHA256 with `SLACK_SIGNING_SECRET`
- `hmac.compare_digest(computed, received)` constant-time compare
- Compare hex-encoded value (Slack format `v0=<hex>`)

### B — Secret hygiene & fail-CLOSED divergence
- Missing/empty `SLACK_SIGNING_SECRET` → endpoint **fails CLOSED** (deliberate divergence from `triggers/slack_events.py` polling-only events surface)
- Document divergence reason in code comment OR module docstring
- No log statement leaks the secret value

### C — Endpoint contract
- Method allowlist: POST only
- Body: `application/x-www-form-urlencoded` with `payload` field
- `parse_qs` then `json.loads` on `payload` value
- Action ID extraction: `payload['actions'][0]['action_id']`
- Action allowlist: `{cortex_approve, cortex_edit, cortex_refresh, cortex_reject}` + `cortex_gold_select_*` no-op; everything else → 400
- `cycle_id` parsing from button `value` (JSON) — missing/invalid → 400, NO handler scheduled

### D — Phase 5 handler dispatch
- Each allowlisted action_id maps to exactly the corresponding `cortex_phase5_act.{cortex_approve|edit|refresh|reject}`
- Handler invoked via `BackgroundTasks.add_task(...)` — NOT awaited synchronously
- Idempotency relies on `_cas_lock_cycle` already in handlers (don't re-implement)

### E — 3s budget compliance
- Endpoint returns 200 in <100ms on happy path
- Ephemeral "Processing…" posted via `response_url` from BackgroundTask, NOT before return
- No DB read/write in synchronous endpoint path before return

### F — Sensitive payload discipline
- Proposal text, matter context, full Slack payload body NEVER appear in `logger.info()` / `logger.warning()` / `logger.error()`
- Only `action_id`, `cycle_id`, `user_name` (or `user_id`) and exception type+short-message may surface
- Grep PR head: `grep -n 'logger\.' triggers/slack_interactivity.py` — confirm no full payload/text logged

### G — Error containment in BackgroundTask
- `_run_handler` wraps EVERYTHING in try/except — Slack already received 200; raising would be silent leak
- `_post_response_update` (or equivalent) swallows urlopen failures (warns, doesn't raise)
- No bare `raise` after BackgroundTask is scheduled

### H — Test integrity
- 8 tests cover: happy approve, happy reject, bad sig, stale ts, missing payload, unknown action, no cycle_id, gold_select no-op
- All 8 PASS literally on PR head (re-run output in §0 of report)
- Regression 59/59 PASS on PR head (interactivity + phase5_act + phase5_idempotency + pre_review_gate)
- No `pytest.skip` / `xfail` / "by inspection" claims (Lesson #50)

### I — Scope discipline
- `gh pr view 81 --json files --jq '.files[].path'` returns ONLY:
  - `briefs/_reports/B2_cortex_slack_interactivity_20260429.md`
  - `briefs/_tasks/CODE_2_PENDING.md`
  - `outputs/dashboard.py`
  - `tests/test_cortex_slack_interactivity.py`
  - `triggers/slack_interactivity.py`
- `orchestrator/cortex_phase5_act.py`, `orchestrator/cortex_phase4_proposal.py`, `triggers/slack_events.py` UNTOUCHED

### J — Render deploy survival
- No new migration / no DB schema change
- `SLACK_SIGNING_SECRET` already on Render (used by `slack_events.py`)
- No new third-party dep (stdlib `hmac`, `hashlib`, `urllib`, `json`, `time`)
- Router include under `/webhook` prefix doesn't shadow existing routes

## STOP criteria

Any of these → STOP, post REQUEST_CHANGES with cited file:line + reproducer:

- HMAC compare uses `==` instead of `hmac.compare_digest`
- Missing-secret path returns 200 (must fail CLOSED)
- Replay window > ±300s
- Any handler invoked synchronously (would blow Slack's 3s budget)
- BackgroundTask path can raise (Slack already received 200)
- Proposal text / matter content appears in any `logger.*()` call
- Action allowlist allows arbitrary action_id through
- Tests fail or any "by inspection" / `pytest.skip` claims (Lesson #47, #50)
- Files outside the 5-file scope modified
- Pre-existing endpoints in `outputs/dashboard.py` modified

## Output

`briefs/_reports/B1_pr81_review_20260429.md` — same format as `B1_pr80_review_20260429.md`:
- §0: literal stdout for all 4 ship-gate commands
- §A–§J: per-section verdict (PASS / FAIL) + evidence (file:line)
- §K: non-blocking observations (note-only)
- Final verdict line: `**OVERALL: PASS / REQUEST_CHANGES**`

If PASS: post comment-fallback approval on PR #81 (self-PR rule precedent #67/#69/#70/#71/#78 — formal GitHub APPROVE blocked).

Mailbox flips OPEN → IN_PROGRESS on claim → COMPLETE on report committed + pushed.

## Co-Authored-By

```
Co-authored-by: Code Brisen #1 <b1@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
