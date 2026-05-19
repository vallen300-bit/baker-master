---
brief_id: DASHBOARD_CORTEX_RATIFY_PANEL_1
target: b1
dispatched_by: lead
status: pending-director-ratification
trigger_class: LOW-MEDIUM
gate_chain: gate-1 (static) + gate-2 (security-review) — gate-3 + gate-4 not required
estimated_effort: 3-5h (Tier 1 ~1.5h + Tier 2 ~2-3h)
anchor_incident: 2026-05-19 brisen-lab cortex drilldown ship-time discovery — main dashboard has no ratify panel; Slack is only ratify surface; Director rejected Slack
anchor_research: ~/baker-vault/wiki/research/2026-05-19-ui-surface-prebrief-market-scan.md
anchor_skill: ~/baker-vault/_ops/skills/ui-surface-prebrief/SKILL.md (v1.1, commit 6467edd)
---

# BRIEF_DASHBOARD_CORTEX_RATIFY_PANEL_1 — Web ratify panel for Cortex Tier-B proposals

## Surface contract (ui-surface-prebrief skill v1.1)

1. **User action:** Director ratifies a Cortex proposal (approve / edit / refresh / reject) via the baker-master web dashboard, with full proposal text + phase-by-phase trace + specialist breakdown + citations + cost telemetry visible inline.
2. **Backend routes:**
   - `GET /api/cortex/cycles/{cycle_id}/proposal` at `outputs/dashboard.py:4446-4500` — returns cycle metadata + synthesis payload. Verified by Read on 2026-05-19.
   - `POST /cortex/cycle/{cycle_id}/action` at `outputs/dashboard.py:12743-12780` — accepts JSON body `{"action": "approve|edit|refresh|reject", "edits"?: str, "selected_gold_files"?: list, "reason"?: str}`. Returns `{"status": "ok", "action": ..., "result": ...}`. Verified by Read on 2026-05-19.
   - **NEW route to add:** `GET /api/cortex/cycles/pending` — list endpoint returning all cycles where `status='tier_b_pending'`. Schema below.
   - **NEW route to add:** `GET /api/cortex/cycles/{cycle_id}/trace` — list endpoint returning all phase outputs (sense / load / reason / propose / archive) + specialist invocations for the cycle. Schema below.
3. **Endpoint contracts (verified by handler reads):**
   - Auth on all four: `Depends(verify_api_key)` — `X-Baker-Key` header required.
   - `GET /proposal`: path param `cycle_id` (UUID-validated, 400 on bad format, 404 on missing).
   - `POST /action`: JSON body action ∈ {approve, edit, refresh, reject} — 400 on invalid_json_body or invalid_action; handlers in `orchestrator.cortex_phase5_act`.
4. **State location:** Postgres tables `cortex_cycles` (one row per cycle, status field is the ratify-pending flag) + `cortex_phase_outputs` (one row per phase output, `artifact_type='synthesis'` holds the proposal text). Both in baker-master DB.
5. **UI repo (= state repo):** `baker-master`. Surface: extend existing Cortex Intent Feed card at `outputs/static/index.html:228-242` — add 4th tab "Pending" next to Events / Dedup / Lint.
6. **Director surface preference:** web. Director ratified 2026-05-19 ~07:45Z — "slack is not an option. why brisen-master does not work. be brief."
7. **Gate-1+2 reviewer instruction:** Reviewers MUST `curl -H "X-Baker-Key: $BAKER_KEY" https://baker-master.onrender.com/api/cortex/cycles/pending` AND manually click each of Approve / Edit / Refresh / Reject on at least one test cycle on the deployed UI before approving the PR. Code-shape review (XSS-safe, syntactically valid JS) is necessary but **not** sufficient. The PR that triggered this brief (brisen-lab #22) shipped clean through code-shape gates with a button pointing at the wrong endpoint.

## Context — why this brief

Slack is the only place a Director can today click Approve/Edit/Refresh/Reject on a Cortex proposal. Director rejected Slack as the ratify surface on 2026-05-19. The brisen-lab drilldown card (PR #22) added a "Open in baker-master" button intended to bridge the gap — but the destination dashboard page didn't exist. The button URL was wrong AND the destination missing.

This brief builds the destination. Once shipped, brisen-lab PR #22's button can be re-pointed at this new page (fast-follow brief, not in scope here).

## Scope — Tier 1 + Tier 2 only

### Tier 1 — Core ratify (must-ship, ~1.5h)

- **New tab on Cortex Intent Feed card** — extend `outputs/static/index.html:230-236` with a 4th tab button "Pending" (suggested label `<button class="cortex-tab" onclick="_cortexTab('pending')" id="cortexTabPending">Pending</button>`).
- **Tab body renders list of cycles** with `status='tier_b_pending'` ordered by `started_at DESC`. Each row shows: matter slug + age (e.g. "3h ago") + proposal preview (first 200 chars).
- **Click on row expands to full proposal view** (inline expansion, not modal — vanilla JS, no new framework). Shows full synthesis text from `cortex_phase_outputs.payload` where `artifact_type='synthesis'`.
- **Four buttons per expanded row:** Approve / Edit / Refresh / Reject. POST to existing `/cortex/cycle/{cycle_id}/action` with the appropriate `action` value. Show inline success/failure toast. Row removes on success (status transitions out of `tier_b_pending`).
- **Edit action:** opens textarea pre-filled with current proposal text; submit POSTs with `action="edit"` + `edits="<new text>"`.
- **Reject action:** opens textarea for optional reason; submit POSTs with `action="reject"` + `reason="<text>"`.

### Tier 2 — "Show your work" (~2-3h)

Below the proposal text in the expanded view, render four collapsible sub-sections:

- **Phase trace** — query `cortex_phase_outputs` for this cycle, render one accordion row per phase (sense / load / reason / propose / archive) with timestamp + payload summary (first 500 chars + "Show full" toggle). Helps Director see WHERE the cycle went wrong, not just the final answer.
- **Specialist breakdown** — within the `reason` phase, parse the payload for invoked specialists (legal / finance / tax-CH/AT/DE / game-theory). For each: name + cost + latency + first 300 chars of output. Director clicks "this expert was wrong" → POSTs to `/cortex/cycle/{cycle_id}/action` with new action `action="flag_specialist"` + `specialist="<name>"` + `reason="<text>"`. **Note:** the `flag_specialist` action does not yet exist in `cortex_phase5_act` — implementation requires adding it (small extension; ~30 LOC). Out-of-scope alternative: render the breakdown as read-only Tier 2.0, defer the flag button to a Tier 2.1 fast-follow brief. **Recommended: read-only for V1.**
- **Citations panel** — parse the synthesis text for citation markers (existing convention: `[curated/<topic>-<date>.md]` and `[signal_queue:<id>]`). Render each as a clickable link to the source file or signal detail endpoint.
- **Cost telemetry** — render `cost_dollars` + `cost_tokens` + cycle duration (computed from `started_at` to `completed_at`) inline at the top of the expanded view. No action button in V1.

### Out of scope — fast-follow briefs (do NOT build in V1)

- Tier 3 (Gold-tag a specialist response / Fire devil's-advocate live / Specialist swap-and-replay / Counterparty drift flag).
- Tier 4 (Convert to brief / Pre-fill outbound / Forward to matter desk / Park with SLA).
- Tier 5 (Stale-cycle list inline / Failed-cycle list / Cost-cap monitor / Cycles-per-matter heatmap).
- The `flag_specialist` action handler in `cortex_phase5_act` (defer per Tier 2 note above).
- Re-pointing brisen-lab PR #22's "Open in baker-master" button at this new page (separate fast-follow brief in the brisen-lab repo).

## Implementation hints (not prescriptive — B1 may improve)

- **Backend additions** in `outputs/dashboard.py`:
  - New `GET /api/cortex/cycles/pending` endpoint. Query: `SELECT cycle_id::text, matter_slug, current_phase, started_at, cost_dollars, cost_tokens, EXTRACT(EPOCH FROM (NOW() - started_at))/60 AS age_minutes FROM cortex_cycles WHERE status='tier_b_pending' ORDER BY started_at DESC LIMIT 50`. Plus a sub-select on `cortex_phase_outputs` for the proposal_preview (first 200 chars of `artifact_type='synthesis'` payload).
  - New `GET /api/cortex/cycles/{cycle_id}/trace` endpoint. Query: `SELECT phase, artifact_type, payload, created_at FROM cortex_phase_outputs WHERE cycle_id=%s ORDER BY created_at ASC`. UUID-validate cycle_id like the existing `/proposal` endpoint at line 4459-4463.
  - Both endpoints: `Depends(verify_api_key)`, `tags=["cortex"]`, mirror the patterns from `get_cortex_cycle_proposal` at line 4446-4500.
- **Frontend additions** in `outputs/static/index.html` + a new JS file `outputs/static/cortex-ratify.js` (or extend the existing cortex tab JS if it lives elsewhere):
  - Vanilla JS, `fetch()` with `credentials: 'include'` if X-Baker-Key auto-injects, otherwise read key from existing dashboard auth pattern (grep for "X-Baker-Key" in current static JS to match convention).
  - Cache-bust the static asset version (`v=11→v=12`).
  - Reuse existing CSS variables (`var(--border)`, `var(--font)`) from `index.html:256` pattern for visual consistency.
- **Polling:** new tab auto-refreshes every 30s while active (matches existing Events tab pattern — grep `_cortexTab('events')` for the existing interval pattern).

## API contract — verified file:line references

| Endpoint | Method | File:line | Verified |
|---|---|---|---|
| `/api/cortex/cycles/{cycle_id}/proposal` | GET | `outputs/dashboard.py:4446` | 2026-05-19 by lead (Read tool) |
| `/cortex/cycle/{cycle_id}/action` | POST | `outputs/dashboard.py:12743` | 2026-05-19 by lead (Read tool) |
| `/api/cortex/cycles/pending` | GET | NEW — to be added | n/a |
| `/api/cortex/cycles/{cycle_id}/trace` | GET | NEW — to be added | n/a |

## Test plan

1. **Unit:** `tests/test_dashboard_cortex_ratify.py` — new file.
   - Mock-DB row in `cortex_cycles` with `status='tier_b_pending'` + synthesis payload.
   - Hit `GET /api/cortex/cycles/pending` — assert 200, row in response, `proposal_preview` truncated to 200 chars.
   - Hit `GET /api/cortex/cycles/<id>/trace` — assert 200, all phase outputs returned in chronological order.
   - Hit `POST /cortex/cycle/<id>/action` with `{"action":"approve"}` — assert 200 + downstream `cortex_approve` handler called (mock).
   - Hit same with `{"action":"reject", "reason":"test"}` — assert reason propagates to handler.
   - Auth: missing `X-Baker-Key` → 403; bad cycle_id format → 400; nonexistent cycle_id → 404.
2. **Integration smoke (manual, Director-runnable):**
   - Insert a test cycle into prod or staging DB with status='tier_b_pending'.
   - Load https://baker-master.onrender.com → navigate to Cortex card → click "Pending" tab.
   - Confirm row appears with matter + age + preview.
   - Click row → confirm expansion shows full proposal + phase trace + specialist breakdown + citations + cost.
   - Click Approve → confirm toast + row removes + DB status changed.
   - Repeat for Reject (with reason), Edit (with edited text), Refresh.
3. **Pytest ship gate:** literal `pytest tests/test_dashboard_cortex_ratify.py -v` output included in ship report. NO "pass by inspection" claims (Lesson #8).
4. **Smoke gate:** screenshot of the new tab rendering on Director's browser, plus a 2-line curl-success log of the new list endpoint, included in ship report.

## Ship gate

- Literal `pytest` green on new tests + existing dashboard tests (`pytest tests/test_dashboard*.py -v`).
- Singleton-pattern CI check clean (`bash scripts/check_singletons.sh`).
- Manual smoke confirmed per Test plan step 2.
- Reviewer load-the-URL confirmation per Surface contract §7.

## Gate-1 + Gate-2 reviewer instructions (per ui-surface-prebrief check 6)

**Mandatory before PASS:**

1. `curl -H "X-Baker-Key: $BAKER_KEY" https://baker-master.onrender.com/api/cortex/cycles/pending` → confirm 200 + JSON array shape.
2. `curl -H "X-Baker-Key: $BAKER_KEY" https://baker-master.onrender.com/api/cortex/cycles/<test-cycle-id>/trace` → confirm 200 + chronological phase rows.
3. Open https://baker-master.onrender.com in browser → click Cortex → Pending tab → expand a row → click each of the 4 buttons against a throw-away test cycle (probe row OK) → confirm each POST lands.
4. Code-shape checks (XSS-safe innerHTML, no inline event handlers without sanitization, fetch error handling) — necessary but not sufficient.

A pure code-shape PASS without the four steps above is a **REQUEST_CHANGES** per ui-surface-prebrief v1.1.

## Trigger class

LOW-MEDIUM. Touches dashboard frontend + adds 2 new read-only API routes. No new auth pattern (reuses `verify_api_key`). No new DB schema. No new dependencies. Gate-1 (static) + Gate-2 (`/security-review`) required. Gate-3 (cross-lane architecture review by deputy) + Gate-4 (`feature-dev:code-reviewer` 2nd-pass) NOT required per `code-reviewer 2nd-pass protocol` trigger criteria — no auth changes, no DB schema, no operation-ordering primitives.

## API version / deprecation / fallback (Code Brief Standards)

- **API version:** FastAPI internal routes — no external API version. Auth: `verify_api_key` (X-Baker-Key) — verified active as of 2026-05-19.
- **Deprecation check:** the four `cortex_phase5_act` handlers (approve / edit / refresh / reject) verified live at `outputs/dashboard.py:12764-12772` on 2026-05-19. No deprecation flag.
- **Fallback:** if the new `/pending` endpoint fails, the existing Slack ratify path stays operational (no removal of Slack handlers in scope). Frontend should render "No pending cycles" on empty array and a friendly error toast on 5xx.

## Migration-vs-bootstrap DDL check

Not applicable — no DB schema additions. Both new routes are read-only.

## Singleton-pattern check

Not applicable — frontend + new HTTP handlers using existing `_get_store()` factory at line 4465. No new singleton-pattern class instantiation.

## Anchors

- **Prior failure:** `~/.claude/projects/-Users-dimitry-bm-aihead1/memory/session_handover_2026-05-19_late_aihead_a_engineering_chain_plus_ui_web_ratify_gap_surfaced.md` (Critical gap section).
- **Skill that gated this brief:** `~/baker-vault/_ops/skills/ui-surface-prebrief/SKILL.md` (v1.1, commit `6467edd`).
- **Researcher market scan that informed scope:** `~/baker-vault/wiki/research/2026-05-19-ui-surface-prebrief-market-scan.md` (Action 1 V2 hardening is parallel separate brief; Action 2 typed-client + Action 3 Schemathesis hold for Director Q1+Q2 ratification before authoring).
- **Slack ratify implementation (do not remove, do not duplicate):** `orchestrator/cortex_phase4_proposal.py:175-188`.
- **Director directive that triggered:** 2026-05-19 ~07:45Z chat — "slack is not an option. why brisen-master does not work. be brief."

## Reporting

- B1 ships → bus-post `ship/dashboard-cortex-ratify-panel-1` to `lead` (this AH1 instance).
- B1 follows reply-target discipline: this brief was authored by AH1-Terminal (`lead`), reply via bus to `lead`.
- Lead drives Gate-1+2 chain on return. No paste-block-to-AH1-App needed; AH1-Terminal handles end-to-end.
