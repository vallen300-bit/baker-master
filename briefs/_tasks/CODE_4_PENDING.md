---
status: PENDING
dispatched_at: 2026-05-25T10:45:00Z
dispatched_by: lead
target: b4
brief: briefs/BRIEF_GMAIL_ATTACHMENT_VISIBILITY_PATCH_1.md
brief_id: GMAIL_ATTACHMENT_VISIBILITY_PATCH_1
type: visibility-only backend patch (no behavior change)
target_repo: baker-master (single repo)
matter_slug: baker-internal
extends: GMAIL_POLLING_DIAGNOSTIC_1 (b4's diagnostic report — `briefs/_reports/B4_gmail_polling_diagnostic_1_20260525.md`, commit d3c23bf)
reply_target: lead (AH1)
expected_time: ~20-30 min
complexity: Low
heartbeat_cadence: 30 min (small brief — flag if not shipped within 1h)
gate_chain: Gate-1+2 lead | Gate-3 SKIP | Gate-4 SKIP (≤30 LOC backend-only) | Gate-5 lead merge | post-deploy WARN observation lead
---

# DISPATCH: GMAIL_ATTACHMENT_VISIBILITY_PATCH_1 → b4

Read the brief at `briefs/BRIEF_GMAIL_ATTACHMENT_VISIBILITY_PATCH_1.md` for the full spec (4 fixes, ~30 LOC, zero behavior change).

## TL;DR

Surface the silent-swallow that's hiding the 9-day `documents` write blackout for `email:%` source paths.

- **Fix 1 (CRITICAL):** add `import logging` to `scripts/extract_gmail.py`. Lead caught this on top of your diagnostic — file calls `logging.getLogger(...)` 5 times but never imports `logging`. Every call raises NameError, swallowed by `format_thread:449`'s wholesale `except`. Without this fix, the debug→warning conversion is a no-op.
- **Fix 2:** convert 4 silent `.debug(...)` calls to `.warning(...)` with structured `err_type={type(e).__name__}` token.
- **Fix 3:** convert `format_thread:449` wholesale `except Exception: pass` to logged WARNING with same `err_type=` token.
- **Fix 4:** add 1 new pytest test file `tests/test_extract_gmail_visibility.py` using `caplog` fixture. 2 test funcs (1 may need `@pytest.mark.skip` marker per brief Key Constraints).

## Sequencing

1. `cd ~/bm-b4 && git fetch origin main && git checkout main && git pull --ff-only`
2. `git checkout -b b4/gmail-attachment-visibility-patch-1`
3. Read full brief at `briefs/BRIEF_GMAIL_ATTACHMENT_VISIBILITY_PATCH_1.md` — all 4 fixes have exact line numbers, copy-pasteable code snippets, Verification commands.
4. Apply Fixes 1-4 in order. Run grep verifications after each fix per the brief.
5. `pytest tests/test_extract_gmail_visibility.py -v` — capture literal output.
6. `pytest tests/ -x` — full suite no regressions.
7. `bash scripts/check_singletons.sh` — singleton CI guard.
8. `git add scripts/extract_gmail.py tests/test_extract_gmail_visibility.py && git commit -m "GMAIL_ATTACHMENT_VISIBILITY_PATCH_1: ..."`
9. `git push origin b4/gmail-attachment-visibility-patch-1 && gh pr create --title "GMAIL_ATTACHMENT_VISIBILITY_PATCH_1 — surface silent-swallow in extract_gmail.py" --body "..."`
10. Bus-post ship report to `lead` with topic `ship/gmail-attachment-visibility-patch-1`. Include: PR number, commit SHA, **literal** pytest output, **literal** grep counts.

## Confirmation phrase

`"B4 oriented. Read: CODE_4_PENDING.md, MEMORY.md."`

## Reply target

Post your ship report bus message to **lead (AH1)** with topic `ship/gmail-attachment-visibility-patch-1`. Lead runs Gates 1+2 + 5 (merge) + post-deploy WARN observation. No Gate-3 (no install/picker change). No Gate-4 (≤30 LOC backend-only, no auth/DB/concurrency surface).

If you discover a defect outside Fixes 1-4 scope during pre-flight, DO NOT scope-creep. Surface to lead as bus reply with `blocker/<reason>` or `ambiguity/<topic>` topic — lead writes follow-up brief.

— lead (AH1) 2026-05-25 ~10:45Z
