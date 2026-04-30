# CODE_1 — PENDING (CORTEX_RUN_SCAN_UI_RENDER_1)

**Status:** PENDING — B1 build
**Brief:** `briefs/BRIEF_CORTEX_RUN_SCAN_UI_RENDER_1.md`
**From:** AI Head A — dispatched 2026-04-30 (Wave 2 #1, swapped ahead of `CORTEX_NOTIFICATION_DEFER_1` per Director ratification 2026-04-30 ~05:35Z)
**Wave:** 2 / Track 1 (V3 rev 4 roadmap)
**Trigger class:** MEDIUM (Director-visible UX gap on Wave-1-shipped feature; frontend + read endpoint; no auth/financial/migration touch)

**Prior CODE_1 task** CORTEX_MANUAL_INVOKE_1 — PR #88 MERGED 2026-04-30T04:46Z (`7a36312`). Mailbox overwritten per §3 hygiene; ship report preserved at `briefs/_reports/B1_cortex_manual_invoke_1_20260429.md`.

## Scope (TL;DR)

Director's post-deploy smoke (cycle `18a18ec5-ea69-4e44-97c9-4308488b8aba`) ran end-to-end on the backend in $1.46 — but Scan UI sat on "Baker is thinking…" indefinitely because front-end SSE consumers only render `data.token`. Cortex stream emits typed events (`{type: started|phase_changed|phase_output|terminal}`) with no `token` and they get silently dropped. This is V7 follow-up F-2 exactly, raised by AI Head B in PR #88 review §F-2 (MEDIUM).

**6 changes:**

1. **NEW endpoint** `GET /api/cortex/cycles/{cycle_id}/proposal` in `outputs/dashboard.py` — read-only, returns cycle metadata + propose-phase synthesis text from `cortex_phase_outputs.payload->>'proposal_text'`. Backs the front-end terminal-card render.
2. **`outputs/static/app.js`** — add `renderCortexEvent(...)` + helpers above `sendScanMessage` (~line 3962); add narrow `data.type` branch inside the SSE reader (~line 4053).
3. **`outputs/static/mobile.js`** — parallel `renderCortexEventMobile(...)` + helpers + branch in `streamChat` (~line 339, 389).
4. **`outputs/static/style.css`** — append Cortex UI styles (`.cortex-stream`, `.cortex-ticker`, `.cortex-terminal-card`, mobile variants).
5. **Cache busts** in `outputs/static/index.html` (and `mobile.html` if present): bump `?v=N` on `app.js`, `style.css`, `mobile.js`, `mobile.css` by exactly 1.
6. **Tests:** new `tests/test_cortex_proposal_endpoint.py` (4 cases: 200 with synthesis / 404 missing / 400 invalid uuid / 200 has_proposal=false on no synthesis) + extend `tests/test_scan_cortex_intent.py` with one typed-event passthrough assertion.

## Working branch

```
b1/cortex-run-scan-ui-render-1
```

## Pre-flight

```bash
cd ~/bm-b1
git fetch origin && git checkout main && git pull --ff-only origin main
git checkout -b b1/cortex-run-scan-ui-render-1
```

Verify the smoke cycle synthesis row exists before you start — fixture and manual verification both depend on it. Use the Baker MCP `baker_raw_query` tool:

```sql
SELECT artifact_type FROM cortex_phase_outputs
WHERE cycle_id = '18a18ec5-ea69-4e44-97c9-4308488b8aba'
  AND artifact_type = 'synthesis' LIMIT 1;
```

Expected: one row with `artifact_type='synthesis'`.

## Hard rules / RA-24 trigger classes (review path)

- Trigger class: **MEDIUM** — Director-visible UX gap, frontend-heavy, plus a small read-only endpoint. **Not** auth / DB-migration / financial / external API / cross-capability state writes.
- **Review path:** AI Head A solo `/security-review` + standard PR review. **No** RA-24 dual-clear required (Director ratified 2026-04-24: only the 7 trigger classes get B1 second-pair). MEDIUM is in AI Head A's autonomous merge scope per charter §4.
- **Self-PR rule:** AI Head A reviews + merges directly via squash-merge (per Item 7 ratification 2026-04-28).

## Acceptance criteria

1. `pytest tests/test_cortex_proposal_endpoint.py tests/test_scan_cortex_intent.py tests/test_cortex_run_endpoint.py tests/test_cortex_run_stream.py -v` — literal green output (paste tail in ship report; no "pass by inspection")
2. `bash scripts/check_singletons.sh` clean
3. `python -c "from outputs.dashboard import app; print('OK')"` clean (catches import errors before deploy)
4. `curl -H "X-Baker-Key: bakerbhavanga" https://baker-master.onrender.com/api/cortex/cycles/18a18ec5-ea69-4e44-97c9-4308488b8aba/proposal` post-deploy returns `has_proposal: true` + Hagenauer state-of-play markdown (confirms end-to-end on real DB row)
5. Manual Scan smoke after AI Head A merges + deploy lands: `run cortex on hagenauer-rg7 — quick state of play` — UI shows phase ticker → terminal card → proposal text inline
6. iOS PWA hard-reload: confirm cache-bust took (no stale `app.js` causing the same hang)
7. JS console clean (no `Uncaught ReferenceError`, no XSS-related warnings)

## Ship report fields (mandatory)

Save to `briefs/_reports/B1_cortex_run_scan_ui_render_1_<date>.md`:

- Files changed (with LOC delta)
- `pytest` literal tail showing all targeted suites green
- Singleton check output
- Import smoke output
- New endpoint manual curl output (200 / 404 / 400)
- Cache-bust verification grep output (`grep -nE 'app\.js\?v=|style\.css\?v=' outputs/static/*.html`)
- Any deviations from brief (with rationale)

## Director paste / PR

When done, push branch + open PR titled:
`feat(cortex): Scan UI renders cortex_run_action SSE events (CORTEX_RUN_SCAN_UI_RENDER_1)`

Body must include the V7 F-2 anchor:
> Closes V7 follow-up F-2 (PR #88 review §F-2 MEDIUM). Backend unchanged — this brief adds the Scan UI render path: phase ticker, terminal card, and inline proposal markdown via new `GET /api/cortex/cycles/{cycle_id}/proposal` endpoint.

## Reference docs

- Brief: `briefs/BRIEF_CORTEX_RUN_SCAN_UI_RENDER_1.md` (the contract)
- AI Head B PR #88 review §F-2: `briefs/_reports/AIHEAD_B_PR88_review_20260429.md` (lines 158-183) — original gap analysis
- V7 snapshot: `memory/project_session_state_20260430_v7.md` — F-2 listed as the only Wave-1-surface follow-up
