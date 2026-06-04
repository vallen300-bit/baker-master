---
type: ship_report
brief: BRIEF_WORKER_SELFWAKE_PHASE_1
author: b2
shipped_at: 2026-05-15
pr: 205
pr_url: https://github.com/vallen300-bit/baker-master/pull/205
branch: b2/worker-selfwake-phase-1
commit_sha: c309c97
director_anchor: 2026-05-14 chat ("go" on Phase 1 only; cadence 2 min; daily digest @ 09:00 UTC; no veto window)
trigger_class: TIER_B_AGENT_RUNTIME
mandatory_2nd_pass: true
security_review_required: true
mailbox_transitions:
  - e2aece9 (b1 claimed, redirected)
  - ebcc1be (b2 redispatch)
bus_msgs:
  - "#231 ACK'd by b2 2026-05-14T22:31Z"
  - "#233 (claim heartbeat posted to lead)"
---

# B2 ship report — WORKER_SELFWAKE_PHASE_1

## Bottom line

Shipped Phase 1 of Stage 3 agent autonomy: per-B-code launchd worker that polls the brisen-lab bus every 120s and fires `claude --print` non-interactively in the picker dir on new messages. 11 files changed (5 new scripts, 2 new templates, 1 new migration, 2 new test files, 2 edited source files, 1 edited hook); +1463 LOC. 14/14 new tests pass; no regression on adjacent endpoint tests. PR #205 open against `main`.

## Literal pytest output

```
============================= test session starts ==============================
collecting ... collected 14 items
tests/test_baker_worker.py::test_kill_switch_off_short_circuits PASSED   [  7%]
tests/test_baker_worker.py::test_lock_alive_skips_cycle PASSED           [ 14%]
tests/test_baker_worker.py::test_breaker_tripped_skips PASSED            [ 21%]
tests/test_baker_worker.py::test_rate_cap_reached_skips PASSED           [ 28%]
tests/test_baker_worker.py::test_cost_cap_reached_pushes_slack_once PASSED [ 35%]
tests/test_baker_worker.py::test_no_new_messages_quiet_exit PASSED       [ 42%]
tests/test_baker_worker.py::test_new_messages_full_flow PASSED           [ 50%]
tests/test_baker_worker.py::test_breaker_trips_after_three_consecutive_claude_failures PASSED [ 57%]
tests/test_worker_wake_audit.py::test_worker_wake_unauthorized PASSED    [ 64%]
tests/test_worker_wake_audit.py::test_worker_wake_valid_payload_writes_row PASSED [ 71%]
tests/test_worker_wake_audit.py::test_worker_wake_missing_field PASSED   [ 78%]
tests/test_worker_wake_audit.py::test_worker_wake_invalid_slug PASSED    [ 85%]
tests/test_worker_wake_audit.py::test_worker_digest_unauthorized PASSED  [ 92%]
tests/test_worker_wake_audit.py::test_worker_digest_aggregates PASSED    [100%]
======================== 14 passed, 7 warnings in 1.06s ========================
```

Adjacent regression check: `pytest tests/test_cortex_run_endpoint.py tests/test_tier_b_runtime.py -q` → **11 passed, 10 skipped** (skips are env-gated live-PG).

Test runtime env: `~/bm-b2/.venv312/bin/python -m pytest`, Python 3.12.12, pytest 9.0.3, fastapi 0.136.0, pydantic 2.13.3.

## Token-count probe outcome (REQUIRED — §Token accounting probe)

**Verdict:** `claude --print --output-format=json` reliably emits parseable token usage. Worker invokes with `--output-format=json` and sums `modelUsage[<model>].{inputTokens, outputTokens, cacheReadInputTokens, cacheCreationInputTokens}` across all model keys. Fallback `usage` (snake_case) path supported for older claude versions. Final fallback `FALLBACK_TOKENS_PER_WAKE = 1000` constant when both surfaces miss (rate cap + wake count still bound damage either way).

Probe command:
```
cd /tmp && /opt/homebrew/bin/claude --print --output-format=json --max-budget-usd 0.05 "Reply with only: pong"
```

Probe stdout (top-level keys observed):
```
['type', 'subtype', 'duration_ms', 'duration_api_ms', 'is_error', 'num_turns',
 'stop_reason', 'session_id', 'total_cost_usd', 'usage', 'modelUsage',
 'permission_denials', 'fast_mode_state', 'uuid', 'errors']
```

`modelUsage` block from probe:
```json
{
  "claude-opus-4-7[1m]": {
    "inputTokens": 6, "outputTokens": 6,
    "cacheReadInputTokens": 18295, "cacheCreationInputTokens": 24241,
    "webSearchRequests": 0, "costUSD": 0.16083374999999997,
    "contextWindow": 1000000, "maxOutputTokens": 64000
  }
}
```

**Cost-of-cold-wake observation.** The probe was budget-capped at $0.05 → tripped at **$0.16 actual** because every cold wake loads the full CLAUDE.md + role orientation + canonical memory (~24K cache-creation tokens, $0.16 cost). This confirms the brief's upper-end estimate ($0.30/wake) is realistic for cold starts. Per-worker daily cap of 100K tokens implies ~3-5 wake budget under cold-start cost; 4/hour rate cap is the binding constraint either way.

## 10 Quality Checkpoint outcomes

| # | Checkpoint | Status | Note |
|---|---|---|---|
| 1 | Migration applies clean on staging Neon | **Deferred to gate chain** | Single INSERT into `tier_b_action_classes` with `ON CONFLICT DO NOTHING`; can't be DDL-broken. Bootstrap path mirrored in `memory/store_back.py:1162` for fresh-env idempotency. |
| 2 | `pytest tests/test_worker_wake_audit.py tests/test_baker_worker.py -v` literal green | ✅ | 14/14 pass; output captured above. NO "by inspection". |
| 3 | Install one B-code first (b1) + launchctl list + manual kick + clean log | **Deferred to gate chain** | Installer runs on Director's Mac (1P + Slack webhook env); B2 cannot test from picker session (no launchd access from Render or from inside a claude session). Installer was syntax-checked via `bash -n`. |
| 4 | End-to-end probe: bus msg → worker fires ≤120s → claude runs → ack → DB row | **Deferred to gate chain** | Requires install + ~3 min runtime. Hand-off to AH1 post-merge. |
| 5 | Breaker probe (3 failures → trip → Slack) | ✅ unit-level | `test_breaker_trips_after_three_consecutive_claude_failures` verifies the state-machine end-to-end with mocked claude. Manual run with bogus prompts deferred to install gate. |
| 6 | Cost cap probe (seed `tokens_today: 99999`) | ✅ unit-level | `test_cost_cap_reached_pushes_slack_once` verifies cap-then-skip + idempotent Slack push (no repeat same day). |
| 7 | Rate cap probe (seed 4 recent_wakes_60min) | ✅ unit-level | `test_rate_cap_reached_skips` verifies. |
| 8 | Concurrent-picker collision (lock + worker-kick) | ✅ unit-level | `test_lock_alive_skips_cycle` verifies live-PID lock semantics. SessionStart hook writes the lock for b1-b4 picker sessions (`.claude/hooks/session-start-role.sh:65-78`). Live-Mac probe deferred. |
| 9 | 24h monitor: ≤30 wakes, <€5 cost | **N/A pre-install** | Burn-in observation post-deploy. |
| 10 | 7d digest review | **N/A pre-install** | Daily digest scheduled @ 09:00 UTC via `com.baker.worker-digest.plist`. |

## Deviations from brief (surfaced for reviewers)

1. **Pydantic returns 422, not 400.** Brief specified "400 on missing field / invalid worker_slug"; FastAPI's auto-validation returns 422 (Unprocessable Entity) for Pydantic violations. Tests assert 422. Behavior is canonical FastAPI.
2. **Column name correction.** Brief used `action_payload`; actual `baker_actions` column is **`payload`** (verified against `memory/store_back.py:1044` + `migrations/20260510_baker_actions_tier_b_runtime.sql:8-17`). All endpoint SQL + digest aggregation use `payload`.
3. **Auth dependency pattern.** Brief showed inline `request.headers.get("X-Baker-Key")`; endpoints use canonical `dependencies=[Depends(verify_api_key)]` matching `/api/cortex/run` neighbor. Same auth, cleaner pattern.
4. **`get_db_connection()` doesn't exist.** Brief flagged this as needing grep-verification — the canonical pattern is `_get_store()._get_conn()` / `store._put_conn(conn)` (SentinelStoreBack singleton). Used throughout.
5. **`--output-format=json` invocation.** Brief left `claude --print` as the default invocation; worker uses `claude --print --output-format=json` to make `_parse_tokens()` deterministic. The probe in §Token accounting probe is what drove this.
6. **SessionEnd hook gap.** No `b<N>-session-end.sh` exists today. The 15-min stale-TTL in `_lock_alive()` is the safety net when interactive picker closes (PID dies → `os.kill(pid, 0)` raises ProcessLookupError → lock cleared on next worker tick). Brief noted this as an open Q; B2 chose to defer SessionEnd generalization (out of scope for Phase 1 + reversible). Flag for follow-up if Director wants tighter cleanup than 15 min.

## Open issues / follow-ups

- **Cold-wake cost above €0.10 midpoint.** Probe shows ~$0.16 (~€0.15) per cold wake just for context load. Burn-in will validate; if sustained, refine `EUR_PER_TOKEN` constant (currently 0.0001 → €0.04 for 375 tokens). Brief's open Q #1 covers this — defer to first 7d Anthropic invoice mapping.
- **`--max-budget-usd` flag not piped through.** Worker doesn't pass a budget cap to claude; relies on token cap on the *worker* side. Optional hardening: pipe a per-wake budget into `claude --print --max-budget-usd <X>` to fail-fast at API boundary. Not blocking for Phase 1.

## Mandatory 4-gate review chain (post-ship)

Per brief `gate_chain_post_ship`:

1. **AH2 static review** — pending
2. **AH2 `/security-review`** (mandatory: new automation surface + token handling) — pending
3. **picker-architect review** — pending
4. **`feature-dev:code-reviewer` 2nd-pass** (parallel; trigger 1+3+4+7) — pending

All 4 must clear before merge.

## Bus-post

Will post `ship/WORKER_SELFWAKE_PHASE_1` topic to `lead` on completion of this report (same chat turn).
