# B4 Ship Report — recommendation-check role-case fix

- **Brief:** recommendation-check.sh uppercase-BAKER_ROLE bug (lead-approved fast-follow, bus #8288; unblocked by AO_MATERIALITY_HOOK_1 close #8437)
- **Dispatched by:** lead (bus #8288) + Director "go build it" this session
- **Branch:** `b4/recommendation-check-role-case-fix`
- **PR:** #521
- **Commit:** 8fe32248

## Problem
`recommendation-check.sh` role exemption matched `BAKER_ROLE` lowercase only. Cowork/Terminal profiles export it uppercase (`BAKER_ROLE=B4`); a set-but-unmatched value skips the cwd fallback, so uppercase roles misfired the hook — demanded a `Recommendation:` line from b-code replies despite the Director 2026-05-29 exemption. Confirmed live: misfired on a b4 reply this session.

## Fix
Normalize `BAKER_ROLE` to lowercase before the `case` match (fixture + deployed user-global copy; drift test green).

## Bundled harness fixes (both latent-red on clean main, independent of role bug)
- `_additional_context` — parse the 2026-05-12 block-form `{decision,reason}` schema (retired `additionalContext` shape); was KeyError-ing whenever a hook fired.
- `_run_hook` — strip `BAKER_ROLE` so Director-facing "should fire" cases are deterministic off-CI.

## Coverage
Parametrized role exemption: `B4/B1/B5/CODEX/CODEX-ARCH/Architect` + lowercase silent; `lead` still fires. RED→GREEN (6 uppercase fails pre-fix).

## Verification (literal)
```
python3 -m pytest tests/test_stop_hooks.py -q
26 passed, 2 failed
```

## Pre-existing failures (out of scope — escalated to lead)
Both fire `False` on clean `main` hermetically; both stale tests encoding pre-2026-05-12 behavior:
1. `test_recommendation_check_warns_on_numbered_options_without_recommendation` — hook tightened 2026-05-12 so bare numbered list ≠ trigger (fixture L129-139).
2. `test_fail_loud_warns_on_shipped_without_verification` — same revision dropped bare status-words from fail-loud triggers (fixture L79-81).

Not touched to avoid scope creep into two different hooks' intended behavior. Lead to decide: update stale tests vs. re-widen hooks.

## Gate plan
codex G3 (medium) → lead merge.
