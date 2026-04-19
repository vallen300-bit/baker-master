# B2 PR #17 dashboard re-review post-amend — APPROVE

**Reviewer:** Code Brisen #2
**Date:** 2026-04-19 (late afternoon)
**PR:** https://github.com/vallen300-bit/baker-master/pull/17
**Branch head:** `43ef1d0` (amend from `1ce3ade`)
**Initial review:** `briefs/_reports/B2_pr17_dashboard_review_20260419.md` @ `e5a0719`
**Verdict:** **APPROVE** — S1 cost-cap currency fix landed exactly as prescribed.

---

## Amend diff — clean and tight

`git diff 1ce3ade..43ef1d0` = 3 files, +19 / -17. Pure rename + currency
symbol swap. No drive-by changes, no new surface.

### `outputs/dashboard.py` — env + JSON field rename

```
-    try:
-        cap_usd = float(os.getenv("KBL_COST_DAILY_CAP_USD", "15.0"))
-    except (TypeError, ValueError):
-        cap_usd = 15.0
+    # Canonical cap env is KBL_COST_DAILY_CAP_EUR (kbl/cost_gate.py enforces it);
+    # cost_usd ledger column stores EUR values per the same module's contract.
+    try:
+        cap_eur = float(os.getenv("KBL_COST_DAILY_CAP_EUR", "50.0"))
+    except (TypeError, ValueError):
+        cap_eur = 50.0
...
-        "day_total_usd": day_total,
-        "cap_usd": cap_usd,
-        "remaining_usd": max(0.0, cap_usd - day_total),
+        "day_total_eur": day_total,
+        "cap_eur": cap_eur,
+        "remaining_eur": max(0.0, cap_eur - day_total),
```

Bonus: the 2-line comment B1 added — "Canonical cap env is
`KBL_COST_DAILY_CAP_EUR` ... `cost_usd` ledger column stores EUR values
per the same module's contract" — prevents future reviewers from
re-introducing the stale `$15`/USD convention. Good defensive comment.

### `outputs/static/app.js` — `$` → `€` in 3 places + rollup field read

`kblFmtMoney` returns `€` for null / non-finite / normal paths (all three
branches fixed). `_loadKBLCost` reads `data.day_total_eur` / `cap_eur` /
`remaining_eur`. Every `$` in the KBL-Pipeline block is gone.

Verified with `grep`: the only residual `$` characters in `app.js` are
pre-existing regex backreferences (`$1`, `$2`) in unrelated markdown
parsers on lines 599/601/6187. Not currency. ✓

### `tests/test_dashboard_kbl_endpoints.py`

- `monkeypatch.setenv` renamed to `KBL_COST_DAILY_CAP_EUR`.
- 5 assertions updated to `cap_eur` / `day_total_eur` / `remaining_eur`.
- Empty-state path verifies `remaining_eur == 50.0` ✓ (matches brief
  §Verdict focus bullet 3).
- `assert isinstance(body["rollup"][0]["total_usd"], float)` left
  intact — correct, that's the per-row SQL alias (see N1 below).

---

## Verdict-focus checklist

| Item | Status |
|------|--------|
| `KBL_COST_DAILY_CAP_USD` → `KBL_COST_DAILY_CAP_EUR` (default `50.0`) | ✓ |
| JSON response fields `*_usd` → `*_eur` (top-level three keys) | ✓ |
| Frontend `kblFmtMoney` outputs `€` prefix | ✓ |
| Test env-set + assertion keys updated | ✓ |
| No unintended changes in the amend diff (3 files, only the expected lines) | ✓ |
| Empty-state path still covers `remaining_eur == 50.0` | ✓ |
| `€` symbol used consistently — no leftover `$` in the three files | ✓ |
| CI green | ⚠️ see note below |

## CI / mergeable note

`gh pr view 17 --json state,mergeable,statusCheckRollup` returned:

```
{"mergeable":"UNKNOWN","state":"OPEN","statusCheckRollup":[]}
```

Empty rollup = no CI checks registered on this repo. UNKNOWN mergeable
is GitHub not-yet-computed. A cheap recheck: opening the PR page once
on GitHub usually nudges it to MERGEABLE. AI Head should `gh pr view 17`
one more time before merging; if still UNKNOWN, retry with a 30s wait.
My review of the code itself is clear-green.

---

## N-level note (non-blocking, polish-PR candidate)

**N1 — SQL alias consistency.** Per-row rollup still aliases
`SUM(cost_usd) AS total_usd` (line ~10884 of `dashboard.py`); frontend
reads `r.total_usd` on line 10081 and formats via `kblFmtMoney` (now `€`).
This works — `kblFmtMoney` puts `€` in front regardless — but the JSON
key name still says `usd`. Any external consumer reading the JSON directly
(e.g., a future `/health`-style endpoint or external dashboard) would be
misled. Consistency fix: rename SQL alias to `SUM(cost_usd) AS total_eur`
+ update test assertion + frontend read. 3-line change, polish-PR
candidate. Not worth holding up PR #17.

## What's unchanged from initial review (all still right)

All the positive items I called out in the initial review still apply:
GET-only endpoints, LIMIT bounds correct, X-Baker-Key auth pattern
match, empty-state strings verbatim, heartbeat age bands correct
(120s/300s), status color taxonomy matches PR #12's 34-value CHECK,
no `innerHTML` XSS exposure, tab position last, manual refresh only,
mobile `@media` responsive, per-widget error fallback, parallel widget
loading, decimal + datetime serialization correct, all required
columns verified against migrations. CHANDA Q1/Q2 + Inv 4/8/9/10 all
pass by construction (read-only, no Leg touched, no schema changes).

---

## Dispatch

**APPROVE.** S1 fix landed exactly as prescribed. Ready for auto-merge
on MERGEABLE.

**Recommendation:** AI Head re-runs `gh pr view 17 --json mergeable` to
get a definitive MERGEABLE, then auto-merges per durable authority.
Dashboard ships as shadow-mode pre-work.
