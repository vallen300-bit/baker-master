# CODE_3_PENDING — B3 REVIEW: PR #53 MAC_MINI_WRITER_AUDIT_1 — 2026-04-23

**Dispatcher:** AI Head (Team 1 — Meta/Persistence)
**Working dir:** `~/bm-b3`
**Target PR:** https://github.com/vallen300-bit/baker-master/pull/53
**Branch:** `mac-mini-writer-audit-1`
**Brief:** `briefs/BRIEF_MAC_MINI_WRITER_AUDIT_1.md` (shipped in commit `f054da7`)
**Ship report:** `briefs/_reports/B1_mac_mini_writer_audit_1_20260423.md` (commit `453bca6`)

**Supersedes:** prior `KBL_SCHEMA_1` B3 review — APPROVE landed; PR #52 merged `a47125c`. Mailbox cleared.

---

## What this PR does

Ships final M0 quintet row 2 sub-brief — CHANDA #9 operational runbook + CHANDA #4 hook-stage correction. 3 files on branch head `f48f052`, with a **1-line follow-up `a0d777c` from AI Head** aligning §4 row #4 Method column to match §6 detector detail.

**Two commits on branch:**
1. `f48f052` (B1 ship) — NEW `_ops/runbooks/mac-mini-vault-writer-audit.md` (115 lines, 5 numbered audit checks), MODIFIED `CHANDA_enforcement.md` (§6 detector #4 method `pre-commit hook` → `commit-msg hook` + §7 amendment-log row), MODIFIED `tests/test_author_director_guard.py` (+1 test `test_hook_works_as_commit_msg_stage_via_git_commit` installing script as `commit-msg` + real `git commit -m` flow).
2. `a0d777c` (AI Head fast-follow) — §4 row #4 Method column `pre-commit hook` → `commit-msg hook`. Single-line alignment with §6. §3 line 19 (`Static check (pre-commit hook, CI)` — method catalog) deliberately NOT touched.

B1 reported: 8/9 ship gate PASS, gate #3 flagged spec tension (dispatch grep expected 0 but brief's do-not-touch rule collided with §4 row #4 Method column). Fast-follow `a0d777c` resolves the tension.

Pytest delta: 830 → 831 passed (+1 new test), 0 regressions.

---

## Your review job (charter §3 — B3 routes; Tier A auto-merge on APPROVE)

### 1. Scope lock — exactly 3 files on the PR

```bash
cd ~/bm-b3 && git fetch && git checkout mac-mini-writer-audit-1 && git pull -q
git diff --name-only main...HEAD
```

Expect exactly these 3 paths, nothing else:

```
CHANDA_enforcement.md
_ops/runbooks/mac-mini-vault-writer-audit.md
tests/test_author_director_guard.py
```

**Reject if:** `invariant_checks/author_director_guard.sh` touched (script must stay stage-agnostic; zero edits per brief), `baker-vault/` paths, or any `models/`, `memory/`, or `triggers/` files.

### 2. Two-commit branch shape

```bash
git log --oneline main..HEAD
```

Expect exactly 2 commits: `f48f052` (B1 ship) + `a0d777c` (AI Head fast-follow). No force-pushes, no collapsed history.

### 3. Runbook YAML frontmatter parses

```bash
python3 -c "import yaml; raw = open('_ops/runbooks/mac-mini-vault-writer-audit.md').read(); d = yaml.safe_load(raw.split('---')[1]); assert d['type'] == 'runbook' and d['invariant'] == 'CHANDA-9'"
```

Expect: zero output, zero error.

### 4. Runbook has 5 numbered checks

```bash
grep -c "^### [0-9]\." _ops/runbooks/mac-mini-vault-writer-audit.md
```

Expect: `5`.

### 5. `pre-commit hook` appears ONLY in legitimate contexts

```bash
grep -n "pre-commit hook" CHANDA_enforcement.md
```

Expect exactly **1 hit**: line 19 (§3 methods catalog `Static check (pre-commit hook, CI)`). All other occurrences should be gone (both §4 row #4 and §6 corrected).

Reject if:
- 0 hits → §3 catalog accidentally edited (out-of-scope deletion).
- 2+ hits → either §4 row #4 or §6 still says "pre-commit hook" (alignment incomplete).

### 6. `commit-msg hook` appears exactly twice

```bash
grep -c "commit-msg hook" CHANDA_enforcement.md
```

Expect: `2` — one in §4 row #4 Method column, one in §6 detector #4 row.

### 7. §7 amendment log — exactly 4 dated rows

```bash
grep -c "^| 2026-04" CHANDA_enforcement.md
```

Expect: `4` (2026-04-21 initial + 2026-04-23 #4 from PR #49 + 2026-04-23 #2 from PR #51 + 2026-04-23 §6 stage from this PR).

### 8. New test function exists and runs in isolation

```bash
grep -n "def test_hook_works_as_commit_msg_stage_via_git_commit" tests/test_author_director_guard.py
pytest tests/test_author_director_guard.py::test_hook_works_as_commit_msg_stage_via_git_commit -v
```

Expect: function present, `1 passed` on isolated run.

### 9. Full GUARD_1 test file green — now 7 tests

```bash
pytest tests/test_author_director_guard.py -v
```

Expect: `7 passed`.

### 10. Regression delta — 830 → 831

```bash
pytest tests/ 2>&1 | tail -3
```

Expect `19 failed, 831 passed, 19 errors` (or whatever main shows + 1 new pass). Compare to main baseline `19f/830p/19e` at review time → delta = +1 pass, 0 regressions.

### 11. `invariant_checks/author_director_guard.sh` UNCHANGED

```bash
git diff main...HEAD -- invariant_checks/author_director_guard.sh | wc -l
```

Expect: `0`. Zero bytes of diff. Script stays stage-agnostic; install-side fix (AI Head post-merge SSH) is out-of-PR.

### 12. No baker-vault writes in diff

```bash
git diff --name-only main...HEAD | grep -E "(^baker-vault/|~?/baker-vault)" || echo "OK: no baker-vault writes."
```

Expect: `OK: no baker-vault writes.` Any hit = CHANDA #9 violation.

### 13. Singleton hook still green

```bash
bash scripts/check_singletons.sh
```

Expect: `OK: No singleton violations found.`

---

## If 13/13 green

Post APPROVE on PR #53. Tier A auto-merge on APPROVE (standing per charter §3). Write ship report to `briefs/_reports/B3_pr53_mac_mini_writer_audit_1_review_20260423.md`.

Overwrite this file with a "B3 dispatch back" summary section. Commit + push on main.

## If any check fails

Use `gh pr review --request-changes` with a specific list. Route back to B1 via new CODE_1_PENDING.md task. Do NOT merge.

---

## Timebox

**~25–30 min.** 13 checks, content-heavy but mechanical.

---

**Dispatch timestamp:** 2026-04-23 post-PR-53-ship + fast-follow (Team 1, M0 quintet row 2c B3 review)
**Team:** Team 1 — Meta/Persistence
**Sequence:** ENFORCEMENT_1 (#45) → GUARD_1 (#49) → LEDGER_ATOMIC_1 (#51) → KBL_SCHEMA_1 (#52) → **MAC_MINI_WRITER_AUDIT_1 (#53, this review)** — closes M0 row 2
