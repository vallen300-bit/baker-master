---
report: B2_cockpit_sidebar_legacy_slug_alias_fix_20260511
brief: briefs/BRIEF_COCKPIT_SIDEBAR_LEGACY_SLUG_ALIAS_FIX_1.md
target_dispatcher: ai-head-1 (AH1)
target_reviewer: ai-head-2 (AH2)
trigger_class: TIER_B_USER_FACING_CORRECTNESS_FIX
status: SHIPPED_AWAITING_REVIEW
pr: https://github.com/vallen300-bit/baker-master/pull/185
branch: b2/cockpit-legacy-slug-alias-fix-1
commit: bd284fde
shipped_at: 2026-05-11T13:10Z
shipped_by: B2
expected_complexity: small-to-medium (~3-4h)
actual_complexity: small (~45m)
---

# B2 ship report — COCKPIT_SIDEBAR_LEGACY_SLUG_ALIAS_FIX_1 — 2026-05-11

## What shipped

PR #185 (`bd284fde`) on `b2/cockpit-legacy-slug-alias-fix-1`. Two-tier alert-side fold in `get_matters_summary()`:

1. `LEGACY_DISPLAY_LABEL_ALIASES` constant added at `outputs/dashboard.py:3899-3907` (verified entries only — see Verification below).
2. `_canonicalize_alert_slug(raw)` + `_fold_alerts_to_canonical(alerts_by_slug)` helpers added before `get_matters_summary()` (`outputs/dashboard.py:3949-4005`).
3. `get_matters_summary()` rewired — priority lookup uses `canonical_alerts.get(p.slug, {})`; inbox-walk unions (a) `unmapped_alerts` and (b) `canonical_alerts` whose canonical slug is not a priority.
4. New file `tests/test_dashboard_alert_fold.py` — 17 unit tests covering Tier-1 + Tier-2 resolution, fold sum/MIN semantics, `_ungrouped` sentinel, mutation guard.

Diff: `+277 / -6` across two files. No `slugs.yml` change. No DB writes. No frontend change. No migration. API response shape unchanged.

## Verification (literal stdout)

`pytest tests/test_dashboard_alert_fold.py -v` — **17 passed in 0.49s**
`pytest tests/test_dashboard.py -v` — **6 passed in 0.83s** (no regression)
`pytest -k "matters_summary or dashboard or priorities_registry"` — **60 passed, 1951 deselected in 1.45s**
`python3 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True)"` — **exit 0**

Full test output captured in PR body.

## Pre-implementation verification grep (brief §Step 1 mandatory step)

Each canonical target in brief's proposed `LEGACY_DISPLAY_LABEL_ALIASES` checked against `baker-vault/slugs.yml`:

| Brief-proposed canonical | In slugs.yml? | Action |
|---|---|---|
| `hagenauer-rg7` | ✅ yes | ✅ included (key: `Oskolkov-RG7`) |
| `mo-vie-exit` | ✅ yes | ✅ included (key: `Mandarin Oriental Sales`) |
| `austrian-tax-corp` | ❌ no | ⛔ dropped |
| `swiss-tax-banking` | ❌ no | ⛔ dropped |
| `family-wealth-overview` | ❌ no | ⛔ dropped |
| `german-property-tax` | ❌ no | ⛔ dropped |
| `brisen-ai` | ❌ no | ⛔ dropped |
| `cross-border-structuring` | ❌ no | ⛔ dropped |
| `cyprus-holding` | ❌ no | ⛔ dropped |
| `campus-schluterstrasse` | ❌ no | ⛔ dropped |
| `owners-lens` | ❌ no | ⛔ dropped |

Per brief §Step 1 ("If any slug missing from slugs.yml: drop from the map"). 9 dropped. Surfaced in PR body as NEEDS-DIRECTOR-RATIFICATION (separate-repo PR follow-on).

## Brief inconsistency surfaced (needs Director ratification)

- **`ao_pm` raw slug**: brief table claims canonical is `ao-pm` (100 items). `ao-pm` is NOT in `slugs.yml`; only `ao` is, and `ao_pm` is not listed as an alias on the `ao` row (`baker-vault/slugs.yml:40-43` — aliases are `[oskolkov, andrey, "andrey oskolkov"]`). Those 100 items stay in inbox post-deploy.
- **Recommended Tier-1 follow-on** (separate-repo `baker-vault` PR, single file):
  - Add `"ao_pm"` to alias list on `ao`, OR
  - Ratify each of the 9 dropped free-text labels as a new canonical (each with its display label in alias list).

Tier-2 dashboard-side map cannot satisfy these alone per repo CLAUDE.md hard rule (no `slugs.yml` edit from this repo); Director Option 1 ratification was scoped to the dashboard-side map. Recommend Director Option 1A (slugs.yml PR for the dropped 9 + `ao_pm` alias) as the next step — single small PR; once merged, no further dashboard.py change needed (Tier-1 catches them).

## Post-deploy verification (post-merge)

After Render auto-deploy on `main`:

```bash
curl -s -H "X-Baker-Key: $BAKER_API_KEY" \
  "https://baker-master.onrender.com/api/dashboard/matters-summary" \
  | python3 -c "
import sys, json
d = json.load(sys.stdin)
print('priorities_version:', d.get('priorities_version'))
print('fallback_mode:', d.get('fallback_mode'))
print('mo-vie-am:', next((p for p in d['projects'] if p['matter_slug']=='mo-vie-am'), {}).get('item_count'))
print('hagenauer-rg7:', next((p for p in d['projects'] if p['matter_slug']=='hagenauer-rg7'), {}).get('item_count'))
print('inbox_count:', d.get('inbox_count'))
"
```

Expected:
- `mo-vie-am: 136` (or current live count — covers Tier-1 `movie_am` alias hit)
- `hagenauer-rg7`: non-zero (covers Tier-1 `hagenauer` alias + Tier-2 `Oskolkov-RG7` hit)
- `inbox_count`: drops from `299` to ~150-200 (residual = `_ungrouped` + 9 unverified free-text + `ao_pm`)
- Phase-2 `ao_pm` follow-on (separate slugs.yml PR) would drop inbox further to ~50.

## Ship gate status

- [x] `pytest tests/test_dashboard_alert_fold.py -v` — 17/17 GREEN
- [x] `pytest tests/test_dashboard.py -v` — 6/6 GREEN
- [x] `pytest -k "matters_summary or dashboard or priorities_registry"` — 60/60 GREEN
- [x] `py_compile` clean
- [x] PR body includes literal pytest stdout (no "passes by inspection" — Lesson #8)
- [ ] `/security-review` skill (mandatory per Lesson #52 — Tier-A user-facing surface)
- [ ] AH2 cross-lane review (autonomy charter §3)
- [ ] Director ratify
- [ ] Post-deploy curl smoke after merge

## Mailbox

`briefs/_tasks/CODE_2_PENDING.md` will be flipped to `SHIPPED_AWAITING_REVIEW` by AH1 per `_ops/processes/b-code-dispatch-coordination.md` §3 mailbox hygiene rule. (B2 does not self-flip per orientation §"REPORT TO: AI Head A".)

## Files modified

- `outputs/dashboard.py` — `+90 / -6`
- `tests/test_dashboard_alert_fold.py` — `+187` (new)

## Files not touched

- `baker-vault/slugs.yml` (separate-repo hard rule)
- `baker-vault/wiki/_priorities.yml` (Director Triaga)
- `kbl/slug_registry.py`, `kbl/priorities_registry.py` (read-only consumers)
- `outputs/static/app.js`, `outputs/static/index.html`, `outputs/static/style.css` (API shape unchanged)
- `_build_legacy_response()` (separate fallback path; unchanged)
- `alerts` table / SQL migrations (read-only)

## PL ship-report

```
**TO: AH1-App PL**
- WHAT: COCKPIT_SIDEBAR_LEGACY_SLUG_ALIAS_FIX_1 shipped — sidebar item counts fold from legacy alert slugs via Tier-1 slug_registry.normalize() + Tier-2 LEGACY_DISPLAY_LABEL_ALIASES (2 verified entries; 9 brief-proposed entries dropped pending separate-repo slugs.yml PR).
- LINKS: PR https://github.com/vallen300-bit/baker-master/pull/185 · commit bd284fde · branch b2/cockpit-legacy-slug-alias-fix-1 · Render deploy pending on merge.
- COST: ~45 min wall-clock (vs brief 3-4h estimate); negligible token cost.
- NEXT: Awaiting /security-review + AH2 cross-lane review + Director ratify. Surfacing follow-on recommendation: separate baker-vault PR to ratify the 9 dropped free-text labels as canonical slugs (and `ao_pm` as alias of `ao`) — Tier-1 then catches them automatically without dashboard.py change.
```
