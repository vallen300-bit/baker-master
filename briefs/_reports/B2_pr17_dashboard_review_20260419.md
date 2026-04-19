# B2 PR #17 KBL_PIPELINE_DASHBOARD_MVP review — REDIRECT

**Reviewer:** Code Brisen #2
**Date:** 2026-04-19 (late afternoon)
**PR:** https://github.com/vallen300-bit/baker-master/pull/17
**Branch head:** `1ce3ade` (base `main` @ `5fa8dfc`, merge-base `16e89e0`)
**Brief:** `briefs/_tasks/CODE_1_PENDING.md` @ `5fa8dfc`
**Verdict:** **REDIRECT** — one S1 (cost-cap env + currency mismatch) on a safety-critical widget; every other audit item clean.

---

## What the PR ships

Diff stat: 5 files, +820/-4 (net of branch being slightly behind main).

| File | Change |
|------|--------|
| `outputs/dashboard.py` | +154 — 4 new `GET /api/kbl/*` endpoints + `_kbl_rows_to_dicts` helper |
| `outputs/static/index.html` | +16 — nav item + view shell + cache-bust bumps (v70→v71, v105→v106) |
| `outputs/static/app.js` | +275 — `loadKBLPipelineTab()` + 4 widget loaders + status/time/money/heartbeat helpers |
| `outputs/static/style.css` | +99 — widget shell + table + status colors + heartbeat dot + mobile @media |
| `tests/test_dashboard_kbl_endpoints.py` | +253 NEW — 8 tests (happy + empty-state × 4 endpoints) |

Brief §Scope items 1-7 all present. CHANDA pre-push passes by construction (read-only, no schema changes, no Leg touched, no prompt mods).

---

## S1 — Cost-cap env var + currency label mismatch (must-fix)

Dashboard cost widget reads:

```python
# outputs/dashboard.py (lines within cost-rollup endpoint)
cap_usd = float(os.getenv("KBL_COST_DAILY_CAP_USD", "15.0"))
...
return {
    "rollup": rows,
    "day_total_usd": day_total,
    "cap_usd": cap_usd,
    "remaining_usd": max(0.0, cap_usd - day_total),
}
```

and frontend renders `kblFmtMoney` → hardcoded `$` prefix in app.js.

**Problem:** the canonical cap is `KBL_COST_DAILY_CAP_EUR` defaulting to
`€50.00`, defined and enforced in `kbl/cost_gate.py:46-47`:

```python
_DAILY_CAP_ENV = "KBL_COST_DAILY_CAP_EUR"
_DEFAULT_DAILY_CAP_EUR = Decimal("50.00")
```

The dashboard invented a new env name (`..._USD`) that is NOT set on
Render. Consequences at shadow-mode flip:

- Render env has `KBL_COST_DAILY_CAP_EUR=50` (set for Step 5's cost gate).
- Dashboard reads `KBL_COST_DAILY_CAP_USD` → unset → falls back to default **$15**.
- Director opens widget, sees `$12.40 of $15.00 used, $2.60 remaining`.
- Actual state: €12.40 of €50, €37.60 remaining. Director thinks he's at
  83% of cap; he's actually at 25%.

The currency label is the second half of the problem — even if the env
name is fixed, the ledger's `cost_usd` column holds EUR values (see
`kbl/cost_gate.py:140-147` — "EUR-treated-as-USD ... cost_usd is the
single-ccy column"), so every `$` in the frontend is mis-labeling EUR
numbers. The AI Head handover explicitly called this out (line 106 of
`AI_HEAD_20260419.md`): "**Daily cost cap = €50** (not $15 per brief
§9.2's stale naming). Folded into PR #14."

PR #17 re-introduced the stale `$15` naming in the observability layer
after PR #14 got rid of it in the gate layer.

### Fix (minimum surface — all three files)

**Backend (`outputs/dashboard.py`):**

```python
try:
    cap_eur = float(os.getenv("KBL_COST_DAILY_CAP_EUR", "50.0"))
except (TypeError, ValueError):
    cap_eur = 50.0
...
return {
    "rollup": rows,
    "day_total_eur": day_total,
    "cap_eur": cap_eur,
    "remaining_eur": max(0.0, cap_eur - day_total),
}
```

**Frontend (`outputs/static/app.js`):**

```javascript
function kblFmtMoney(n) {
    if (n === null || n === undefined) return '€0.00';
    var v = Number(n);
    if (!isFinite(v)) return '€0.00';
    return '€' + v.toFixed(2);
}
...
// inside _loadKBLCost:
var dayTotal = Number(data.day_total_eur || 0);
var cap = Number(data.cap_eur || 0);
var remaining = Number(data.remaining_eur || 0);
```

**Test (`tests/test_dashboard_kbl_endpoints.py`):**

- Line 104: `monkeypatch.setenv("KBL_COST_DAILY_CAP_EUR", "50.0")`
- Lines 173-175: `body["cap_eur"] == 50.0`, `body["day_total_eur"]`, `body["remaining_eur"]`
- Line 191: `body["remaining_eur"] == 50.0`

Total diff: ~15 lines across 3 files. Small-surface fix — B1 amends on
same branch per brief's "Small-surface fixes: B1 applies as amend commit".

Why this is S1 (not S2 or N): it's a safety-critical metric that
Director reads to decide whether to intervene. A dashboard that
misrepresents cap compliance by 3.3× (showing 83% when actual is 25%,
or 300% when actual is 60%) defeats the widget's one purpose. Every
other aspect of PR #17 is clean — this is the only blocker.

---

## Audit checklist (full)

| Item | Status |
|------|--------|
| All 4 endpoints are `GET` — no write endpoints | ✓ (`@app.get(...)` on all four) |
| LIMIT bounds — 50 signals / 10 silver / 24h cost window / 1 heartbeat | ✓ |
| Signals query uses `ORDER BY id DESC LIMIT 50` → PK index scan | ✓ fast |
| Silver query uses `ORDER BY committed_at DESC NULLS LAST LIMIT 10` | ⚠️ no index on `committed_at` (see N1) |
| Heartbeat query uses `ORDER BY id DESC LIMIT 1` → PK scan | ✓ fast |
| `X-Baker-Key` auth via `Depends(verify_api_key)` | ✓ matches existing pattern exactly (sampled 10+ other `/api/*` routes) |
| Empty-state strings match brief spec for each widget | ✓ verbatim match |
| Heartbeat age bands: `<120s green, <300s yellow, else red` | ✓ matches brief spec |
| Status color-coding (terminal-ok green, failed red, in-flight yellow) | ✓ via `KBL_TERMINAL_OK` / `KBL_TERMINAL_FAIL` sets + `kblStatusClass()` |
| No `innerHTML` with untrusted data | ✓ all DOM writes via `createElement` + `textContent` (grep confirmed) |
| Tab position = last | ✓ (after "Baker Data", `FUNCTIONAL_TABS` set updated) |
| Manual refresh button, no auto-poll | ✓ `kblRefreshBtn` click → `loadKBLPipelineTab()` |
| Mobile responsive | ✓ `@media (max-width: 480px)` wraps table in scrollable container |
| Required columns exist in DB | ✓ `vedana` / `primary_matter` / `triage_score` / `target_vault_path` / `committed_at` / `commit_sha` all verified against migrations + step7_commit inline ALTER |
| Decimal + datetime serialization | ✓ `_kbl_rows_to_dicts` handles both; test asserts `isinstance(triage_score, float)` |
| Error handling per endpoint | ✓ try/except → HTTPException(500) + `logger.exception` |
| Frontend per-widget error fallback | ✓ `_kblError(body, e)` renders inline error, doesn't break siblings |
| Widgets load in parallel | ✓ `Promise.all([...])` in `loadKBLPipelineTab()` |
| Tests: 8 (happy + empty-state × 4) | ✓ all well-structured (could not independently run — see note below) |
| CHANDA Q1/Q2 + Inv 4/8/9/10 | ✓ read-only endpoints, no file writes, no schema changes |

**Test-run note.** I could not independently run the tests in `~/bm-b2` —
local python is 3.9 and `tools/ingest/extractors.py:275` uses 3.10+ union
syntax (`str | None`), so test collection fails on import of
`outputs.dashboard`. This is a pre-existing local-env issue, not a PR
concern. The test file itself reads correctly: `_FakeCursor` with
queued results, `dependency_overrides[verify_api_key]`, 8 assertions on
shape + types. B1 reports 8/8 green on CI-equivalent py3.12 env; PR's
CI rollup is still `UNKNOWN`/empty at time of review. If CI stays
green after fix-amend, that's sufficient.

---

## N-level notes (not blocking merge, candidates for polish PR)

- **N1. Index on `signal_queue.committed_at`.** `silver-landed` query
  filters `WHERE status='completed' ORDER BY committed_at DESC`. Column
  was added inline by `step7_commit.py:253` (PR #16 S2 already flagged
  this hygiene issue). No index exists. At current scale (tens of rows)
  the sort is sub-ms; at months of production it could be N*log(N) on
  completed-count. Clean fix: migration `CREATE INDEX IF NOT EXISTS
  idx_signal_queue_committed_at ON signal_queue (committed_at DESC)
  WHERE status='completed'`. Polish-PR candidate.

- **N2. No auth-rejection test.** Test file header acknowledges
  `verify_api_key` is bypassed and says the X-Baker-Key flow is covered
  elsewhere. Reasonable for MVP; worth adding one negative-path test
  per endpoint in the polish PR so regressions on the dep-injection
  don't slip (e.g., a future refactor that accidentally drops
  `dependencies=[...]` from one of the four routes).

- **N3. `kblFmtTime` error fallback returns raw ISO.** If `new Date(iso)`
  throws for a weird input, the catch returns `iso` as-is. Fine for
  dev; for production consider returning `'—'` to avoid showing
  garbled ISO timestamps to Director. Cosmetic.

- **N4. Signals widget has no "X more" indicator** when `len > 50`.
  Brief said "table with compact columns"; didn't require pagination.
  Acceptable for MVP but worth flagging once signals exceed 50 in a
  real burn-in so Director knows he's not seeing everything.

- **N5. `_kblError` renders `err.message` if available** — good — but
  if backend returns `HTTPException(500, detail="...")`, the frontend's
  `resp.ok` check triggers the generic `'HTTP ' + resp.status` path
  instead of surfacing the detail. Minor; Director likely checks
  server logs anyway.

- **N6. CSS cache-bust at v71 / v106** — clean bump discipline. Good.

None of N1-N6 block.

---

## What's right (for the record)

- **Architectural discipline:** 4 endpoints + 1 helper, no admin
  surface, no SSE, no write path. Reads from canonical tables
  (`signal_queue`, `kbl_cost_ledger`, `mac_mini_heartbeat`) with
  properly-bounded queries.
- **XSS-safe rendering.** Every user-data path goes through
  `textContent` / `createElement`; no template string injection.
- **Parallel widget loading** via `Promise.all` — failed widget
  doesn't block the others.
- **Terminal state taxonomy is correct** — `KBL_TERMINAL_OK` includes
  `completed` + `routed_inbox`; `KBL_TERMINAL_FAIL` includes all seven
  `*_failed` states + `paused_cost_cap`. Matches the 34-value CHECK
  from PR #12.
- **Heartbeat schema match** — query columns (`host`, `version`,
  `created_at`) all exist per `migrations/20260419_mac_mini_heartbeat.sql`.
- **Mobile responsive CSS** with horizontal scroll for wide tables —
  dashboard usable on Director's phone if he refreshes from a train.
- **Tests, 8 of them, per-endpoint happy + empty.** Assertions hit
  shape, type coercion (Decimal → float), and ISO-ness of datetimes.

---

## Dispatch

**REDIRECT.** One small-surface amend on the same branch:

1. Rename `KBL_COST_DAILY_CAP_USD` env → `KBL_COST_DAILY_CAP_EUR` in
   `outputs/dashboard.py`, default `50.0`.
2. Rename JSON response fields `day_total_usd`/`cap_usd`/`remaining_usd`
   → `_eur` suffix.
3. Update `outputs/static/app.js` `kblFmtMoney` to `€` prefix + read the
   new `_eur` keys.
4. Update `tests/test_dashboard_kbl_endpoints.py` env-set + assertion keys.

~15 lines, one amend commit, CI re-runs, B2 flips to APPROVE in ~10 min.

**Recommendation:** B1 amend-on-same-branch; AI Head auto-merges on
APPROVE per durable authority. No new PR. Dashboard goes live as part
of shadow-mode flip pre-work — accurate cap display IS part of the
observability contract.
