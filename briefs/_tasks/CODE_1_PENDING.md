# Code Brisen #1 — Pending Task

**From:** AI Head
**To:** Code Brisen #1 (fresh terminal tab)
**Task posted:** 2026-04-20 (afternoon, post-B3-review)
**Status:** OPEN — Phase D recall (2 critical fixes + 4 new tests)

---

## Task: Fix S1a + S1b on baker-master PR #28

B3's review identified two stacking critical defects that would silently break the mirror on first Render deploy. Both are small deltas but load-bearing. Fix both, add 4 new tests, push to the same branch.

**B3 review report:** `briefs/_reports/B3_pr28_phase_d_master_review_20260420.md` on baker-master at head `4be92c9`. Read that first — it has exact file/line pointers + failure-mode reasoning.

**Branch:** `sot-obsidian-1-phase-d-vault-read` (same as before). Do NOT rebase onto main — push fixes on top; B3 will re-review the delta.

---

## S1a — Remove the wrapper's `try/except Exception` in `outputs/dashboard.py::_ensure_vault_mirror`

**Problem:** wrapper catches `Exception` and swallows the `RuntimeError` that `ensure_mirror()` raises on first-clone failure. Brief §1 + your own ship report both promise "fatal on first-clone" — this wrapper defeats both.

**Fix:** delete the `try/except` block entirely. Let the `RuntimeError` propagate up through FastAPI's startup hook so the service fails to boot (as designed). The pull path (subsequent ticks) should still be non-fatal — verify that distinction remains intact.

**Test to add:** `test_startup_call_order.py` (or equivalent): first-clone failure raises at startup → FastAPI lifespan raises → `TestClient(app)` construction fails. Confirm the error propagates, not swallowed.

---

## S1b — Inject `GITHUB_TOKEN` into clone URL in `vault_mirror.py::_remote_url`

**Problem:** baker-vault is a PRIVATE repo (verified by B3: `gh repo view baker-vault --json visibility` → PRIVATE). Current `_remote_url` returns `https://github.com/vallen300-bit/baker-vault.git` with no auth. First clone on Render will fail with a 403/auth error.

**Fix:** when `GITHUB_TOKEN` env is set (Render always sets this for baker-master), rewrite the URL to `https://x-access-token:${GITHUB_TOKEN}@github.com/vallen300-bit/baker-vault.git`. When unset, return the plain URL (local dev / test). Do NOT log the tokenized URL — only the host.

**Tests to add:**
1. `test_token_injection`: with `GITHUB_TOKEN=fake`, `_remote_url()` returns the tokenized form.
2. `test_override_wins`: if `VAULT_REMOTE_URL` env is also set (future override hook), that wins over token injection.
3. `test_symlink_escape`: symlink inside `_ops/` pointing to `/etc/passwd` — `baker_vault_read` rejects (closes B3's nit on path-safety test 6/6).

Total: 4 new tests (S1a fatality + 3 above).

---

## Commit shape

Single commit on top of existing branch. Message: `fix(D): S1a fatal-propagation + S1b GITHUB_TOKEN injection + 4 new tests`. Cite B3's review report in the body.

Push to `sot-obsidian-1-phase-d-vault-read`. Do NOT force-push. B3 will re-review the delta (he's closed the tab — AI Head will re-dispatch him after you push).

## Estimated effort

~20 min per B3's estimate. If it takes more than 45 min, flag.

## baker-vault PR #6 (Cowork doc)

No changes needed there. B3 approved-hold. Master PR #28 must re-approve first, then AI Head merges both together.

Close tab after push.
