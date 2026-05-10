---
status: SHIPPED
brief: briefs/BRIEF_CORTEX_COCKPIT_SIDEBAR_WIRING.md
trigger_class: TIER_A_USER_FACING_RENDER_SURFACE
dispatched_at: 2026-05-10
dispatched_by: ai-head-1 (AH1)
target: b2
claimed_at: 2026-05-10T11:00Z
claimed_by: B2
shipped_at: 2026-05-10T11:30Z
shipped_by: B2
pr: https://github.com/vallen300-bit/baker-master/pull/180
commit: f923f15292cc37c940fa56fce123ad54c19839d3
report: briefs/_reports/B2_cortex_cockpit_sidebar_wiring_20260510.md
gate_to_merge: /security-review PASS + AH B cross-team review + Director ratify + post-deploy verifications (real-vault smoke, fallback smoke, 375px PWA)
director_ratification: Director ratified Option (b) standalone brief 2026-05-10; AID scope-confirmed Phase 1 (render-only) 2026-05-10 conditional on Phase 2 follow-up; AID DISPATCH AUTHORIZED 2026-05-10 in scope-lock reply file `_01_INBOX_FROM_CLAUDE/2026-05-10-aid-to-ah1-cockpit-phase1-conditional-accept-phase2-required.md`
priority: P1
phase: 1 of 2 (Phase 2 = CORTEX_COCKPIT_GOLD_WRITES_1, AH1 authors next session)
unblocks:
  - Brisen Desk cockpit-vs-priorities-review 2026-05-10 findings A/B/C/D (naming drift, missing matters, Director-dismissed items, severity-from-volume)
  - Phase 2 CORTEX_COCKPIT_GOLD_WRITES_1 (depends on Phase 1 merge for rendered sidebar to wire onto)
expected_pr_count: 1 (baker-master)
expected_branch_name: b2/cortex-cockpit-sidebar-wiring
expected_complexity: medium (~5-7h)
mandatory_2nd_pass: TRUE  # feature-dev:code-reviewer on brief done; /security-review on PR REQUIRED (Lesson #52, Tier-A user-facing surface)
last_heartbeat: 2026-05-10T11:30Z
autopoll_eligible: false
---

# CODE_2_PENDING — BRIEF_CORTEX_COCKPIT_SIDEBAR_WIRING — 2026-05-10

**Brief:** `briefs/BRIEF_CORTEX_COCKPIT_SIDEBAR_WIRING.md` (READ FIRST — 665 lines, full spec, copy-pasteable code blocks, test plan, ship gate)
**Working dir:** `~/bm-b2`
**Working branch:** `b2/cortex-cockpit-sidebar-wiring`
**Repo:** `vallen300-bit/baker-master`

## Summary

Render-only cockpit sidebar wiring. Today the sidebar (baker-master.onrender.com left panel) is a parallel list to the Triaga — ~60% of Director-ratified priorities missing, ~40% present under non-canonical labels, 1 Director-dismissed item still rendered (Kempinski), severity dots correlate with email volume not Triaga importance. This brief makes the sidebar a VIEW of `wiki/_priorities.yml` (Triaga source of truth) + `slugs.yml` (canonical labels).

**4 changes:**

1. **New loader** `kbl/priorities_registry.py` — singleton mirroring `slug_registry.py` module-level cache + threading.Lock pattern (NOT `_get_global_instance()` — see brief §Risks for verbatim slug_registry pattern). Reads `${BAKER_VAULT_PATH}/wiki/_priorities.yml` (Director-curated, schema v1, 40 matters). Public API: get_all / get_by_slug / get_all_for_slug / severity_for / category_for / is_active_priority / registry_version / registry_ratified_at / reload. Fail-soft on file-missing (returns empty, logs warning once).

2. **Backend** `outputs/dashboard.py:3888-3937` — rewrite `GET /api/dashboard/matters-summary`. Two-source merge: priorities (source of truth for projects/operations bucketing + severity field) + alerts (kept for item_count + inbox flat-bucket). Explicit `_build_legacy_response(cur)` else-branch runs when priorities loader returns empty (fail-soft fallback to current behavior). LIMIT 500 on alerts query. Response shape adds `display_label`, `severity` enum, `category`, `triaga_ref`, `priorities_version`, `priorities_ratified_at`, `fallback_mode`.

3. **Frontend** `outputs/static/app.js:1554-1591` — `_renderMatterSection` reads `m.display_label` (canonical from API, falls back to title-cased slug for legacy rows) and `m.severity` enum (critical/high/medium/low/frozen → red/amber/blue/slate/lgray dot classes, all existing palette per `outputs/static/style.css:180-186`).

4. **Cache-bust** `outputs/static/index.html` — bump `?v=N` query on `app.js` reference (iOS PWA hard caches; mandated by `.claude/rules/frontend.md`).

## CRITICAL — reviewer-caught issues already folded into brief

A `feature-dev:code-reviewer` pass on the brief itself (2026-05-10) caught 4 blockers + 1 quality nit. ALL FOLDED INTO THE BRIEF. If you encounter:

- `slug_registry.describe(slug)` raising `KeyError` — yes, this is real (verified `kbl/slug_registry.py:215-220`). Brief specifies `_safe_describe()` helper. USE IT.
- `priorities_registry_version` / `priorities_registry_ratified_at` — these come from `priorities_registry`, NOT `slug_registry`. Brief specifies explicit import + qualifier. DO NOT improvise.
- Singleton pattern: copy `slug_registry.py`'s module-level cache + threading.Lock + `_get_registry()` verbatim. DO NOT invent `_get_global_instance()` method.
- Fallback path: `_build_legacy_response(cur)` is an explicit else-branch. DO NOT skip it; one of the 15 tests exercises it.
- CSS: NO new CSS rules required. The 5 dot classes (red/amber/blue/slate/lgray) all exist at `style.css:180-186`. Mapping is in brief Step 3.

## Scope discipline (Phase 1 only)

This brief is **Phase 1** of a 2-phase split (AID scope-lock 2026-05-10):

- **Phase 1 (THIS brief, b2)** — render hygiene. Sidebar reads `_priorities.yml` correctly + canonical labels + Triaga-driven severity. Director's clicks do NOT yet train Cortex.
- **Phase 2 (separate brief, AH1 authors next session)** — `CORTEX_COCKPIT_GOLD_WRITES_1`. Wires Director sidebar interactions (ratify/dismiss/snooze/open) to emit Gold writes per B6 + I6. Depends on Phase 1 merging first.

**Do NOT add Gold-write hooks in this PR.** That is Phase 2 scope. If you find yourself touching `signal_queue` writes or click → POST handlers, STOP and flag back.

## Ship gate

1. `pytest tests/test_priorities_registry.py tests/test_dashboard.py -v` — ≥15 net new tests pass.
2. `python3 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True); py_compile.compile('kbl/priorities_registry.py', doraise=True)"` — exit 0.
3. Real-vault curl smoke (brief §Verification 3) — `projects[]` includes `mrci`, `lilienmatt`, `annaberg`, `aukera`, `franck-muller` (Triaga-active slugs WITHOUT pending alerts); does NOT include `kitz-kempinski` (Director-dismissed Q34); Hagenauer entry `severity: "critical"`.
4. Fallback smoke (brief §Verification 7) — move `_priorities.yml` aside; reload; response has `fallback_mode: "legacy_no_priorities"`; sidebar renders legacy shape.
5. Mobile viewport (375px iOS PWA) — sidebar collapses + new dot classes render.
6. PR description includes literal `pytest` stdout (no "passes by inspection" — Lesson #8).
7. **`/security-review` skill MANDATORY** before merge — Tier-A user-facing surface (Lesson #52).
8. Cross-team review: AI Head B per autonomy charter §4.

## Files touched

**Create:**
- `kbl/priorities_registry.py`
- `tests/test_priorities_registry.py`
- `tests/fixtures/priorities/_priorities_mini.yml`
- `tests/fixtures/priorities/_priorities_bad_schema.yml`

**Modify:**
- `outputs/dashboard.py` (one endpoint, line 3888)
- `outputs/static/app.js` (one function, line 1554)
- `outputs/static/index.html` (cache-bust)
- `tests/test_dashboard.py` (extend)

**Do NOT touch:**
- `baker-vault/wiki/_priorities.yml` (Director-curated)
- `baker-vault/slugs.yml` (separate-repo PR-only)
- `kbl/slug_registry.py` (use as-is)
- `kbl/ingest_endpoint.py` (out of scope)
- signal_queue tables (producer side unchanged — AID lock)
- `matter_registry` (legacy fallback path)
- `outputs/static/mobile.*` (V2 deferred)
- Anything Gold-write-related (Phase 2 scope)

## Estimated complexity

Medium · ~5-7h · 1 PR · Tier-A user-facing surface.

## Heartbeat

Update `last_heartbeat: <UTC ISO>` in this mailbox file every 30 min during active work. Standard b-code-dispatch-coordination.md §3 protocol.

## Prior CODE_2 task (archive reference)

BRIEF_WHATSAPP_RECIPIENT_RESOLVER_FIX_1 — COMPLETE 2026-05-08 (incident-containment dispatch by ai-head-b). PR #173 merged 2026-05-08. Mailbox hygiene rule applied — overwriting per `_ops/processes/b-code-dispatch-coordination.md` §3.
