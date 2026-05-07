# BRIEF: BEN_CROSS_MATTER_GOLD_WRITE_1 — BEN earns conditional Tier-B GOLD-write on Director ratification

## Context

Director ratified 2026-05-06 PM (relayed via AH2-T): BEN earns write access to cross-matter Cortex GOLD upon Director ratification. Justification: BEN carries depth other Desks lack today (2,200-page NotebookLM-curated German RE-finance library; today's session reports were excellent). Pattern is **prototype**: each Desk/agent later gets equivalent gated GOLD-write scoped to its domain (russo-at = Austrian law, russo-de = German law, russo-ch = Swiss law, AO/MOVIE/Hagenauer Desks = matter-specific). BEN ships first; others follow per Desk-domain depth.

**Charter §4 capability change** (Cortex Design prerogative — Director-ratified; not auto-resolvable). Design Q's a-d ratified by Director 2026-05-07 ~07:55Z:
- (a) Scope-guard: **frontmatter `domain:` tag per H2 entry**
- (b) Write target: **`wiki/_cortex/director-gold-global.md` only for V1**; per-matter `wiki/matters/<slug>/gold.md` deferred to Phase B follow-on (mrci/lilienmatt/annaberg lack canonical gold.md today; only `proposed-gold.md` staging exists — adding 3 new files concurrently with capability = larger blast radius)
- (c) Ratification trigger phrase: **`"ratified — promote to GOLD"` + artefact path**
- (d) Sequencing: **BEN brief ships first**; researcher library-build for russo-* / matter Desks runs as separate parallel dispatch

## Estimated time: ~3-4h
## Complexity: Medium (capability-extension; touches CONTRACT.md + authority-boundary-table.md + skill flow + audit infra)
## Prerequisites: none (all referenced files exist + verified)

---

## Fix 1: Frontmatter `domain:` schema in `wiki/_cortex/director-gold-global.md`

### Problem
Today every entry is cross-cutting (no scope-guard). BEN must only write entries tagged to its domain (`bb-finance`); other Desks' future writes scoped likewise.

### Current State
`wiki/_cortex/director-gold-global.md` has document-level frontmatter (`type: gold`, `scope: global`, `authority: director (writes); ...`); per-entry H2 sections have no scope tags.

### Implementation

Add to the document-level header (after `## Schema` if exists, else after the existing intro paragraph):

```markdown
## Entry frontmatter — domain scoping (added 2026-05-07 per BRIEF_BEN_CROSS_MATTER_GOLD_WRITE_1)

Every `## H2` entry MUST carry one of:
- `domain: cross-cutting` — Director-only writes (default; no agent may auto-promote)
- `domain: bb-finance` — BEN may auto-promote on Director phrase
- `domain: russo-at` / `russo-de` / `russo-ch` — reserved (Phase B per-Desk activations)
- `domain: ao` / `movie` / `hagenauer` — reserved (Phase B per-matter Desk activations)

Format: H2 entry header is followed by a blank line, then a fenced HTML comment carrying the tag:
```
## YYYY-MM-DD — topic
<!-- domain: bb-finance -->

<entry body>
```

Agents enforce tag presence + domain match via pre-commit hook (`scripts/check_gold_domain_tags.py` — added by this brief). Director's manual edits bypass the hook (DV-only initials in commit message exempts).
```

### Verification
- Pre-commit hook fires on every `wiki/_cortex/director-gold-global.md` write; rejects entries without `<!-- domain: ... -->` line within 3 lines of H2 header.
- Test: BEN attempts write of entry tagged `domain: bb-finance` → hook PASS; BEN attempts write tagged `domain: ao` → hook FAIL (BEN not authorized for `ao`); Director write with bare H2 (no tag) → hook FAIL (forces tag; even Director must declare scope).

---

## Fix 2: Scope-guard implementation — `scripts/check_gold_domain_tags.py`

### Problem
Need a deterministic pre-commit gate: BEN's commit may only contain entries with `domain: bb-finance` tag. Any entry tagged for other domains in the same commit = REJECT.

### Implementation

Create new file `scripts/check_gold_domain_tags.py`:

```python
#!/usr/bin/env python3
"""Pre-commit gate for wiki/_cortex/director-gold-global.md writes.

Enforces:
1. Every NEW or MODIFIED H2 entry carries `<!-- domain: <tag> -->` within 3 lines of header.
2. The committing author (from --author flag or git config) is authorized for that domain.

Domain authority matrix (locked in this script, not config — domain assignment is a
capability change requiring its own brief):
    cross-cutting → director only
    bb-finance    → ben (bb-finance agent commits) + director
    russo-at|de|ch, ao, movie, hagenauer → reserved (no agent yet); director only

Usage (called by pre-commit hook):
    python3 scripts/check_gold_domain_tags.py --author "$(git config user.name)" --staged
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path


_AUTHORITY = {
    "cross-cutting": {"director", "Dimitry Vallen"},
    "bb-finance":    {"director", "Dimitry Vallen", "BEN", "bb-finance"},
    "russo-at":      {"director", "Dimitry Vallen"},
    "russo-de":      {"director", "Dimitry Vallen"},
    "russo-ch":      {"director", "Dimitry Vallen"},
    "ao":            {"director", "Dimitry Vallen"},
    "movie":         {"director", "Dimitry Vallen"},
    "hagenauer":     {"director", "Dimitry Vallen"},
}

_TARGET = "wiki/_cortex/director-gold-global.md"
_H2_RE = re.compile(r"^## \d{4}-\d{2}-\d{2}")
_DOMAIN_RE = re.compile(r"<!--\s*domain:\s*([\w-]+)\s*-->")


def _staged_diff() -> str:
    out = subprocess.run(
        ["git", "diff", "--cached", "--unified=10", "--", _TARGET],
        capture_output=True, text=True, check=False,
    )
    return out.stdout


def _check(diff: str, author: str) -> list[str]:
    """Return list of error strings; empty list = PASS."""
    errors: list[str] = []
    in_added = False
    pending_h2 = None
    pending_h2_lineno = 0
    line_after_h2 = 0

    for raw in diff.splitlines():
        if raw.startswith("+## ") and _H2_RE.match(raw[1:]):
            pending_h2 = raw[1:].strip()
            pending_h2_lineno = 0
            line_after_h2 = 0
            in_added = True
            continue
        if pending_h2 and raw.startswith("+"):
            line_after_h2 += 1
            m = _DOMAIN_RE.search(raw)
            if m:
                domain = m.group(1).strip()
                allowed = _AUTHORITY.get(domain, set())
                if author not in allowed and not any(a in author for a in allowed):
                    errors.append(
                        f"REJECT: entry '{pending_h2}' tagged domain={domain} but "
                        f"author={author!r} not in {sorted(allowed)}"
                    )
                pending_h2 = None
            elif line_after_h2 > 3:
                errors.append(
                    f"REJECT: entry '{pending_h2}' has no `<!-- domain: ... -->` tag "
                    f"within 3 lines of H2 header"
                )
                pending_h2 = None

    return errors


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--author", required=True)
    p.add_argument("--staged", action="store_true")
    args = p.parse_args()

    if not args.staged:
        print("only --staged mode supported in V1", file=sys.stderr)
        return 2

    diff = _staged_diff()
    if not diff:
        return 0  # nothing staged for this file

    errors = _check(diff, args.author)
    if errors:
        for e in errors:
            print(e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Wire to `.git/hooks/pre-commit` (existing hook script — append; do not overwrite):

```bash
# BEN GOLD-write scope-guard (BRIEF_BEN_CROSS_MATTER_GOLD_WRITE_1)
if git diff --cached --name-only | grep -q "^wiki/_cortex/director-gold-global\.md$"; then
    python3 scripts/check_gold_domain_tags.py --author "$(git config user.name)" --staged || exit 1
fi
```

### Verification
1. `pytest tests/test_check_gold_domain_tags.py` GREEN with literal output (test cases: missing tag, wrong domain, correct domain match, multi-entry mixed-domain commit, Director bypass, etc.)
2. Manual: BEN drafts a commit adding entry with `domain: bb-finance` tag → pre-commit PASS; BEN drafts commit adding entry tagged `domain: ao` → pre-commit FAIL with REJECT message

---

## Fix 3: Ratification trigger phrase parser — BEN side

### Problem
BEN must detect Director's `"ratified — promote to GOLD"` phrase + artefact path in chat, then enter the GOLD-promotion workflow.

### Implementation

Add to `~/.claude/skills/bb-finance/SKILL.md` under a new `## §5. GOLD-Write Capability (Tier-B conditional)` section:

```markdown
## §5. GOLD-Write Capability (Tier-B conditional)

**Activation:** Director ratifies a Layer 3 (proposed-reports) artefact with the EXACT phrase:

```
ratified — promote to GOLD: <artefact-path>
```

(em-dash `—` not hyphen `-`; phrase is load-bearing — bare "ratified" does NOT trigger.)

**Flow on detection:**

1. **Read** the ratified artefact at `<artefact-path>` (must exist; if not, surface error to Director).
2. **Draft** a proposed GOLD entry following Hybrid C schema (`## YYYY-MM-DD — topic`, ratification quote, resolution; DV initials).
3. **Tag** the entry with `<!-- domain: bb-finance -->` immediately after the H2 header.
4. **Surface** the diff to Director inline (full proposed entry text) before any write. Director either:
   - ratifies the diff (typed `ok` / `commit` / `approved`) → BEN proceeds to step 5
   - rejects (`no` / `revise: ...`) → BEN re-drafts and re-surfaces, OR aborts
5. **Commit** with message format:
   ```
   gold(bb-finance): promote <topic-slug> from <artefact-path>

   Source artefact: <artefact-path>
   Director ratification: <verbatim DV phrase>
   GOLD entry: see wiki/_cortex/director-gold-global.md
   Audit log: see wiki/_cortex/gold-promotions.md

   Co-Authored-By: BEN <bb-finance@brisengroup.com>
   ```
6. **Append** audit row to `wiki/_cortex/gold-promotions.md` (new file — Fix 4).
7. **Surface** ship confirmation to Director with revert command:
   ```
   GOLD promotion shipped: <commit-sha>. Single-command revert: git revert <commit-sha>
   ```

**Refuse-conditions:**
- Phrase missing the `— promote to GOLD` suffix → reply "Detected ratify, but missing GOLD-promotion phrase. Add `— promote to GOLD: <path>` to trigger."
- Artefact-path doesn't exist or unreadable → reply with error
- Artefact not tagged for `bb-finance` domain (if/when Layer 3 artefacts gain domain tags) → reply with refusal + suggest other Desk
- Pre-commit hook FAILS → surface hook error to Director, abort commit
```

### Verification
- Test: Director types `"ratified — promote to GOLD: wiki/_finance/baden-baden/proposed-reports/2026-05-06-aukera-fa-review-pull-list.md"` → BEN reads file + drafts diff + surfaces to Director.
- Test: Director types bare `"ratified"` (no GOLD suffix) → BEN does NOT enter promotion workflow.
- Test: Director ratifies non-existent path → BEN replies with error.

---

## Fix 4: New audit log `wiki/_cortex/gold-promotions.md`

### Implementation

Create `wiki/_cortex/gold-promotions.md`:

```markdown
---
title: GOLD Promotions Log
type: audit
authority: append-only by domain agents (BEN: bb-finance; reserved for other Desks)
schema_anchor: BRIEF_BEN_CROSS_MATTER_GOLD_WRITE_1
ignore_by_pipeline: false
---

# GOLD Promotions Log

Append-only. Every entry promoted to `wiki/_cortex/director-gold-global.md` (or per-matter `wiki/matters/<slug>/gold.md` once Phase B activates) gets one row here.

Format:

```
## <ISO-timestamp>
- **Domain:** <domain-tag>
- **Promoter:** <agent-slug or director>
- **Source artefact:** <path>
- **Director ratification:** <verbatim phrase>
- **Target file:** wiki/_cortex/director-gold-global.md
- **Entry header:** ## YYYY-MM-DD — topic
- **Commit SHA:** <short-sha>
- **Revert command:** `git revert <short-sha>`
```

Tail latest 20 entries are displayed in BEN's session-start checklist for quick rollback access.
```

### Verification
- BEN's first GOLD promotion appends correctly formatted row
- `tail -20` of file is parseable + displayable in session-start

---

## Fix 5: BEN CONTRACT.md amendments

### Problem
CONTRACT.md §3.2 today says "Tier C blanket — never". Need carve-out for `bb-finance`-domain GOLD writes.

### Implementation

In `_ops/agents/bb-finance/CONTRACT.md`, find the section with the Tier-C blanket statement (currently row in §3 "What BEN does NOT do") and amend:

```markdown
### 3.2 What BEN does NOT do (Tier C blanket — already ratified)

**EXCEPTION (added 2026-05-07 per BRIEF_BEN_CROSS_MATTER_GOLD_WRITE_1):** BEN may write to `wiki/_cortex/director-gold-global.md` ONLY when:
1. Director's chat-message contains the exact phrase `ratified — promote to GOLD: <artefact-path>`, AND
2. The proposed entry is tagged `<!-- domain: bb-finance -->`, AND
3. Director ratifies the inline diff before commit, AND
4. Pre-commit hook (`scripts/check_gold_domain_tags.py`) PASSES.

This is conditional Tier-B. Failure of any of the four gates above = Tier-C refusal applies.

(All other Tier-C prohibitions in §3.2 remain unchanged.)
```

Update CONTRACT.md frontmatter `last_updated:` and append entry to its changelog if any.

### Verification
- BEN reads updated CONTRACT.md on session-start; recognizes the conditional exception
- Director can verify CONTRACT.md state by reading the file directly

---

## Fix 6: authority-boundary-table.md row revision

### Implementation

In `wiki/_finance/baden-baden/authority-boundary-table.md`, find the row covering "GOLD-write" or equivalent (per AH2-T's reference to "row 5 / wherever GOLD-write sits"). Revise its tier from Tier C to:

```markdown
| Conditional Tier B (was Tier C) — bb-finance-domain GOLD writes only | Director ratification phrase + diff preview + scope-guard hook | conditional gate |
```

Update file's frontmatter `last_updated:` to 2026-05-07 + add brief changelog entry pointing to this brief.

### Verification
- Director reviews authority-boundary-table.md before merging this brief; confirms row revision matches intent
- BEN reads authority-boundary-table.md on session-start; recognizes new conditional Tier-B

---

## Fix 7: Single-command revert path in BEN session-start

### Implementation

Add to `_ops/agents/bb-finance/OPERATING.md` (or BEN's SKILL.md session-start checklist):

```markdown
## §X. GOLD-promotion revert path

On session-start, BEN reads tail of `wiki/_cortex/gold-promotions.md` (latest 20 entries). For any entry within the last 7 days, BEN surfaces to Director (only if Director asks "show me recent GOLD promotions"):

> Recent GOLD promotions (last 7d):
> - <date> — <domain> — <topic> (commit <sha>)
> - ...
> Revert any with: `git revert <sha>`
```

(No auto-display — Director-on-demand to avoid session-start noise.)

---

## Fix 8: Tests

Create `tests/test_check_gold_domain_tags.py` covering:
1. Entry with correct `domain: bb-finance` tag + author `BEN` → PASS
2. Entry with wrong `domain: ao` tag + author `BEN` → FAIL with REJECT message
3. Entry with NO `<!-- domain -->` tag within 3 lines → FAIL with no-tag message
4. Multi-entry commit: one tagged correctly, one tagged wrong → FAIL on the wrong one
5. Director author + `domain: cross-cutting` → PASS
6. Director author + bare H2 (no tag) → FAIL (even Director must declare scope)
7. Diff with no changes to target file → PASS (early return)

---

## Files Modified
- `wiki/_cortex/director-gold-global.md` — add domain-scoping schema doc
- NEW: `wiki/_cortex/gold-promotions.md` — audit log
- NEW: `scripts/check_gold_domain_tags.py` — pre-commit gate
- NEW: `tests/test_check_gold_domain_tags.py` — gate tests
- `.git/hooks/pre-commit` — wire the gate (one-line append, idempotent grep-guarded)
- `~/.claude/skills/bb-finance/SKILL.md` — new §5 GOLD-Write Capability section
- `_ops/agents/bb-finance/CONTRACT.md` — §3.2 carve-out
- `wiki/_finance/baden-baden/authority-boundary-table.md` — row revision
- `_ops/agents/bb-finance/OPERATING.md` — §X revert-path session-start clause

## Do NOT Touch
- Other Desks' SKILL.md (russo-at / russo-de / russo-ch / AO / MOVIE / Hagenauer Desks) — Phase B follow-on per Desk
- Researcher's library-build track for other Desks — Director will dispatch separately
- BEN Phase 4 sentinels (BEN's own roadmap; capability addition ≠ Phase 4)
- Per-matter `wiki/matters/<slug>/gold.md` for mrci/lilienmatt/annaberg — Phase B follow-on once cross-matter pattern proves out (Q (b) ratified V1=cross-matter only)

## Quality Checkpoints
1. `pytest tests/test_check_gold_domain_tags.py -v` GREEN with literal output (NOT "by inspection")
2. Existing pytest suite GREEN (no regression)
3. Pre-commit hook fires on `wiki/_cortex/director-gold-global.md` writes ONLY (other files pass-through unchanged)
4. Test: BEN attempts a commit with `domain: ao` tag → hook FAILS with REJECT message
5. Test: BEN's first GOLD promotion produces correctly formatted row in `gold-promotions.md`
6. CONTRACT.md + authority-boundary-table.md frontmatter `last_updated:` reflect 2026-05-07
7. SKILL.md §5 readable + parseable by BEN on session-start

## Verification SQL
N/A (file-system + git operations only; no PG schema touched)

## §"Pattern generalisation" appendix — russo-de slot-in worked example

Once russo-de Desk activates (separate brief, Phase B):

1. Add `russo-de` to `_AUTHORITY` map in `scripts/check_gold_domain_tags.py`:
   ```python
   "russo-de": {"director", "Dimitry Vallen", "russo-de"},
   ```
2. Russo-de Desk's SKILL.md adds equivalent §5 GOLD-Write Capability section, scoped to `<!-- domain: russo-de -->`
3. Russo-de Desk's CONTRACT.md gets equivalent §3.2 carve-out
4. Russo-de Desk's authority-boundary-table row gets equivalent Tier-B conditional revision

NO changes needed to: gold-promotions.md (schema-agnostic), pre-commit hook wiring, target file frontmatter (already supports arbitrary domain values).

**Pattern proves out:** ~6 lines of code change in the pre-commit gate + ~3 file edits in the new Desk's own files = full activation. No core schema redesign, no GOLD-target file restructure, no audit-log changes. Confirms the per-Desk slot-in is concrete + cheap.

Same pattern applies to russo-at, russo-ch, AO Desk, MOVIE Desk, Hagenauer Desk. Per-matter `wiki/matters/<slug>/gold.md` writes (Phase B) require an additional code path in the pre-commit gate to ALSO check those files — but the schema design is unchanged.

## Gates
- `feature-dev:code-reviewer` (Gate 1 + 4 — AH1-App spawns; logic + edge cases on regex parsing + git diff handling + author-authorization map)
- `/security-review` (Gate 2 — AH2 or AH1-App; new pre-commit hook touches author-string from git config; verify no shell injection in subprocess args)
- `code-architecture-reviewer` (Gate 3 — AH1-T spawns picker-architect; reviews capability-extension architecture, scope-guard mechanism, pattern-generalisation soundness)

## Ship Target
- PR with all gates passing
- Ship report at `briefs/_reports/<bN>_ben_cross_matter_gold_write_1_<date>.md`
- Pre-commit hook activated on baker-vault repo (where target files live) — verify hook fires before declaring ship
- BEN performs first live GOLD promotion against one of the 6 staged Layer 3 reports (Director-curated test set per V2 addendum) AFTER merge — that's the burn-in proof

## Caller / Provenance
- AH2-T re-emit 2026-05-07 ~07:53Z (re-relayed after prior session API-terminated; primary dispatch + V2 addendum from chat-history context, persisted to bm-aihead2/memory/ben_gold_write_brief_paste_blocks.md)
- AH1-App authored brief 2026-05-07 ~07:55Z via `/write-brief` skill (Step 1 EXPLORE verified BEN files + GOLD targets + 6 staged reports + charter §4; Step 2 PLAN ratified by Director with Q's a-d; Step 3 WRITE 2026-05-07 ~08:00Z)
- AH1-T cross-recommendations on Q's a-d reconciled (msg #22 to /msg/cowork-ah1) — divergence on Q (b) resolved in AH1-T's favor (cross-matter only V1; per-matter Phase B)
- Director ratifications:
  - 2026-05-06 PM (capability ratification): "BEN earns write access to cross-matter Cortex GOLD upon Director ratification" (relayed via AH2-T)
  - 2026-05-07 ~07:55Z (Q's a-d): "follow your recoms" → (a) A1 frontmatter + (b) B2 cross-matter only V1 + (c) C1 phrase + (d) D1 BEN first

## PL ship-report
End your chat ship report with the fenced PL paste-block per `_ops/skills/ai-head/SKILL.md` §"PL ship-report contract".
