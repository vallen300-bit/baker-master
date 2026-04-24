# Code Brisen #5 — Pending Task

**From:** AI Head (Team 1 — Meta/Persistence)
**To:** Code Brisen #5 (idle; first-ship dispatch)
**Task posted:** 2026-04-24
**Status:** OPEN — `CHANDA_PLAIN_ENGLISH_REWRITE_1` (paired with shipped CHANDA_ENFORCEMENT_1)

**First actual ship for b5.** Prior CODE_5_PENDING.md was created + removed 2026-04-23 when GUARD_1 was routed to b1 instead. Fresh dispatch here.

Parallel tasks in flight: B1 on `PROMPT_CACHE_AUDIT_1` (M0 row 4), B3 on `CITATIONS_API_SCAN_1` (M0 row 5). Your task is independent, no file overlap, no coordination needed.

---

## Brief-route note (charter §6A)

Full `/write-brief` 6-step protocol. Brief at `briefs/BRIEF_CHANDA_PLAIN_ENGLISH_REWRITE_1.md`.

Pure-replace of `CHANDA.md` per Research Agent's 2026-04-21 ratified artefact. Verbatim content ready — all body text in the brief's fenced block. ~30–45 min. One file, one PR.

---

## Context (TL;DR)

`CHANDA.md` is read by every agent at session start. Current version has:
- Pali terms (Chanda, Vīmaṃsā, Iddhipāda, Viriya, Citta, ayoniso) — LLMs reason imprecisely on these.
- 10 invariants duplicated in `CHANDA_enforcement.md` (which already shipped PR #45).
- No pointer to the enforcement file.

Director ratified 2026-04-21: plain English + 5 missions + anti-goals + §8 pointer + 2-file split. Content is ready verbatim in the brief.

## Action (3 steps)

1. Read `briefs/BRIEF_CHANDA_PLAIN_ENGLISH_REWRITE_1.md` end to end. Focus on §Implementation → Step 1 — the fenced ```markdown block is the **byte-perfect content** of the target file (including new frontmatter).

2. Overwrite `/Users/dimitry/Vallen Dropbox/Dimitry vallen/Baker-Project/15_Baker_Master/01_build/CHANDA.md` with exactly that fenced block's content.

3. Verify per brief §Quality Checkpoints (7 checks). Ship PR.

## Commit discipline (MANDATORY)

Commit message MUST carry a `Director-signed:` marker. Use this pattern (adapt slightly if you prefer):

```
chanda: plain-English rewrite + 5 missions + anti-goals + §8 pointer to enforcement

Director-signed: "can we then switch to a normal language. So that the machine will
understand that as you said, Buddhist terms are difficult... This file is for machine,
not for me." + "yes" (2-file split) + "no need. proceed" (2026-04-21 ratification
captured in baker-vault/_ops/ideas/2026-04-21-chanda-plain-english-rewrite.md)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

Why: `CHANDA.md` frontmatter carries `author: director`. CHANDA invariant #4 hook LIVE on Mac Mini baker-vault; baker-master hook deferred to Director-local install. Forward-compatibility: when belt-and-braces hook lands on baker-master, this commit already conforms.

## Ship gate (literal output required in ship report)

```
head -12 CHANDA.md
grep -c "^## §" CHANDA.md                                              # expect 8
tail -3 CHANDA.md
sed -n '/^# CHANDA/,$p' CHANDA.md | grep -iE "vimamsa|iddhipāda|iddhipada|viriya|citta|ayoniso" || echo "(no Pali — expected)"
sed -n '/^## §5/,/^## §6/p' CHANDA.md | grep -cE "^\*\*[0-9]+\."       # expect 6 anti-goals
grep "CHANDA_enforcement.md" CHANDA.md                                 # expect >=1
git diff --name-only main...HEAD                                       # exactly CHANDA.md
git log -1 --format=%B | grep "^Director-signed:"                      # >=1 match
pytest tests/ 2>&1 | tail -3                                           # baseline unchanged
```

**No "pass by inspection"** (per `feedback_no_ship_by_inspection.md`).

## Ship shape

- **PR title:** `CHANDA_PLAIN_ENGLISH_REWRITE_1: rewrite CHANDA.md per 2026-04-21 ratification (5 missions + anti-goals + §8 pointer)`
- **Branch:** `chanda-plain-english-rewrite-1`
- **Files:** 1 (`CHANDA.md` pure replace).
- **Commit style:** see Commit discipline above — MUST include `Director-signed:` marker.
- **Ship report:** `briefs/_reports/B5_chanda_plain_english_rewrite_1_20260424.md`. Include all 7 Quality Checkpoint outputs + baseline pytest tail + `git diff --stat`.

**Tier A auto-merge on B3 APPROVE** (standing per charter §3).

## Out of scope (explicit)

- **Do NOT** touch `CHANDA_enforcement.md` (shipped separately).
- **Do NOT** touch `CLAUDE.md` (its §Philosophy is the footnote anchor, unchanged).
- **Do NOT** add a §9 or any section beyond Footnote + References.
- **Do NOT** change the title's "CHANDA" reference (filename + title retained per Research).
- **Do NOT** bump `updated:` frontmatter to today (2026-04-24); Research ratification date (2026-04-21) is the content-accurate timestamp.
- **Do NOT** reword body text or convert more Pali — the fenced block is the final plain-English rendering.
- **Do NOT** add or remove any file under `tests/`, `scripts/`, `memory/`, or `_ops/`.

## Timebox

**30–45 min.** If >1h, stop and report — pure replace should be fast.

**Working dir:** `~/bm-b5`.

---

**Dispatch timestamp:** 2026-04-24 (Team 1, paired closure of CHANDA 2-file split — ENFORCEMENT shipped PR #45, REWRITE ships next)
**Team:** Team 1 — Meta/Persistence
**Parallel:** B1 on PROMPT_CACHE_AUDIT_1 (M0 row 4), B3 on CITATIONS_API_SCAN_1 (M0 row 5). Independent scope; no coordination needed.
