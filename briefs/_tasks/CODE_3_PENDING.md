# Code Brisen #3 — Pending Task

**From:** AI Head
**To:** Code Brisen #3 (fresh terminal tab)
**Task posted:** 2026-04-20 (midday, post-Phase-A merge + B2 review nits)
**Status:** OPEN — lessons-grep-helper v2 (address B2's N1 + N2 from Phase A review)

---

## Task: LESSONS_GREP_HELPER_V2 — fix two nits from first-use drift data

B2 used the helper on baker-vault PR #3 (first real-world use) and flagged two non-blocking nits. Both worth fixing before Phase B lands — Phase B will be a bigger, mixed-content review where helper quality matters more.

Brief review source: `_reports/B2_sot_phase_a_review_20260420.md` on baker-vault main (commit `bc0ba5d`).

**Target PR:** `baker-master` repo. Branch: `lessons-grep-helper-v2`. Base: `main`. Reviewer: B2.

### Scope

**Fix 1 — Cross-repo support (B2's N1):**

Helper currently breaks when reviewing a PR on a DIFFERENT repo than the one holding `tasks/lessons.md`. B2 had to pipe manually for the Phase A review (baker-master helper, baker-vault PR).

- Add optional `--repo <owner>/<name>` flag passed through to `gh pr diff` and `gh pr view`. Default = current repo detected via `gh repo view`.
- Add optional `LESSONS_FILE=<path>` env override so the lessons file location is configurable (helper today hardcodes `<repo_root>/tasks/lessons.md`; with `--repo` the helper may run inside a baker-vault clone but needs to read `tasks/lessons.md` from baker-master).
- Usage examples in script header:
  ```
  bash lessons-grep-helper.sh 3 --repo vallen300-bit/baker-vault
  LESSONS_FILE=/path/to/baker-master/tasks/lessons.md bash lessons-grep-helper.sh sot-obsidian-1-phase-b --repo vallen300-bit/baker-vault
  ```

**Fix 2 — Doc-heavy PR false-positive suppression (B2's N2):**

On Phase A (pure-scaffold / pure-markdown PR), helper returned top-5 with scores 28-42 but ZERO were actually relevant — all false positives triggered by common words in docs body vs lesson "Mistake:" paragraphs.

Three-part fix:

1. **Filter to `+`-added lines only.** Helper today tokenizes the full diff output (including `-` removed lines, file paths, context). Change to: `grep '^+' | grep -v '^+++'` before tokenizing. Added content is what the PR is adding — the only thing lessons should score against.

2. **IDF-weight tokens.** A token that appears in 30 of 42 lessons is near-useless signal. A token that appears in 2 lessons is strong signal. Compute IDF = `log(total_lessons / lessons_containing_token)` during ranking; score = sum of IDF for intersecting tokens, not raw count. Keep the 6+ char noise filter.

3. **Canned "all-false-positive" output when top-5 scores are bunched low.** If the highest score is < 2× the lowest (i.e., no real signal), replace the top-5 block with:
   ```
   [lessons-grep] No strongly-ranked lessons for PR #<N>.
   Likely reason: PR is docs-only / scaffold-only / scope below lessons' resolution.
   Fall back to manual sweep of lessons #34-42 (most recent) if PR touches production code.
   ```

### Verification

1. **Reproduce the false-positive case.** Run v1 (current main) against PR #3 on baker-vault: `bash briefs/_templates/lessons-grep-helper.sh 3 --repo vallen300-bit/baker-vault` — confirm current behavior is broken (the `--repo` flag errors out or is ignored). Document before-state.

2. **Run v2 against the same PR.** Expect the "no strongly-ranked lessons" fallback block (Phase A is pure scaffold docs — no real lesson applies).

3. **Regression check on B2's original smoke tests** (from PR #25 description):
   - PR #21 (alias rename) → #42 still ranked in top-5 after IDF weighting ✅
   - PR #22 (dead code + env fallback) → #37 still ranked #1 or #2 ✅
   - PR #24 (FEEDLY_WHOOP_KILL) → #37 + #39 both in top-5 ✅
   
   If IDF weighting drops any of these below top-5, v2 is worse than v1 — iterate until all three land correctly.

4. **Unit-test-esque:** add 2-3 synthetic test cases as comments at the top of the script or in a sibling `lessons-grep-helper.tests.sh` showing expected-input / expected-output pairs. Don't need pytest — bash is fine.

### Hard constraints

- **Do NOT touch `tasks/lessons.md` itself.** Content stays stable; helper gets smarter.
- **Do NOT break existing B2 template references** to the helper output format (`#<N> (score <S>) — <title>`). The template parses this; if you change format, template must update in same PR.
- **Keep the script < 80 LOC total.** If you need more, something's wrong. IDF can be computed in a single awk pass across the lessons file.
- **No new deps.** `gh`, `git`, `grep`, `awk`, `sort`, `comm` only.

### Coordination note

B1 is in parallel working on SOT_OBSIDIAN_UNIFICATION_1 Phase B. No conflict — different files (helper lives in baker-master, Phase B is baker-vault). Both PRs can ship independently.

### Output

Ship PR, ping B2 for review when ready. Brief PR body mentions the three smoke-test regression checks from B2's original PR #25 description.

Expected time: 30-45 min. The IDF weighting is the substantive piece; --repo + false-positive fallback are mechanical.
