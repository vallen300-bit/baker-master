---
status: OPEN
brief: review_pr_80_cortex_pre_review_gate_1
trigger_class: HIGH
dispatched_at: 2026-04-29T01:30:00Z
dispatched_by: ai-head-a
director_authorization: "A" (Pick A — URL-based pre-cycle approval gate to economize cost)
review_target_pr: 80
review_target_branch: cortex-pre-review-gate-1
review_target_url: https://github.com/vallen300-bit/baker-master/pull/80
builder: b2
reviewer: b1
ai_head_review: A is running /security-review in parallel
b1_review_reason: "External API + new signed-token auth surface (no X-Baker-Key — must be tap-from-Slack-iPhone friendly) + new Slack DM behavior on auto-dispatch path — RA-24 trigger fires"
goal: "Structural review of PR #80 BEFORE Tier-A merge. Confirm: (1) HMAC signing/verification correct + constant-time, (2) token unforgeable + bound to (signal_id, action, expires_at), (3) URL parameter handling safe (Pydantic / FastAPI query types), (4) idempotency via baker_actions audit works, (5) gate properly bypasses /api/cortex/trigger (manual path), (6) no scope creep beyond brief, (7) CORTEX_GATE_SECRET length validated, (8) Lesson #48 — tests PASS literally."
files_to_review:
  - triggers/cortex_pre_review_gate.py (NEW, +275 LOC)
  - triggers/cortex_pipeline.py (+55 LOC, gate fork)
  - outputs/dashboard.py (+110 LOC, /api/cortex/gate/decide endpoint + background-fire helper)
  - tests/test_cortex_pre_review_gate.py (NEW, +177 LOC, 7 tests)
  - briefs/_reports/B2_cortex_pre_review_gate_20260429.md (B2 ship report)
schema_deviation_note: "B2 corrected schema: signal_queue uses 'summary' + 'matter' columns (not 'signal_text'/'matter_slug' from brief). Anchored in module docstring."
known_pre_existing_bug: "test_cortex_trigger_endpoint.py::test_trigger_cortex_cycle_unauthorized fails when test_cortex_action_endpoint.py runs first. Confirmed pre-existing on main via git stash + checkout — NOT introduced by PR #80. Will be parked for separate follow-up."
claimed_at: null
claimed_by: null
last_heartbeat: null
blocker_question: null
ship_report: briefs/_reports/B1_pr80_review_20260429.md
autopoll_eligible: false
---

# CODE_1_PENDING — B1: REVIEW PR #80 CORTEX_PRE_REVIEW_GATE_1 — 2026-04-29

**Dispatcher:** AI Head A (sole orchestrator)
**Working dir:** `~/bm-b1/01_build`
**Trigger class:** HIGH (external API + signed-token auth + Slack-side cost gate behavior — RA-24 second-pair-of-eyes review required pre-merge)

## Predecessor

B2 shipped PR #80 at 2026-04-29T01:25Z. 7 unit tests PASS literally (1.47s). Regression suite (gate + alerts_to_signal + cortex_runner_phase126) = 35/35 PASS (1.17s). py_compile clean on all 3 modified files. B2's ship report: `briefs/_reports/B2_cortex_pre_review_gate_20260429.md`.

A is running /security-review on the same diff in parallel. Your review is structural; A's is security. Both must clear before merge.

## What this PR does

- NEW `triggers/cortex_pre_review_gate.py`: HMAC token sign/verify + signal preview lookup + Slack DM compose + `record_decision` audit insert
- MODIFY `triggers/cortex_pipeline.py`: `maybe_trigger_cortex` now forks on `CORTEX_GATE_ENABLED` (default true). Gate path posts cheap Slack DM + returns. Disabled-secret fallback continues to legacy direct-fire path
- MODIFY `outputs/dashboard.py`: NEW `GET /api/cortex/gate/decide` endpoint (signed-token auth via query params, no X-Baker-Key) + `_cortex_gate_fire_cycle` BackgroundTask helper
- 7 unit tests covering: token roundtrip, expired, bad-signature, unknown-action, secret-unset disables gate, already_decided idempotency, full endpoint approve flow

## Review checklist

### A — HMAC token correctness
- [ ] `hmac.new(secret.encode(), payload, hashlib.sha256)` — SHA-256 (not weaker)
- [ ] `hmac.compare_digest` is used in `verify_token` (constant-time, NOT `==`)
- [ ] Token is bound to `signal_id` + `action` + `expires_at` (substituting any of these fails verification)
- [ ] Base64url encoding (no `+`/`/` chars in URL)
- [ ] No information leak in failure message (gate_disabled / expired / bad_signature / invalid_action are 4 distinct buckets — fine; do they leak unsigned-message contents? probably not)

### B — Secret hygiene
- [ ] `_secret()` reads `CORTEX_GATE_SECRET`, returns `None` if `len < 32`
- [ ] `sign_token` returns empty string when secret unset (caller checks)
- [ ] Test confirms: secret-unset → `gate_disabled` returned + sign_token returns ""

### C — URL endpoint (`GET /api/cortex/gate/decide`)
- [ ] FastAPI query types are `int signal_id`, `str action`, `int exp`, `str token` (Pydantic-coerced; rejects non-int signal_id with 422)
- [ ] `verify_token` runs BEFORE any DB lookup (don't expose signal_queue rows on bad token)
- [ ] Bad token → 403 HTML response (not 200 with error JSON)
- [ ] Already-decided → 200 HTML with prior decision (idempotent re-click)
- [ ] Approve path: `record_decision` BEFORE `BackgroundTask.add_task` (so even if cycle fires twice, audit is one row — but BackgroundTask still added once per request; double-tap = check decision-already check on 2nd hit)
- [ ] Skip path: `record_decision` then 200 HTML — no cycle fire
- [ ] HTTPException re-raise present (no wrap-into-500 bug)

### D — `cortex_pipeline.py` fork
- [ ] `_gate_enabled()` reads `CORTEX_GATE_ENABLED` — default true
- [ ] When gate enabled + secret OK + `post_gate` returns True → `return` (no cycle fire)
- [ ] When gate enabled + secret missing → log error + fall through to legacy direct-fire
- [ ] When gate disabled → fall through to legacy direct-fire
- [ ] Existing `maybe_dispatch` sync entry point is unchanged

### E — Idempotency via baker_actions
- [ ] `already_decided` queries baker_actions for `cortex:gate:approved` / `cortex:gate:skipped` with `target_task_id = str(signal_id)` (signal_id is int → cast to str; consistent with insert)
- [ ] `record_decision` inserts both action_type + target_task_id + payload + trigger_source — all 4 audit columns populated
- [ ] On insert exception → conn.rollback() before raise (canonical PG pattern)

### F — Sensitive payload discipline
- [ ] `signal_text` / preview content NOT logged at info level
- [ ] Token NOT logged anywhere
- [ ] Slack DM has the preview (intentional — that's how Director decides) but logger does not echo it

### G — Bypass guarantee for `/api/cortex/trigger`
- [ ] Confirm `/api/cortex/trigger` is unchanged (manual Director path still bypasses gate)
- [ ] No path inside `maybe_run_cycle` triggers the gate (gate only happens on auto-dispatch)

### H — Test integrity (Lesson #48)
- [ ] All 7 new tests run as `pytest tests/test_cortex_pre_review_gate.py -v` and PASS
- [ ] Regression suite passes (B2 reported 35/35 — re-run on B1 worktree to confirm)
- [ ] No silent skips on missing env / dep
- [ ] `monkeypatch.setenv` + `importlib.reload` pattern is correctly applied (module-level secret read)

### I — Scope discipline
- [ ] Only the 4 listed files touched + bookkeeping (mailbox + ship report)
- [ ] `orchestrator/cortex_runner.py` untouched
- [ ] `kbl/bridge/alerts_to_signal.py` untouched
- [ ] No other dashboard endpoints modified

### J — Render deploy survival
- [ ] No DB migration (uses existing baker_actions + signal_queue)
- [ ] Two new env vars expected post-deploy: `CORTEX_GATE_SECRET`, `CORTEX_GATE_ENABLED` (gracefully degrades if missing)
- [ ] No new package dependency

## Pass / fail verdict

PASS if all 10 sections clear. PARTIAL_PASS if minor obs (note in ship report, do NOT block merge). FAIL if any blocker — surface to A immediately.

## Output

Create `briefs/_reports/B1_pr80_review_20260429.md` with:
- Section-by-section verdicts (A through J)
- Quoted line+code for any obs
- Final verdict: PASS / PARTIAL_PASS / FAIL
- Comment-fallback APPROVE message text (since GitHub blocks formal self-PR APPROVE)

If PASS: post your APPROVE comment to PR #80 via `gh pr comment 80 --body "..."`.

## STOP criteria

- HMAC compare_digest NOT used → STOP, surface (timing attack risk)
- Token NOT bound to all 3 fields (signal_id + action + expires_at) → STOP
- Auth bypass possible (e.g. token verified AFTER db lookup leaks rows) → STOP
- Audit insert without rollback in except → STOP
- /api/cortex/trigger regression → STOP
- Tests fail when re-run → STOP

## Co-Authored-By

```
Co-authored-by: Code Brisen #1 <b1@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
