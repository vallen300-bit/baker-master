# CODE_2_PENDING — BRISEN_LAB_AUTHZ_FACTORY_1

**Dispatched:** 2026-05-06
**Tier:** A (auth-touching surface)
**Repo:** `vallen300-bit/brisen-lab` (NOT baker-master)
**Branch:** `b2/brisen-lab-authz-factory-1`
**Brief:** `briefs/BRIEF_BRISEN_LAB_AUTHZ_FACTORY_1.md` (in baker-master repo — read it first)

## Summary (read the full brief — this is the dispatch shortcut, not the spec)

Bundle of two F1 follow-ups, both F2-gating. Director ratified bundle 2026-05-06.

- **F1-FU-1** — add `_is_director` exemption to `GET /msg/{terminal}` + regression test (test 9 in `test_inbox_read_authz.py`). Matches existing exemption at event-full / ack / delete.
- **F1-FU-2** — extract FastAPI `Depends(authz(policy, allow_director))` factory consolidating 6 hand-rolled authz shapes at `bus.py:184/307/362/398/446/510` (architect H2 finding).

The factory is the natural home for the Director exemption — fold them in one PR.

## What to build

NEW file `authz.py`: `Policy` enum + `CallerContext` dataclass with row-helpers + `authz(policy, allow_director=True)` Depends factory.

REFACTOR `bus.py`: 5 of the 6 hand-rolled shapes consume the factory. `ratify_decision` keeps its bespoke H7 chain (token + jti + parent FOR UPDATE too entangled). After refactor, `_require_worker_slug` (line 66) and `_is_director` (line 73) are dead and removed.

NEW `tests/test_authz_factory.py`: 22 matrix tests (factory + CallerContext helpers).

EXTEND `tests/test_inbox_read_authz.py`: add test 9 (Director-on-GET-{terminal} regression). Update docstring 8→9.

## CRITICAL: 5-gate review chain MANDATORY before AH1-T merge

Run reviews in **parallel** in a single message:

1. **AH2 static review** — `feature-dev:code-reviewer` agent
2. **AH2 `/security-review`** — full pass over auth surface; verdict in PR comment
3. **picker-architect review** — abstraction sanity (Policy enum, CallerContext shape, inline-boolean carve-outs in delete + ack)
4. **feature-dev:code-reviewer 2nd-pass** — after any review-driven changes

Tag PR with `tier-a-auth-touching`. Link to ClickUp `86c9nnyvj` (FU-1) + `86c9nnywq` (FU-2).

## CRITICAL: AC A9 — pin-not-vacuous local sanity check

Verify the F1-FU-1 regression test 9 isn't vacuously passing:

1. Temporarily flip `Depends(authz(Policy.RECIPIENT_OF_TERMINAL, allow_director=True))` → `allow_director=False` on `GET /msg/{terminal}` in `bus.py`
2. `pytest tests/test_inbox_read_authz.py::test_get_msg_director_exemption_succeeds -v` — must FAIL (403 reader_slug_mismatch)
3. Revert the flip — do NOT commit `False`
4. Document the local-only verification in PR body

This pins the choice the Director ratified.

## Acceptance criteria (full table in brief — quick form here)

- A1: 22 factory tests PASS
- A2: 9 inbox tests PASS (8 existing + 1 new)
- A3: full `pytest` PASS (no regressions)
- A4: `grep -n "_require_worker_slug\|_is_director\b" bus.py` = empty
- A5: `grep -n "x_terminal_key" bus.py` = empty
- A6: `grep -n "Header(None)" bus.py` = ONLY `x_human_confirmation_token` line
- A7: py_compile bus.py + authz.py clean
- A8: `from authz import authz, CallerContext, Policy` works
- A9: pin-not-vacuous sanity check (above) — document in PR body

## Ship-report

After merge, write `briefs/_reports/B2_brisen_lab_authz_factory_1_<YYYYMMDD>.md` in baker-master repo: PR number, merge commit, AC table all ☑, files modified, in-flight observations, any V0.x amendments triggered by review feedback.

## Files modified

- NEW: `authz.py` (~85 lines, repo root)
- MODIFY: `bus.py` (refactor 5 endpoints; remove 2 dead helpers; update imports)
- NEW: `tests/test_authz_factory.py` (22 tests)
- EXTEND: `tests/test_inbox_read_authz.py` (add test 9, update docstring)

## Do NOT touch

- `auth_lab.py` (slug + JWT primitives stay; we just consume them)
- Inner H7 chain in `_ratify_decision_inner`
- `app.py`, `migrations/`, `lifecycle.py`, `freeze.py`, `tier_classification.py`
- `conftest.py` (env-loaded test keys already match)

## Lessons applied (in brief)

- function-signature verification (every snippet in brief written after reading actual files — no guessed signatures)
- Tier-A `/security-review` mandatory (Lesson #52)
- pin-not-vacuous test (AC A9)
- in-place brief amendments if review chain produces fixes (NOT append-only)
- PEP 563 `from __future__ import annotations` already in bus.py:24 — keep convention in new authz.py
