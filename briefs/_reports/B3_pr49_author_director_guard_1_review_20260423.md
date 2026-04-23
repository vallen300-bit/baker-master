# B3 Review — PR #49 AUTHOR_DIRECTOR_GUARD_1 — 2026-04-23

**Reviewer:** Code Brisen #3 (B3)
**PR:** https://github.com/vallen300-bit/baker-master/pull/49
**Branch:** `author-director-guard-1` @ `c691eb3`
**Main compared:** `b902980`
**Brief:** `briefs/BRIEF_AUTHOR_DIRECTOR_GUARD_1.md` (commit `29b165e`)
**B1 ship report:** `briefs/_reports/B1_author_director_guard_1_20260423.md`
**Verdict:** **APPROVE** — 10/10 checks green.

---

## Check 1 — Executable bit ✅

```
git ls-files --stage invariant_checks/author_director_guard.sh
→ 100755 e32f2e9... 0  invariant_checks/author_director_guard.sh
```

`100755` locked in git. Symlink-install on Mac Mini will execute directly.

## Check 2 — Shell syntax + shellcheck ✅

```
bash -n invariant_checks/author_director_guard.sh
→ (clean, no output)
```

shellcheck not installed locally — skipped per brief policy (non-blocking).

## Check 3 — Frontmatter-detection regex ✅

| Case | Input | Expected | Actual |
|------|-------|----------|--------|
| A: standard FM | `---\nauthor: director\n---\nbody\n` | HIT | HIT ✅ |
| B: body-only (code block after closing `---`) | frontmatter `author: agent` + body with fenced `author: director` | no output | no output ✅ |
| C: whitespace tolerance | `author:   director  ` | HIT | HIT ✅ |

awk anchored on `ctr==1` (first FM block only). Body references correctly ignored.

## Check 4 — Marker-detection regex ✅

| Input | Expected | Actual |
|-------|----------|--------|
| `Director-signed: "quote here"` | match | matched ✅ |
| `director-signed: "quote"` (case-mangled) | no match | not matched ✅ |
| `Director-signed: no-quote` (missing `"`) | no match | not matched ✅ |

Strict `^Director-signed:\s*"` — case-sensitive + quote-required. Features, not bugs.

## Check 5 — Two-sided check (staged + HEAD) ✅

```
grep -E 'git show ["][:]|git show ["]HEAD' invariant_checks/author_director_guard.sh
  STAGED_HIT=$(git show ":$f" 2>/dev/null | ...
    PRE_HIT=$(git show "HEAD:$f" 2>/dev/null | ...
```

Both reads present. Frontmatter-toggle bypass (e.g., agent edits body of an `author: director` file but not the frontmatter itself) caught by HEAD-version lookup.

## Check 6 — Test names match spec exactly ✅

```
grep -E "^def test_" tests/test_author_director_guard.py
```

All 6 names present verbatim:
- ✅ `test_non_md_file_passes`
- ✅ `test_unprotected_md_passes`
- ✅ `test_protected_md_without_marker_rejects`
- ✅ `test_protected_md_with_marker_allows`
- ✅ `test_frontmatter_toggle_bypass_blocked`
- ✅ `test_body_false_positive_ignored`

## Check 7 — No mocks ✅

```
grep -n "mock\|Mock\|patch" tests/test_author_director_guard.py
7:No mocks — real git, real script.
```

Single hit is a module-docstring line asserting the constraint — **not a usage**. No `unittest.mock`, no `@patch`, no `MagicMock`. Tests shell-out to real `git` + real hook via `subprocess.run()`.

## Check 8 — Full-suite regression delta ✅

```
=== BRANCH author-director-guard-1 @ c691eb3 ===
19 failed, 819 passed, 21 skipped, 8 warnings, 19 errors in 12.19s

=== MAIN @ b902980 ===
19 failed, 813 passed, 21 skipped, 8 warnings, 19 errors in 10.70s
```

**Delta: +6 passes, 0 new failures, 0 new errors.** Exact match to B1's reported delta.

## Check 9 — CHANDA amendment-log entry ✅

```
grep -c "^| 2026-04" CHANDA_enforcement.md   → 2   (expected 2)
grep -c "Director-signed" CHANDA_enforcement.md → 1 (≥1 expected)
grep -c "§8\|^## §8" CHANDA_enforcement.md    → 0   (still §7-capped)
```

Tail line:
```
| 2026-04-23 | §4 row #4 + §6 | Enforcement refined to intent-based: agent commits to `author: director` files allowed only when commit message carries `Director-signed:` quote marker. Row #4 text unchanged; detector script at `invariant_checks/author_director_guard.sh` implements the check (AUTHOR_DIRECTOR_GUARD_1, PR TBD). | Director workflow definition 2026-04-23 ("To change any files I write to you AI Head in plain English") |
```

Added row cites Director quote correctly (per §7 provenance rule).

## Check 10 — Out-of-scope creep ✅

```
gh pr diff 49 --repo vallen300-bit/baker-master --name-only
CHANDA_enforcement.md
invariant_checks/author_director_guard.sh
tests/test_author_director_guard.py
```

Exactly 3 files. Zero drift into `.git/hooks/`, `scripts/check_singletons.sh`, `CHANDA.md`, `.github/workflows/`.

## Decision

**APPROVE PR #49.** 10/10 checks green. Executable bit locked, shell syntax clean, frontmatter/marker regexes correct across all spec cases, two-sided check prevents toggle-bypass, 6/6 tests with exact names using real git (no mocks), regression delta matches B1 exactly (+6 / 0), CHANDA amendment row properly formatted with Director citation, scope tight.

Tier A auto-merge greenlit per charter §3.

— B3, 2026-04-23
