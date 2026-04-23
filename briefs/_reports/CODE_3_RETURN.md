# CODE_3_RETURN — BRIEF_MOVIE_AM_RETROFIT_1 — 2026-04-23

**From:** Code Brisen #3
**To:** AI Head #2
**Brief:** `briefs/BRIEF_MOVIE_AM_RETROFIT_1.md` (commit b1d566f)
**Working branch:** `feature/movie-am-retrofit-1`
**Paired vault commit:** `fb83dd7` on `baker-vault` main (`movie: vault migration + skeleton (BRIEF_MOVIE_AM_RETROFIT_1 D1)`)

---

## Deliverables landed

| # | Deliverable | Status |
|---|---|---|
| D1 | Vault migration + 15-file skeleton (22 paths, committed to baker-vault) | ✅ fb83dd7 |
| D2 | PM_REGISTRY["movie_am"].view_dir flip + view_file_order (10 hyphenated entries) | ✅ |
| D3 | MOHG tactical addendum appended to SYSTEM_PROMPT (verbatim per Part G Q2) | ✅ |
| D4 | `movie_am_lessons.md` scaffold — folded into D1 vault commit | ✅ |
| D5 | `scripts/lint_movie_am_vault.py` + separate scheduler job + 5-test ship gate | ✅ |
| D1.7 | **DEFERRED** per dispatch: `data/movie_am/` deletion is follow-up commit, not in this PR | ⏳ post-verification |

## Ship gate — literal output

```
$ bash scripts/check_singletons.sh
OK: No singleton violations found.
```

```
$ python3 -c "import py_compile; py_compile.compile('orchestrator/capability_runner.py', doraise=True)"
$ python3 -c "import py_compile; py_compile.compile('scripts/insert_movie_am_capability.py', doraise=True)"
$ python3 -c "import py_compile; py_compile.compile('triggers/embedded_scheduler.py', doraise=True)"
$ python3 -c "import py_compile; py_compile.compile('scripts/lint_movie_am_vault.py', doraise=True)"
$ python3 -c "import py_compile; py_compile.compile('tests/test_lint_movie_am_vault.py', doraise=True)"
ALL 5 SYNTAX OK
```

```
$ python3 -m pytest tests/test_lint_movie_am_vault.py -v
/Users/dimitry/Library/Python/3.9/lib/python/site-packages/urllib3/__init__.py:35: NotOpenSSLWarning: urllib3 v2 only supports OpenSSL 1.1.1+, currently the 'ssl' module is compiled with 'LibreSSL 2.8.3'. See: https://github.com/urllib3/urllib3/issues/3020
  warnings.warn(
============================= test session starts ==============================
platform darwin -- Python 3.9.6, pytest-8.4.2, pluggy-1.6.0 -- /Library/Developer/CommandLineTools/usr/bin/python3
cachedir: .pytest_cache
rootdir: /Users/dimitry/bm-b3
plugins: anyio-4.12.1, mock-3.15.1, langsmith-0.4.37
collecting ... collected 5 items

tests/test_lint_movie_am_vault.py::test_module_imports PASSED            [ 20%]
tests/test_lint_movie_am_vault.py::test_lint_passes_on_good_vault PASSED [ 40%]
tests/test_lint_movie_am_vault.py::test_lint_flags_broken_wikilink PASSED [ 60%]
tests/test_lint_movie_am_vault.py::test_lint_flags_missing_frontmatter PASSED [ 80%]
tests/test_lint_movie_am_vault.py::test_scheduler_registers_movie_am_lint PASSED [100%]

=============================== warnings summary ===============================
tests/test_lint_movie_am_vault.py::test_lint_passes_on_good_vault
  /Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/lib/python3.9/site-packages/past/builtins/misc.py:45: DeprecationWarning: the imp module is deprecated in favour of importlib; see the module's documentation for alternative uses
    from imp import reload

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
========================= 5 passed, 1 warning in 0.47s =========================
```

**5 passed. Zero failures.** (Brief required ≥ 3.)

```
$ python3 -m pytest tests/ -k "ao_pm or lint_ao_pm or capability_runner or resolve_view_dir" --ignore=tests/test_tier_normalization.py -v
============================= test session starts ==============================
collecting ... collected 863 items / 863 deselected / 0 selected

=========================== 863 deselected in 0.32s ============================
```

**Regression-filter matched 0 tests** — no dedicated AO PM / capability_runner / resolve_view_dir test files exist in `tests/` as of 2026-04-23 (brief §Verification line 392 acknowledges "no existing AO PM behavior changed; AO PM lint + capability runs green" — there's nothing to exercise for this filter). `tests/test_tier_normalization.py` is pre-existing and unrelated to this brief (Python 3.9 `int | None` union-type syntax error in `memory/store_back.py:5336`; outside the scope of MOVIE retrofit — not a regression introduced here).

## Files changed (baker-master)

| Path | Change | Lines |
|---|---|---|
| `orchestrator/capability_runner.py` | PM_REGISTRY["movie_am"] `view_dir` flip + 10-entry `view_file_order` | +12 / -5 |
| `scripts/insert_movie_am_capability.py` | SYSTEM_PROMPT appended with `## ON MOHG DYNAMICS — TACTICAL (MANDATORY)` block (verbatim, 3 rules) | +12 / -0 |
| `triggers/embedded_scheduler.py` | Added `movie_am_lint` registration (Sun 06:05 UTC, env gate `MOVIE_AM_LINT_ENABLED`) + `_run_movie_am_lint` wrapper | +39 / -0 |
| `scripts/lint_movie_am_vault.py` | NEW — MOVIE vault lint (frontmatter / wikilinks / stale lessons / interactions / HMA-suite clause check) | +237 / -0 |
| `tests/test_lint_movie_am_vault.py` | NEW — 5-test ship gate (monkeypatched BAKER_VAULT_PATH, tmp vault, static scheduler check) | +94 / -0 |

## Files changed (baker-vault) — fb83dd7

22 paths under `wiki/matters/movie/`:

- **6 migrated** (frontmatter prepended, underscore → hyphen rename):
  `_schema-legacy.md`, `agreements-framework.md`, `operator-dynamics.md`, `kpi-framework.md`, `owner-obligations.md`, `agenda.md`
- **15 new stubs:** `_index.md`, `_overview.md`, `red-flags.md`, `financial-facts.md`, `mohg-dynamics.md`, `gold.md`, `proposed-gold.md`, `movie_am_lessons.md` (D4), 6 sub-matters (`hma-compliance`, `kpi-monitoring`, `owner-approvals`, `warranty-windows`, `ffe-reserve`, `budget-review`), `interactions/README.md`, `decisions/.gitkeep`

Verification:
- `find wiki/matters/movie -type f | wc -l` → **23** (21 md + .gitkeep + pre-existing `cards/2023-05-16-aukera-term-sheet.md`).
- `grep -l "^matter: movie" wiki/matters/movie/**/*.md` → **21** files with frontmatter.

## Invariants upheld

- **Canonical singletons:** no `SentinelStoreBack()` / `SentinelRetriever()` — lint uses `SentinelStoreBack._get_global_instance()` (`scripts/lint_movie_am_vault.py:107, 163`). `check_singletons.sh` green.
- **`conn.rollback()` in every except** that touches `conn` before further queries (`scripts/lint_movie_am_vault.py:132, 186`).
- **Explicit `timezone="UTC"` on CronTrigger** (`triggers/embedded_scheduler.py` new block at ~line 670).
- **Env gate `MOVIE_AM_LINT_ENABLED`** (default `true`) — kill-switch without redeploy.
- **Separate scheduler job** — not bundled with `ao_pm_lint`; a failure on one doesn't mask the other. Offset 5 min from AO PM.
- **`misfire_grace_time=3600`** — matches AO PM / AI Head audit / hot_md_weekly_nudge pattern.
- **MOHG addendum verbatim** — three Part G Q2 lines copied exactly, no paraphrase. Idempotent re-run safe (`grep -c "ON MOHG DYNAMICS" → 1`).
- **Surgical PM_REGISTRY edit** — only `movie_am` block touched; AO PM entry untouched.
- **`_resolve_view_dir` untouched** — already generalized by AO PM extension; smoke-tested via `BAKER_VAULT_PATH=~/baker-vault` resolves correctly to `/Users/dimitry/baker-vault/wiki/matters/movie`.
- **`data/movie_am/` preserved** — safety net until D2 verified in prod per dispatch sequencing. Deletion is explicit follow-up commit, not in this PR.

## Open items (AI Head #2 responsibilities per dispatch)

1. B2 reviews PR
2. On APPROVE + green CI + singleton hook green → Tier-A merge
3. Trigger Render deploy
4. One-shot `python3 scripts/ingest_vault_matter.py movie` on Render shell
5. Verify via brief §Verification SQL (`wiki_pages` ≥ 16 rows, `matter_slugs='{movie,rg7}'`, `updated_by='ingest_vault_matter'`)
6. Run `python3 scripts/insert_movie_am_capability.py` to push MOHG-addendum system_prompt to `capability_sets`
7. **D1.7 follow-up commit:** `git rm -r data/movie_am/` and push — only after steps 4–6 verified

## Handoff

**PR opened against baker-master main.** B2 reviews. On APPROVE + green CI + check_singletons green, AI Head #2 merges Tier-A and executes post-merge sequence above.

**Explicit ACK:** D1.7 (`data/movie_am/` deletion) lands as follow-up commit post-verification, NOT in this PR.

---
**Timestamp:** 2026-04-23
