---
brief: BRIEF_BRISEN_LAB_RENDER_CONFIG_READ_1
builder: b4
filed_at: 2026-05-12
filed_under_authorization: lead bus msg #136 (topic authorize/v0-3-mailbox-flip)
note: Retrospective V0.3 completion report — closing housekeeping gap. Mailbox status flipped to COMPLETE at baker-master commit 8354b8b on 2026-05-11. This report files the ship narrative under briefs/_reports/ per standing PL ship-report contract.
status: COMPLETE
pr: https://github.com/vallen300-bit/brisen-lab/pull/9
pr_head_v0_1: 3e2fc3c8213b282cc763d81882eddc19adb61824
pr_head_v0_2: 58d17c4cd3758c83ac0518eabf9496be1d863511
pr_head_v0_3: b2eef4f05e971ae3c9b678ff0a97073fb4b418a3
merged_at: 2026-05-11T11:05:22Z
merge_commit: 96ed2702ef7a2a0ff77410452cfe45eba10eb103
post_merge_deploy: dep-d80rft67r5hc739squeg
env_var_put: RENDER_API_KEY on srv-d7q7kvlckfvc739l2e8g 2026-05-11 ~11:05Z
mailbox_flip_commit: 8354b8b (baker-master main, 2026-05-11 ~11:08Z)
aid_close_out_msg: 84
---

# B4 V0.3 ship — BRIEF_BRISEN_LAB_RENDER_CONFIG_READ_1

## Outcome

PR brisen-lab #9 merged 2026-05-11T11:05:22Z at commit `96ed2702`. Render env-var PUT (`RENDER_API_KEY` on `srv-d7q7kvlckfvc739l2e8g`) + auto-deploy `dep-d80rft67r5hc739squeg` landed ~11:08Z. 6/6 live smoke tests GREEN.

## Live smoke (post-deploy)

1. AID list services → 200 (count=4)
2. AID env-vars on baker-master → 200 (count=67, BAKER_VAULT_PATH visible at correct value)
3. lead list services → 200
4. b1 list services → 403 `not_authorized_for_render_config`
5. no key → 401 `bad_terminal_key`
6. malformed service-id → 400 `invalid_service_id`

## Gate chain (V0.1 → V0.3)

| Version | Gate 1 (B4 pytest) | Gate 2 (AH2 /security-review) | Gate 3 (AH1 architect) | Gate 4 (AH1 code-reviewer 2nd-pass) |
|---|---|---|---|---|
| V0.1 | GREEN | PASS-WITH-CONCERNS (1H + 3M + 1L → folded F1-F4) | PASS-WITH-CONCERNS (structural MED deferred) | PASS-WITH-NITS (convergent MEDs folded) |
| V0.2 | GREEN (25/25 + 109/1-skipped) | NOT RUN (AH2 idle past ultimatum; AH1 proceeded per AID v1.1 §4) | SKIPPED (shape unchanged) | PASS-WITH-NITS (Gate 4 M1 → folded F5 in V0.3) |
| V0.3 | GREEN | SKIPPED (3-line fault-tolerance patch on cleared surface) | n/a | PASS clean |

## Folds folded

- **F1** (V0.2, Gate 2 HIGH): bus_audit emission threaded through `render_config.register()` on `/render/services` reads (services + env-vars). Mirror to `list_services`. +2 tests.
- **F2** (V0.2): tighten service_id regex to `^srv-[A-Za-z0-9_-]+$` with `fullmatch`. +3 tests for `?`, `#`, `%`.
- **F3** (V0.2): httpx-level tests — `TimeoutException` → 504, `HTTPError` → 502. +2 tests.
- **F4** (V0.2): drop dead `allow_director=False` kwarg from both `Depends()` calls (no-op under AUTH_ONLY per `authz.py:161-162`). +1-line comment each.
- **F5** (V0.3, Gate 4 V0.2 MED M1): wrap each `await audit_emitter(...)` call in `render_config.py` (`list_services` ~L153-161 + `get_env_vars` ~L191-200) in try/except. On audit failure log to stderr ("[render_config] audit emit failed: ...") + continue — successful Render read still returns 200. +1 test (`test_envvars_read_returns_200_when_audit_emitter_raises`).

## Acceptance criteria

ACs A1-A18 all GREEN. Full enumeration in mailbox `briefs/_tasks/CODE_4_PENDING.md` at commit `8354b8b` (now overwritten by codex-judge STAGED dispatch; recoverable via `git show 8354b8b -- briefs/_tasks/CODE_4_PENDING.md`).

## Deferred (NOT in this brief)

- Depends-layer whitelist via `Policy` enum (architect V0.1 MED — structural).
- Split env-vars endpoint into keys-only + per-key-audited (Gate 2 V0.1 MED#3 — design).
- httpx client pooling.
- Pagination truncated flag.
- `print()` → structured logger with otel context.
- Regex anchor cosmetic cleanup (Gate 4 V0.2 LOW L1 — indefinite defer).

## Anchors

- Director ratifications: V0.1 "go" 2026-05-11 ~08:30Z; V0.2 "go" 09:30Z; V0.3 "go" 10:35Z; merge "go" 11:00Z.
- AID close-out: bus msg #84 (endpoint live + example queries + service IDs; closes AID ask msg #59 — Render-MCP gap).
- Mailbox flip on baker-master main: `8354b8b` (2026-05-11 13:07:59 +0200).
- This report filed under authorization of lead bus msg #136 on 2026-05-12.

— B4
