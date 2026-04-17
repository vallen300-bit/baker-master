# Code Brisen #1 — Pending Task

**From:** AI Head
**To:** Code Brisen #1 (terminal instance, 1M context, R3/R4/R5 reviewer of decisions doc)
**Task posted:** 2026-04-17
**Status:** OPEN — awaiting execution

---

## Task: R1 Architecture Review on KBL-A Infrastructure Code Brief

### Target

**File:** `briefs/KBL-A_INFRASTRUCTURE_CODE_BRIEF_DRAFT.md`
**URL:** https://github.com/vallen300-bit/baker-master/blob/main/briefs/KBL-A_INFRASTRUCTURE_CODE_BRIEF_DRAFT.md
**Commit:** `942c347`
**Size:** 1407 lines

### Scope — full architectural pass (not a spot-check)

Verify that all 15 ratified decisions in `briefs/DECISIONS_PRE_KBL_A_V2.md` (commit `d8bc2c0`) are correctly translated into implementation spec. Check:

- **(a) Decision fidelity** — every D1-D15 spec reflected correctly in build phases
- **(b) Schema** — `signal_queue` additions + 5 new tables + FK reconciliation (`INTEGER` type + `ON DELETE SET NULL`). Check `briefs/_drafts/KBL_A_SCHEMA.sql` alignment (Code B2 is updating this to match — if not yet aligned when you review, flag as should-fix for B2 follow-up)
- **(c) Mac Mini install** — `scripts/install_kbl_mac_mini.sh`, LaunchAgents, flock wrapper. Correct macOS semantics? Idempotent? Handles failure modes? sudo prompt UX?
- **(d) kbl/*.py modules** — retry ladder, circuit breaker, cost tracking, logging, alert dedupe. Any race conditions, state consistency issues, or silent-failure paths?
- **(e) Gold drain worker** — idempotency guarantees, git commit with Director identity, push path, conflict handling, frontmatter parse/write correctness
- **(f) Deploy sequence** — Render-first + Mac Mini-second. Rollback plan viable? Data loss risk?
- **(g) Acceptance criteria per phase** — testable, complete, measurable? Missing any edge cases?
- **(h) Env var table** — complete? Anything hardcoded that should be env? Anything env-configurable that should be hardcoded?
- **(i) Known Open Items §17** — any you'd add or elevate?

### Output structure

Same format as R3/R4/R5:

```markdown
## BLOCKERS (must fix before dispatch)
- [B1] <description>

## SHOULD FIX (strongly recommended)
- [S1] <description>

## NICE TO HAVE (optional)
- [N1] <description>

## MISSING (gaps)
- [M1] <description>
```

### Context — do NOT re-open settled material

The decisions document went through 5 review rounds (R1-R5). DO NOT re-litigate decisions. Focus review on:
- Implementation correctness (code paths, SQL, bash)
- Schema details (types, constraints, indexes)
- Failure modes (what happens when X breaks?)
- Race conditions (concurrency on PG, filesystem, WAHA)
- Completeness of acceptance tests

If you find a decision that looks broken in implementation, flag as `[B<n>] Implementation diverges from D<x>` rather than reopening the decision.

### Time budget

**45-60 minutes** (this is a 1407-line brief; invest appropriately). If you finish in <30 min, you probably skimmed.

### Pass criteria

| Result | Next step |
|---|---|
| 0 blockers | Director ratifies KBL-A → dispatch to Code Brisen for implementation |
| 1-3 blockers | AI Head revises to v2 → re-review |
| ≥4 blockers | AI Head restructures (architectural miss, not incremental fix) |

### Parallel context (informational, not your scope)

- Code Brisen #2 (app instance) aligning `briefs/_drafts/KBL_A_SCHEMA.sql` to match KBL-A §5 FK reconciliation. Their task at `briefs/_tasks/CODE_2_PENDING.md`.
- Director's D1 eval-labeling session pending (~60 min when ready) — unblocks D1 conditional ratification, not blocking KBL-A dispatch.
- Director's SSH hardening run pending — drop-in ready at `briefs/_drafts/200-hardening.conf`, not blocking dispatch.

### Reporting

Return findings in the structured format above. When complete:

```
R1 review complete (<N> min).
Findings: <X> blockers, <Y> should-fix, <Z> nice-to-have, <W> missing.
Verdict: <ratification-ready | v2 revision | restructure>.
```

Then paste structured findings.

---

*Task posted by AI Head 2026-04-17. Overwritten when next task lands for Code Brisen #1.*
