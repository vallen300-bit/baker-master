# Code Brisen #1 — Pending Task

**From:** AI Head (Team 1 — Meta/Persistence)
**To:** Code Brisen #1
**Task posted:** 2026-04-23
**Status:** OPEN — `AUTHOR_DIRECTOR_GUARD_1` (CHANDA detector #4 pre-commit hook + §7 amendment-log entry)

**Supersedes:** prior `AUDIT_SENTINEL_1` task — shipped as PR #48, merged `5831c77` 2026-04-23 06:34 UTC. Mailbox cleared.

---

## Brief-route note (charter §6A)

Full `/write-brief` 6-step protocol. Brief at `briefs/BRIEF_AUTHOR_DIRECTOR_GUARD_1.md`.

Ships CHANDA detector #4 per Research Agent's 2026-04-21 engineering-matrix sequencing (Step 2 of 4 — ENFORCEMENT_1 already shipped as PR #45). Bundles a 1-line amendment-log entry in `CHANDA_enforcement.md` §7 per Director's "bank-client" framing.

---

## Context (TL;DR)

CHANDA_enforcement.md §4 row #4 requires `author: director` files stay "untouched by agents." Director ratified 2026-04-23 that his workflow is **plain English → AI Head commits the .md edit** — so email-allowlist bypass blocks the real workflow. New mechanism: **intent-based commit-signing** — hook checks commit message for a `Director-signed:` marker with a quoted instruction.

Two live protected files in baker-vault (`wiki/hot.md`, `_ops/ideas/2026-04-21-chanda-plain-english-rewrite.md`). Baker-master has zero today; hook is defensive for future.

## Action

Read `briefs/BRIEF_AUTHOR_DIRECTOR_GUARD_1.md` end-to-end. All 3 implementation blocks (shell script, pytest, amendment-log entry) are copy-pasteable.

**Script location** — CHANDA §6 path:
```
/Users/dimitry/Vallen Dropbox/Dimitry vallen/Baker-Project/15_Baker_Master/01_build/invariant_checks/author_director_guard.sh
```

**Executable bit required** — git must track as `100755`. Set after creation:
```bash
chmod +x invariant_checks/author_director_guard.sh
git update-index --chmod=+x invariant_checks/author_director_guard.sh
```

Verify: `git ls-files --stage invariant_checks/author_director_guard.sh` → prefix `100755`.

## Ship gate (literal output required in ship report)

```
bash -n invariant_checks/author_director_guard.sh
git ls-files --stage invariant_checks/author_director_guard.sh    # prefix 100755
pytest tests/test_author_director_guard.py -v                     # 6 passed
python3 -c "import py_compile; py_compile.compile('tests/test_author_director_guard.py', doraise=True)"
bash scripts/check_singletons.sh                                  # OK
pytest tests/ 2>&1 | tail -3                                      # +6 passes, 0 regressions
grep -c "^| 2026-04" CHANDA_enforcement.md                        # 2
grep "Director-signed" CHANDA_enforcement.md                      # >=1 hit
tail -1 CHANDA_enforcement.md                                     # new 2026-04-23 row
```

**No "pass by inspection"** (per `feedback_no_ship_by_inspection.md`). Paste literal outputs.

## Ship shape

- **PR title:** `AUTHOR_DIRECTOR_GUARD_1: CHANDA detector #4 pre-commit hook (intent-based commit-signing)`
- **Branch:** `author-director-guard-1`
- **Files:** 2 new (script + pytest) + 1 modified (CHANDA_enforcement.md 1-line amendment)
- **Commit style:** one clean squash-ready commit. Example: `chanda(detector#4): author:director files guarded by intent-based commit-signing hook`
- **Ship report:** `briefs/_reports/B1_author_director_guard_1_20260423.md`. Include all 9 Quality Checkpoint outputs + 1-line CHANDA_enforcement.md diff + `git ls-files --stage` line showing executable bit.

**Tier A auto-merge on B3 APPROVE** (standing per charter §3).

## Out of scope (explicit)

- **Do NOT** install hook in `.git/hooks/pre-commit` — AI Head post-merge SSH to Mac Mini handles baker-vault install; baker-master local hook install is Director-local.
- **Do NOT** add `.github/workflows/` CI — no CI infra exists yet; follow-on brief post-M0.
- **Do NOT** modify `scripts/check_singletons.sh` — unrelated singleton hook.
- **Do NOT** touch `CHANDA.md` — paired rewrite is `CHANDA_PLAIN_ENGLISH_REWRITE_1`.
- **Do NOT** add §8 to `CHANDA_enforcement.md` — append ONE ROW to §7 amendment log table only.
- **Do NOT** tighten against rename-bypass edge case — flagged for follow-on `AUTHOR_DIRECTOR_GUARD_2` post-M0; out of MVP scope.

## Timebox

**1.5–2h.** If >3h, stop and report — something's wrong.

**Working dir:** `~/bm-b1`.

---

**Dispatch timestamp:** 2026-04-23 (Team 1, M0 quintet row 2a — CHANDA detector #4)
**Team:** Team 1 — Meta/Persistence
**Sequence:** CHANDA_ENFORCEMENT_1 (shipped PR #45) → **AUTHOR_DIRECTOR_GUARD_1 (this)** → LEDGER_ATOMIC_1 (next) → MAC_MINI_WRITER_AUDIT_1 (docs, last)
