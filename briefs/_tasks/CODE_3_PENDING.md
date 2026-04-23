# CODE_3_PENDING — B3 REVIEW: PR #49 AUTHOR_DIRECTOR_GUARD_1 — 2026-04-23

**Dispatcher:** AI Head (Team 1 — Meta/Persistence)
**Working dir:** `~/bm-b3`
**Target PR:** https://github.com/vallen300-bit/baker-master/pull/49
**Branch:** `author-director-guard-1`
**Brief:** `briefs/BRIEF_AUTHOR_DIRECTOR_GUARD_1.md` (shipped in commit `29b165e`)
**Ship report:** `briefs/_reports/B1_author_director_guard_1_20260423.md` (commit `76d2daa`)

**Supersedes:** prior `AUDIT_SENTINEL_1` B3 review — APPROVE landed; PR #48 merged `5831c77`. Mailbox cleared.

---

## What this PR does

Ships CHANDA detector #4 (pre-commit hook) + §7 amendment-log entry. 3 files, +274/-0 LOC:

- NEW `invariant_checks/author_director_guard.sh` (executable, `100755`) — grep+awk-driven shell script; scans staged diff for `author: director` YAML frontmatter hits (staged + HEAD pre-version); rejects commit if hit AND no `Director-signed:` marker in commit message.
- NEW `tests/test_author_director_guard.py` — 6 scenarios via real git + subprocess (no mocks).
- MODIFIED `CHANDA_enforcement.md` — +1 row in §7 amendment log documenting intent-based enforcement refinement.

B1 reported: 8/8 ship gate PASS, pytest delta +6 passes / 0 regressions, 55 min build (well within 1.5–2h target).

---

## Your review job (charter §3 — B3 routes; Tier A auto-merge on APPROVE)

### 1. Executable bit locked in git

Brief mandated `100755` permission on the shell script. Verify independently:

```bash
cd ~/bm-b3 && git fetch && git checkout author-director-guard-1
git ls-files --stage invariant_checks/author_director_guard.sh
```

Expected first token: `100755`. Any other (e.g., `100644`) = REDIRECT — shell script won't be directly executable via git-hook symlink on Mac Mini install.

### 2. Shell syntax + shellcheck if available

```bash
bash -n invariant_checks/author_director_guard.sh
command -v shellcheck >/dev/null && shellcheck invariant_checks/author_director_guard.sh || echo "(shellcheck not installed — skip)"
```

Expected: zero output on `bash -n`. shellcheck warnings non-blocking (note but don't REDIRECT).

### 3. Frontmatter-detection correctness

The hook uses an awk one-liner anchored to the first `---` block. Verify the logic handles the 3 key cases:

```bash
# Case A: standard frontmatter — should HIT
printf -- '---\nauthor: director\n---\nbody\n' | \
  awk '/^---[[:space:]]*$/{ctr++; next} ctr==1 && /^author:[[:space:]]*director[[:space:]]*$/{print "HIT"; exit}'

# Case B: body-only reference (code block) — should NOT HIT
printf -- '---\nauthor: agent\n---\nbody\n```yaml\nauthor: director\n```\n' | \
  awk '/^---[[:space:]]*$/{ctr++; next} ctr==1 && /^author:[[:space:]]*director[[:space:]]*$/{print "HIT"; exit}'

# Case C: whitespace tolerance — should HIT
printf -- '---\nauthor:   director  \n---\nbody\n' | \
  awk '/^---[[:space:]]*$/{ctr++; next} ctr==1 && /^author:[[:space:]]*director[[:space:]]*$/{print "HIT"; exit}'
```

Expected: Case A HIT, Case B no output, Case C HIT. Any drift = REDIRECT.

### 4. Marker-detection correctness

```bash
# Should match (valid Director-signed)
printf 'commit body\n\nDirector-signed: "quote here"\n' | \
  grep -E '^Director-signed:[[:space:]]*"'

# Should NOT match (case-mangled)
printf 'commit body\n\ndirector-signed: "quote"\n' | \
  grep -E '^Director-signed:[[:space:]]*"' || echo "(not matched — expected)"

# Should NOT match (missing quote)
printf 'commit body\n\nDirector-signed: no-quote\n' | \
  grep -E '^Director-signed:[[:space:]]*"' || echo "(not matched — expected)"
```

Expected: only the first regex matches. Case-sensitivity and strict opening-quote are features, not bugs.

### 5. Two-sided check (staged + pre-version)

Verify the script reads BOTH `git show :$f` (staged) AND `git show HEAD:$f` (pre-version). Grep the script:

```bash
grep -E 'git show ["][:]|git show ["]HEAD' invariant_checks/author_director_guard.sh
```

Expected: 2+ hits (both staged-version and HEAD-version reads present). Missing one = REDIRECT (frontmatter-toggle bypass would not be caught).

### 6. Test file quality — 6 scenarios match brief spec exactly

```bash
grep -E "^def test_" tests/test_author_director_guard.py
```

Expected 6 names:
- `test_non_md_file_passes`
- `test_unprotected_md_passes`
- `test_protected_md_without_marker_rejects`
- `test_protected_md_with_marker_allows`
- `test_frontmatter_toggle_bypass_blocked`
- `test_body_false_positive_ignored`

Missing/renamed = dig into what B1 did and why (possible scope slip).

### 7. Test runs use real git, not mocks

Brief constraint: no mocks. Verify:

```bash
grep -n "mock\|Mock\|patch" tests/test_author_director_guard.py | head
```

Expected: zero hits. Any mock/patch usage = REDIRECT (brief intent was honest shell-out testing).

### 8. Full-suite regression delta

```bash
pytest tests/ 2>&1 | tail -3       # on branch
git checkout main && git pull -q
pytest tests/ 2>&1 | tail -3       # on main
```

B1 reported: main `19f/813p/19e` → branch `19f/819p/19e` = +6 passes, 0 regressions.

Expected: your reproduction matches (modulo timing-flaky tests — re-run if uncertain).

### 9. CHANDA amendment-log entry

```bash
grep -c "^| 2026-04" CHANDA_enforcement.md     # expect 2
grep "Director-signed" CHANDA_enforcement.md    # expect >=1 hit
tail -1 CHANDA_enforcement.md                   # 2026-04-23 row
grep -c "§8\|^## §8" CHANDA_enforcement.md      # expect 0 — file still ends at §7
```

Expected: 2 amendment rows, Director-signed marker documented, new 2026-04-23 row at tail, still zero §8 section.

### 10. Out-of-scope creep check

```bash
gh pr diff 49 --repo vallen300-bit/baker-master --name-only
```

Expected exactly 3 files:
- `invariant_checks/author_director_guard.sh` (new)
- `tests/test_author_director_guard.py` (new)
- `CHANDA_enforcement.md` (modified)

Any other file = REDIRECT (especially `.git/hooks/*`, `scripts/check_singletons.sh`, `CHANDA.md`, `.github/workflows/` — all marked Do-NOT-Touch).

## Ship shape (your output)

- Report path: `briefs/_reports/B3_pr49_author_director_guard_1_review_20260423.md`
- Commit + push your report
- Message me with APPROVE / REDIRECT + 1-line summary per check

## Decision tree

- **10/10 checks clean** → APPROVE → AI Head auto-merges (Tier A, standing).
- **Exec bit wrong** OR **frontmatter/marker regex off** OR **one-sided check** OR **mocks used** OR **out-of-scope file touched** → REDIRECT with specifics.
- **shellcheck warnings only** → note, do not block.

## Timebox

30–45 min. Structural checks fast; regex manual tests + regression delta are the bulk.

---

**Dispatch timestamp:** 2026-04-23 (Team 1, post-B1-ship of PR #49)
**Team:** Team 1 — Meta/Persistence
**Next in M0 row 2b:** `LEDGER_ATOMIC_1` (CHANDA detector #2) — queued for next dispatch post PR #49 merge.
