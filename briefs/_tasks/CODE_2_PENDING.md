# Code Brisen #2 — Pending Task

**From:** AI Head
**To:** Code Brisen #2 (app instance)
**Previous:** KBL-B §4-5 review shipped (`0743def`), 3 blockers applied by AI Head inline (`1448479`)
**Task posted:** 2026-04-18
**Status:** OPEN — awaiting execution
**Supersedes:** KBL-B §4-5 review task (shipped)

---

## Task: Review PR #3 — TCC-Safe Install Fix

**PR:** https://github.com/vallen300-bit/baker-master/pull/3
**Branch:** `kbl-a-tcc-fix`
**Head commit:** `04b494b`
**Report:** `briefs/_reports/B1_tcc_fix_dburl_20260418.md` (commit `c86aed0` on main)

B1 shipped both deliverables from CODE_1_PENDING. TCC fix is in PR #3 awaiting merge. DATABASE_URL 1P item is live (separate, no PR needed).

### Scope of this review

**IN — PR #3:**
- Templated plists with `__REPO__` placeholder + install-time sed substitution
- Post-sed `grep __REPO__` guard (fails install if placeholder didn't get replaced)
- `/usr/local/bin/kbl-*.sh` symlinks dropped entirely (plist-as-source-of-truth per B2's earlier N2 implicit preference)
- TCC refuse-guard on `~/Desktop/`, `~/Documents/`, `~/Downloads/`
- Default `KBL_REPO` → `~/baker-code`
- KBL-A brief §6 TCC note + updated acceptance criteria

**OUT:**
- DATABASE_URL 1P item (created via `op item create`, no code change, no PR)
- Mac Mini live state (B1 verified byte-identical re-run)

### Specific scrutiny

Apply your usual reviewer discipline. On top of that:

1. **`__REPO__` substitution safety.** sed replacing a placeholder in a plist — is the sed robust against edge cases (repo path contains spaces? special chars? trailing slash?)? Would an adversarial `KBL_REPO=/path'/with"quote` break parsing?
2. **Refuse-guard coverage.** B1 blocklisted `~/Desktop/`, `~/Documents/`, `~/Downloads/`. Are there other TCC-protected paths on macOS 15 worth blocklisting (e.g., `~/Pictures/`, iCloud Drive `~/Library/Mobile Documents/`)? Or is conservative blocklist acceptable with `__REPO__` guard as backstop?
3. **Non-regression vs live Mac Mini.** B1 claims re-running installer produces byte-identical ProgramArguments to the manual bandage. Verify the claim by pulling the branch and comparing output of a dry-run to the current `~/Library/LaunchAgents/*.plist` on Mac Mini (via `ssh macmini`).
4. **Backward compat on clones that were installed pre-this-fix.** Mac Mini has the bandaged plists already. If Director re-runs the new installer, does it clean the stale `/usr/local/bin/kbl-*.sh` symlinks (would need sudo) OR does it leave them dangling (harmless but messy)?
5. **Brief §6 note.** Check that the TCC explanation in the brief is self-contained — a fresh reader in 6 months understands why plist-as-source-of-truth without needing git-blame archaeology.

### Output format

File: `briefs/_reports/B2_pr3_review_20260418.md`

Sections:
1. **Verdict:** APPROVE / REQUEST CHANGES / REJECT
2. **Blockers**
3. **Should-fix**
4. **Nice-to-have**
5. **Non-regression check result** (actual diff output from your Mac Mini pull + compare)

Match the format of `B2_pr1_review_20260417.md`.

### Time budget

~30 min. PR is small (targeted fix + tests, ~100-200 line diff estimated).

### Dispatch back

> B2 PR #3 review done — see `briefs/_reports/B2_pr3_review_20260418.md`, commit `<SHA>`. Verdict: <APPROVE | REQUEST CHANGES | REJECT>.

---

## Scope guardrails

- Merge decision is Director's — you report verdict, don't auto-merge.
- Don't re-open KBL-A ratified architecture. Scope is THIS PR's 4 deliverables.

---

*Dispatched 2026-04-18 by AI Head.*
