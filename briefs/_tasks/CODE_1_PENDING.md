# Code Brisen #1 — Pending Task

**From:** AI Head (Team 1 — Meta/Persistence)
**To:** Code Brisen #1
**Task posted:** 2026-04-23
**Status:** OPEN — `MAC_MINI_WRITER_AUDIT_1` (CHANDA #9 operational runbook + CHANDA #4 hook-stage correction)

**Supersedes:** prior `KBL_SCHEMA_1` task — shipped as PR #52, merged `a47125c` 2026-04-23. Mailbox cleared.

---

## Brief-route note (charter §6A)

Full `/write-brief` 6-step protocol. Brief at `briefs/BRIEF_MAC_MINI_WRITER_AUDIT_1.md`.

Final M0 quintet row 2 sub-brief (detector #9). Bundles a correction for a CHANDA #4 hook-stage bug surfaced during the KBL_SCHEMA_1 vault mirror (2026-04-23 afternoon — required temp-hook bypass to land vault commit `07089e3`). Memory capture: `memory/feedback_chanda_4_hook_stage_bug.md`.

---

## Context (TL;DR)

Two related vault-writer integrity concerns in one focused brief:

1. **CHANDA #9** (Mac Mini sole writer) — needs an operational runbook (Research matrix §Recommendation step 4 was explicit: "Audit + document detector #9 in operational runbook. No code, but explicit.")

2. **CHANDA #4 hook-stage bug** — `author_director_guard.sh` (PR #49) was installed at `.git/hooks/pre-commit` on Mac Mini. Script reads `.git/COMMIT_EDITMSG` to check the `Director-signed:` marker, but git's pre-commit stage fires BEFORE `-F`/`-m` content is written to that file. Result: hook rejects legit `git commit -F msg.txt` even when the marker is correctly in the message. Script itself is correct and already handles both stages via `${1:-.git/COMMIT_EDITMSG}` — only the install stage is wrong. Fix is a post-merge SSH `mv pre-commit commit-msg`.

## Action

Read `briefs/BRIEF_MAC_MINI_WRITER_AUDIT_1.md` end-to-end. 3 features:

1. **NEW** `_ops/runbooks/mac-mini-vault-writer-audit.md` (~120 lines). 5 numbered audit checks (reachability, Render creds, committer identity, hook install+smoke, SSH key rotation). Verbatim content in brief Feature 1.

2. **MODIFIED** `CHANDA_enforcement.md`:
   - §6 row #4: change `pre-commit hook` → `commit-msg hook` (one text substitution).
   - §7 amendment log: append ONE row for 2026-04-23 §6 stage correction. Verbatim in brief Feature 2.

3. **MODIFIED** `tests/test_author_director_guard.py`: append ONE test function (~45 LOC) — `test_hook_works_as_commit_msg_stage_via_git_commit`. Installs script as `.git/hooks/commit-msg`, exercises via real `git commit -m`. Verbatim in brief Feature 3.

**Non-negotiable invariants:**
- Do NOT touch `invariant_checks/author_director_guard.sh` — script is correct, zero edits needed. Install stage (AI Head post-merge SSH) is the fix.
- Do NOT touch `baker-vault/` or `~/baker-vault/` — Mac Mini sole writer.
- Do NOT add §8 to `CHANDA_enforcement.md` — amendment-log append only.
- Keep the new test cleanly appended to existing test file (reuse existing `_init_repo` / `_write` / `_stage` / `_commit_clean` helpers).

## Ship gate (literal output required in ship report)

**Baseline first** — run `pytest tests/ 2>&1 | tail -3` on `main` BEFORE branching.

Then, after implementation:

```bash
# 1. YAML frontmatter parses (runbook)
python3 -c "import yaml; raw = open('_ops/runbooks/mac-mini-vault-writer-audit.md').read(); d = yaml.safe_load(raw.split('---')[1]); assert d['type'] == 'runbook' and d['invariant'] == 'CHANDA-9'"

# 2. Runbook has 5 numbered checks
grep -c "^### [0-9]\." _ops/runbooks/mac-mini-vault-writer-audit.md

# 3. CHANDA_enforcement.md stage correction applied
grep "commit-msg hook" CHANDA_enforcement.md          # expect 1
grep -c "pre-commit hook" CHANDA_enforcement.md       # expect 0
grep -c "^| 2026-04" CHANDA_enforcement.md            # expect 4
tail -1 CHANDA_enforcement.md                         # the new 2026-04-23 §6 row

# 4. Test syntax clean
python3 -c "import py_compile; py_compile.compile('tests/test_author_director_guard.py', doraise=True)"

# 5. New test passes in isolation
pytest tests/test_author_director_guard.py::test_hook_works_as_commit_msg_stage_via_git_commit -v

# 6. Full GUARD_1 test file green
pytest tests/test_author_director_guard.py -v   # expect 7 passed

# 7. Regression delta
pytest tests/ 2>&1 | tail -3                    # +1 pass vs main baseline, 0 regressions

# 8. Singleton hook still green
bash scripts/check_singletons.sh

# 9. No baker-vault writes in diff
git diff --name-only main...HEAD | grep -E "(^baker-vault/|~?/baker-vault)" || echo "OK: no baker-vault writes."
```

**No "pass by inspection"** (per `feedback_no_ship_by_inspection.md`). Paste literal outputs.

## Ship shape

- **PR title:** `MAC_MINI_WRITER_AUDIT_1: CHANDA #9 runbook + #4 hook-stage correction (commit-msg)`
- **Branch:** `mac-mini-writer-audit-1`
- **Files:** 3 — 1 NEW (runbook) + 2 MODIFIED (CHANDA_enforcement.md + test file).
- **Commit style:** `chanda(#9+#4): vault-writer audit runbook + hook-stage correction to commit-msg`
- **Ship report:** `briefs/_reports/B1_mac_mini_writer_audit_1_20260423.md`. Include all 9 outputs literal + baseline pytest line + git diff --stat.

**Tier A auto-merge on B3 APPROVE** (standing per charter §3).

## Out of scope (explicit)

- **Do NOT** modify `invariant_checks/author_director_guard.sh` — script is stage-agnostic via `${1:-.git/COMMIT_EDITMSG}`. Zero edits.
- **Do NOT** SSH Mac Mini or touch baker-vault from this PR — AI Head post-merge handles the `mv pre-commit commit-msg` install.
- **Do NOT** remove the `pre-commit hook` text from `§4 row #4` — §4 text is the INVARIANT description (unchanged); §6 is the DETECTOR detail (changed).
- **Do NOT** refactor existing 6 GUARD_1 tests — append test #7 only.
- **Do NOT** add `.github/workflows/` CI — no CI yet.
- **Do NOT** bundle any other M0 rows (KBL_INGEST_ENDPOINT / PROMPT_CACHE_AUDIT / CITATIONS_API_SCAN_1) — those are separate briefs.
- **Do NOT** touch `triggers/embedded_scheduler.py`, `memory/store_back.py`, `models/cortex.py`, `invariant_checks/ledger_atomic.py`, `vault_scaffolding/` — all unrelated.

## Timebox

**1.5h.** If >2.5h, stop and report — docs brief should not exceed this.

**Working dir:** `~/bm-b1`.

---

**Dispatch timestamp:** 2026-04-23 post-vault-mirror (Team 1, M0 quintet row 2c + hook-stage fix)
**Team:** Team 1 — Meta/Persistence
**Sequence:** ENFORCEMENT_1 (#45) → GUARD_1 (#49) → LEDGER_ATOMIC_1 (#51) → KBL_SCHEMA_1 (#52) → **MAC_MINI_WRITER_AUDIT_1 (this, closes M0 row 2)**
