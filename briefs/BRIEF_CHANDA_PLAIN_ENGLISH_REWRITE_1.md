# BRIEF: CHANDA_PLAIN_ENGLISH_REWRITE_1 — rewrite CHANDA.md in plain English, 5 missions, 2-file split

## Context

Paired with `CHANDA_ENFORCEMENT_1` (shipped PR #45, `3b60b0d`). Ships the directional half of Research Agent's ratified 2026-04-21 2-file split: directional content stays in CHANDA.md (plain English, 5 missions, anti-goals); operational enforcement already lives in `CHANDA_enforcement.md`.

**Why rewrite:**
1. Pali terminology (Chanda, Vīmaṃsā, Iddhipāda, Viriya, Citta, ayoniso) — LLMs reason about it imprecisely; transliteration dilutes meaning at inference time.
2. Token cost — current CHANDA.md + engineering matrix would push every session past 3–4k tokens of mandatory constitutional reading regardless of agent role.
3. Invariants in CHANDA.md are now redundant — they live in `CHANDA_enforcement.md` with severity tiers + mechanical detectors.

**Source artifact (verbatim rewrite target):** `/Users/dimitry/baker-vault/_ops/ideas/2026-04-21-chanda-plain-english-rewrite.md` — Director ratified 2026-04-21 ("no need. proceed" + "yes" to 2-file split + implicit "yes" to anti-goals).

**Commit discipline:** This file is `author: director` (current + new frontmatter). CHANDA invariant #4 hook LIVE on Mac Mini baker-vault via PR #49. Baker-master doesn't have the hook installed YET (Director-local action) but **commit message MUST carry `Director-signed:` marker** as forward-compatible pattern — when belt-and-braces hook installs later, this commit should already conform.

## Estimated time: ~30–45 min
## Complexity: Low (pure replace — content verbatim from Research spec)
## Prerequisites: PR #45 (`CHANDA_enforcement.md` exists) — merged `3b60b0d` ✓.

---

## Fix/Feature 1: Replace CHANDA.md body with plain-English §1–§8 structure

### Problem

Current `CHANDA.md` (101 lines) carries:
- Pali terms in body + Section 4 ownership table
- 10 invariants in Section 3 (now duplicated in `CHANDA_enforcement.md` §4)
- No §8 pointer to enforcement file
- Missing anti-goals section (Director ratified 6 anti-goals 2026-04-21)

### Current State

- `/15_Baker_Master/01_build/CHANDA.md` exists, 101 lines, frontmatter timestamp `updated: 2026-04-19`.
- Frontmatter line 4: `author: director` (protected by CHANDA invariant #4 hook).
- `CHANDA_enforcement.md` lives in same directory, §4 holds the 11 KBL + 5 Surface invariants.
- Research Agent source spec at `_ops/ideas/2026-04-21-chanda-plain-english-rewrite.md` lines 44–121 carry the full §1–§8 body verbatim; lines 137–148 hold the new frontmatter block.

### Implementation

**Step 1 — Overwrite `/15_Baker_Master/01_build/CHANDA.md`** with exactly the content in the fenced block below. Preserve filename. No other files touched.

**Byte-perfect target content** (copy verbatim; contains both new frontmatter AND new §1–§8 body):

```markdown
---
title: CHANDA — Baker Mission & Ownership
voice: gold
author: director
created: 2026-04-18
updated: 2026-04-21
status: promoted
note: Directional document. Filename retained for compatibility;
      content in plain English to reduce LLM interpretation drift.
      Operational enforcement lives in CHANDA_enforcement.md.
---

# CHANDA — Baker Mission & Ownership

> Read this file in full before every brief and every coding session. It is the only file that defines *why* Baker exists. CLAUDE.md defines *what* Baker is right now. This file defines *what Baker must remain*.

---

## §1. Scope

This file governs the KBL subsystem and Baker surfaces (Scan, WhatsApp, Slack, Cockpit). External MCPs, plugins, and third-party skills are out of scope.

---

## §2. Mission

AI scans broadly across objects AND drills deeply into any single object. Director ratifies both. Baker's job is to produce scan-and-drill outputs the Director can trust enough to judge, and to turn judgment back into conditioning for the next run.

---

## §3. The Five Missions

**1. Preserve the self-learning loop.**
Every correction, promotion, or dismissal from the Director must be captured atomically in the feedback ledger and must condition the next pipeline run. The loop — Director judgment → ledger → next run → Director judgment again — is the system. If any leg breaks, Baker stops learning even while it keeps running.

**2. Four-factor ownership.**

| Factor | Owner | Scope |
|---|---|---|
| **Purpose** — *why we build* | Director | Direction and intent |
| **Execution** — *how we build* | AI / Code | Implementation, engineering |
| **State-awareness** — *what we know about the system* | AI / Code | Introspection, diagnostics |
| **Review** — *did what was built match the purpose* | Director | Ratification, audit |

Director owns the bookends. AI owns the middle. Without Director on both ends, AI optimizes for convenience and drifts from purpose.

**3. Depth over surface expansion.**
Baker grows by deepening judgment on existing matters, not by adding new sources, features, or user-facing surfaces. When torn between *deeper loop* and *wider scope*, depth wins.

**4. Learning lives in data, not prompts.**
The system gets smarter through rows added to the feedback ledger. Not through prompt edits, model fine-tuning, or pipeline code changes. Every learning signal is data — auditable, reversible, inspectable.

**5. Analytical depth is first-class.**
AI performs two kinds of work: **broad scans** across many objects, and **deep drills** into single objects (counterparty models, BATNA trees, pre-mortems, research syntheses, scenario maps). Drills produce framings and options the Director could not reach alone in available time. Director ratifies both scan and drill. AI is a thinking partner in depth work, not only a filter in breadth work.

---

## §4. Core Mechanism — The Learning Loop

```
Director judgment (Review)
   → captured as data (feedback ledger + Gold promotions)
   → read by every future pipeline run (Step 1)
   → shapes how Silver is compiled
   → presented to Director for judgment again
```

Three legs:
- **Leg 1 — Compounding:** Pipeline reads all Gold (by matter) before compiling Silver. No shortcuts.
- **Leg 2 — Capture:** Every Director action (promote, correct, ignore, respond/dismiss) writes to the feedback ledger atomically. Ledger write fails → Director action fails.
- **Leg 3 — Flow-forward:** Step 1 reads `hot.md` AND the feedback ledger on every pipeline run. Not one or the other. Not on schedule. Every run.

---

## §5. Anti-Goals — What Baker Must Never Become

1. **Not a data lake.** Storage serves judgment. Storage growth without judgment growth = drift.
2. **Not a latency-sensitive consumer product.** Baker optimizes conviction-per-decision, not response-time-per-query.
3. **Not a judgment replacer.** Never ratifies a matter without Director sign-off.
4. **Not a multi-user system.** Built for one Director's cognition.
5. **Not an autonomous actor.** Never acts on third parties without explicit Director authorization.
6. **Not a self-improving black box.** Learns through data; prompts and code remain human-authored.

---

## §6. Pre-Push Check

**Q1 — Loop Test (asked first):**
Does this change preserve all three legs of §4 (Compounding, Capture, Flow-forward)? Any change to the reading pattern (Leg 1), the ledger write mechanism (Leg 2), or the Step 1 integration (Leg 3) → stop, flag, wait for Director approval.

**Q2 — Wish Test:**
Does this serve the mission or engineering convenience? Convenience → stop, flag, wait. Both → state the tradeoff in the commit message.

---

## §7. Governance

Only the Director changes CHANDA.md. No agent, no automation, no Code session. When the mission evolves, the Director rewrites the affected section and updates the timestamp. An anti-goal or mission is removed only when genuinely wrong, not inconvenient. An amendment log is maintained in CHANDA_enforcement.md §7.

---

## §8. Operational Enforcement

Operational enforcement of these missions and ownership lives in **CHANDA_enforcement.md**. Agents whose actions can trigger an invariant — Code agents at commit time, runtime pipeline, surface handlers (Scan/WhatsApp/Slack) — must read that file at session start. Research-agents may skip it.

---

## Footnote

For the Abhidhamma-inspired framing that originally motivated these commitments, see CLAUDE.md §Philosophy. Filename retained for historical continuity; content re-stated in plain English to serve the file's actual reader — the Code agent.

---

**References:** KBL-1 through KBL-18 (Baker DB #11747–11844) · Related: CLAUDE.md (state), ~/baker-vault/ (the wiki), CHANDA_enforcement.md (operational enforcement), schema/ (prompts, Tier 3 only)
```

**That is the entire content of the file.** Do not add sections, do not alter headings, do not reword body text.

### Key Constraints

- **Pure replace.** Delete the old 101 lines; insert the content above. Net diff = ~90 removals + ~100 additions.
- **Frontmatter preserved on `author: director`** — required for CHANDA #4 hook enforcement. Do NOT change this line.
- **Frontmatter timestamp `updated: 2026-04-21`** matches Research Agent's ratification date. Do NOT bump to 2026-04-24 (today); the ratified-content date is what matters per CHANDA governance rules.
- **§7 Amendment log reference** — body text says "amendment log is maintained in CHANDA_enforcement.md §7" (was §6 in Research's artefact draft — shipped CHANDA_enforcement.md places the log at §7; verify by inspecting shipped file).
- **No §9 or beyond.** File ends at Footnote + References line.
- **No Pali words in body.** Spot-check: grep must return zero hits for `Chanda|Vīmaṃsā|Iddhipāda|Viriya|Citta|ayoniso|Pali` in the final CHANDA.md.
- **References line preserved** with update — add `CHANDA_enforcement.md` to the Related list (matches the shipped paired file).
- **Commit message MUST carry `Director-signed:` marker.** Example:
  ```
  chanda: plain-English rewrite + 5 missions + anti-goals + §8 pointer to enforcement

  Director-signed: "can we then switch to a normal language. So that the machine will
  understand that as you said, Buddhist terms are difficult... This file is for machine,
  not for me." + "yes" (2-file split) + "no need. proceed" (2026-04-21 ratification
  captured in baker-vault/_ops/ideas/2026-04-21-chanda-plain-english-rewrite.md)
  ```
  Quotes taken from Research Agent's handoff block (lines 180–184 of source artefact). When belt-and-braces hook lands on baker-master, this commit conforms.

### Verification

1. **File exists at exact path:**
   ```
   ls -la /Users/dimitry/Vallen\ Dropbox/Dimitry\ vallen/Baker-Project/15_Baker_Master/01_build/CHANDA.md
   ```

2. **Frontmatter preserved** — first line `---`, contains `title: CHANDA — Baker Mission & Ownership`, `author: director`, `updated: 2026-04-21`, `status: promoted`:
   ```bash
   head -12 CHANDA.md
   ```

3. **H1 on line 13 reads:** `# CHANDA — Baker Mission & Ownership`:
   ```bash
   grep -n "^# CHANDA" CHANDA.md | head
   ```

4. **8 section headings present:** `grep -c "^## §" CHANDA.md` → exactly **8** (§1 through §8).

5. **No Pali words anywhere:** `grep -iE "vimamsa|iddhipāda|iddhipada|viriya|citta|ayoniso|pali|chandra" CHANDA.md` → zero hits (note: "Chanda" in the title is OK — that's the filename reference; the body text must have no Pali).

   Stricter filter for body-only:
   ```bash
   sed -n '/^# CHANDA/,$p' CHANDA.md | grep -iE "vimamsa|iddhipāda|iddhipada|viriya|citta|ayoniso"
   ```
   Expected: zero matches.

6. **§5 Anti-Goals present with 6 numbered items:**
   ```bash
   sed -n '/^## §5/,/^## §6/p' CHANDA.md | grep -cE "^\*\*[0-9]+\."
   ```
   Expected: 6.

7. **§8 pointer to CHANDA_enforcement.md:**
   ```bash
   grep "CHANDA_enforcement.md" CHANDA.md
   ```
   Expected: ≥1 hit (body + References line).

8. **Line count** — expect ~110–130 lines (not rigid; structural checks above are authoritative).

9. **Only CHANDA.md modified:**
   ```bash
   git diff --name-only main...HEAD
   ```
   Expected: exactly `CHANDA.md`. Any other file = REDIRECT.

10. **Commit message carries marker:**
    ```bash
    git log -1 --format=%B | grep "^Director-signed:"
    ```
    Expected: ≥1 match.

---

## Files Modified

- `/15_Baker_Master/01_build/CHANDA.md` — pure replace (~90 deletions + ~100 additions).

## Do NOT Touch

- `CHANDA_enforcement.md` — paired file already shipped as PR #45. No edits.
- `CLAUDE.md` — §Philosophy section unchanged; footnote in new CHANDA.md points to it.
- `invariant_checks/author_director_guard.sh` — detector #4 script; unrelated.
- Any test file — this is a pure markdown rewrite; no test suite touched.

## Quality Checkpoints

Paste literal outputs in ship report:

1. **File structure:**
   ```
   head -12 CHANDA.md
   grep -c "^## §" CHANDA.md    # expect 8
   tail -3 CHANDA.md
   ```

2. **No Pali:**
   ```
   sed -n '/^# CHANDA/,$p' CHANDA.md | grep -iE "vimamsa|iddhipāda|iddhipada|viriya|citta|ayoniso" || echo "(none — expected)"
   ```

3. **Anti-goals count:**
   ```
   sed -n '/^## §5/,/^## §6/p' CHANDA.md | grep -cE "^\*\*[0-9]+\."    # expect 6
   ```

4. **Enforcement pointer:**
   ```
   grep "CHANDA_enforcement.md" CHANDA.md    # expect >=1
   ```

5. **Scope:**
   ```
   git diff --name-only main...HEAD    # expect exactly CHANDA.md
   ```

6. **Commit marker:**
   ```
   git log -1 --format=%B | grep "^Director-signed:"    # expect >=1 match
   ```

7. **Full-suite regression sanity:**
   ```
   pytest tests/ 2>&1 | tail -3    # markdown-only; expect baseline unchanged
   ```

## Verification SQL

N/A — no DB changes.

## Rollback

`git revert <merge-sha>` — single-file, single-PR, clean revert.

---

## Ship shape

- **PR title:** `CHANDA_PLAIN_ENGLISH_REWRITE_1: rewrite CHANDA.md per 2026-04-21 ratification (5 missions + anti-goals + §8 pointer)`
- **Branch:** `chanda-plain-english-rewrite-1`
- **Files:** 1 (CHANDA.md pure replace).
- **Commit style:** `chanda: plain-English rewrite + 5 missions + anti-goals + §8 pointer to enforcement`
- **Ship report:** `briefs/_reports/B5_chanda_plain_english_rewrite_1_20260424.md`. Include all 7 Quality Checkpoint outputs + pytest-tail baseline line + `git diff --stat`.

**Tier A auto-merge on B3 APPROVE** (standing per charter §3). Belt-and-braces install of baker-master pre-commit hook remains deferred to Director-local action.

## Out of scope (explicit)

- **Do NOT** modify `CHANDA_enforcement.md` (separate shipped file).
- **Do NOT** touch `CLAUDE.md`.
- **Do NOT** change the Pali reference in the title ("CHANDA") — filename + title retained per Research spec.
- **Do NOT** bump `updated:` frontmatter to 2026-04-24; content reflects the 2026-04-21 ratification.
- **Do NOT** add a §9 or additional sections beyond what's in the verbatim block above.
- **Do NOT** file CHANDA_enforcement.md §7 amendment-log entry in this brief — if Director wants one, it's a separate 1-line tweak like `AUTHOR_DIRECTOR_GUARD_1` did.

## Timebox

**30–45 min.** If >1h, stop and report — pure replace should be fast.

**Working dir:** `~/bm-b5` (Team 1 fresh clone; first-ship dispatch).
