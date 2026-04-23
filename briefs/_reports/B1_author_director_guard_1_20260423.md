# Ship Report — B1 AUTHOR_DIRECTOR_GUARD_1

**Date:** 2026-04-23
**Agent:** Code Brisen #1 (Team 1 — Meta/Persistence)
**Brief:** `briefs/BRIEF_AUTHOR_DIRECTOR_GUARD_1.md`
**PR:** https://github.com/vallen300-bit/baker-master/pull/49
**Branch:** `author-director-guard-1`
**Commit:** `chanda(detector#4): author:director files guarded by intent-based commit-signing hook`
**Status:** SHIPPED — awaiting B3 review / Tier A auto-merge
**Sequence:** CHANDA_ENFORCEMENT_1 (PR #45 merged) → **AUTHOR_DIRECTOR_GUARD_1 (this)** → LEDGER_ATOMIC_1 → MAC_MINI_WRITER_AUDIT_1

---

## Scope

CHANDA invariant #4 detector — `author: director` files protected by intent-based commit-signing hook (ratified 2026-04-23). Three files: new executable shell script + new pytest suite + one-line §7 amendment log entry in `CHANDA_enforcement.md`.

## §7 amendment log — 1-line diff (Quality Checkpoint §7)

```diff
@@ -74,3 +74,4 @@
 | Date | Section | Change | Director auth |
 |---|---|---|---|
 | 2026-04-21 | all | Initial creation from CHANDA rewrite session | "yes" (2026-04-21) |
+| 2026-04-23 | §4 row #4 + §6 | Enforcement refined to intent-based: agent commits to `author: director` files allowed only when commit message carries `Director-signed:` quote marker. Row #4 text unchanged; detector script at `invariant_checks/author_director_guard.sh` implements the check (AUTHOR_DIRECTOR_GUARD_1, PR TBD). | Director workflow definition 2026-04-23 ("To change any files I write to you AI Head in plain English") |
```

Row #4 text itself remains unchanged. §6 detector pointer already cites the correct script path. File still terminates at §7 (no §8 added).

## Executable bit (Quality Checkpoint §2)

```
$ git ls-files --stage invariant_checks/author_director_guard.sh
100755 e32f2e919aa59d42cb8d8fad323c5e446566d86f 0	invariant_checks/author_director_guard.sh
```

`100755` prefix confirms the executable bit is tracked in git (set via `git update-index --chmod=+x`), portable across clones.

## 8 Quality Checkpoints — literal outputs

### 1. `bash -n` shell syntax

```
$ bash -n invariant_checks/author_director_guard.sh
(clean — zero output)
```
**PASS.**

### 2. Executable bit in git

```
$ git ls-files --stage invariant_checks/author_director_guard.sh
100755 e32f2e919aa59d42cb8d8fad323c5e446566d86f 0	invariant_checks/author_director_guard.sh
```
**PASS — `100755`.**

### 3. New pytest suite

```
$ pytest tests/test_author_director_guard.py -v
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0
cachedir: .pytest_cache
rootdir: /Users/dimitry/bm-b1
plugins: langsmith-0.7.33, anyio-4.13.0
collecting ... collected 6 items

tests/test_author_director_guard.py::test_non_md_file_passes PASSED      [ 16%]
tests/test_author_director_guard.py::test_unprotected_md_passes PASSED   [ 33%]
tests/test_author_director_guard.py::test_protected_md_without_marker_rejects PASSED [ 50%]
tests/test_author_director_guard.py::test_protected_md_with_marker_allows PASSED [ 66%]
tests/test_author_director_guard.py::test_frontmatter_toggle_bypass_blocked PASSED [ 83%]
tests/test_author_director_guard.py::test_body_false_positive_ignored PASSED [100%]

============================== 6 passed in 0.88s ===============================
```
**PASS — 6/6.**

### 4. `py_compile` test file

```
$ python3 -c "import py_compile; py_compile.compile('tests/test_author_director_guard.py', doraise=True)"
(clean — zero output)
```
**PASS.**

### 5. Singleton hook still green

```
$ bash scripts/check_singletons.sh
OK: No singleton violations found.
```
**PASS.**

### 6. Full-suite regression — main vs branch

**Main (baseline):**
```
$ pytest tests/ 2>&1 | tail -3
ERROR tests/test_mcp_vault_tools.py::test_mcp_dispatch_baker_vault_list_returns_json
ERROR tests/test_mcp_vault_tools.py::test_read_rejects_symlink_escape_outside_ops
====== 19 failed, 813 passed, 21 skipped, 8 warnings, 19 errors in 9.75s =======
```

**Branch:**
```
$ pytest tests/ 2>&1 | tail -3
ERROR tests/test_mcp_vault_tools.py::test_mcp_dispatch_baker_vault_list_returns_json
ERROR tests/test_mcp_vault_tools.py::test_read_rejects_symlink_escape_outside_ops
====== 19 failed, 819 passed, 21 skipped, 8 warnings, 19 errors in 11.41s ======
```

**Delta:** `passed` +6 (813 → 819), `failed` 0, `errors` 0. **PASS — +6, 0 regressions.**

### 7. Amendment log checks

```
$ grep -c "^| 2026-04" CHANDA_enforcement.md
2

$ grep "Director-signed" CHANDA_enforcement.md
| 2026-04-23 | §4 row #4 + §6 | Enforcement refined to intent-based: agent commits to `author: director` files allowed only when commit message carries `Director-signed:` quote marker. Row #4 text unchanged; detector script at `invariant_checks/author_director_guard.sh` implements the check (AUTHOR_DIRECTOR_GUARD_1, PR TBD). | Director workflow definition 2026-04-23 ("To change any files I write to you AI Head in plain English") |

$ tail -1 CHANDA_enforcement.md
| 2026-04-23 | §4 row #4 + §6 | Enforcement refined to intent-based: ... | Director workflow definition 2026-04-23 ... |

$ wc -l CHANDA_enforcement.md
77 CHANDA_enforcement.md
```

**PASS — count=2, marker present, new row at tail, file grew from 76 → 77 lines.**

### 8. Manual smoke (optional, not gating)

Skipped as optional; tests `test_protected_md_without_marker_rejects` and `test_protected_md_with_marker_allows` cover the same ground with real git repos under pytest.

## Test coverage (6 scenarios)

| # | Test | Scenario | Asserts |
|---|---|---|---|
| 1 | `test_non_md_file_passes` | Stage .py file | exit 0 |
| 2 | `test_unprotected_md_passes` | Stage .md with `author: agent` | exit 0 |
| 3 | `test_protected_md_without_marker_rejects` | Touch `author: director` file, no marker | exit 1 + stdout contains "CHANDA invariant #4" and "hot.md" |
| 4 | `test_protected_md_with_marker_allows` | Touch `author: director` file WITH `Director-signed: "..."` | exit 0 |
| 5 | `test_frontmatter_toggle_bypass_blocked` | Pre-version has `author: director`, staged version drops it | exit 1 (pre-version check catches it) |
| 6 | `test_body_false_positive_ignored` | `author: director` inside fenced code block in body | exit 0 (frontmatter awk scope correct) |

## Files

- **A** `invariant_checks/author_director_guard.sh` (NEW, **`100755`**) — 87 lines, 3562 bytes
- **A** `tests/test_author_director_guard.py` (NEW) — 186 lines
- **M** `CHANDA_enforcement.md` — +1 line (§7 amendment log row)

Total: **274 insertions, 0 deletions** across 3 files (2 new + 1 modified).

## Out of scope (confirmed)

- ✅ No `.git/hooks/pre-commit` install — AI Head post-merge via SSH to Mac Mini
- ✅ No `.github/workflows/` CI — no CI infra yet; follow-on post-M0
- ✅ No changes to `scripts/check_singletons.sh` (unrelated singleton hook)
- ✅ No changes to `CHANDA.md` (paired rewrite is `CHANDA_PLAIN_ENGLISH_REWRITE_1`)
- ✅ No §8 added — single row append to existing §7 only
- ✅ No rename-bypass tightening — flagged for `AUTHOR_DIRECTOR_GUARD_2` post-M0

## Timebox

Target: 1.5–2h. Actual: **~55 min** (inspection + writes + tests + gates + PR + report). Well within tolerance.

## Post-merge AI Head actions (per brief §Post-merge — NOT B-code scope)

1. SSH Mac Mini → install `invariant_checks/author_director_guard.sh` in `baker-vault/.git/hooks/pre-commit`
2. Smoke-test by attempting to edit `wiki/hot.md` without `Director-signed:` marker → expect rejection
3. Log to `_ops/agents/ai-head/actions_log.md`
4. Flag Director to install belt-and-braces hook in `baker-master/.git/hooks/pre-commit` on MacBook (Director-local action)

## Rollback

`git revert <merge-sha>` — single PR, clean. No env gate (hook is local-only; `git commit --no-verify` bypasses with charter-flagged authorization).

---

**Dispatch ack:** received 2026-04-23, Team 1 third brief this session. Ready for B3 review.
