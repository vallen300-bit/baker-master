---
brief: briefs/BRIEF_BRISEN_LAB_AUTH_COMPLETION_1.md
brief_version: V0.4 (V0.5 §T doc-prose fold)
scope: F1 ONLY — recipient-bound authz on GET /msg/{terminal}
trigger_class: TIER_A_AUTH_TOUCHING
claimed_at: 2026-05-06T~09:46Z
claimed_by: b2
target_repo: vallen300-bit/brisen-lab
target_branch: b2/brisen-lab-auth-completion-1
pr: https://github.com/vallen300-bit/brisen-lab/pull/4
head_sha: c7e4200
gates_b2_self_invoked:
  architect_post_write: PASS-WITH-NITS (3 LOW, none blocking)
  code_reviewer_standard: PASS-WITH-NITS (2 LOW — folded)
  code_reviewer_auth_2nd_pass: PASS-WITH-NITS (2 LOW, non-blocking)
gates_pending_external:
  security_review: AH2 lane (AC A13 — mandatory auth-touching)
  b1_situational_review: B1 lane (auth-trigger per ai_head_b1_review_triggers.md)
ship_gate: A1+A3+A4+A12+A14 GREEN; A2 regression-verified; A5+A6 pending prod deploy; A13 pending AH2
variant_determination: Variant B (pre-edit clauses bare; SQL OR-branch added per V0.3 §K)
---

# B2 Ship Report — BRIEF_BRISEN_LAB_AUTH_COMPLETION_1 F1 — 2026-05-06

## Bottom line

F1 (recipient-bound authz on `GET /msg/{terminal}`) implemented + reviewed +
PR opened. Variant B confirmed and SQL OR-branch added per V0.3 §K. All 8
brief-mandated tests GREEN; full suite has 3 pre-existing pytest-asyncio
failures unrelated to F1 (verified on clean `main`).

PR #4 awaits AH2 `/security-review` (AC A13) + B1 situational review.

## Diff

```
 bus.py                              |   8 +++++++-
 tests/test_inbox_read_authz.py      | 190 ++++++++++++++++++++++++++++ (new)
 2 files changed, 197 insertions(+), 1 deletion(-)
```

`bus.py` change (one logical edit, two lines):

```diff
@@ get_msg
         reader_slug = _require_worker_slug(x_terminal_key)
+        # F1: caller must be the addressed terminal (closes horizontal-privilege
+        # peek hole — pre-fix, any valid terminal-key could read any inbox).
+        # Broadcasts (to_terminals=['*']) reach the caller via the OR-branch in
+        # the SQL clause below; no per-call exemption needed here.
+        if reader_slug != terminal:
+            raise HTTPException(status_code=403, detail="reader_slug_mismatch")
         if kind is not None and kind not in VALID_KINDS:
             raise HTTPException(status_code=400, detail=f"bad_kind:{kind}")
@@ SQL clause-builder
-        clauses = ["%s = ANY(to_terminals)"]
+        clauses = ["(%s = ANY(to_terminals) OR '*' = ANY(to_terminals))"]
         params: list[Any] = [terminal]
```

## Variant determination (AC A14)

**Variant B** confirmed during EXPLORE step. Pre-edit `bus.py:313` had:
```python
clauses = ["%s = ANY(to_terminals)"]
```
No `OR '*' = ANY(to_terminals)` branch. Without F1's SQL extension, the
recipient-bind 403 gate would silently drop every `to_terminals=['*']`
broadcast delivery to self-readers (a regression). Edit 1 expands per
V0.3 §K to add the OR-branch.

## Tests

### New file `tests/test_inbox_read_authz.py` — 8 tests per V0.4 §L+§M

Literal pytest output (last run after standard-pass nit fold):

```
tests/test_inbox_read_authz.py::test_get_msg_self_succeeds PASSED        [ 12%]
tests/test_inbox_read_authz.py::test_get_msg_cross_terminal_403 PASSED   [ 25%]
tests/test_inbox_read_authz.py::test_get_msg_no_key_401 PASSED           [ 37%]
tests/test_inbox_read_authz.py::test_get_msg_self_broadcast_succeeds PASSED [ 50%]
tests/test_inbox_read_authz.py::test_ack_self_addressed_succeeds PASSED  [ 62%]
tests/test_inbox_read_authz.py::test_ack_not_in_recipients_403 PASSED    [ 75%]
tests/test_inbox_read_authz.py::test_get_msg_cross_slug_attack_403 PASSED [ 87%]
tests/test_inbox_read_authz.py::test_ack_director_exemption_succeeds PASSED [100%]
======================== 8 passed, 2 warnings in 54.43s ========================
```

### Full suite — 46 passed, 3 pre-existing failures, 1 skipped

```
======= 3 failed, 46 passed, 1 skipped, 5 warnings in 362.14s (0:06:02) ========
FAILED tests/test_a10_a14_lifecycle.py::test_a14_h4_threshold_triggers_hermes
FAILED tests/test_review_fixes_2026_05_05.py::test_fix2_emit_freeze_broadcast_is_async
FAILED tests/test_review_fixes_2026_05_05.py::test_fix3_confirm_idle_pops_flow
```

The 3 failures all use `@pytest.mark.asyncio` against a `pytest-asyncio` plugin
that is not in `requirements.txt`. **Verified pre-existing** by running the
same 3 tests on clean `main` (without F1 changes): same 3 failed. Not
introduced by F1; orthogonal infra gap. Flagging for future cleanup, not
blocking.

## Review chain run by B2 (Tier-A AUTH-TOUCHING)

| Gate | Verdict | Findings |
|---|---|---|
| feature-dev:code-architect post-WRITE | **PASS-WITH-NITS** | 3 LOW (test 7 restore-None edge; GET /event/{id}/full out-of-scope confirmation; broadcast helper cleanup). All non-blocking. |
| feature-dev:code-reviewer standard pass | **PASS-WITH-NITS** | 2 LOW — folded inline before commit (tests 5 + 8 now `assert r.json().get("ok") is True`). |
| feature-dev:code-reviewer auth-trigger 2nd pass | **PASS-WITH-NITS** | 2 LOW: (a) `_seed_broadcast` test isolation fragility for hypothetical future parallelization; (b) dead `# noqa: PLC0415` tag (no pylint config in repo, but conftest.py uses same convention so left for consistency). Non-blocking. |

Auth-specific 2nd-pass coverage confirmed:
- Cross-peek closed; self-read + broadcast both pass.
- Path-traversal payloads (`%2F`) — FastAPI decodes; no novel surface.
- Case-sensitivity bypass — slugs canonical lowercase; not a vector.
- Header injection — Starlette joins duplicate headers with comma; no key match.
- Timing channel — 403 fires pre-SQL; no enumeration oracle (attacker already
  knows their own valid key resolves to a specific slug).
- 403 body leaks no enumerable info (`reader_slug_mismatch` is a fixed
  literal; reader_slug + terminal not echoed).
- `auth_lab._TERMINAL_KEYS` mutation in test 7 acceptable given try/finally
  cleanup; constant-time `hmac.compare_digest` semantics preserved.

## V0.4 §L parenthetical mechanism note (surfaced to AH1 in PR body)

The brief V0.4 §L parenthetical for test 7 says "insert into test DB worker
registry". There is no such DB table — terminal keys live in
`auth_lab._TERMINAL_KEYS` (process-memory module dict, populated from
`BRISEN_LAB_TERMINAL_KEYS` env JSON at startup; see `auth_lab.py:48-69`).

Test 7 satisfies the brief's INTENT (use a valid third-slug key, expect 403
not 401) by mutating that module dict in-process with try/finally restore.
Architect + 2nd-pass reviewer both ratified the approach. Surfaced in PR
body for AH1 awareness; not a STOP-and-escalate level fact-error per the
brief's own classification (the amendments' substantive claims about F1
behavior are correct; only the test-implementation mechanism description
is imprecise).

## Acceptance Criteria status

| AC | Description | Status |
|---|---|---|
| A1 | 403 on `reader_slug != terminal`; broadcast OR-branch verified | ✅ Code + 8 tests |
| A2 | `bus.py:442-463` ack-authz REGRESSION-VERIFIED unchanged (Edit 2 struck) | ✅ Tests 5/6/8 verify `_is_director` exemption preserved |
| A3 | All 8 unit tests pass on `TEST_DATABASE_URL_BRISEN_LAB` | ✅ Literal pytest above |
| A4 | Existing brisen-lab test suite unchanged (no regressions) | ✅ 3 pre-existing async-plugin failures only; verified on clean main |
| A5 | Prod: `lead` → `/msg/cowork-ah1` returns 403 | ⏳ Pending PR merge + deploy |
| A6 | Prod: `lead` → `/msg/lead` returns 200 | ⏳ Pending PR merge + deploy |
| A12 | `feature-dev:code-reviewer` standard pass | ✅ PASS-WITH-NITS (folded) |
| A13 | `/security-review` standard pass | ⏳ AH2 lane |
| A14 | Variant determination in PR body | ✅ Variant B surfaced |

## Environment / setup notes for next B-code on this repo

- Python pinned 3.12 (per repo `start.sh` + `render.yaml`); /usr/bin/python3
  is 3.9 — must `python3.12 -m venv .venv` for compat (Python 3.14 also fails
  due to psycopg2-binary 2.9.9 incompatibility).
- Test DB DSN at `op://Baker API Keys/TEST_DATABASE_URL_BRISEN_LAB/credential`.
- `pytest-asyncio` not in `requirements.txt`; 3 tests using
  `@pytest.mark.asyncio` skip silently as PytestUnknownMarkWarning →
  effectively-noop tests. Pre-existing on `main` since at least 2026-05-05.
  Out-of-scope for F1 but worth a separate fix.

## Next gates (B2 stopping)

1. AH2 runs `/security-review` on PR #4 (AC A13).
2. B1 runs situational review per auth-trigger.
3. AH1 reviews + merges after both pass.
4. AH1 verifies A5/A6 in prod via curl one-liners.
5. AH1 marks `briefs/_tasks/CODE_2_PENDING.md` status COMPLETE.

No autonomous polling. B2 standing by next dispatch.
