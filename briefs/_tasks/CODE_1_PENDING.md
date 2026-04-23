# Code Brisen #1 — Pending Task

**From:** AI Head (Team 1 — Meta/Persistence)
**To:** Code Brisen #1
**Task posted:** 2026-04-23 (session reboot, M0 quintet kick-off)
**Status:** OPEN — `CHANDA_ENFORCEMENT_1` (pure-insert markdown file)

**Supersedes:** prior `OBSERVABILITY_STEP7_PLUS_POLLER_DOC_1` task — that work SHIPPED as PR #43, merged `ae867ea` at 2026-04-22 16:43 UTC. Mailbox cleared.

---

## Brief-route note (charter §6A)

Full `/write-brief` 6-step protocol followed. Brief at `briefs/BRIEF_CHANDA_ENFORCEMENT_1.md`.

Pure-insert markdown file. No code, no DB, no LLM, no imports. ~15 min — one file landing, one PR.

---

## Context (TL;DR)

Research Agent's 2026-04-21 ratified 2-file CHANDA split:
- `CHANDA.md` stays directional (missions, ownership, anti-goals).
- `CHANDA_enforcement.md` (NEW) holds operational enforcement: 11 KBL + 5 Surface invariants, 3 severity tiers, mechanical detectors, amendment log.

This brief creates **CHANDA_enforcement.md only**. The paired CHANDA.md rewrite is a separate brief (`CHANDA_PLAIN_ENGLISH_REWRITE_1`) and is NOT yours — do not touch CHANDA.md.

## Action (3 steps)

1. Read `briefs/BRIEF_CHANDA_ENFORCEMENT_1.md` end to end. Focus on §Implementation → Step 2 — the fenced ```markdown block there is the **verbatim, byte-perfect content** of the target file.

2. Create `/Users/dimitry/Vallen Dropbox/Dimitry vallen/Baker-Project/15_Baker_Master/01_build/CHANDA_enforcement.md` containing exactly that fenced block's content (including the H1 title `# CHANDA Enforcement — engineering matrix` at the top, no frontmatter).

3. Verify per §Verification (8 checks). Ship PR.

## Tests

N/A — markdown-only file, no test suite touched. Run `pytest tests/` once to confirm baseline unchanged: `16 failed / 818 passed / 21 skipped` (current main post PR #43 merge).

## Ship shape

- **PR title:** `CHANDA_ENFORCEMENT_1: create CHANDA_enforcement.md (invariant matrix + severity tiers)`
- **Branch:** `chanda-enforcement-1`
- **Files:** 1 new file — `15_Baker_Master/01_build/CHANDA_enforcement.md`. Nothing else.
- **Commit style:** match recent CHANDA commits (see `git log --grep="chanda"` — e.g. `a356e97 chanda(§3.9): clarify agent vs director writer distinction`). Suggested: `chanda(enforcement): create CHANDA_enforcement.md with invariant matrix + severity tiers`
- **Ship report:** `briefs/_reports/B1_chanda_enforcement_1_20260423.md`. Include:
  - `diff` or byte-count confirmation that file content matches brief's fenced block verbatim
  - Full 8-check Verification results (each check pass/fail with output snippet)
  - Full pytest tail (literal output, no "by inspection" — per `feedback_no_ship_by_inspection.md`)
- **Tier A auto-merge on B3 APPROVE.**

## Out of scope (explicit)

- **Do NOT touch `CHANDA.md`.** Paired rewrite is `CHANDA_PLAIN_ENGLISH_REWRITE_1`, not yours.
- **Do NOT create `invariant_checks/` directory or any detector scripts.** Follow-on briefs: `AUTHOR_DIRECTOR_GUARD_1`, `LEDGER_ATOMIC_1`, `MAC_MINI_WRITER_AUDIT_1`.
- **Do NOT add frontmatter** to the production file. Source artifact has frontmatter because it's a research-agent idea doc; production file does not carry it.
- **Do NOT add a §8 section** or anything beyond §7 amendment log. File ends at §7.
- **Do NOT edit CLAUDE.md, MEMORY.md, or any other file.**
- **Do NOT refactor `tasks/lessons.md` or any existing markdown.** Single-file insert only.

## Timebox

15 min. If it's taking longer than 30 min, you're doing the wrong thing — stop and report back.

**Working dir:** `~/bm-b1`.

---

**Dispatch timestamp:** 2026-04-23 (Team 1 first dispatch this session, post-reboot)
**Team:** Team 1 — Meta/Persistence (M0 quintet, brief 1 of 5)
