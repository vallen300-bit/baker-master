# Code Brisen #3 — Pending Task

**From:** AI Head
**To:** Code Brisen #3 (fresh terminal tab)
**Task posted:** 2026-04-20 (morning)
**Status:** OPEN — drop CI workflow from PR #23

---

## Task: PR23_DROP_WORKFLOW — remove `.github/workflows/pytest.yml` from your own PR #23

Director-authorized 2026-04-20 *(plain English: "I agree with your recommendations")*.

### Context

Your PR #23 ran its first CI pass 01:58 UTC and failed in 40s — the workflow `pytest tests/ -v` runs the full test suite, but a big fraction of those tests need real DB / Qdrant / external API secrets that GitHub Actions doesn't have. Not a fixture bug; workflow scope is too aggressive for a first CI pass.

**Decision:** drop the workflow file from PR #23 entirely and ship just the conftest fixture. CI scope becomes a separate design question we take up post-production-flip.

### Scope

On branch `conftest-neon-ephemeral-fixture`:

```bash
cd ~/bm-b3
git checkout conftest-neon-ephemeral-fixture
git pull
git rm .github/workflows/pytest.yml
# If .github/workflows/ is now empty, also remove the dir:
rmdir -p .github/workflows .github 2>/dev/null || true
git commit -m "CONFTEST_NEON_EPHEMERAL_FIXTURE: drop premature CI workflow

First run failed 40s — workflow scope covered the full test suite which
needs DB/Qdrant/API secrets not set in GHA. Decision per AI Head / Director
2026-04-20: ship the conftest fixture alone; defer CI scope design to a
separate brief post-production-flip.

Fixture is still useful: local pytest already unifies on needs_live_pg +
ephemeral_neon_db, and any future CI workflow can pick up the fixture
without further changes here.

Co-Authored-By: Code Brisen 3 <code-brisen-3@brisengroup.com>"
git push origin conftest-neon-ephemeral-fixture
```

### Acceptance

1. `git ls-tree origin/conftest-neon-ephemeral-fixture .github/` returns empty (or `.github/` absent entirely).
2. No new CI run fires (the workflow file is gone).
3. `pytest tests/ -xvs` still green on your machine — fixture itself untouched.
4. `gh pr view 23 --json mergeStateStatus` returns `CLEAN` (no failing required-check bubble).

### Output

Ping AI Head once pushed. AI Head updates B2's mailbox to unblock PR #23 review.

Expected: 5-10 min.
