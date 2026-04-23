# Ship Report — B1 CHANDA_ENFORCEMENT_1

**Date:** 2026-04-23
**Agent:** Code Brisen #1 (Team 1 — Meta/Persistence)
**Brief:** `briefs/BRIEF_CHANDA_ENFORCEMENT_1.md`
**PR:** https://github.com/vallen300-bit/baker-master/pull/45
**Branch:** `chanda-enforcement-1`
**Commit:** `ed8938c chanda(enforcement): create CHANDA_enforcement.md with invariant matrix + severity tiers`
**Status:** SHIPPED — awaiting B3 review / Tier A auto-merge

---

## Scope

Single-file insert. Created `CHANDA_enforcement.md` at repo root (corresponds to Dropbox path `/15_Baker_Master/01_build/CHANDA_enforcement.md`) with verbatim §1–§7 from Research Agent's ratified 2026-04-21 engineering matrix — 11 KBL + 5 Surface invariants, 3 severity tiers, 5 detection methods, top-3 detector pointers, amendment log. No other file touched.

## Byte-count / diff confirmation

```
-rw-r--r--@ 1 dimitry  staff  4822 Apr 23 05:04 CHANDA_enforcement.md
```

Diff vs source artifact (`/Users/dimitry/baker-vault/_ops/ideas/2026-04-21-chanda-engineering-matrix.md` lines 37–110 with H1 `# CHANDA Enforcement — engineering matrix` prepended + blank line):

```
$ (echo "# CHANDA Enforcement — engineering matrix"; echo ""; sed -n '37,110p' source.md) | diff - CHANDA_enforcement.md
$ echo $?
0
```

**Result:** diff is clean — byte-perfect match against source §1–§7 + H1.

## 8-check Verification Results

### Check 1 — file exists
```
$ ls -la CHANDA_enforcement.md
-rw-r--r--@ 1 dimitry  staff  4822 Apr 23 05:04 CHANDA_enforcement.md
```
**PASS** — file exists.

### Check 2 — `head -1` returns H1 title
```
$ head -1 CHANDA_enforcement.md
# CHANDA Enforcement — engineering matrix
```
**PASS** — exact match, no frontmatter, no BOM.

### Check 3 — section header count
```
$ grep -c '^## §' CHANDA_enforcement.md
7
```
**PASS** — 7 sections (§1–§7) as expected.

### Check 4 — `tail -1` amendment row
```
$ tail -1 CHANDA_enforcement.md
| 2026-04-21 | all | Initial creation from CHANDA rewrite session | "yes" (2026-04-21) |
```
**PASS** — exact match.

### Check 5 — table row count
```
$ grep -c '^| ' CHANDA_enforcement.md
28
```
**PASS (with variance note).** Brief expected ~22 approx; actual 28 = 4 (severity: 1 header + 3 data) + 12 (KBL: 1 header + 11 data) + 6 (Surface: 1 header + 5 data) + 4 (detectors: 1 header + 3 data) + 2 (amendment: 1 header + 1 data). Brief explicitly allows small variance ("exact number is not load-bearing, only approximate").

### Check 6 — `wc -l`
```
$ wc -l CHANDA_enforcement.md
      76 CHANDA_enforcement.md
```
**PASS** — 76 lines, within brief's ±5 of ~75.

### Check 7 — `git status --short`
```
$ git status --short
?? CHANDA_enforcement.md
```
**PASS.** Brief notation `?? 15_Baker_Master/01_build/CHANDA_enforcement.md` reflects the Dropbox-clone path prefix; `~/bm-b1` is a parallel clone where the repo root maps to the Dropbox `/15_Baker_Master/01_build/` directory, so `git status` correctly shows only the single new file at the effective same location. No other files changed.

### Check 8 — no `§8` reference
```
$ grep -c '§8' CHANDA_enforcement.md || echo "0"
0
```
**PASS** — file terminates at §7 as required.

## Pytest baseline (literal output, per `feedback_no_ship_by_inspection.md`)

Used `/Users/dimitry/bm-b2/.venv312/bin/pytest` (bm-b1 has no local venv; sibling worktree venv provides pytest 8.4.2 under Python 3.12).

### main (pre-change) — tail
```
=========================== short test summary info ============================
...
ERROR tests/test_mcp_vault_tools.py::test_mcp_dispatch_baker_vault_read_traversal_returns_error_string
ERROR tests/test_mcp_vault_tools.py::test_mcp_dispatch_baker_vault_read_missing_path_arg
ERROR tests/test_mcp_vault_tools.py::test_mcp_dispatch_baker_vault_list_returns_json
ERROR tests/test_mcp_vault_tools.py::test_read_rejects_symlink_escape_outside_ops
20 failed, 801 passed, 21 skipped, 8 warnings, 19 errors in 8.99s
```

### chanda-enforcement-1 — tail
```
=========================== short test summary info ============================
...
ERROR tests/test_mcp_vault_tools.py::test_read_rejects_symlink_escape_outside_ops
20 failed, 801 passed, 21 skipped, 8 warnings, 19 errors in 9.79s
```

**PASS — identical counts on main vs branch: `20 failed / 801 passed / 21 skipped / 19 errors`. Markdown-only change is orthogonal to Python test suite.**

*Note on baseline drift:* Brief predicted `16 failed / 818 passed / 21 skipped` based on main post PR #43. Actual baseline in `~/bm-b1` (using bm-b2 venv) is `20 failed / 801 passed / 21 skipped / 19 errors`. Discrepancy is environmental (venv package versions across worktrees) — the relevant signal for THIS ship is that main and chanda-enforcement-1 produce **identical** results, which confirms the change introduces zero regression. Flagging for AI Head awareness but not blocking.

## Files Modified

- **NEW** `CHANDA_enforcement.md` (76 lines, 4822 bytes)

## Nothing else touched

- `CHANDA.md` — untouched (paired rewrite = `CHANDA_PLAIN_ENGLISH_REWRITE_1`)
- No `invariant_checks/` directory created (follow-on briefs)
- `CLAUDE.md`, `MEMORY.md`, `tasks/lessons.md` — untouched
- No Python files touched

## Timebox

Target: 15 min. Actual: ~20 min (incl. pytest baseline diagnosis across worktrees). Within tolerance.

## Ship shape

- PR title: `CHANDA_ENFORCEMENT_1: create CHANDA_enforcement.md (invariant matrix + severity tiers)`
- Tier A — auto-merge on B3 APPROVE
- Commit: `ed8938c` (follows `chanda(…)` convention)

---

**Dispatch ack:** received 2026-04-23, Team 1 first brief this session. Ready for B3 review.
