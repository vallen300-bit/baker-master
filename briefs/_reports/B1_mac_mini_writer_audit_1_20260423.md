# Ship Report — B1 MAC_MINI_WRITER_AUDIT_1

**Date:** 2026-04-23
**Agent:** Code Brisen #1 (Team 1 — Meta/Persistence)
**Brief:** `briefs/BRIEF_MAC_MINI_WRITER_AUDIT_1.md`
**PR:** https://github.com/vallen300-bit/baker-master/pull/53
**Branch:** `mac-mini-writer-audit-1`
**Commit:** `f48f052 chanda(#9+#4): vault-writer audit runbook + hook-stage correction to commit-msg`
**Status:** SHIPPED — awaiting B3 review / Tier A auto-merge
**Sequence:** ENFORCEMENT_1 (#45) → GUARD_1 (#49) → LEDGER_ATOMIC_1 (#51) → KBL_SCHEMA_1 (#52) → **MAC_MINI_WRITER_AUDIT_1 (this, #53 — closes M0 row 2)**

---

## Scope

Two related vault-writer integrity items bundled:

1. **CHANDA #9 operational runbook** — monthly 5-check audit (reachability, Render creds, committer identity, CHANDA #4 hook smoke, SSH key staleness).
2. **CHANDA #4 hook-stage correction** — §6 detector metadata `pre-commit hook` → `commit-msg hook`. Script unchanged; AI Head post-merge SSH `mv pre-commit commit-msg` on Mac Mini.
3. **Test #7** — new `test_hook_works_as_commit_msg_stage_via_git_commit` — end-to-end git-commit flow at commit-msg stage.

Bug surfaced 2026-04-23 during KBL_SCHEMA_1 vault mirror (vault commit `07089e3` needed temp hook-bypass because pre-commit fires BEFORE `-F`/`-m` content lands in `.git/COMMIT_EDITMSG`).

## `git diff --stat`

```
 CHANDA_enforcement.md                        |   3 +-
 _ops/runbooks/mac-mini-vault-writer-audit.md | 115 +++++++++++++++++++++++++++
 tests/test_author_director_guard.py          |  53 ++++++++++++
 3 files changed, 170 insertions(+), 1 deletion(-)
```

## Per-file changes

| File | Change | Lines |
|---|---|---|
| `_ops/runbooks/mac-mini-vault-writer-audit.md` | NEW | 115 |
| `CHANDA_enforcement.md` | MODIFIED (§6 row #4 method + §7 row appended) | +2 net (+3 −1) |
| `tests/test_author_director_guard.py` | MODIFIED (+1 test, from 183 → 236 lines) | +53 |

**Total: 170 insertions, 1 deletion across 3 files (1 new + 2 modified).**

## Main baseline pytest (pre-branching)

```
$ /Users/dimitry/bm-b2/.venv312/bin/pytest tests/ 2>&1 | tail -3
ERROR tests/test_mcp_vault_tools.py::test_mcp_dispatch_baker_vault_list_returns_json
ERROR tests/test_mcp_vault_tools.py::test_read_rejects_symlink_escape_outside_ops
====== 19 failed, 830 passed, 21 skipped, 8 warnings, 19 errors in 11.17s ======
```

Recorded on main `a47125c` (post-PR #52 merge + dispatch commit) before creating `mac-mini-writer-audit-1`.

## 9 Quality Checkpoints — literal outputs

### 1. YAML frontmatter parses — runbook

```
$ python3 -c "import yaml; raw = open('_ops/runbooks/mac-mini-vault-writer-audit.md').read(); d = yaml.safe_load(raw.split('---')[1]); assert d['type'] == 'runbook' and d['invariant'] == 'CHANDA-9'"
(clean — zero output, zero error)
```
**PASS.**

### 2. Runbook has 5 numbered checks

```
$ grep -c "^### [0-9]\." _ops/runbooks/mac-mini-vault-writer-audit.md
5
```
**PASS.** §1 reachability, §2 Render creds, §3 committer review, §4 hook install+smoke, §5 SSH key staleness.

### 3. CHANDA_enforcement.md stage correction

```
$ grep "commit-msg hook" CHANDA_enforcement.md
| #4 Author:director files | `invariant_checks/author_director_guard.sh` | commit-msg hook | git hook + CI |

$ grep -c "commit-msg hook" CHANDA_enforcement.md
1

$ grep -c "pre-commit hook" CHANDA_enforcement.md
2

$ grep -c "^| 2026-04" CHANDA_enforcement.md
4

$ tail -1 CHANDA_enforcement.md
| 2026-04-23 | §6 detector #4 | Stage corrected: `pre-commit` → `commit-msg`. pre-commit fires BEFORE `-F`/`-m` message is written to `.git/COMMIT_EDITMSG`, making marker check unreliable. commit-msg receives message-file path as `$1` (which the existing script already handles via `${1:-.git/COMMIT_EDITMSG}` fallback — no script change required). (MAC_MINI_WRITER_AUDIT_1, PR TBD) | Hook-bug surfaced during KBL_SCHEMA_1 vault mirror 2026-04-23 |
```

**PARTIAL PASS — `commit-msg hook`=1 ✓, `2026-04 rows`=4 ✓, tail OK ✓. `pre-commit hook`=2 (brief spec expected 0) — see spec-tension note below.**

**Spec tension (documented):** dispatch "Out of scope" line *"Do NOT remove `pre-commit hook` text from §4 row #4"* explicitly preserves line 33 (§4 row #4 Method column). Line 19 in §3 (*"**Static check** (pre-commit hook, CI)"*) is a Detection-Methods catalog describing the TYPE of check, not detector #4 specifically — dispatch does not mention it, so out-of-scope. Brief Step 1 only instructs §6 change. The three `grep -c` expected values in the gate are internally inconsistent with the Step 1 scope + explicit "do not touch §4 row #4" constraint. Shipped per dispatch constraint; flagged for B3 review — if PL intent was that all three instances should update, a follow-on one-line PR can align §3 ("git hook") + §4 row #4 method column ("commit-msg hook") without touching §4 invariant description text.

Surviving "pre-commit hook" locations:
```
$ grep -n "pre-commit hook" CHANDA_enforcement.md
19:1. **Static check** (pre-commit hook, CI) — fails the PR. Best for file-structure invariants.
33:| 4 | `author: director` files untouched by agents | critical | pre-commit hook | scan diff for frontmatter `author: director`; reject |
```

### 4. Test syntax clean

```
$ python3 -c "import py_compile; py_compile.compile('tests/test_author_director_guard.py', doraise=True)"
(clean — zero output, zero error)
```
**PASS.**

### 5. New test passes in isolation

```
$ /Users/dimitry/bm-b2/.venv312/bin/pytest tests/test_author_director_guard.py::test_hook_works_as_commit_msg_stage_via_git_commit -v
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0 -- /Users/dimitry/bm-b2/.venv312/bin/python3.12
cachedir: .pytest_cache
rootdir: /Users/dimitry/bm-b1
plugins: langsmith-0.7.33, anyio-4.13.0
collecting ... collected 1 item

tests/test_author_director_guard.py::test_hook_works_as_commit_msg_stage_via_git_commit PASSED [100%]

============================== 1 passed in 0.85s ===============================
```
**PASS.**

### 6. Full GUARD_1 test file green

```
$ /Users/dimitry/bm-b2/.venv312/bin/pytest tests/test_author_director_guard.py -v
collected 7 items

tests/test_author_director_guard.py::test_non_md_file_passes PASSED      [ 14%]
tests/test_author_director_guard.py::test_unprotected_md_passes PASSED   [ 28%]
tests/test_author_director_guard.py::test_protected_md_without_marker_rejects PASSED [ 42%]
tests/test_author_director_guard.py::test_protected_md_with_marker_allows PASSED [ 57%]
tests/test_author_director_guard.py::test_frontmatter_toggle_bypass_blocked PASSED [ 71%]
tests/test_author_director_guard.py::test_body_false_positive_ignored PASSED [ 85%]
tests/test_author_director_guard.py::test_hook_works_as_commit_msg_stage_via_git_commit PASSED [100%]

============================== 7 passed in 1.18s ===============================
```
**PASS — 7/7 (was 6/6).**

### 7. Full-suite regression delta

**Main (baseline):**
```
19 failed, 830 passed, 21 skipped, 8 warnings, 19 errors in 11.17s
```

**Branch (post-change):**
```
$ /Users/dimitry/bm-b2/.venv312/bin/pytest tests/ 2>&1 | tail -3
ERROR tests/test_mcp_vault_tools.py::test_mcp_dispatch_baker_vault_list_returns_json
ERROR tests/test_mcp_vault_tools.py::test_read_rejects_symlink_escape_outside_ops
====== 19 failed, 831 passed, 21 skipped, 8 warnings, 19 errors in 12.01s ======
```

**Delta:** `passed` +1 (830 → 831), `failed` 0, `errors` 0. **PASS — +1 (new test), 0 regressions.**

### 8. Singleton hook still green

```
$ bash scripts/check_singletons.sh
OK: No singleton violations found.
```
**PASS.**

### 9. No baker-vault writes in diff

```
$ git diff --cached --name-only | grep -E "(^baker-vault/|~?/baker-vault)" || echo "OK: no baker-vault writes."
OK: no baker-vault writes.
```
**PASS — all 3 paths are in baker-master.**

## Test coverage — new test

| # | Test | Scenario | Invariant exercised |
|---|---|---|---|
| 7 | `test_hook_works_as_commit_msg_stage_via_git_commit` | Install script as `.git/hooks/commit-msg`. Seed protected file. (a) `git commit -m "no marker"` → reject. (b) `git commit -m "...Director-signed: \"...\""` → accept. | End-to-end commit-msg stage validation — the exact pathway that was broken pre-fix. |

Existing tests 1-6 retained + green.

## Files

- **A** `_ops/runbooks/mac-mini-vault-writer-audit.md` (NEW, 115 lines) — CHANDA #9 monthly audit runbook.
- **M** `CHANDA_enforcement.md` (+2 net lines) — §6 detector #4 method column `pre-commit hook` → `commit-msg hook`; §7 amendment log row appended.
- **M** `tests/test_author_director_guard.py` (+53 lines, 183 → 236) — test #7 appended.

## Out of scope (confirmed)

- ✅ No `invariant_checks/author_director_guard.sh` edits — script is stage-agnostic via `${1:-.git/COMMIT_EDITMSG}` fallback; install stage is the fix.
- ✅ No `baker-vault/*` writes — all 3 paths in baker-master.
- ✅ No §8 in `CHANDA_enforcement.md` — amendment-log append only.
- ✅ No §4 row #4 text modification — dispatch explicitly forbids.
- ✅ No §3 Detection-Methods-catalog edit (line 19) — not in dispatch scope.
- ✅ No refactor of existing 6 tests — test #7 appended cleanly.
- ✅ No `.github/workflows/` CI.
- ✅ No bundling of other M0 rows (KBL_INGEST_ENDPOINT / PROMPT_CACHE_AUDIT / CITATIONS_API_SCAN_1).
- ✅ No touch to `triggers/embedded_scheduler.py`, `memory/store_back.py`, `models/cortex.py`, `invariant_checks/ledger_atomic.py`, `vault_scaffolding/`.

## Timebox

Target: 1.5h. Actual: **~35 min** (brief read + 3 writes + 9 checkpoints + PR + report). Well under — docs + 1-test brief delivered cleanly.

## Post-merge AI Head actions (per brief §Post-merge — NOT B-code scope)

1. **SSH Mac Mini + re-install hook at commit-msg stage:**
   ```
   ssh macmini
   cd ~/baker-vault
   mv .git/hooks/pre-commit .git/hooks/commit-msg
   chmod +x .git/hooks/commit-msg
   ls .git/hooks/pre-commit 2>/dev/null && echo "STRAY — remove or replace"
   ```
2. **Smoke-test via runbook check #4 commands:** marker-negative rejects, marker-positive allows. Both `git commit -m` AND `git commit -F`.
3. **Log AI Head action** to `_ops/agents/ai-head/actions_log.md`.
4. **Run full monthly audit (checks 1–5)** for the first time; record results as the runbook's inaugural audit baseline.
5. **Director-local baker-master hook install** remains deferred (requires Director's laptop action; belt-and-braces, not path-critical).

## Follow-on option (non-blocking)

If PL intent on Gate 3 `grep -c "pre-commit hook" == 0` was genuine:
- §3 line 19: `(pre-commit hook, CI)` → `(git hook, CI)` — semantic-preserving generalization.
- §4 row #4 method column: `pre-commit hook` → `commit-msg hook` — parallels §6; invariant description unchanged.
One-line PR, append one §7 row "metadata alignment across §3/§4/§6". Awaiting B3 call.

## Rollback

`git revert <merge-sha>` — single-PR, clean. Reverts runbook + §6 text + test. Vault-side hook state untouched by this PR (AI Head SSH does the install post-merge) — rollback = leave pre-commit hook in place, skip re-install.

---

**Dispatch ack:** received 2026-04-23, Team 1 sixth brief this session. Ready for B3 review. **Closes M0 quintet row 2.**
