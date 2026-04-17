# `briefs/_reports/` — Report Mailboxes

**Purpose:** substantive reports from Code Brisen instances (to AI Head / Director). Symmetric with `briefs/_tasks/`: tasks IN are files, reports OUT are files.

## When to file a report (vs reply inline)

### File a report if ANY of:
- Contains tables
- Contains SQL, code blocks > 5 lines, or multi-section findings
- Response is > 10 lines
- Structured review output (e.g., BLOCKERS/SHOULD-FIX/NICE/MISSING)

### Reply inline if ALL of:
- ≤ 10 lines
- No tables or code blocks > 5 lines
- Simple confirmation, status check, or single-fact answer

### Examples

**Inline:** *"Done. Commit `abc1234`. All 4 tests pass. No concerns."*

**File:** full architectural review with blocker/should-fix tiers, or any report that includes schema diffs, SQL, cost analysis, or multi-topic findings.

## Naming convention

`briefs/_reports/B<n>_<topic>_<YYYYMMDD>.md`

- **`B<n>`** — `B1` for Code Brisen #1 (terminal), `B2` for Code Brisen #2 (app)
- **`<topic>`** — short snake_case slug identifying the work (e.g., `kbl_a_r1_review`, `schema_fk_reconciliation`)
- **`<YYYYMMDD>`** — dispatch date; if same-day collision, suffix `_2`, `_3`

Examples:
- `briefs/_reports/B1_kbl_a_r1_review_20260417.md`
- `briefs/_reports/B2_schema_fk_reconciliation_20260417.md`

## Report header template

```markdown
# <Report title — short, topic-style>

**From:** Code Brisen #<n>
**To:** AI Head
**Re:** briefs/_tasks/CODE_<n>_PENDING.md commit <SHA-at-task-dispatch>
**Date:** YYYY-MM-DD
**Related commits:** <SHAs of any work this report summarizes>

---

## TL;DR

<one-line summary, directive (pass/fail/blockers-count/etc)>

---

## <Section 1>

...
```

## Flow

1. Code executes task → writes report to `briefs/_reports/B<n>_<topic>_<date>.md`
2. Code commits + pushes the report
3. Code reports to Director in chat: `Report at briefs/_reports/B<n>_<topic>_<date>.md, commit <SHA>. TL;DR: <one line>.`
4. Director forwards just the path + SHA to AI Head
5. AI Head pulls, reads, quotes specific sections when responding
6. If AI Head has a follow-up task for same Code: overwrites `briefs/_tasks/CODE_<n>_PENDING.md` with next task, which references the prior report for cross-linking

## Why files over chat paste

- **Searchable history** — `grep -r "schema_fk" briefs/_reports/` replays every reconciliation ever done
- **Quotable** — AI Head can say "your §3.2 concern is addressed by ..."
- **Survives sessions** — reports don't disappear when a chat context resets
- **Versions alongside briefs** — `git log briefs/_reports/` is the full audit trail

## Directory hygiene

- No cleanup needed in practice — git keeps everything
- If a report becomes obsolete (e.g., superseded by later review), add a `DEPRECATED-BY:` line at top referencing the newer report — don't delete
- Monthly directory ls stays readable because filenames are date-sorted

## Paired with `briefs/_tasks/`

See `briefs/_tasks/README.md` for the input side of this pattern.
