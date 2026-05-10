---
status: FOLD_FIX_REQUIRED_THEN_CURSOR_CAP
fold_fix_pr: 180  # P1 — fold PR #180 FIRST (see UPDATE 2026-05-10T23:00Z below); cursor-cap dispatch (this frontmatter) is P3, second in queue
fold_fix_branch: b2/cortex-cockpit-sidebar-wiring  # NOT the cursor-cap branch — different branch
brief: briefs/BRIEF_BUS_DRAIN_CURSOR_CAP_FIX_1.md
trigger_class: TIER_B_FOLLOWUP_CORRECTNESS_FIX
dispatched_at: 2026-05-11
dispatched_by: ai-head-1 (AH1)
target: b2
director_ratification: Director ruled "ship now, fix later" on parent PR #183 cursor-cap data-loss bug (2026-05-11); Director "fire follow-ups" 2026-05-11 greenlit this dispatch end-to-end.
priority: P3
phase: 1 of 1 (single PR, follow-up to PR #183)
unblocks:
  - Closes confirmed data-loss bug at session-start-bus-drain.sh:377 (silent loss of messages 31-50 in backlog drains)
  - Removes line-161 unused-var nit AH2 flagged
  - Adds regression test for cursor-cap behavior
expected_pr_count: 1 (baker-master)
expected_branch_name: b2/bus-drain-cursor-cap-fix-1
expected_complexity: small (~30 min)
mandatory_2nd_pass: FALSE  # 1-line semantic change in already-reviewed file (PR #183 cleared cross-lane + /security-review); no re-pass needed
last_heartbeat: null
autopoll_eligible: true
gate_to_merge: AH2 cross-lane review per autonomy charter §3 (no Director smoke needed for a 1-line follow-up to already-deployed hook)
---

# CODE_2_PENDING — BRIEF_BUS_DRAIN_CURSOR_CAP_FIX_1 — 2026-05-11

**Brief:** `briefs/BRIEF_BUS_DRAIN_CURSOR_CAP_FIX_1.md` (READ FIRST — short brief, single-line fix + 1 test + 1 nit cleanup)
**Working dir:** `~/bm-b2`
**Working branch:** `b2/bus-drain-cursor-cap-fix-1` (branch from latest main `2cc97a7`)
**Repo:** `vallen300-bit/baker-master`

## Summary

Follow-up to PR #183 (merged 2026-05-10T22:59Z) — fix the cursor-cap data-loss bug AH2 flagged on `/security-review`. When daemon returns 31-50 unread messages, cursor jumps past all of them after rendering only the first 30; messages 31-50 are silently lost.

**One-line fix:** `tests/fixtures/session-start-bus-drain.sh:377` — change `for m in msgs` to `for m in shown`. Cursor now advances to the rendered slice's max `created_at`, not the full fetched slice's max.

**Daemon ASC confirmed** (`bus.py:349`) — so `shown = msgs[:30]` are the 30 oldest unread; next drain `since=msgs[29].created_at` returns `msgs[30:]` correctly.

**Plus:** drop the unused `body_json` at `tests/test_bus_drain_hook.py:647` + add `test_overflow_cursor_advances_to_rendered_max` regression test.

**Plus (post-merge):** re-deploy the user-global hook by cp'ing the fixed fixture to `~/.claude/hooks/session-start-bus-drain.sh`. The drift-detection test you added in PR #183 catches drift, so this step closes the loop.

## Ship gate

1. `bash -n ~/.claude/hooks/session-start-bus-drain.sh` — passes.
2. `pytest tests/test_bus_drain_hook.py -v` — 10/10 (was 9/9 + 1 new regression test).
3. PR description includes literal `pytest` stdout.
4. AH2 cross-lane review — fast turnaround expected (cleared parent PR yesterday).
5. After merge: cp `tests/fixtures/session-start-bus-drain.sh` to `~/.claude/hooks/session-start-bus-drain.sh` + verify drift-detection test passes.

## Files touched

**Modify (in-repo):**
- `tests/fixtures/session-start-bus-drain.sh` — line 377 (`msgs` → `shown`)
- `tests/test_bus_drain_hook.py` — drop line 647 unused var + add 1 regression test

**Modify (user-global, post-merge):**
- `~/.claude/hooks/session-start-bus-drain.sh` — cp from fixed fixture

**Do NOT touch:**
- `~/.claude/settings.json` — unchanged (hook path + timeout same)
- `brisen-lab/` daemon — unchanged
- Anything else in `session-start-bus-drain.sh` beyond line 377

## Estimated complexity

Small · ~30 min · 1 PR · Tier-B correctness follow-up. No `/security-review` re-pass.

## Heartbeat

12h cadence binding. Brief is small enough one heartbeat suffices.

## Prior CODE_2 task (archive reference)

BRIEF_BRISEN_LAB_TERMINAL_BUS_DRAIN_ON_SESSION_START_1 — SHIPPED 2026-05-11 (PR #183 squash-merged at `2cc97a7` 2026-05-10T22:59Z). AH2 cross-lane CLEARED, `/security-review` CLEARED, Director ratified user-global state, Director skipped live smoke. Mailbox hygiene rule applied — overwriting per `_ops/processes/b-code-dispatch-coordination.md` §3.

---

# UPDATE 2026-05-10T23:05Z — FOLD_FIX_REQUIRED on PR #180 (P1 — do BEFORE cursor-cap above)

The 4-gate review chain on PR #180 returned. **Cursor-cap dispatch above DEFERRED** until PR #180 fold ships + merges. Context-switch to `b2/cortex-cockpit-sidebar-wiring` branch.

Priority order:
  1. **THIS** — PR #180 fold-fix (P1, ~45-60 min, unblocks cascade)
  2. Cursor-cap dispatch (P3, ~30 min) — already in mailbox frontmatter above; resume after PR #180 merges

## All 4 gates returned on PR #180

- **Gate 1 pytest:** PASS (28/28 GREEN per ship report)
- **Gate 2 AH2 /security-review:** PASS — no HIGH/MEDIUM security findings (cleared all 8 attack-surface categories)
- **Gate 3 code-architecture-reviewer:** PASS_WITH_CONCERNS
- **Gate 4 feature-dev:code-reviewer:** PASS_WITH_CONCERNS

## Fold scope

### Fold item 1 — Convergent HIGH (both reviewers): `registry_version()` / `registry_ratified_at()` None-coercion bug

**File:** `kbl/priorities_registry.py` (the two getters at the bottom; current truthiness gate `reg.priorities or reg.schema_version` returns `None` when the file loaded fine but `schema_version=0`).

**Fix shape:**

1. Add `loaded: bool = False` field to the `_PrioritiesRegistry` dataclass.
2. `_empty_registry()` keeps `loaded=False` (default).
3. `_parse_yaml()` sets `loaded=True` on the registry it returns (after successful validation).
4. `registry_version()` and `registry_ratified_at()` switch to:

```python
def registry_version() -> Optional[int]:
    reg = _get_registry()
    return reg.schema_version if reg.loaded else None

def registry_ratified_at() -> Optional[str]:
    reg = _get_registry()
    return reg.ratified_at if reg.loaded else None
```

### Fold item 2 — Gate 4 HIGH: parse-storm on persistent schema violation

**File:** `kbl/priorities_registry.py:_get_registry()`.

**Problem:** `_parse_yaml(path)` raises `PrioritiesRegistryError` on schema violation — exception propagates out of the `with _lock:` block WITHOUT setting `_cache`. Every subsequent call retries the parse on every request. Under load this is a parse-storm.

**Fix shape** (catch the parse error inside the lock; cache empty sentinel; log loud ONCE):

```python
def _get_registry() -> _PrioritiesRegistry:
    global _cache, _missing_file_warned, _parse_error_warned
    if _cache is None:
        with _lock:
            if _cache is None:
                try:
                    path = _resolve_yaml_path()
                except PrioritiesRegistryError as e:
                    if not _missing_file_warned:
                        logger.warning("priorities_registry unavailable: %s", e)
                        _missing_file_warned = True
                    _cache = _empty_registry()
                    return _cache

                if not path.is_file():
                    if not _missing_file_warned:
                        logger.warning(
                            "priorities_registry: %s not found; sidebar will use legacy fallback",
                            path,
                        )
                        _missing_file_warned = True
                    _cache = _empty_registry()
                    return _cache

                try:
                    _cache = _parse_yaml(path)
                except PrioritiesRegistryError as parse_err:
                    # Schema violation: log LOUD (Director must fix YAML),
                    # cache empty sentinel so we don't re-parse on every call
                    # (parse-storm). reload() clears the cache + retries.
                    if not _parse_error_warned:
                        logger.error(
                            "priorities_registry SCHEMA VIOLATION in %s: %s — sidebar in legacy fallback until reload()",
                            path, parse_err,
                        )
                        _parse_error_warned = True
                    _cache = _empty_registry()
                    return _cache
    return _cache
```

Add a sibling module-level flag at the top alongside `_missing_file_warned`:
```python
_parse_error_warned: bool = False
```

Reset both flags in `reload()`:
```python
def reload() -> None:
    global _cache, _missing_file_warned, _parse_error_warned
    with _lock:
        _cache = None
        _missing_file_warned = False
        _parse_error_warned = False
```

### Fold item 3 — Gate 3 MEDIUM: fallback_mode banner in cockpit UI

**File:** `outputs/static/app.js` (around the `_renderMatterSection` block).

The endpoint already emits `data.fallback_mode` (∈ {null, "legacy_no_priorities", "error"}). Frontend currently ignores it. Director sees legacy shape silently.

**Fix shape** (add a small degraded-state hint above the sidebar matter list):

```javascript
// Inside the render fn, after data is fetched
if (data.fallback_mode) {
  const banner = document.getElementById('cockpit-fallback-banner');
  if (banner) {
    banner.style.display = 'block';
    banner.textContent =
      data.fallback_mode === 'legacy_no_priorities'
        ? 'Priorities source unavailable — showing legacy view'
        : 'Priorities source error — showing legacy view';
  }
} else {
  const banner = document.getElementById('cockpit-fallback-banner');
  if (banner) banner.style.display = 'none';
}
```

Add the banner element to the sidebar header in `outputs/static/index.html` (small inline div with muted background, hidden by default — id="cockpit-fallback-banner"). Bump cache-bust `?v=111` → `?v=112` on `app.js` reference.

### Fold item 4 — Gate 3 MEDIUM: cache invalidation trigger (admin reload endpoint)

**File:** `outputs/dashboard.py`.

Director edits `_priorities.yml` in the vault → in-process cache survives until Render dyno restart. Add a manual reload endpoint:

```python
@app.post("/api/admin/priorities/reload", dependencies=[Depends(verify_api_key)])
async def priorities_reload():
    """Drop the priorities-registry cache; next call re-reads _priorities.yml."""
    from kbl import priorities_registry
    priorities_registry.reload()
    return {
        "reloaded_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": priorities_registry.registry_version(),
        "ratified_at": priorities_registry.registry_ratified_at(),
        "priority_count": len(priorities_registry.get_all()),
    }
```

Place adjacent to existing admin endpoints in `dashboard.py` (grep `/api/admin/` for the section). Pattern mirrors the existing `Depends(verify_api_key)` admin endpoints.

## REFUTED finding — Gate 4 HIGH #1 ("`reload()` writes _missing_file_warned outside lock")

**False positive.** Current source at `kbl/priorities_registry.py` reload() — verified directly via `git show origin/b2/cortex-cockpit-sidebar-wiring:kbl/priorities_registry.py`:

```python
def reload() -> None:
    global _cache, _missing_file_warned
    with _lock:
        _cache = None
        _missing_file_warned = False
```

The `_missing_file_warned = False` IS inside `with _lock:`. No fold needed — reviewer mis-read. (After Fold item 2 lands, the reload() function additionally resets `_parse_error_warned` — see Fold item 2.)

## Out of fold scope (deferred — confirmed by AH2 PASS)

- LOW: missing_file_warned reset comment
- LOW: severity enum extension silent degradation
- LOW: slug normalization asymmetry between priorities + alerts inbox
- LOW: duplicate bad-schema fixture test
- LOW: notes default handling

## After fold

1. Re-run full test suite:
   ```bash
   pytest tests/test_priorities_registry.py tests/test_dashboard.py -v
   ```
   Expect existing 28/28 GREEN + 2-3 new tests for the loaded:bool field + parse-storm sentinel + admin reload endpoint. Add tests yourself.
2. Verify cache-bust on `app.js?v=112` (Lesson #4).
3. Push fold commit to same branch (`b2/cortex-cockpit-sidebar-wiring`).
4. Append ship-report at `briefs/_reports/B2_cortex_cockpit_sidebar_wiring_20260510.md` with the fold section. Status flips to `SHIPPED_FOLD_OK`.

**Per SKILL.md narrow-fold-scope exemption:** Gates 2+3+4 will NOT be re-fired post-fold. AH2 PASS already covers the post-fold perimeter. AH1 proposes merge directly on your fold ship-report.

## After PR #180 merge — resume cursor-cap dispatch

Once PR #180 merges:
1. Status flips back to `PENDING` on the cursor-cap dispatch above.
2. Branch switches to `b2/bus-drain-cursor-cap-fix-1` (per the cursor-cap frontmatter).
3. Proceed with the cursor-cap brief as originally dispatched.

ETA estimates:
  - Fold PR #180: ~45-60 min
  - Cursor-cap resume: ~30 min as originally scoped

— AH1
