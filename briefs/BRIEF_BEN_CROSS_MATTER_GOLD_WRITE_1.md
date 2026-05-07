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

Agents enforce tag presence + domain match via pre-commit hook (`scripts/check_gold_domain_tags.py` — added by this brief). **Director bypass** (V0.2): commit author email matches `_DIRECTOR_EMAILS` allowlist (`dvallen@brisengroup.com`, `vallen300@gmail.com`). NOT bypassable via "DV" initials in commit message — that text is unverifiable (Gate 3 IMP 8).
```

### Verification
- Pre-commit hook fires on every `wiki/_cortex/director-gold-global.md` write; rejects entries without `<!-- domain: ... -->` line within 3 lines of H2 header.
- Test: BEN attempts write of entry tagged `domain: bb-finance` → hook PASS; BEN attempts write tagged `domain: ao` → hook FAIL (BEN not authorized for `ao`); Director write with bare H2 (no tag) → hook FAIL (forces tag; even Director must declare scope).

---

## Fix 2: Scope-guard implementation — `scripts/check_gold_domain_tags.py` (V0.2 hardened)

### Problem
Need a deterministic pre-commit gate. **V0.2 fold** (Gate 3 CRIT 1 + 3 + IMP 5 + 8 addressed):
- Diff-only inspection misses MODIFICATIONS to existing entries (CRIT 1)
- Substring author-match leaks scope (CRIT 3 — "directory-bot" matches "director")
- Audit log append-only must be enforced, not just documented (IMP 5)
- "DV initials in commit msg" bypass is brittle — anyone can type DV (IMP 8)

### Implementation (V0.2)

Create new file `scripts/check_gold_domain_tags.py`:

```python
#!/usr/bin/env python3
"""Pre-commit gate for wiki/_cortex/director-gold-global.md + gold-promotions.md writes.

Two enforcement modes:
1. director-gold-global.md — every CHANGED H2 entry must carry `<!-- domain: <tag> -->`
   within 3 lines of header; author email must be authorized for that domain. Inspection
   uses POST-COMMIT file state (not just diff) so modifications/deletions to existing
   entries are validated against their domain authority.
2. gold-promotions.md — append-only enforced: any modification removing or altering
   existing lines is REJECTED. Only pure additions at end-of-file pass.

Director bypass: commit author email matches `_DIRECTOR_EMAILS` allowlist → both checks
skipped (Director may write any domain entry, may rewrite audit log if needed).
NOT bypassable via "DV" in commit message — that text is unverifiable.

Usage (called from .git/hooks/pre-commit):
    python3 scripts/check_gold_domain_tags.py --staged
"""
from __future__ import annotations

import re
import subprocess
import sys
import unicodedata
from pathlib import Path


# Author allowlist by email. Domain assignment is itself a capability change requiring
# its own brief — adding a Desk to this map = brief amendment.
_AUTHORITY_BY_EMAIL: dict[str, set[str]] = {
    "cross-cutting": set(),  # Director-only via _DIRECTOR_EMAILS bypass
    "bb-finance":    {"bb-finance@brisengroup.com", "ben@brisengroup.com"},
    "russo-at":      set(),  # reserved
    "russo-de":      set(),  # reserved
    "russo-ch":      set(),
    "ao":            set(),
    "movie":         set(),
    "hagenauer":     set(),
}

_DIRECTOR_EMAILS: set[str] = {"dvallen@brisengroup.com", "vallen300@gmail.com"}

_GOLD_TARGET = "wiki/_cortex/director-gold-global.md"
_AUDIT_LOG = "wiki/_cortex/gold-promotions.md"

_H2_RE = re.compile(r"^## \d{4}-\d{2}-\d{2}\b")
# V0.3 fix C2: scope-guard intentionally only inspects DATE-format H2s (Gold entries).
# Non-date H2s (e.g., "## Schema", "## Entry frontmatter — domain scoping", structural
# document sections) are NOT scope-guarded — they are document-level prose that
# Director-only writes by convention. The brief's Fix 1 explicitly establishes this:
# Gold ENTRIES use `## YYYY-MM-DD — topic` format; structural sections use other H2s
# and don't carry domain tags. Author authority on structural sections is enforced
# by Inv 9 (single AGENT writer = Mac Mini); BEN cannot modify the file outside
# its own promotion flow per skill discipline. If a future Desk needs to scope-guard
# non-date sections, broaden _H2_RE to `^##\s+` and require ALL H2 sections to carry
# a domain tag (with a reserved `domain: structural` for document-level sections).
_DOMAIN_RE = re.compile(r"<!--\s*domain:\s*([\w-]+)\s*-->")


def _git(*args: str) -> str:
    out = subprocess.run(["git", *args], capture_output=True, text=True, check=False)
    return out.stdout


def _author_email() -> str:
    """Read the author email git will use for the impending commit. Lowercased + stripped."""
    return _git("config", "user.email").strip().lower()


def _staged_files() -> list[str]:
    return [ln for ln in _git("diff", "--cached", "--name-only").splitlines() if ln]


def _staged_file_content(path: str) -> str:
    """Returns POST-COMMIT file content (i.e., index version, what will land if commit lands)."""
    return _git("show", f":{path}")


def _staged_diff(path: str) -> str:
    return _git("diff", "--cached", "--unified=0", "--", path)


# --- gold-target enforcement (CRIT 1: post-commit state parse) ---


def _parse_h2_to_domain(text: str) -> dict[str, str]:
    """Build {h2_header_line: domain_tag} from full file content.

    H2 line is matched as `## YYYY-MM-DD ...`. Domain tag must appear within the next
    ~5 non-empty lines (tolerant: 3 lines per spec + slack for blank lines).
    Entries without tag map to empty string (will fail enforcement).
    """
    result: dict[str, str] = {}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        if _H2_RE.match(lines[i]):
            h2 = lines[i].rstrip()
            # scan up to 5 following lines
            domain = ""
            for j in range(i + 1, min(i + 6, len(lines))):
                m = _DOMAIN_RE.search(lines[j])
                if m:
                    domain = m.group(1).strip()
                    break
            result[h2] = domain
        i += 1
    return result


def _changed_h2s_from_diff(diff: str) -> set[str]:
    """Map each diff hunk to its enclosing H2 header.

    Strategy: walk the diff line-by-line, tracking the current H2 (last seen header in
    pre-image OR post-image). Any added or removed line = its enclosing H2 is "changed".
    NEW entries (added with `+## YYYY-MM-DD ...`) are caught naturally because the H2
    line itself is a `+` line — it sets `current` AND counts as a change.
    """
    changed: set[str] = set()
    current: str | None = None
    for raw in diff.splitlines():
        if raw.startswith(("---", "+++", "@@", "diff ")):
            continue
        body = raw[1:] if raw and raw[0] in "+- " else raw
        if _H2_RE.match(body.strip()):
            current = body.rstrip()
        if raw.startswith(("+", "-")) and not raw.startswith(("+++", "---")) and current:
            changed.add(current)
    return changed


def _check_gold_target(author_email: str) -> list[str]:
    if _GOLD_TARGET not in _staged_files():
        return []
    if author_email in _DIRECTOR_EMAILS:
        return []  # Director bypass

    post_text = _staged_file_content(_GOLD_TARGET)
    if not post_text:
        return []  # file deleted entirely — let other guards handle
    h2_to_domain_post = _parse_h2_to_domain(post_text)

    # V0.3 fix L1: also parse pre-commit (HEAD) state to recover domain of DELETED entries.
    # Without this, a deletion of an `ao`-domain entry by BEN would emit the misleading
    # "no domain tag" error instead of the correct "not authorized to delete domain=ao" error.
    pre_text = _git("show", f"HEAD:{_GOLD_TARGET}") if _GOLD_TARGET else ""
    h2_to_domain_pre = _parse_h2_to_domain(pre_text) if pre_text else {}

    diff = _staged_diff(_GOLD_TARGET)
    changed = _changed_h2s_from_diff(diff)

    errors: list[str] = []
    for h2 in changed:
        # Prefer post-commit domain (for adds/modifications); fall back to pre-commit
        # (for deletions where H2 no longer exists in post-commit).
        domain = h2_to_domain_post.get(h2) or h2_to_domain_pre.get(h2, "")
        if not domain:
            errors.append(
                f"REJECT [{_GOLD_TARGET}]: changed entry {h2!r} has no "
                f"`<!-- domain: ... -->` tag within 5 lines of H2 header (neither pre- nor post-commit)"
            )
            continue
        allowed = _AUTHORITY_BY_EMAIL.get(domain, set())
        if author_email not in allowed:
            # Distinguish deletion vs add/modify in the error message for clearer debugging.
            verb = "delete" if h2 not in h2_to_domain_post else "modify"
            errors.append(
                f"REJECT [{_GOLD_TARGET}]: not authorized to {verb} entry {h2!r} "
                f"(domain={domain}); author email {author_email!r} not in allowlist "
                f"{sorted(allowed) or '(reserved)'}"
            )
    return errors


# --- audit log enforcement (IMP 5: append-only) ---


def _check_audit_log_append_only(author_email: str) -> list[str]:
    if _AUDIT_LOG not in _staged_files():
        return []
    if author_email in _DIRECTOR_EMAILS:
        return []

    diff = _staged_diff(_AUDIT_LOG)
    # Append-only = no `-` lines in the diff (no removals or modifications), and all
    # `+` lines are after the prior end-of-file marker. We approximate: any `-` line
    # (other than `---` file marker) → REJECT.
    for raw in diff.splitlines():
        if raw.startswith("---"):
            continue
        if raw.startswith("-"):
            return [
                f"REJECT [{_AUDIT_LOG}]: append-only enforcement — diff contains "
                f"removal {raw!r}; only pure end-of-file additions allowed"
            ]
    return []


# --- ratification trigger parser (Fix 3 — bundled into this module per V0.4 fold) ---


_TRIGGER_RE = re.compile(
    r"\bratified\s*[-‐-―]\s*promote\s+to\s+GOLD\s*:\s*(?P<path>\S+)",
    re.IGNORECASE,
)


def parse_ratification_trigger(chat_text: str) -> str | None:
    """Returns the artefact path if Director's ratification trigger phrase is present
    in chat_text, else None. Apply Unicode NFKC normalization first to fold smart-quote
    variants and width forms; the tolerant dash class handles all common dash forms.
    """
    if not chat_text:
        return None
    normalized = unicodedata.normalize("NFKC", chat_text)
    m = _TRIGGER_RE.search(normalized)
    return m.group("path") if m else None


def main() -> int:
    if "--staged" not in sys.argv:
        print("only --staged mode supported", file=sys.stderr)
        return 2

    author_email = _author_email()
    if not author_email:
        print("REJECT: git config user.email is empty; cannot authorize", file=sys.stderr)
        return 1

    errors = _check_gold_target(author_email) + _check_audit_log_append_only(author_email)
    if errors:
        for e in errors:
            print(e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Wire to `.git/hooks/pre-commit` (existing hook — append; idempotent grep-guarded):

```bash
# BEN GOLD-write scope-guard + audit append-only (BRIEF_BEN_CROSS_MATTER_GOLD_WRITE_1)
if ! grep -q "check_gold_domain_tags.py" "$0" 2>/dev/null; then : ; fi  # marker
files=$(git diff --cached --name-only)
if echo "$files" | grep -qE "^wiki/_cortex/(director-gold-global|gold-promotions)\.md$"; then
    python3 scripts/check_gold_domain_tags.py --staged || exit 1
fi
```

### Verification (V0.2)
1. `pytest tests/test_check_gold_domain_tags.py` GREEN with literal output. New test cases (V0.2 additions): modification of existing tagged entry by wrong-author REJECTED (CRIT 1); deletion of entry by wrong-author REJECTED (CRIT 1); audit-log non-append modification REJECTED (IMP 5); substring-spoofing attempts ("directory-bot@example.com" claiming director access) REJECTED (CRIT 3); Director email bypass works for both files (IMP 8).
2. Manual: BEN edits an EXISTING `domain: bb-finance` entry (modification, not new add) → pre-commit PASSES (correct: BEN authorized for bb-finance). BEN attempts to edit an EXISTING `domain: ao` entry → pre-commit FAILS (correct: BEN NOT authorized for ao). V1 hook missed this; V0.2 catches it.

---

## Fix 3: Ratification trigger phrase parser — BEN side (V0.2 hardened)

### Problem
BEN must detect Director's GOLD-promotion phrase + artefact path in chat. **V0.2 fold** (Gate 3 CRIT 2): V1 said "em-dash not hyphen" but no regex spec; smart quotes / case / whitespace make activation non-deterministic. Fix: tolerant regex with Unicode normalization + named capture for path.

### Canonical regex (locked) — IMPLEMENTED IN FIX 2 MODULE

**V0.4 fold:** the `parse_ratification_trigger` function + `_TRIGGER_RE` regex are bundled directly into `scripts/check_gold_domain_tags.py` (the Fix 2 module body) so a B-code creating that file from Fix 2's code block alone has all required code. Tests at `tests/test_parse_ratification_trigger.py` (Fix 8) import it via:

```python
from scripts.check_gold_domain_tags import parse_ratification_trigger
```

The function spec (regex + NFKC normalization + named capture group `path`) is defined in Fix 2's module code block (search for `# --- ratification trigger parser`). Match any Unicode hyphen/dash variant (U+002D ASCII hyphen, U+2010 hyphen, U+2011 non-breaking hyphen, U+2012 figure dash, U+2013 en-dash, U+2014 em-dash, U+2015 horizontal bar); case-insensitive on `ratified` and `promote to GOLD`.

### Implementation

Add to `~/.claude/skills/bb-finance/SKILL.md` under a new `## §5. GOLD-Write Capability (Tier-B conditional)` section:

```markdown
## §5. GOLD-Write Capability (Tier-B conditional)

**Activation:** Director ratifies a Layer 3 (proposed-reports) artefact with the canonical trigger phrase:

```
ratified — promote to GOLD: <artefact-path>
```

**Tolerant regex** (BEN's parser at `parse_ratification_trigger` per Fix 3 spec):
- `ratified` — case-insensitive match
- separator — any Unicode dash/hyphen (U+002D, U+2010-U+2015) — accepts `-`, `‐`, `‑`, `‒`, `–`, `—`, `―`
- `promote to GOLD` — case-insensitive
- `:` — required
- `<path>` — non-whitespace token; the parser does NOT validate the path syntactically — caller does the file-exists check

**Bare `ratified` does NOT trigger.** The full phrase including `— promote to GOLD: <path>` is load-bearing. If Director uses ambiguous wording, BEN replies asking for the canonical form.

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

## Fix 8: Tests (V0.2 expanded)

Create `tests/test_check_gold_domain_tags.py` covering V0.2 hardening:

**V1 baseline cases:**
1. New entry with correct `domain: bb-finance` tag + author email `bb-finance@brisengroup.com` → PASS
2. New entry with `domain: ao` tag + author email `bb-finance@brisengroup.com` → FAIL (BEN not authorized for ao)
3. New entry with NO `<!-- domain -->` tag within 5 lines → FAIL with no-tag message
4. Multi-entry commit: one tagged bb-finance, one tagged ao, author=BEN → FAIL on the ao entry
5. Director email `dvallen@brisengroup.com` → bypass passes regardless of tags
6. Diff with no changes to target file → PASS (early return)

**V0.2 critical-path cases (Gate 3 fold):**
7. **MODIFICATION** of an existing `domain: bb-finance` entry by author=`bb-finance@brisengroup.com` → PASS (CRIT 1: V1 missed this; V0.2 catches via post-commit file state parse)
8. **MODIFICATION** of an existing `domain: ao` entry by author=`bb-finance@brisengroup.com` → FAIL (CRIT 1: BEN cannot edit ao-domain even on existing entries)
9. **DELETION** of lines from existing `domain: ao` entry by author=`bb-finance@brisengroup.com` → FAIL (CRIT 1)
10. **Substring spoofing**: author email `directory-bot@evilcorp.com` claiming director access → FAIL (CRIT 3: V1's `a in author` would have matched "director"; V0.2 exact-match prevents)
11. **Trigger phrase regex** — separate test file `tests/test_parse_ratification_trigger.py`. Import path: `from scripts.check_gold_domain_tags import parse_ratification_trigger` (place the function in that module alongside the gate logic; if separated later into `scripts/parse_trigger.py`, update tests + V0.3 §5 reference). Test stub:

```python
"""Tests for parse_ratification_trigger — V0.3 fix H2."""
import pytest
from scripts.check_gold_domain_tags import parse_ratification_trigger


@pytest.mark.parametrize("phrase, expected_path", [
    # ASCII hyphen
    ("ratified - promote to GOLD: wiki/_finance/baden-baden/proposed-reports/x.md",
     "wiki/_finance/baden-baden/proposed-reports/x.md"),
    # Em-dash (U+2014)
    ("ratified — promote to GOLD: foo.md", "foo.md"),
    # En-dash (U+2013)
    ("ratified – promote to GOLD: bar.md", "bar.md"),
    # Non-breaking hyphen (U+2011)
    ("ratified ‑ promote to GOLD: baz.md", "baz.md"),
    # Smart quote-style hyphen (U+2010)
    ("ratified ‐ promote to GOLD: q.md", "q.md"),
    # Horizontal bar (U+2015)
    ("ratified ― promote to GOLD: q.md", "q.md"),
    # Case variants — ratified/RATIFIED/Ratified
    ("RATIFIED — promote to gold: y.md", "y.md"),
    # Extra whitespace tolerance
    ("ratified   —    promote   to   GOLD :   spaced.md", "spaced.md"),
])
def test_trigger_matches_dash_variants(phrase, expected_path):
    assert parse_ratification_trigger(phrase) == expected_path


@pytest.mark.parametrize("non_match_phrase", [
    "ratified",  # bare ratify
    "ratified the offer",  # ratified without GOLD suffix
    "promote to GOLD: orphan.md",  # missing 'ratified' lead
    "ratified — promote to GOLD",  # missing colon + path
    "ratified — promote to GOLD: ",  # trailing colon, no path token
    "ratifiedpromote to GOLD: x.md",  # missing dash separator
])
def test_trigger_does_not_match_invalid(non_match_phrase):
    assert parse_ratification_trigger(non_match_phrase) is None


def test_trigger_extracts_first_path_only():
    # If two trigger phrases appear, only the first match wins (search returns first).
    text = "ratified — promote to GOLD: a.md\nlater: ratified — promote to GOLD: b.md"
    assert parse_ratification_trigger(text) == "a.md"
```
12. **Audit log append-only**: addition at end of `gold-promotions.md` → PASS (IMP 5)
13. **Audit log non-append**: any `-` line in diff of `gold-promotions.md` (modification or deletion) by non-Director → FAIL (IMP 5)
14. **Audit log Director bypass**: same modification by Director email → PASS (IMP 5 + IMP 8)
15. **Empty `git config user.email`** → FAIL with explicit error (V0.2 guard)
16. **Multi-file commit** with ONE valid bb-finance edit AND ONE invalid ao edit by BEN → FAIL on the ao one only (single-file rejection isolates blast radius)

---

## Fix 9: State machine for Director-decline mid-flow (Gate 3 IMP 4)

### Problem
V1 had no spec for what happens if Director sees the inline diff and rejects/revises. No staged-state file, no resume protocol, no timeout. BEN would be stuck holding draft state in process memory only.

### Implementation

Add to `~/.claude/skills/bb-finance/SKILL.md` §5 (GOLD-Write Capability):

```markdown
### §5.1. Staged-state file + resume + timeout

After step 2 (BEN drafts proposed GOLD entry), BEN persists the draft to:

```
$TMPDIR/baker/ben/gold-promotion-staged-<session-id>.json
```

Schema:
```json
{
  "session_id": "<uuid>",
  "staged_at_utc": "<iso-8601>",
  "ttl_hours": 24,
  "source_artefact": "<path>",
  "proposed_h2_header": "## YYYY-MM-DD — topic",
  "proposed_domain_tag": "bb-finance",
  "proposed_body": "<full body markdown>",
  "director_ratification_quote": "<verbatim>",
  "state": "awaiting_director_diff_ratify"
}
```

**Three resume paths:**

1. **Director ratifies diff in-session** (`ok` / `commit` / `approved`) → BEN proceeds to step 5 (commit). On success, delete staged file.

2. **Director revises in-session** (`revise: <instructions>`) → BEN updates proposed_body + bumps `staged_at_utc`, re-surfaces. Stays in `awaiting_director_diff_ratify`.

3. **Director declines** (`no` / `abort` / silent) → BEN moves staged file to `$TMPDIR/baker/ben/gold-promotion-declined-<session-id>.json` for audit; clears working state.

**Timeout:** any staged file with `staged_at_utc` older than 24h is auto-expired on next BEN session-start: moved to `gold-promotion-expired-<session-id>.json` for audit; not auto-resumed.

**Resume on session-start:** BEN reads `$TMPDIR/baker/ben/gold-promotion-staged-*.json`. For each non-expired file, surfaces to Director: "Pending GOLD promotion from <staged_at>: <h2_header>. Resume / revise / abort?". Director-on-demand only — does NOT auto-resume to avoid surprise commits.
```

---

## Fix 10: Concurrency lock (Gate 3 IMP 7)

### Problem
Two concurrent BEN sessions could stage GOLD promotions on the same target file → race on commit. V1 had no lock.

### Implementation

Add to `~/.claude/skills/bb-finance/SKILL.md` §5:

```markdown
### §5.2. Concurrency lock

Before staging a GOLD-promotion (step 2 of §5 flow), BEN acquires an advisory lock:

```bash
# Pseudocode — actual implementation in BEN's skill helper
exec 200>$BAKER_VAULT_ROOT/wiki/_cortex/.gold-promotion.lock
flock --nonblock 200 || {
    echo "Another GOLD promotion in progress. Try again after that one commits or expires (24h TTL)." >&2
    exit 1
}

# ... staging + Director-diff-ratify + commit happens inside lock ...
# Lock auto-released on shell exit (FD 200 close).
```

If BEN cannot acquire the lock, surface to Director: "Another BEN session has a GOLD promotion in flight. Wait or check `wiki/_cortex/.gold-promotion.lock` mtime to see how long it's been held." Do NOT proceed.

`.gold-promotion.lock` file is in `.gitignore` (lock state, not tracked).
```

---

## Files Modified
- `wiki/_cortex/director-gold-global.md` — add domain-scoping schema doc
- NEW: `wiki/_cortex/gold-promotions.md` — audit log
- NEW: `scripts/check_gold_domain_tags.py` — pre-commit gate (V0.2 — post-commit state parse + audit append-only + email-based author auth)
- NEW: `tests/test_check_gold_domain_tags.py` — gate tests (16 cases V0.2)
- NEW: `tests/test_parse_ratification_trigger.py` — trigger-phrase regex tests (Unicode dash variants + smart quotes + case)
- `.git/hooks/pre-commit` — wire the gate (idempotent grep-guarded append; activation step LAST per Ship Target)
- `~/.claude/skills/bb-finance/SKILL.md` — new §5 (GOLD-Write Capability) + §5.1 (staged-state machine) + §5.2 (concurrency lock)
- `_ops/agents/bb-finance/CONTRACT.md` — §3.2 carve-out (V0.2: email-allowlist Director bypass, NOT DV-initials)
- `wiki/_finance/baden-baden/authority-boundary-table.md` — row revision
- `_ops/agents/bb-finance/OPERATING.md` — §X revert-path session-start clause
- `.gitignore` (baker-vault) — add `wiki/_cortex/.gold-promotion.lock` (lock state, not tracked)

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

1. Add `russo-de` to `_AUTHORITY_BY_EMAIL` map in `scripts/check_gold_domain_tags.py` (V0.2 model — emails only, not name/role strings):
   ```python
   "russo-de": {"russo-de@brisengroup.com"},
   ```
   Director bypass is inherited from `_DIRECTOR_EMAILS` automatically — do NOT add `"director"` or `"Dimitry Vallen"` strings into the authorized set. (V0.3 fix C1: prior V0.2 example used legacy name/role strings; corrected here to email-only.)
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

## Ship Target (V0.2 — cross-repo merge ordering, Gate 3 IMP 6)

Implementation spans TWO repos. **Strict merge order to avoid activation racing schema:**

1. **baker-vault PR FIRST** — schema-only changes; idempotent; safe to merge before code lands.
   Files: `wiki/_cortex/director-gold-global.md` (frontmatter schema doc), NEW `wiki/_cortex/gold-promotions.md` (audit log skeleton), `_ops/agents/bb-finance/CONTRACT.md` (§3.2 carve-out + email-allowlist replaces DV-initials), `wiki/_finance/baden-baden/authority-boundary-table.md` (row revision), `_ops/agents/bb-finance/OPERATING.md` (§X revert path), `~/.claude/skills/bb-finance/SKILL.md` (§5 + §5.1 + §5.2).

2. **baker-master PR SECOND** — code + tests; depends on schema being merged so test fixtures match production state.
   Files: NEW `scripts/check_gold_domain_tags.py`, NEW `tests/test_check_gold_domain_tags.py`, NEW `tests/test_parse_ratification_trigger.py`.

3. **Activation step LAST** (manual, post both merges) — append the pre-commit hook block to `.git/hooks/pre-commit` in BAKER-VAULT local checkout (where target files live). NOT a PR commit; local-checkout activation. Verify hook fires by attempting a tagged-but-wrong-domain commit on a scratch branch — must FAIL.

- Ship report at `briefs/_reports/<bN>_ben_cross_matter_gold_write_1_<date>.md`
- BEN performs first live GOLD promotion against one of the 6 staged Layer 3 reports (Director-curated test set per V2 addendum) AFTER merge — that's the burn-in proof
- Roll-back path: `git revert` on each repo's merge commit; remove pre-commit hook block; staged files in `$TMPDIR/baker/ben/` cleaned up on next session-start (auto-expire)

## Caller / Provenance
- AH2-T re-emit 2026-05-07 ~07:53Z (re-relayed after prior session API-terminated; primary dispatch + V2 addendum from chat-history context, persisted to bm-aihead2/memory/ben_gold_write_brief_paste_blocks.md)
- AH1-App authored brief 2026-05-07 ~07:55Z via `/write-brief` skill (Step 1 EXPLORE verified BEN files + GOLD targets + 6 staged reports + charter §4; Step 2 PLAN ratified by Director with Q's a-d; Step 3 WRITE 2026-05-07 ~08:00Z)
- AH1-T cross-recommendations on Q's a-d reconciled (msg #22 to /msg/cowork-ah1) — divergence on Q (b) resolved in AH1-T's favor (cross-matter only V1; per-matter Phase B)
- Director ratifications:
  - 2026-05-06 PM (capability ratification): "BEN earns write access to cross-matter Cortex GOLD upon Director ratification" (relayed via AH2-T)
  - 2026-05-07 ~07:55Z (Q's a-d): "follow your recoms" → (a) A1 frontmatter + (b) B2 cross-matter only V1 + (c) C1 phrase + (d) D1 BEN first

## PL ship-report
End your chat ship report with the fenced PL paste-block per `_ops/skills/ai-head/SKILL.md` §"PL ship-report contract".
