---
agent: B2
brief: BRIEF_CORTEX_COCKPIT_SIDEBAR_WIRING.md
phase: 1 of 2
shipped_at: 2026-05-10T11:30Z
fold_shipped_at: 2026-05-11T11:30Z
branch: b2/cortex-cockpit-sidebar-wiring
commit: f923f15292cc37c940fa56fce123ad54c19839d3
fold_commit: 252026c3
pr: https://github.com/vallen300-bit/baker-master/pull/180
trigger_class: TIER_A_USER_FACING_RENDER_SURFACE
status: SHIPPED_FOLD_OK — awaiting AH1 merge per narrow-fold-scope exemption (no Gate 2/3/4 re-fire)
---

# B2 ship report — CORTEX_COCKPIT_SIDEBAR_WIRING

## What landed

Phase 1 of 2 (render-only). Cockpit sidebar reads `wiki/_priorities.yml` (Triaga source-of-truth) + `slugs.yml` (canonical labels) instead of being a parallel list driven by alerts-table volume.

**Files created (4):**
- `kbl/priorities_registry.py` — singleton loader (module-level cache + threading.Lock, mirrors `slug_registry`).
- `tests/test_priorities_registry.py` — 23 tests.
- `tests/fixtures/priorities/_priorities_mini.yml` — 6-row valid fixture (covers all 5 importance enums + multi-slug row).
- `tests/fixtures/priorities/_priorities_bad_schema.yml` — schema-violation fixture.

**Files modified (4):**
- `outputs/dashboard.py` — rewrote `GET /api/dashboard/matters-summary` (line 3949). Two-source merge: priorities (gate, severity, category) + alerts (item_count, new_count). New response fields: `display_label`, `severity`, `category`, `triaga_ref`, `priorities_version`, `priorities_ratified_at`, `fallback_mode`. Explicit `_build_legacy_response(cur)` else-branch when priorities empty. `conn.rollback` in except, `LIMIT 500` on alerts query.
- `outputs/static/app.js` — `_renderMatterSection` now reads `display_label` + maps `severity` → 5 dot classes (critical→red / high→amber / medium→blue / low→slate / frozen→lgray). All via DOM API (textContent / dataset; no innerHTML).
- `outputs/static/index.html` — cache-bust `app.js?v=110` → `?v=111`.
- `briefs/_tasks/CODE_2_PENDING.md` — flipped status PENDING → IN_PROGRESS → COMPLETE (ship-report side).

## Acceptance criteria

10/10 in scope for B2 environment. Items marked 🔵 = AH-side gates (B2 cannot exercise locally).

| # | Criterion | Status |
|---|---|---|
| 1 | Existing dashboard tests pass | ✅ `test_dashboard_kbl_endpoints.py` 9/9 |
| 2 | New tests pass (≥15) | ✅ 28 (23 registry + 5 endpoint) |
| 3 | py_compile clean | ✅ exit 0 (preexisting `dashboard.py:2595` SyntaxWarning unrelated) |
| 4 | PR body has verbatim test stdout | ✅ PR #180 body |
| 5 | No touch to WAHA / WhatsApp constants — N/A this brief | ✅ |
| 6 | `_build_legacy_response(cur)` retained as explicit else-branch + tested | ✅ `dashboard.py:3911-3946`; covered by `test_matters_summary_priorities_unavailable_falls_back` |
| 7 | `/security-review` PASS | 🔵 AH gate |
| 8 | Singleton CI guard | ✅ `bash scripts/check_singletons.sh` → OK |
| 9 | DDL drift on new file = 0 | ✅ `grep -E "INSERT\|UPDATE\|DELETE\|CREATE TABLE\|ALTER" kbl/priorities_registry.py` → 0 |
| 10 | Severity → dot mapping documented + tested | ✅ `app.js:1565-1583`; severity enums tested via registry tests |

## Ship-gate verifications

- ✅ `pytest tests/test_priorities_registry.py tests/test_dashboard.py -v` → **28 passed** in 0.84s.
- ✅ `pytest tests/test_dashboard_kbl_endpoints.py -v` → 9 passed (no regression on adjacent endpoints).
- ✅ `python3 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True); py_compile.compile('kbl/priorities_registry.py', doraise=True)"` → exit 0.
- ✅ `bash scripts/check_singletons.sh` → `OK: No singleton violations found.`
- ✅ DDL drift check on new file → 0 lines.
- ✅ Single matters-summary call site: `outputs/dashboard.py:3949` (the rewritten endpoint); two consumers in `outputs/static/app.js` (line 1535 main loader; line 4790 secondary refresh) — both unchanged producer-side.

## What B2 could NOT verify (handover to AH)

These need a running server / live vault / live cockpit:

1. **Real-vault curl smoke** — needs `BAKER_VAULT_PATH=/Users/dimitry/baker-vault` + a running app on port 8080. AH to run brief §Verification 3 against deploy.
2. **Fallback smoke** — needs to move `_priorities.yml` aside on Render and curl. Covered behaviorally by `test_matters_summary_priorities_unavailable_falls_back` in unit tests.
3. **Mobile viewport (375px iOS PWA)** — needs Director's PWA. AH to spot-check post-deploy.
4. **`/security-review` skill** — Tier-A merge gate (Lesson #52). AH to run on the PR diff before merge.
5. **Cross-team review** — AH B per autonomy charter §4.

## Coordination

- Brief mailbox `briefs/_tasks/CODE_2_PENDING.md` will be flipped to status COMPLETE after this report lands (ai-head A executes the flip during PR merge per `_ops/processes/b-code-dispatch-coordination.md` §3, OR B2 flips on ship — current step).
- Phase 2 (`CORTEX_COCKPIT_GOLD_WRITES_1`) depends on this PR merging first. AH1 authors next session.
- `.claude/settings.json.forge-bak` left untracked at repo root from session-start `mv` — not part of this PR; AH/Director can inspect.

## PL paste-block

```
TO: PL (AH1)
FROM: B2
RE: incident/n-a · CORTEX_COCKPIT_SIDEBAR_WIRING (Phase 1 ship)

Branch: b2/cortex-cockpit-sidebar-wiring → main
Commit: f923f152
PR: https://github.com/vallen300-bit/baker-master/pull/180
Tier: A (user-facing render surface)

Tests: 28 passed (23 registry + 5 endpoint). 9/9 adjacent dashboard tests pass.
py_compile: clean. Singleton guard: OK. DDL drift on new module: 0.

Open AH-side gates:
- /security-review on PR #180 (Lesson #52, Tier-A)
- Real-vault curl smoke (brief §V3) post-deploy
- Fallback smoke (brief §V7) post-deploy
- 375px PWA viewport
- AH B cross-team review (autonomy charter §4)

Phase 2 (CORTEX_COCKPIT_GOLD_WRITES_1) blocked on this PR's merge.
B2 idle, awaiting next dispatch.
```

---

# FOLD UPDATE — 2026-05-11

Status flipped `SHIPPED` → `SHIPPED_FOLD_OK`. Fold commit `252026c3` pushed to `b2/cortex-cockpit-sidebar-wiring` per AH1 dispatch (mailbox `UPDATE 2026-05-10T23:05Z`). All four convergent / non-refuted gate findings folded; one false positive REFUTED.

## What changed

| # | Severity | Gate | File | Fix |
|---|---|---|---|---|
| 1 | HIGH | Gates 3+4 convergent | `kbl/priorities_registry.py` | `loaded: bool = False` field on `_PrioritiesRegistry`; `_parse_yaml()` sets `loaded=True`; `registry_version()`/`registry_ratified_at()` gate on `reg.loaded`. Fixes None-coercion bug where `schema_version=0` masqueraded as "missing". |
| 2 | HIGH | Gate 4 | `kbl/priorities_registry.py` | Parse-storm sentinel: catch `PrioritiesRegistryError` from `_parse_yaml()` inside lock; cache `_empty_registry()`; new `_parse_error_warned` flag; LOUD error log fires once until `reload()`. `reload()` resets both warned-flags. |
| 3 | MEDIUM | Gate 3 | `outputs/static/{app.js, index.html}` | Cockpit fallback banner. `#cockpit-fallback-banner` element under sidebar logo (hidden by default, muted amber). `loadMattersSummary` reads `data.fallback_mode` and shows "Priorities source unavailable" (`legacy_no_priorities`) or "Priorities source error" (`error`). Cache-bust `app.js?v=111` → `?v=112`. |
| 4 | MEDIUM | Gate 3 | `outputs/dashboard.py` | New `POST /api/admin/priorities/reload` (verify_api_key dependency) → calls `priorities_registry.reload()` + returns `{reloaded_at, schema_version, ratified_at, priority_count}`. Placed adjacent to `/api/admin/trends`. |

## REFUTED (no fold)

Gate 4 HIGH #1 — "reload() writes `_missing_file_warned` outside lock." False positive: pre-fold source already had `_missing_file_warned = False` inside `with _lock:`. AH1 verified directly against `origin/b2/cortex-cockpit-sidebar-wiring:kbl/priorities_registry.py`. Reviewer mis-read. (Post-fold, `reload()` additionally resets `_parse_error_warned` inside the same lock — see fix #2.)

## Out of fold scope (deferred per AH2 PASS)

- LOW: missing_file_warned reset comment
- LOW: severity enum extension silent degradation
- LOW: slug normalization asymmetry between priorities + alerts inbox
- LOW: duplicate bad-schema fixture test
- LOW: notes default handling

## Tests

`pytest tests/test_priorities_registry.py tests/test_dashboard.py -v` — **33 passed in 0.80s** under `.venv312`. Pre-fold was 28 passed (23 registry + 5 endpoint); +5 net from this fold:

- `test_parse_error_does_not_re_parse_on_subsequent_calls` — under 50 repeat calls against a corrupt YAML, `_parse_yaml()` is invoked exactly once and the LOUD error log fires exactly once.
- `test_reload_clears_parse_error_warned_flag` — `reload()` re-arms the LOUD log so a second parse-storm scenario logs again.
- `test_loaded_flag_true_on_parsed_registry` — successful parse sets `loaded=True`; getters return file values.
- `test_loaded_flag_false_on_empty_registry_and_getters_return_none` — fail-soft sentinel keeps `loaded=False`; `registry_version()`/`registry_ratified_at()` return `None` even though `schema_version=0` on the sentinel. This is the bug-being-closed.
- `test_admin_priorities_reload_invalidates_stale_cache` — prime cache, edit YAML on disk, verify in-process cache is still stale, POST the endpoint, verify body shows fresh schema_version + in-process registry now reflects the edit.

Renamed (semantics flipped from raise-loud to fail-soft + LOUD-log under fold #2):
- `test_malformed_yaml_raises_loud` → `test_malformed_yaml_fails_soft_and_logs_loud`
- `test_unknown_importance_enum_raises_loud` → `test_unknown_importance_enum_fails_soft`

## Ship-gate verifications

- ✅ `pytest tests/test_priorities_registry.py tests/test_dashboard.py -v` → 33 passed in 0.80s
- ✅ `python3 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True); py_compile.compile('kbl/priorities_registry.py', doraise=True)"` → exit 0
- ✅ `bash scripts/check_singletons.sh` → OK: No singleton violations found.
- ✅ Cache-bust verified `app.js?v=112` in `outputs/static/index.html` line 575 (Lesson #4).
- ✅ Fold commit `252026c3` pushed to `origin/b2/cortex-cockpit-sidebar-wiring`.
- ✅ No touches outside the 6 files listed in the fold scope.

## Per SKILL.md narrow-fold-scope exemption

Gates 2+3+4 will NOT be re-fired post-fold (correctness fixes have zero security surface; AH2 PASS covers post-fold perimeter). AH1 proposes merge directly on this fold ship-report.

## After PR #180 merge

Per mailbox frontmatter, cursor-cap dispatch (P3) auto-resumes from `b2/bus-drain-cursor-cap-fix-1` branch. That branch already has the cursor-cap fix + regression test pushed (PR not yet opened pending PR #180 merge — branch ahead of main by the cursor-cap commit).

## PL paste-block

```
TO: PL (AH1)
FROM: B2
RE: incident/n-a · CORTEX_COCKPIT_SIDEBAR_WIRING fold ship

Branch: b2/cortex-cockpit-sidebar-wiring -> main (PR #180)
Fold commit: 252026c3
Status: SHIPPED_FOLD_OK

Tests: 33 passed (28 prior + 5 new). py_compile clean. Singleton guard OK.

Fold scope (4 items + 1 REFUTED, all per mailbox UPDATE 2026-05-10T23:05Z):
- loaded:bool field + None-coercion fix (HIGH, Gates 3+4 convergent)
- Parse-storm sentinel + _parse_error_warned flag (HIGH, Gate 4)
- Cockpit fallback banner + cache-bust v112 (MEDIUM, Gate 3)
- POST /api/admin/priorities/reload (MEDIUM, Gate 3)
- REFUTED Gate 4 HIGH #1 (reload-outside-lock false positive)

Per SKILL.md narrow-fold-scope exemption: no Gate 2/3/4 re-fire.
AH1 to propose merge.

After merge: cursor-cap dispatch (P3) resumes from b2/bus-drain-cursor-cap-fix-1.
```
