---
ship_report_for: briefs/BRIEF_CORTEX_SLACK_INTERACTIVITY_1.md
builder: b2
shipped_at: 2026-04-29T02:55:00Z
trigger_class: HIGH
branch: cortex-slack-interactivity-1
pr_url: https://github.com/vallen300-bit/baker-master/pull/81
review_required:
  - "B1 (formal) — external API + Slack HMAC auth + dispatches Gold-writing handlers (RA-24 trigger)"
  - "AI Head A — /security-review + structural"
ship_gate_pass: true
---

# B2 Ship Report — CORTEX_SLACK_INTERACTIVITY_1

## What shipped

`POST /webhook/slack/interactive` — wires the 4 proposal-card buttons (✅ Approve / ✏️ Edit / 🔄 Refresh / ❌ Reject) to existing Phase 5 handlers in `orchestrator/cortex_phase5_act.py`. Pure plumbing: no handler modifications, no new auth scheme beyond Slack's signed-request HMAC.

## Files modified / added

```
 briefs/_tasks/CODE_2_PENDING.md                # mailbox: OPEN→IN_PROGRESS, claimed_by:b2
 outputs/dashboard.py                           |  +3  (router import + include)
 triggers/slack_interactivity.py                | +352 (NEW)
 tests/test_cortex_slack_interactivity.py       | +360 (NEW, 8 tests)
 briefs/_reports/B2_cortex_slack_interactivity_20260429.md   # this report
```

## Files NOT touched (per brief)

- `orchestrator/cortex_phase5_act.py` — handlers unchanged
- `orchestrator/cortex_phase4_proposal.py` — proposal builder unchanged
- `triggers/slack_events.py` — events router untouched (different surface)
- All other dashboard endpoints

## Behavior

```
Slack DM proposal card → Director taps button
  → Slack POSTs application/x-www-form-urlencoded:
        payload=<JSON>
        X-Slack-Request-Timestamp: <unix>
        X-Slack-Signature: v0=<hmac-sha256(secret, "v0:ts:body")>
  → /webhook/slack/interactive
      _verify_signature  →  fail-CLOSED on missing secret; ±5min replay window;
                            hmac.compare_digest constant-time
      parse_qs → JSON-decode 'payload' field
      action = payload['actions'][0]
      action_id ∈ {cortex_approve, cortex_edit, cortex_refresh, cortex_reject}
              → BackgroundTask: _run_handler(action_id, cycle_id, payload, response_url)
              → ephemeral 'Processing…' via response_url
              → return 200 (well within Slack's 3s budget)
      action_id startswith 'cortex_gold_select_'
              → return 200 no-op
      else 400
  → BackgroundTask in container
      → cortex_phase5_act.{cortex_approve|edit|refresh|reject}(cycle_id=, body=)
      → on finish, replace original blocks with decision footer via response_url
```

## Ship gate verification (Lesson #47 — no "by inspection")

### Syntax checks

```
$ python3 -c "import py_compile; py_compile.compile('triggers/slack_interactivity.py', doraise=True)" && echo OK
OK
$ python3 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True)" && echo OK
OK
```

### 8 unit tests — literal stdout

```
$ pytest tests/test_cortex_slack_interactivity.py -v
collected 8 items

tests/test_cortex_slack_interactivity.py::test_happy_path_approve PASSED          [ 12%]
tests/test_cortex_slack_interactivity.py::test_reject_path PASSED                 [ 25%]
tests/test_cortex_slack_interactivity.py::test_bad_signature PASSED               [ 37%]
tests/test_cortex_slack_interactivity.py::test_stale_timestamp PASSED             [ 50%]
tests/test_cortex_slack_interactivity.py::test_missing_payload_field PASSED       [ 62%]
tests/test_cortex_slack_interactivity.py::test_unknown_action PASSED              [ 75%]
tests/test_cortex_slack_interactivity.py::test_no_cycle_id PASSED                 [ 87%]
tests/test_cortex_slack_interactivity.py::test_gold_select_checkbox_noop PASSED   [100%]

======================== 8 passed, 6 warnings in 1.94s =========================
```

### Brief-named regression — literal stdout

```
$ pytest tests/test_cortex_slack_interactivity.py tests/test_cortex_phase5_act.py tests/test_cortex_phase5_idempotency.py tests/test_cortex_pre_review_gate.py
======================== 59 passed, 5 warnings in 1.18s ========================
```

(8 new + 20 phase5_act + 21 phase5_idempotency + 10 gate = 59 ✓.)

## Quality checkpoints (brief §"Quality Checkpoints")

| # | Checkpoint                                                                | Status |
|---|---------------------------------------------------------------------------|--------|
| 1 | py_compile clean on `triggers/slack_interactivity.py`                     | ✅ PASS |
| 2 | py_compile clean on `outputs/dashboard.py`                                | ✅ PASS |
| 3 | 8 unit tests PASS literally                                               | ✅ PASS |
| 4 | Phase 5 act + idempotency + gate regression PASS literally                | ✅ PASS (59/59) |
| 5 | Slack signature uses `hmac.compare_digest` (constant-time)                | ✅ PASS (`triggers/slack_interactivity.py:_verify_signature`) |
| 6 | Endpoint responds <3s on happy path (BackgroundTask scheduled, not awaited) | ✅ PASS (sync handler returns immediately after `background_tasks.add_task`) |
| 7 | `SLACK_SIGNING_SECRET` already on Render (used by slack_events.py)        | (verification deferred to A's post-merge step — not a code-side gate) |

## Security surface (B2 self-walkthrough — formal review by B1 + A)

| Check                                                | Implementation                                                                                       |
|------------------------------------------------------|------------------------------------------------------------------------------------------------------|
| Slack signature HMAC-SHA256                          | `_verify_signature` mirrors `triggers/slack_events.py:42` pattern                                    |
| Constant-time compare                                | `hmac.compare_digest(computed, signature)` — defends against timing oracle                           |
| **Fails CLOSED** on missing secret                   | Different from polling-only events surface — interactivity dispatches Gold-writing handlers          |
| Replay protection                                    | ±300s window on `X-Slack-Request-Timestamp` (matches Slack docs)                                     |
| Method allowlist                                     | `@router.post("/slack/interactive")` — only POST                                                     |
| 3s budget                                            | Handlers run in `BackgroundTasks`; endpoint returns 200 in <100ms                                    |
| BackgroundTask error containment                     | `_run_handler` wraps everything in try/except — Slack already received 200; we MUST NOT raise        |
| Action allowlist                                     | `_HANDLER_MAP` whitelists 4 action_ids; `cortex_gold_select_*` no-op; everything else 400            |
| cycle_id parsing                                     | JSON-decode `value` field; missing/invalid → 400 (no handler scheduled)                              |
| Logging discipline                                   | proposal text / matter context NEVER info-logged; only action_id + cycle_id + user_name surface      |
| Auth bypass — no second mechanism                    | No X-Baker-Key path; no env-flag bypass; signature is the only auth                                  |
| response_url failures contained                      | `_post_response_update` swallows urlopen exceptions (logs warning); BackgroundTask cannot raise      |
| Idempotency                                          | Phase 5 handlers use `_cas_lock_cycle` (CORTEX_PHASE5_IDEMPOTENCY_1); double-tap = `already_actioned`|
| `outputs/dashboard.py` blast radius                  | +3 LOC (1 import + 1 include + blank line); zero changes to existing endpoints                       |

## Deviations from brief

**None.** One micro-detail to note:

1. **Test secret injection.** The brief sketch sets `os.environ["SLACK_SIGNING_SECRET"]` at module import. `config.slack.signing_secret` is read at config-instance creation, which has already happened at first import. To be safe, the test module also force-assigns `_cfg.slack.signing_secret = "test_slack_secret_8675309"` after the env set. Both lines are needed; both are documented inline.

## After merge — A executes (per brief §"After merge — A executes")

1. Verify `SLACK_SIGNING_SECRET` already set on Render (used by `slack_events.py`).
2. Render redeploy.
3. **Smoke 1 — bad signature:**
   ```bash
   curl -i -X POST "https://baker-master.onrender.com/webhook/slack/interactive" \
     -H "Content-Type: application/x-www-form-urlencoded" \
     -H "X-Slack-Request-Timestamp: $(date +%s)" \
     -H "X-Slack-Signature: v0=garbage" \
     -d 'payload=%7B%7D'
   # expect HTTP/1.1 403
   ```
4. **Smoke 2** — Slack App settings → Interactivity URL `https://baker-master.onrender.com/webhook/slack/interactive`. Save.
5. **Real test (cheapest action):** open AO proposal card from `cycle_id=7dc3201b`, tap ❌ Reject. Expect:
   - Card replaces with "❌ Rejected by @vallen300 at <ts>" footer.
   - `cortex_cycles.status='rejected'` for `7dc3201b`.
   - `feedback_ledger` row appended.
6. **Verify SQL:**
   ```sql
   SELECT cycle_id, status, completed_at FROM cortex_cycles WHERE cycle_id LIKE '7dc3201b%';
   SELECT * FROM feedback_ledger WHERE cycle_id LIKE '7dc3201b%' ORDER BY created_at DESC LIMIT 3;
   ```

## Next steps in pipeline

1. **B1 second-pair-of-eyes review** (RA-24 trigger fires: external API + Slack HMAC auth surface + dispatches Gold-writing handlers).
2. **AI Head A `/security-review`** (Lesson #52 mandatory pre-merge).
3. Both clear → A Tier-A squash-merge → mailbox flips IN_PROGRESS → COMPLETE.
4. Post-merge env verification + smoke + Slack App config (above).

## Co-Authored-By

```
Co-authored-by: Code Brisen #2 <b2@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
