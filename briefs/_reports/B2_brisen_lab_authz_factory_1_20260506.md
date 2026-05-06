---
status: PR_OPEN
brief: briefs/BRIEF_BRISEN_LAB_AUTHZ_FACTORY_1.md (baker-master 1165a639)
target_repo: vallen300-bit/brisen-lab
target_branch: b2/brisen-lab-authz-factory-1
pr: https://github.com/vallen300-bit/brisen-lab/pull/5
trigger_class: TIER_A_AUTH_TOUCHING
shipped_by: B2
shipped_at: 2026-05-06
ratification_pending: AH1-T merge (5th gate; reviewers 1-4 green)
---

# B2 ship report — BRISEN_LAB_AUTHZ_FACTORY_1 (F1-FU-1 + F1-FU-2)

## Summary

Bundle of two F1 follow-ups, both F2-gating. PR #5 opened on `vallen300-bit/brisen-lab`, branch `b2/brisen-lab-authz-factory-1`. 4 reviewer gates green; AH1-T merge pending.

- **F1-FU-1** — `_is_director` exemption added to `GET /msg/{terminal}` so Director can read any terminal's inbox. Pinned by new test 9.
- **F1-FU-2** — `authz(policy, allow_director)` Depends factory consolidates 6 hand-rolled authz shapes at `bus.py:184/307/362/398/446/510`. Dead helpers `_require_worker_slug` + `_is_director` removed.

## PR

- **URL:** https://github.com/vallen300-bit/brisen-lab/pull/5
- **Branch:** `b2/brisen-lab-authz-factory-1` (commits `2c6b86b` initial + `f7a5a34` docstring fix per architect)
- **Label:** `tier-a-auth-touching` (created in repo)
- **ClickUp:** [86c9nnyvj](https://app.clickup.com/t/86c9nnyvj) (FU-1) + [86c9nnywq](https://app.clickup.com/t/86c9nnywq) (FU-2)

## AC table

| AC | Test | Status |
|----|------|--------|
| A1 | 22/22 factory tests PASS | ☑ |
| A2 | 9/9 inbox tests PASS | ☑ |
| A3 | full pytest 72 passed, 1 skipped (intentional H7-skip), 0 failed | ☑ |
| A4 | `_require_worker_slug` + `_is_director` purged from bus.py | ☑ |
| A5 | `x_terminal_key` purged from bus.py | ☑ |
| A6 | `Header(None)` only on `x_human_confirmation_token` line | ☑ |
| A7 | py_compile bus.py + authz.py clean | ☑ |
| A8 | `from authz import authz, CallerContext, Policy` works | ☑ |
| A9 | Pin-not-vacuous: `allow_director=False` flip → test 9 FAILS 403; reverted before commit | ☑ |

## Files modified

| File | Change | LOC |
|------|--------|-----|
| `authz.py` | NEW — Policy enum + CallerContext dataclass + authz() factory | +163 |
| `bus.py` | Refactor 5 endpoints; remove dead helpers; ratify_decision keeps H7 chain | +40 / -107 |
| `tests/test_authz_factory.py` | NEW — 22-test factory matrix | +241 |
| `tests/test_inbox_read_authz.py` | Extend — test 9 + docstring 8→9 | +28 / -7 |

## 5-gate review chain

| Gate | Reviewer | Verdict |
|------|----------|---------|
| 1 | feature-dev:code-reviewer (static) | LGTM (1 pre-existing informational on conftest.py `Optional` import — NOT in this PR's diff) |
| 2 | /security-review | NO HIGH-CONFIDENCE security issues |
| 3 | feature-dev:code-architect (abstraction) | REQUEST_CHANGES → 3 items (4, 5, 6); Item 6 partially applied in `f7a5a34`; Items 4 + 5 surfaced to AH1 (out of B2 scope) |
| 4 | feature-dev:code-reviewer 2nd-pass | LGTM 2nd-pass — auth envelopes preserved, carve-outs equivalent, fixture ordering safe |
| 5 | AH1-T merge | **PENDING** — B2 not authorized to merge per standing scope |

## Architect items — disposition

- **Item 4 (allow_director default flip).** NOT B2-applied. Brief's ratified design specifies `True` as default to match every pre-existing exemption (Director ratified 2026-05-06). Surfaced to AH1 in PR body for re-ratification decision.
- **Item 5 (bool-predicate companions on CallerContext).** NOT applied. Defer to F2 first additional `to_thread` site.
- **Item 6 (SSOT docstring overstated).** Partially applied in `f7a5a34` — docstring modested to accurately describe runtime state. `bus.py:264` itself untouched (out of 6-shape brief scope); flagged as F2 / follow-up consolidation candidate.

## In-flight observations

1. **Factory test fixture compensation.** Standalone `FastAPI()` in `test_authz_factory.py` skips app lifespan, so `_ensure_terminal_keys_loaded` autouse fixture explicitly calls `auth_lab.load_terminal_keys()` before each test. Idempotent — bus tests still go via app startup. 2nd-pass reviewer confirmed safe ordering with `_set_required_env`.

2. **Cursor type changes.** DELETE (bus.py:_delete) and ack (bus.py:_ack) inner functions switched from tuple-returning `conn.cursor()` to `conn.cursor(cursor_factory=RealDictCursor)` per brief Edit 6+7 to access `row["from_terminal"]` / `row["to_terminals"]` etc. 2nd-pass reviewer confirmed: SELECT columns are NOT NULL per schema, no missing-key risk on bare `row[...]` access.

3. **Conftest.py pre-existing `Optional` import gap.** First reviewer flagged `tests/conftest.py:28` uses `Optional[str]` without `from typing import Optional`. NOT introduced by this PR; brief explicitly says "Do NOT touch conftest.py". Pytest 72/72 passes today (Python 3.9, `from __future__ import annotations` defers evaluation). Latent issue if any tooling calls `get_type_hints()` — surface to AH1 as follow-up if Python version bump or stricter type-check tooling lands.

## Lessons applied (per brief Lessons section)

- **Function-signature verification** — every code edit verified against actual files (bus.py, authz.py, conftest.py, auth_lab.py). No guessed signatures.
- **Tier-A `/security-review` mandatory** — invoked via skill; verdict pasted in PR body. NO HIGH-CONFIDENCE issues.
- **Pin-not-vacuous test** — AC A9 executed locally, documented in PR body, NOT committed `False` flip.
- **In-place review-driven fix** — architect Item 6 fold landed as commit `f7a5a34` (docstring modesty), not append-only.
- **PEP 563 convention** — new `authz.py` uses `from __future__ import annotations` matching `bus.py:24`.

## Lessons learned this build

- **Architect REQUEST_CHANGES that contradict the brief's ratified design are NOT B2-applied.** Architect Item 4 (default flip) was a ratified design choice. B2 surfaced rather than overrode. Standing scope: "Execute briefs as written. No scope deviation without escalation back to AI Head A."
- **Out-of-scope architect findings.** `bus.py:264` is in dispatch force-fresh-context — NOT one of the 6 hand-rolled authz shapes the brief scoped. Architect's recommended fix would expand brief scope; B2 modested the docstring instead and flagged for F2.
- **Brief-scope conftest constraint.** Brief said "Do NOT touch conftest.py" → reviewer's pre-existing `Optional` import flag was not B2-actionable.

## Mailbox hygiene

Mailbox `briefs/_tasks/CODE_2_PENDING.md` will be flipped by AH1 on merge per `_ops/processes/b-code-dispatch-coordination.md` §3.

## Next steps for AH1

1. Decide on architect Item 4 (default flip): accept brief's ratified True default OR re-ratify with Director.
2. If Item 4 accepted as-is → AH1-T squash-merge PR #5.
3. Post-merge:
   - Verify Render auto-deploy succeeds (brisen-lab service).
   - Flip `briefs/_tasks/CODE_2_PENDING.md` → `CODE_2_COMPLETE.md`.
   - Optionally schedule follow-up tickets for architect Items 4, 5, 6 (bus.py:264 SSOT) and conftest.py `Optional` import.
