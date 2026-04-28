---
ship_report_for: briefs/BRIEF_CORTEX_PRE_REVIEW_GATE_1.md
builder: b2
shipped_at: 2026-04-29T01:35:00Z
trigger_class: HIGH
branch: cortex-pre-review-gate-1
pr_url: <opened by gh pr create immediately after this report is committed>
review_required:
  - "B1 (formal) — external API + signed-token auth + Slack DM behavior change (RA-24 trigger)"
  - "AI Head A — /security-review + structural"
ship_gate_pass: true
---

# B2 Ship Report — CORTEX_PRE_REVIEW_GATE_1

## What shipped

URL-based pre-cycle approval gate. Director receives a cheap Slack DM ("📨 New AO signal — review with Cortex (~$4)?") with two signed-URL links instead of an immediate $4 cycle. Tap **✅ Yes** → cycle fires as a FastAPI background task. Tap **❌ Skip** → audit row only, no spend.

Director-manual `/api/cortex/trigger` (PR #78) is **unchanged** — bypasses the gate intentionally.

## Files modified / added

```
 briefs/_tasks/CODE_2_PENDING.md            # mailbox: OPEN→IN_PROGRESS, claimed_by:b2 (hygiene)
 outputs/dashboard.py                       | +110 (HTMLResponse import + endpoint + bg-fire helper)
 triggers/cortex_pipeline.py                |  +55 (_gate_enabled() + gate fork in maybe_trigger_cortex)
 triggers/cortex_pre_review_gate.py         | +275 (NEW — token sign/verify + Slack post + audit + lookups)
 tests/test_cortex_pre_review_gate.py       | +177 (NEW — 7 tests)
 briefs/_reports/B2_cortex_pre_review_gate_20260429.md  # this report
```

## Files NOT touched (per brief)

- `orchestrator/cortex_runner.py` — `maybe_run_cycle` signature + timeout semantics unchanged
- `kbl/bridge/alerts_to_signal.py` — bridge unchanged; calls `maybe_dispatch` whose interface is unchanged
- Existing `/api/cortex/trigger` endpoint — manual path, bypasses gate

## Behavior change summary

```
BEFORE  signal lands → maybe_dispatch → maybe_trigger_cortex → maybe_run_cycle ($4 every signal)
AFTER   signal lands → maybe_dispatch → maybe_trigger_cortex
                       └→ if CORTEX_GATE_ENABLED=true (default):
                          - post_gate() → cheap Slack DM with 2 signed URLs (no spend)
                          - Director taps approve → /api/cortex/gate/decide?action=approve&...
                            → BackgroundTasks fires maybe_run_cycle (cycle starts; HTTP returns immediately)
                          - Director taps skip → /api/cortex/gate/decide?action=skip&...
                            → baker_actions audit row, no spend
                       └→ if gate disabled (kill-switch / secret missing): legacy direct-fire (unchanged)
```

## Schema deviation note (defensive correction)

Brief used speculative column names `signal_text` and `matter_slug`; the **real** schema in `memory/store_back.py:6600` uses `summary` and `matter`. I fixed the SQL accordingly:

- `_signal_preview()`: `SELECT summary FROM signal_queue WHERE id = %s`
- `lookup_matter_slug()`: `SELECT matter FROM signal_queue WHERE id = %s` (helper extracted from inline so the dashboard endpoint can reuse + tests can patch)

Lesson #40 cousin — verify schema before referencing. Documented inline in module docstring.

## Ship gate verification (Lesson #47 — no "by inspection")

### Syntax checks (3 files)

```
$ python3 -c "import py_compile; py_compile.compile('triggers/cortex_pre_review_gate.py', doraise=True)" && echo "gate.py OK"
gate.py OK
$ python3 -c "import py_compile; py_compile.compile('triggers/cortex_pipeline.py', doraise=True)" && echo "pipeline.py OK"
pipeline.py OK
$ python3 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True)" && echo "dashboard.py OK"
dashboard.py OK
```

### New unit tests — literal stdout

```
$ pytest tests/test_cortex_pre_review_gate.py -v
=========================== test session starts ===========================
collected 7 items

tests/test_cortex_pre_review_gate.py::test_sign_verify_roundtrip PASSED          [ 14%]
tests/test_cortex_pre_review_gate.py::test_verify_expired PASSED                 [ 28%]
tests/test_cortex_pre_review_gate.py::test_verify_bad_signature PASSED           [ 42%]
tests/test_cortex_pre_review_gate.py::test_verify_unknown_action PASSED          [ 57%]
tests/test_cortex_pre_review_gate.py::test_secret_unset_disables_gate PASSED     [ 71%]
tests/test_cortex_pre_review_gate.py::test_already_decided_returns_prior PASSED  [ 85%]
tests/test_cortex_pre_review_gate.py::test_gate_decide_endpoint_approve_flow PASSED [100%]

======================== 7 passed, 6 warnings in 1.47s =========================
```

### Brief-named regression — literal stdout

```
$ pytest tests/test_cortex_pre_review_gate.py tests/test_alerts_to_signal_cortex_dispatch.py tests/test_cortex_runner_phase126.py -v
======================== 35 passed, 7 warnings in 1.17s ========================
```

(Brief listed `tests/test_cortex_pipeline.py` — that file does not exist in the tree. The pipeline-shape regression coverage is in `tests/test_alerts_to_signal_cortex_dispatch.py`, which exercises `maybe_dispatch` calling into `maybe_trigger_cortex`. All 5 tests there green.)

### Broader regression — full cortex + alerts suite

```
$ pytest tests/test_cortex_*.py tests/test_alerts_to_signal*.py
======================== 1 failed, 198 passed, 6 warnings in 1.47s =========================
```

**Pre-existing failure (NOT caused by this PR):**
- `tests/test_cortex_trigger_endpoint.py::test_trigger_cortex_cycle_unauthorized`

Confirmed via `git stash → checkout main → pytest …` that the same test fails on plain `main`. Root cause: `tests/test_cortex_action_endpoint.py` mutates module-level `outputs.dashboard._BAKER_API_KEY` in a way that leaks to subsequent test files when collected together. This is a test-isolation bug in the previous trigger-endpoint PR (#78) and is fixable with an autouse fixture in `test_cortex_trigger_endpoint.py` — out of scope for this brief, but flagged here for AI Head A to triage as a follow-up.

If we exclude that pre-existing fail, the picture is **198/198** green for everything else.

## Quality checkpoints (brief §"Quality Checkpoints")

| # | Checkpoint                                                                | Status |
|---|---------------------------------------------------------------------------|--------|
| 1 | `py_compile` clean on `triggers/cortex_pre_review_gate.py`                | ✅ PASS |
| 2 | `py_compile` clean on `triggers/cortex_pipeline.py`                       | ✅ PASS |
| 3 | `py_compile` clean on `outputs/dashboard.py`                              | ✅ PASS |
| 4 | `pytest tests/test_cortex_pre_review_gate.py -v` — 7/7 PASS literal       | ✅ PASS |
| 5 | Phase 1/2/6 + bridge + (no test_cortex_pipeline.py) regression PASS       | ✅ PASS (brief-named scope) |
| 6 | HMAC uses `hmac.compare_digest` (constant-time)                           | ✅ PASS (line 86 of gate module) |
| 7 | CORTEX_GATE_SECRET length validated (>=32)                                | ✅ PASS (`_secret()` helper) |

## Security surface review (B2 self-walkthrough — formal review by B1 + A)

| Check                                | Implementation                                                                                  |
|--------------------------------------|-------------------------------------------------------------------------------------------------|
| Auth — signed token (HMAC-SHA256)    | `sign_token` / `verify_token`; secret from `CORTEX_GATE_SECRET` (>=32 chars)                    |
| Constant-time compare                | `hmac.compare_digest(expected, token)` — no early-out on mismatch                               |
| Token TTL                            | 24h hard cap (`GATE_TTL_SECONDS`)                                                                |
| Action allowlist                     | `verify_token` rejects anything not in `{approve, skip}`                                        |
| Replay / idempotency                 | `already_decided(signal_id)` check on every gate decide; second tap returns recorded decision    |
| URL length                           | Approve URL ~200 chars (signed token ~43 base64url chars + query string); well under 1000       |
| Sensitive content logging            | preview / signal_text NEVER info-logged; only error-level + matter_slug + signal_id             |
| SQL injection — gate module          | All SQL parameterized; `record_decision` uses `json.dumps` for payload (no f-string injection)  |
| SQL injection — dashboard endpoint   | All lookups go through helper functions; no user-supplied SQL fragments                         |
| BAKER_API_KEY confusion              | Gate endpoint deliberately does NOT use `Depends(verify_api_key)` (Slack-tap iOS Safari drops headers); auth is via signed token only |
| Kill-switch                          | `CORTEX_GATE_ENABLED=false` falls through to legacy direct-fire path                            |
| Runaway-spend protection             | `post_gate` returning False with secret set → SKIP cycle (warning logged, no direct-fire)       |
| HTMLResponse on error paths          | 403 / 404 / 503 return tiny HTML pages — no stack-trace leakage                                 |
| Background-task error containment    | `_cortex_gate_fire_cycle` catches all exceptions — pool stays healthy on failure                |

## Deviations from brief

1. **Schema correction** (above) — `signal_text` → `summary`, `matter_slug` → `matter`. Defensive, prevents silent SQL errors. Anchored in module docstring.
2. **Helper extraction** — added `lookup_matter_slug(signal_id)` to gate module instead of inlining the SELECT in the dashboard endpoint. Lets tests `patch("triggers.cortex_pre_review_gate.lookup_matter_slug", return_value="oskolkov")` cleanly.
3. **Defensive `try/except` in pipeline gate fork** — runaway-spend guard: when `post_gate` fails for non-secret reasons (e.g., Slack post error), pipeline does NOT direct-fire; it logs a warning and skips. Brief language said "fall through if secret missing" but did not specify behavior on transient post failure; chose the safer skip-with-warning interpretation.
4. **Brief regression file `test_cortex_pipeline.py` doesn't exist** — used existing `test_alerts_to_signal_cortex_dispatch.py` instead, which is the actual pipeline-shape regression file in the tree.

## After merge — A executes (per brief §"After merge — A executes")

1. Generate `CORTEX_GATE_SECRET`:
   ```bash
   python3 -c "import secrets; print(secrets.token_urlsafe(48))"
   ```
2. Set Render env (per-key PUT):
   - `CORTEX_GATE_SECRET=<48 random urlsafe chars>`
   - `CORTEX_GATE_ENABLED=true` (default true; explicit for clarity)
3. POST `/deploys` to apply env-vars (env PUT alone doesn't restart)
4. Smoke test 1 — synthesized URL:
   ```bash
   python3 -c "from triggers.cortex_pre_review_gate import sign_token; import time; \
     exp=int(time.time())+3600; tok=sign_token(signal_id=1,action='approve',expires_at=exp); \
     print(f'https://baker-master.onrender.com/api/cortex/gate/decide?signal_id=1&action=approve&exp={exp}&token={tok}')"
   ```
   Open URL → expect 200 + "Cycle started" HTML (or 404 if signal_id=1 not in queue)
5. Smoke test 2 — organic flow: insert a signal_queue row + call `maybe_dispatch` → expect Slack DM in Director channel D0AFY28N030 with 2 links + no cycle yet
6. Tap Skip → 200 "Skipped" + baker_actions row created + no cycle
7. Trigger again → tap "Yes review" → 200 "Cycle started" + 4-5min later proposal_card lands

## Next steps in pipeline

1. **B1 second-pair-of-eyes review** (RA-24 trigger — external API + new auth surface + Slack DM behavior change). HIGH trigger class; B1 ≠ b2.
2. **AI Head A `/security-review`** (Lesson #52 mandatory pre-merge gate).
3. Both clear → A Tier-A squash-merge → mailbox flips IN_PROGRESS → COMPLETE.
4. Post-deploy env-var PUT + smoke (above).

## Co-Authored-By

```
Co-authored-by: Code Brisen #2 <b2@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
