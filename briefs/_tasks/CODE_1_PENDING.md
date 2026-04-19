# Code Brisen #1 — Pending Task

**From:** AI Head
**To:** Code Brisen #1 (terminal instance — fresh tab post-PR-#16-merge)
**Previous:** PR #16 STEP7-COMMIT-IMPL merged at `20370e7e`. **Phase 1 code complete: 7/7 pipeline steps on main.**
**Task posted:** 2026-04-19 (late afternoon)
**Status:** OPEN — dashboard MVP before shadow-mode go-live

---

## Task: KBL_PIPELINE_DASHBOARD_MVP — Real visibility on the pipeline

### Why

Phase 1 code is shipped but Director has **zero observability** for the KBL pipeline today. Dashboard has nothing on signal_queue / kbl_cost_ledger / Silver commits. Before shadow-mode flips on tonight, Director needs a browser tab he can refresh to see signals moving. MVP scope — 3 widgets, not a full phase-2 rebuild.

### Scope

**IN**

1. **New tab in `outputs/dashboard.py`** (or sibling frontend file — follow existing Cockpit tab patterns):
   - Tab label: **"KBL Pipeline"**
   - Tab position: after existing tabs (last position)
   - Manual refresh button (no auto-poll in MVP — keep simple)

2. **Widget A — Recent signals (state tracker):**
   - Query: `SELECT id, source, primary_matter, status, vedana, triage_score, created_at FROM signal_queue ORDER BY id DESC LIMIT 50`
   - Display: table with compact columns. State column color-coded (terminal states green, failed red, in-flight yellow).
   - Empty state: message "No signals yet — ingestion will populate this once shadow mode fires. Heartbeat still live." Link to Mac Mini heartbeat widget for confirmation.

3. **Widget B — Today's cost ledger rollup:**
   - Query: `SELECT step, model, COUNT(*) AS calls, SUM(cost_usd) AS total_usd, SUM(input_tokens) AS in_tok, SUM(output_tokens) AS out_tok FROM kbl_cost_ledger WHERE created_at > NOW() - INTERVAL '24 hours' GROUP BY step, model ORDER BY total_usd DESC`
   - Display: small table. Footer row: daily total + remaining cap ("€X.XX of €50 used, €Y.YY remaining").
   - Empty state: "No Opus or Voyage calls yet today. Gemma runs locally (zero cost; token counts on first signal)."

4. **Widget C — Silver landed (vault commits):**
   - Query: `SELECT id, primary_matter, target_vault_path, committed_at, substring(commit_sha, 1, 7) AS short_sha FROM signal_queue WHERE state = 'completed' ORDER BY committed_at DESC LIMIT 10`
   - Display: chronological list with link format `wiki/<matter>/<yyyy-mm-dd>_<slug>.md`.
   - Empty state: "No Silver committed yet. First Silver lands once a signal clears Steps 1-7 (shadow or production)."

5. **Widget D — Mac Mini heartbeat (liveness):**
   - Query: `SELECT host, version, created_at, NOW() - created_at AS age FROM mac_mini_heartbeat ORDER BY id DESC LIMIT 1`
   - Display: one-line status. Green if age < 2 min, yellow 2-5 min, red >5 min.
   - Empty state: "Mac Mini heartbeat not received. SSH to macmini and check launchctl list | grep brisen.baker."

6. **API endpoints** (add to `baker` router or existing dashboard API):
   - `GET /api/kbl/signals` — returns JSON for widget A
   - `GET /api/kbl/cost-rollup` — returns JSON for widget B
   - `GET /api/kbl/silver-landed` — returns JSON for widget C
   - `GET /api/kbl/mac-mini-status` — returns JSON for widget D
   - Auth: same pattern as existing dashboard APIs (X-Baker-Key header)
   - All read-only. No write endpoints.

7. **Tests** — minimal:
   - `tests/test_dashboard_kbl_endpoints.py` — one test per endpoint. Use fixture data. Assert response shape, not content.
   - Empty-state rendering: test each widget with zero rows. Must render gracefully.

### Hard constraints

- **Read-only dashboard.** No admin controls, no "kill pipeline" buttons, no edit capabilities. Observability only.
- **No auto-refresh in MVP.** Manual refresh button only. Auto-poll is Phase 2.
- **No Chart.js / D3 / new libraries.** Use whatever charting already lives in the dashboard codebase. If nothing, use plain HTML tables.
- **Queries must be fast.** LIMIT 50 on widget A, LIMIT 10 on C — no full-table scans. Use indexes (all relevant columns are indexed per migrations).

### CHANDA pre-push

- **Q1 Loop Test:** read-only dashboard, no Leg touched. Pass.
- **Q2 Wish Test:** serves wish — gives Director real visibility into the compounding pipeline. Pass.
- **Inv 4 / Inv 8 / Inv 9 / Inv 10** — dashboard only reads; no file writes, no schema changes, no prompt mods. All pass by construction.

### Branch + PR

- Branch: `kbl-pipeline-dashboard-mvp`
- Base: `main`
- PR title: `KBL_PIPELINE_DASHBOARD_MVP: signal state + cost rollup + silver landed + mac-mini status`
- Target PR: #17

### Reviewer

B2.

### Timeline

~60-90 min. Focused surface: 4 API endpoints + 1 tab + 4 widgets + tests.

### Dispatch back

> B1 KBL_PIPELINE_DASHBOARD_MVP shipped — PR #17 open, branch `kbl-pipeline-dashboard-mvp`, head `<SHA>`, <N>/<N> tests green. 4 widgets + 4 API endpoints. Manual refresh. Empty states handled. Ready for B2 review.

### After this task

- B2 reviews PR #17 → auto-merge on APPROVE
- AI Head flips shadow mode on (`KBL_FLAGS_PIPELINE_ENABLED=true` on Render + `BAKER_VAULT_DISABLE_PUSH=true` on Mac Mini)
- Director opens dashboard, refreshes, watches first real signal flow through 7 steps
- Next B1 ticket: polish PR (PR #15 S2 + PR #16 2×S2 + ~10 nice-to-haves consolidated)
- Then: KBL-C handler implementations

---

## Working-tree reminder

Work in `~/bm-b1` or `~/Desktop/baker-code` (wherever you were). Never `/tmp/`. **Quit Terminal tab after this amend** — memory hygiene.

---

*Posted 2026-04-19 by AI Head. (iii) parallel path ratified: dashboard builds while I verify shadow-mode activation. Both land within the hour.*
