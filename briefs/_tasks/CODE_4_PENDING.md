---
status: PENDING
dispatched_at: 2026-05-25T11:46:00Z
dispatched_by: lead
target: b4
brief: briefs/BRIEF_GMAIL_ATTACHMENT_VISIBILITY_V2_1.md
brief_id: GMAIL_ATTACHMENT_VISIBILITY_V2_1
type: visibility-only backend patch (no behavior change) + 1 silent-debug→warning conversion in backfill script
target_repo: baker-master (single repo)
matter_slug: baker-internal
extends: GMAIL_ATTACHMENT_VISIBILITY_PATCH_1 (V1 merged PR #259 11:00:44Z, FAILURE-path visibility; V2 adds SKIP-path visibility + fixes backfill silent-swallow)
reply_target: lead (AH1)
expected_time: ~30-45 min
complexity: Low
heartbeat_cadence: 30 min (small brief — flag if not shipped within 1h)
gate_chain: Gate-1+2 lead | Gate-3 SKIP | Gate-4 SKIP (≤30 LOC backend-only) | Gate-5 lead merge | post-merge lead re-triggers backfill + observes SKIP/FAILED log distribution
queued_after_this: CAPABILITY_RUNNER_COST_RUNAWAY_DIAGNOSTIC_1 (peer-defect; brief authored at ~/baker-vault/_ops/briefs/BRIEF_CAPABILITY_RUNNER_COST_RUNAWAY_DIAGNOSTIC_1.md; will dispatch to b4 once V2 ships)
---

# DISPATCH: GMAIL_ATTACHMENT_VISIBILITY_V2_1 → b4

Read the brief at `briefs/BRIEF_GMAIL_ATTACHMENT_VISIBILITY_V2_1.md` for the full spec (3 fixes, ~30 LOC, zero behavior change).

## TL;DR

V1 deployed cleanly. Lead triggered 9-day backfill post-V1 — 692 emails checked, 1 missing found, 0 stored, ZERO err_type WARNs. But lead's spot-check confirms Hagenauer "water damage" 2026-05-21 (id `19e4aefec5c46b97`, 2 attachments per Gmail API) has NO documents row. So the underlying defect is NOT in the V1-patched exception paths — it's in the SKIP paths upstream, AND in the backfill script's own silent-swallow.

3 fixes — all spelled out in the brief with exact line numbers + copy-pasteable code:

- **Fix 1**: add 6 `.info()` calls to `extract_attachments_text` SKIP paths (no_attachment_parts / unsupported_ext / oversize / inline_no_data / inline_extractor_returned_none / gmail_returned_empty_data / api_extractor_returned_none). Reason= token is the diagnostic key — keep exactly as specified.
- **Fix 2**: convert `scripts/backfill_missed_attachments.py:87-88` silent `.debug` to `.warning` with err_type token (SAME anti-pattern V1 fixed in extract_gmail.py).
- **Fix 3**: 1 new unit test appended to existing `tests/test_extract_gmail_visibility.py` (covers unsupported_ext SKIP path).

## Sequencing

1. `cd ~/bm-b4 && git fetch origin main && git checkout main && git pull --ff-only` (HEAD must include PR #259 squash 45ba6c7 + the new b4 mailbox flip)
2. `git checkout -b b4/gmail-attachment-visibility-v2-1`
3. Read full brief at `briefs/BRIEF_GMAIL_ATTACHMENT_VISIBILITY_V2_1.md`
4. Apply Fixes 1-3 in order; run grep verifications after each per brief
5. `pytest tests/test_extract_gmail_visibility.py -v` → expect 3 passed
6. `pytest tests/ -x` clean
7. `bash scripts/check_singletons.sh`
8. `git add scripts/extract_gmail.py scripts/backfill_missed_attachments.py tests/test_extract_gmail_visibility.py && git commit -m "GMAIL_ATTACHMENT_VISIBILITY_V2_1: ..."`
9. `git push origin b4/gmail-attachment-visibility-v2-1 && gh pr create`
10. Bus-post ship report to `lead` with topic `ship/gmail-attachment-visibility-v2-1` — include PR number, commit SHA, LITERAL pytest output, LITERAL grep counts (warning, info, reason, SKIP, debug).

## Confirmation phrase

`"B4 oriented. Read: CODE_4_PENDING.md, MEMORY.md."`

## Reply target

Post your ship report bus message to **lead (AH1)** with topic `ship/gmail-attachment-visibility-v2-1`. Lead runs Gates 1+2 + 5 (merge) + post-merge re-trigger of backfill + observation of SKIP/FAILED log distribution.

If you discover a defect outside Fixes 1-3 scope during pre-flight, DO NOT scope-creep. Surface to lead as bus reply with `blocker/<reason>` or `ambiguity/<topic>` topic.

Heartbeat 30 min. Flag to lead if not shipped within 1h.

— lead (AH1) 2026-05-25 ~11:46Z
