# B1 Ship Report — CORTEX_RUN_SCAN_UI_RENDER_1

**Date:** 2026-04-30
**Branch:** `b1/cortex-run-scan-ui-render-1`
**PR:** https://github.com/vallen300-bit/baker-master/pull/90
**Commit:** `4b10a89` — `feat(cortex-ui): Scan renders Cortex SSE typed events (CORTEX_RUN_SCAN_UI_RENDER_1)`
**Brief:** `briefs/BRIEF_CORTEX_RUN_SCAN_UI_RENDER_1.md`
**Wave:** 2 / Track 1
**Trigger class:** MEDIUM (no RA-24 dual-clear required)
**Closes:** AI Head B's PR #88 review §F-2 (MEDIUM)

---

## Summary

Closes V7 F-2: Scan UI hung on Cortex intent because frontend SSE consumers (`app.js sendScanMessage`, `mobile.js streamChat`) only rendered `data.token`; the four typed events `cortex_run_stream` emits — `started | phase_changed | phase_output | terminal` — have no `token` and were silently swallowed by the catch-all `try/catch`.

**Backend was correct.** Director's 2026-04-30 04:46Z smoke (cycle `18a18ec5-ea69-4e44-97c9-4308488b8aba`) confirmed the cycle ran end-to-end: cost \$1.46, status `tier_b_pending`, full propose-phase synthesis (`# Hagenauer RG7 — State of Play`) written to `cortex_phase_outputs`. The card sat on `Baker is thinking…` for 5+ minutes purely because the frontend never rendered the typed events.

Brief scope: render path + one read-only DB endpoint to surface the synthesis text after `terminal`.

---

## Files changed (9 files, +762 / -4)

| File | Δ | What |
|---|---|---|
| `outputs/dashboard.py` | +90 | NEW `GET /api/cortex/cycles/{cycle_id}/proposal` endpoint (read-only) |
| `outputs/static/app.js` | +188 | `renderCortexEvent` + 4 helpers + branch in `sendScanMessage` |
| `outputs/static/mobile.js` | +119 | `renderCortexEventMobile` + 3 helpers + branch in `streamChat` |
| `outputs/static/style.css` | +106 | Phase ticker + terminal card + mobile variants |
| `outputs/static/mobile.css` | +41 | Mobile cortex variants (mobile.html only loads mobile.css) |
| `outputs/static/index.html` | +2/-2 | Cache busts: `style.css 73→74`, `app.js 109→110` |
| `outputs/static/mobile.html` | +2/-2 | Cache busts: `mobile.css 37→38`, `mobile.js 40→41` |
| `tests/test_cortex_proposal_endpoint.py` | +143 (new) | 4 tests: 200/404/400/has_proposal:false |
| `tests/test_scan_cortex_intent.py` | +68 | +1 typed-event passthrough test |

---

## Ship gate

### 1. Pytest (literal output)

```
.venv-b1/bin/python -m pytest tests/test_cortex_proposal_endpoint.py \
  tests/test_scan_cortex_intent.py tests/test_cortex_run_endpoint.py \
  tests/test_cortex_run_stream.py -v
```

Tail:
```
tests/test_cortex_proposal_endpoint.py::test_proposal_returns_200_with_synthesis           PASSED [  3%]
tests/test_cortex_proposal_endpoint.py::test_proposal_returns_404_when_cycle_missing       PASSED [  6%]
tests/test_cortex_proposal_endpoint.py::test_proposal_returns_400_for_invalid_uuid         PASSED [  9%]
tests/test_cortex_proposal_endpoint.py::test_proposal_returns_has_proposal_false_when_no_synthesis PASSED [ 12%]
tests/test_scan_cortex_intent.py::test_quick_cortex_run_detect_run_on                      PASSED [ 16%]
tests/test_scan_cortex_intent.py::test_quick_cortex_run_detect_fire_for                    PASSED [ 19%]
tests/test_scan_cortex_intent.py::test_quick_cortex_run_detect_review_on                   PASSED [ 22%]
tests/test_scan_cortex_intent.py::test_quick_cortex_run_detect_no_match                    PASSED [ 25%]
tests/test_scan_cortex_intent.py::test_quick_cortex_run_detect_hyphenated_slug             PASSED [ 29%]
tests/test_scan_cortex_intent.py::test_classify_intent_fast_path_skips_llm                 PASSED [ 32%]
tests/test_scan_cortex_intent.py::test_scan_branch_rejects_matter_without_config           PASSED [ 35%]
tests/test_scan_cortex_intent.py::test_cortex_run_yields_typed_events_for_ui               PASSED [ 38%]
tests/test_cortex_run_endpoint.py::test_run_endpoint_unauthorized                          PASSED [ 41%]
tests/test_cortex_run_endpoint.py::test_run_endpoint_validation_short_question             PASSED [ 45%]
tests/test_cortex_run_endpoint.py::test_run_endpoint_no_cortex_config_rejected             PASSED [ 48%]
tests/test_cortex_run_endpoint.py::test_run_endpoint_rate_limited_at_cap                   PASSED [ 51%]
tests/test_cortex_run_endpoint.py::test_run_endpoint_cost_warn_posts_slack_and_runs        PASSED [ 54%]
tests/test_cortex_run_endpoint.py::test_run_endpoint_happy_path_streams                    PASSED [ 58%]
tests/test_cortex_run_stream.py::test_sse_format_single_data_block                         PASSED [ 61%]
tests/test_cortex_run_stream.py::test_runs_in_last_hour_returns_count                      PASSED [ 64%]
tests/test_cortex_run_stream.py::test_runs_in_last_hour_db_unavailable_returns_zero        PASSED [ 67%]
tests/test_cortex_run_stream.py::test_specialist_calls_today_returns_count                 PASSED [ 70%]
tests/test_cortex_run_stream.py::test_specialist_calls_today_db_unavailable_returns_zero   PASSED [ 74%]
tests/test_cortex_run_stream.py::test_snapshot_cycle_returns_dict                          PASSED [ 77%]
tests/test_cortex_run_stream.py::test_snapshot_cycle_returns_none_when_no_cycle            PASSED [ 80%]
tests/test_cortex_run_stream.py::test_snapshot_cycle_returns_none_when_db_unavailable      PASSED [ 83%]
tests/test_cortex_run_stream.py::test_stream_cycle_events_emits_full_sequence              PASSED [ 87%]
tests/test_cortex_run_stream.py::test_stream_cycle_events_terminal_failed_on_exception     PASSED [ 90%]
tests/test_cortex_run_stream.py::test_stream_cycle_events_terminal_timeout                 PASSED [ 93%]
tests/test_cortex_run_stream.py::test_snapshot_cycle_disambiguates_concurrent_taps         PASSED [ 96%]
tests/test_cortex_run_stream.py::test_stream_cycle_events_concurrent_isolation             PASSED [100%]

======================== 31 passed, 5 warnings in 1.29s ========================
```

**31/31 PASS literal — no "by inspection" (Lesson #48).**

### 2. Singleton check

```
$ bash scripts/check_singletons.sh
OK: No singleton violations found.
```

### 3. Import smoke

```
$ .venv-b1/bin/python -c "from outputs.dashboard import app; print('routes:', sum(1 for r in app.routes if 'cortex/cycles' in str(getattr(r, 'path', ''))))"
routes: 1
```

New route `/api/cortex/cycles/{cycle_id}/proposal` registered.

### 4. JS syntax check

Both `app.js` and `mobile.js` parse cleanly via Node syntax check (`node --check`-equivalent inline parse). No `Uncaught ReferenceError` for any helper added in this brief.

### 5. director_question not info-logged

```
$ grep -rn "director_question" outputs/dashboard.py outputs/cortex_run_stream.py | grep -i "info\|log"
outputs/dashboard.py:4229:    Sensitive payload (director_question, aborted_reason) is NOT info-logged —
outputs/cortex_run_stream.py:246:    work. ``director_question`` is never logged at INFO level (sensitive
```

Only docstring references stating it's not logged. No `logger.info("...director_question...")` calls.

### 6. Cache bust verification

```
$ grep -nE 'app\.js\?v=|style\.css\?v=|mobile\.js\?v=|mobile\.css\?v=' outputs/static/index.html outputs/static/mobile.html
outputs/static/index.html:16:    <link rel="stylesheet" href="/static/style.css?v=74">
outputs/static/index.html:573:<script src="/static/app.js?v=110"></script>
outputs/static/mobile.html:16:    <link rel="stylesheet" href="/static/mobile.css?v=38">
outputs/static/mobile.html:146:<script src="/static/mobile.js?v=41"></script>
```

Each bumped by exactly +1 vs main.

---

## Production curl smoke (post-deploy — pending merge + Render auto-deploy)

The brief's QC #1-3 require live curl against `baker-master.onrender.com`, which only works after PR #90 merges and Render auto-deploys. Three curls deferred to post-merge verification:

```bash
# QC #1 — happy path
curl -s -H "X-Baker-Key: $BAKER_API_KEY" \
  "https://baker-master.onrender.com/api/cortex/cycles/18a18ec5-ea69-4e44-97c9-4308488b8aba/proposal" \
  | python3 -m json.tool
# Expected: has_proposal:true, proposal_text starts with "# Hagenauer RG7 — State of Play",
# cost_dollars approx 1.4620, status:"tier_b_pending"

# QC #2 — 404
curl -s -o /dev/null -w "%{http_code}\n" -H "X-Baker-Key: $BAKER_API_KEY" \
  "https://baker-master.onrender.com/api/cortex/cycles/00000000-0000-0000-0000-000000000000/proposal"
# Expected: 404

# QC #3 — 400
curl -s -o /dev/null -w "%{http_code}\n" -H "X-Baker-Key: $BAKER_API_KEY" \
  "https://baker-master.onrender.com/api/cortex/cycles/not-a-uuid/proposal"
# Expected: 400
```

Director's UI smoke on the dashboard (running `run cortex on hagenauer-rg7 — give me a 1-line state of play`) is the final acceptance signal — phase ticker animates, terminal card shows cost + cycle hash + proposal markdown.

---

## Brief lane discipline

**Did NOT touch (verified):**
- `outputs/cortex_run_stream.py` — backend SSE source
- `orchestrator/action_handler.py` — intent classifier
- `outputs/dashboard.py:7854-7886` — `cortex_run_action` routing branch
- `outputs/dashboard.py:7611-7644` — `_action_stream_response` (token-only helper)
- `cortex_phase_outputs` schema — read-only path

---

## Notes for review

- **Mobile CSS split:** brief F-4 says "append to style.css" with both desktop + mobile rules in one block, but `mobile.html` only loads `mobile.css`. Implemented mobile-specific rules in `mobile.css` so the mobile path actually receives the styles; desktop rules stay in `style.css` per brief intent.
- **Helper `_serialize_dt` does not exist** — used `_serialize` (line 376) per brief's fallback instruction. Same helper used by `get_cortex_events` at line 3989.
- **`if (data.token)` branch preserved** — non-cortex Scan responses still flow through the existing token render path. No regression risk for AO/MOVIE chat.
- **All `data.*` interpolations use `document.createTextNode()`** for plain strings; `proposal_text` flows through `md() → setSafeHTML()` (same XSS-safe path as existing token render at app.js:4052).
- **`continue` after `renderCortexEvent`** in both consumers — typed events never fall through to the token branch.

---

## Review path

PR #90 → AI Head A `/security-review` + structural + AI Head B cross-lane → Tier-MEDIUM merge on dual clear.
