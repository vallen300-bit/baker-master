# Code Brisen #3 — Pending Task

**From:** AI Head (Team 1 — Meta/Persistence)
**To:** Code Brisen #3
**Task posted:** 2026-04-24
**Status:** OPEN — run `/security-review` on your own PR #59 + append output to ship report

**Supersedes:** CITATIONS_API_SCAN_1 coder task — shipped as PR #59 (`d9b110a`) with ship report at `briefs/_reports/B3_citations_api_scan_1_20260424.md`. All 11 ship-gate checks green, +14 tests passing.

---

## Why this step

Per SKILL.md Security Review Protocol + Director 2026-04-24 directive, every Tier A auto-merge is gated on **green /security-review**. B3 coded PR #59, so AI Head (not B3) will do the peer review + merge — but **the /security-review scan itself is a mechanical tool, not peer review**, and you running it on your own code is fine and fastest (you have all the context).

This closes the last pre-merge gate. AI Head #1 picks up after your push.

---

## Action

1. Still in `~/bm-b3`. `git checkout citations-api-scan-1 && git pull -q` if needed.

2. Run `/security-review` on the pending changes of the PR branch.

3. Capture the literal output. Append a new `## /security-review (post-ship)` section at the bottom of `briefs/_reports/B3_citations_api_scan_1_20260424.md`. Shape:

```markdown
## /security-review (post-ship)

**Ran:** 2026-04-24
**Command:** /security-review

```
<literal /security-review output>
```

**Verdict:** PASS / FAIL / ISSUES

**Findings (if any):**
- <specific issue>
- ...

**AI Head action:**
- If PASS → ready for auto-merge.
- If ISSUES → flag to AI Head #1 before merge; do NOT auto-merge.
```

4. Commit to main (not the PR branch) as:
   ```
   report(B3): /security-review output appended to PR #59 ship report
   ```

5. Push.

6. Tab done. AI Head #1 picks up — 1-pass peer review + rebase-if-needed vs B1's parallel PROMPT_CACHE_AUDIT_1 PR + auto-merge on PASS.

## Merge-compat reminder

Both PR #59 (your citations work) and B1's in-flight PROMPT_CACHE_AUDIT_1 touch `outputs/dashboard.py` `/api/scan` handler. Whichever merges second rebases onto the first. AI Head manages; no action from you.

## If /security-review surfaces a real issue

Do NOT fix in this dispatch — write up the finding in the report, push, then stop. AI Head #1 decides: (a) minor → request-changes on PR + dispatch you to fix, or (b) blocking → halt merge + coordinate. Either way, that's AI Head's call.

Minor / style issues are PASS with notes; only real vulnerabilities are FAIL.

## Timebox

**~15–25 min.** The scan is mechanical.

**Working dir:** `~/bm-b3`.

---

**Dispatch timestamp:** 2026-04-24 (Team 1, closing PR #59 pre-merge gate)
**Team:** Team 1 — Meta/Persistence
**Sequence:** CITATIONS_API_SCAN_1 (#59, this /security-review) → AI Head 1-pass review + merge → M0 row 5 CLOSED.
