---
status: PENDING
brief: briefs/BRIEF_COCKPIT_SIDEBAR_LEGACY_SLUG_ALIAS_FIX_1.md
trigger_class: TIER_B_USER_FACING_CORRECTNESS_FIX
dispatched_at: 2026-05-11
dispatched_by: ai-head-1 (AH1)
target: b2
director_ratification: Director 2026-05-11 "yes draft the brief" + "yes" (dispatch greenlight) — cockpit sidebar Project section showing 0 for every project (root cause: alert-side legacy slugs not folded to canonical priorities).
priority: P1
phase: 1 of 1 (single PR, Phase-2 follow-on to PR #180 cockpit wiring)
unblocks:
  - Cockpit Project sidebar attributes 299 pending alerts to canonical projects instead of inbox
  - mo-vie-am gets ~136 items, ao-pm gets ~100 items, hagenauer-rg7 gets its alerts visible to Director
expected_pr_count: 1 (baker-master)
expected_branch_name: b2/cockpit-legacy-slug-alias-fix-1
expected_complexity: small-to-medium (~3-4h)
mandatory_2nd_pass: FALSE  # scope <100 LOC, no auth/DB/concurrency surface; AH1 judgment per SKILL.md §Code-reviewer 2nd-pass Protocol — trigger classes 1-4 not hit
last_heartbeat: null
autopoll_eligible: true
gate_to_merge: AH2 cross-lane review + /security-review (Lesson #52) per autonomy charter §3
---

# CODE_2_PENDING — BRIEF_COCKPIT_SIDEBAR_LEGACY_SLUG_ALIAS_FIX_1 — 2026-05-11

**Brief:** `briefs/BRIEF_COCKPIT_SIDEBAR_LEGACY_SLUG_ALIAS_FIX_1.md` (READ FIRST — full spec)
**Working dir:** `~/bm-b2`
**Working branch:** `b2/cockpit-legacy-slug-alias-fix-1` (branch from latest `origin/main`)
**Repo:** `vallen300-bit/baker-master`

## Summary

Director observed 2026-05-11: Project section in left sidebar shows `0` for every project. Live `/api/dashboard/matters-summary` confirms: priorities load fine (`priorities_version: 1`, `fallback_mode: null`) but every canonical priority row has `item_count: 0`. Meanwhile 299 alerts sit under legacy slugs in the inbox bucket (`movie_am: 136`, `ao_pm: 100`, free-text labels: 63).

Root cause: `outputs/dashboard.py:3998-3999` normalizes the priority slug (already canonical) instead of the alert slug (legacy). Lookup never hits.

Fix: alert-side fold via two tiers.
- Tier 1: `slug_registry.normalize(raw_slug)` — catches registered aliases (`movie_am` → `mo-vie-am`, `hagenauer` → `hagenauer-rg7`, …).
- Tier 2: new module-level dict `LEGACY_DISPLAY_LABEL_ALIASES` in `dashboard.py` — covers ~10 free-text labels not in slugs.yml.
- Unmapped raw slugs stay in inbox bucket (safe default).

Read-only API change. No DB writes, no migration, no `slugs.yml` PR, no frontend.

## Implementation summary (brief has full spec)

1. Add `LEGACY_DISPLAY_LABEL_ALIASES` constant near `_PROJECTS_CATEGORIES` (around `outputs/dashboard.py:3895-3897`).
2. **MANDATORY pre-step:** verify each canonical target (`austrian-tax-corp`, `swiss-tax-banking`, …) exists in BOTH `baker-vault/slugs.yml` AND `baker-vault/wiki/_priorities.yml`. Drop unverified entries from the map (route to inbox instead). See brief §Step 1 for the grep verification block.
3. Add `_canonicalize_alert_slug()` + `_fold_alerts_to_canonical()` helpers before `get_matters_summary()` (around `outputs/dashboard.py:3947`).
4. Rewire the lookup + inbox-walk in `get_matters_summary()` (currently `outputs/dashboard.py:3987-4026`) to use `canonical_alerts` (folded) instead of raw `alerts_by_slug`.
5. Tests: new `tests/test_dashboard_alert_fold.py` (≥8 unit tests covering Tier-1 alias resolution, Tier-2 label resolution, fold semantics with collapsing slugs, _ungrouped passthrough, None worst_tier handling).

## Ship gate

1. `pytest tests/test_dashboard_alert_fold.py -v` — ≥8/8 GREEN, **literal stdout** in PR description.
2. `pytest tests/ -v -k "matters_summary or dashboard"` — no prior-passing test regresses.
3. `python3 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True)"` — exit 0.
4. PR description includes ship-report PL paste-block per SKILL.md §"PL ship-report contract".
5. AH2 cross-lane review + `/security-review` skill pass (Lesson #52).
6. Post-deploy smoke (in ship report):
   ```bash
   curl -s -H "X-Baker-Key: $BAKER_API_KEY" \
     "https://baker-master.onrender.com/api/dashboard/matters-summary" \
     | python3 -c "import sys,json; d=json.load(sys.stdin); print('mo-vie-am:', next((p for p in d['projects'] if p['matter_slug']=='mo-vie-am'), {}).get('item_count')); print('inbox_count:', d.get('inbox_count'))"
   ```
   Must print `mo-vie-am: 136` (or current live count) + `inbox_count` dropped from `299` to ≤50.

## Files touched

**Modify (in-repo):**
- `outputs/dashboard.py` — add constant + 2 helpers + rewire one endpoint's lookup block (~50 LOC delta)
- `tests/test_dashboard_alert_fold.py` — new file, ≥8 unit tests
- Optional: extend `tests/test_dashboard.py` with 1-2 integration tests if the existing TestClient + DB fixture pattern is straightforward

**Do NOT touch:**
- `baker-vault/slugs.yml` — separate-repo hard rule
- `baker-vault/wiki/_priorities.yml` — Director-ratified via Triaga
- `kbl/slug_registry.py`, `kbl/priorities_registry.py` — read-only consumers
- `outputs/static/app.js`, `outputs/static/index.html`, `outputs/static/style.css` — API shape unchanged
- `_build_legacy_response()` at `outputs/dashboard.py:3911` — separate fallback path; intentionally unchanged
- `alerts` table schema / migrations — read-only

## Estimated complexity

Small-to-medium · ~3-4h · 1 PR · Tier-B user-facing correctness fix. No mandatory 2nd-pass code-reviewer (scope <100 LOC, no trigger-class hit per SKILL.md §"Code-reviewer 2nd-pass Protocol — When the protocol FIRES").

## PL ship-report

End your chat ship report with a fenced PL paste-block per SKILL.md §"PL ship-report contract":

```
**TO: AH1-App PL**
- WHAT: COCKPIT_SIDEBAR_LEGACY_SLUG_ALIAS_FIX_1 shipped — sidebar item counts fold from legacy alert slugs
- LINKS: <PR # / commit SHA / Render deploy ID>
- COST: <time / token usage>
- NEXT: <next blocker or "ready for next">
```

## Heartbeat

12h cadence binding (SKILL.md §"B-code stall chase"). Brief should fit in one heartbeat window.

## Prior CODE_2 task (archive reference)

BRIEF_BUS_DRAIN_CURSOR_CAP_FIX_1 — RESOLVED upstream: parallel-AH1 instance merged the cursor-cap fix as PR #184 at `990a606` 2026-05-11. Prior fold-fix on PR #180 also merged (squash `901c66d`). Mailbox hygiene rule (`_ops/processes/b-code-dispatch-coordination.md` §3) applied — overwriting with new dispatch.

— AH1
