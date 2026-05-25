---
status: PENDING
dispatched_at: 2026-05-25T16:40:00Z
dispatched_by: deputy
target: b4
brief: briefs/BRIEF_SUBSTACK_NATE_PATCH_1.md
brief_id: SUBSTACK_NATE_PATCH_1
reply_target: deputy (AH2) — cc lead
expected_time: ~1h
complexity: Low
---

# CODE_4_PENDING — SUBSTACK_NATE_PATCH_1

## TL;DR

Patch 3 line-anchored defects in PR #248 (SUBSTACK_NATE_INGEST_1, merged @ `eeca2e09`) surfaced by deputy's retro security + code-review gate. Two HIGH (timeout missing on Gmail call → polling-loop stall risk; unbounded pagination in backfill → runaway risk), one MEDIUM (List-Id substring-match → spoofable). Full spec in `briefs/BRIEF_SUBSTACK_NATE_PATCH_1.md`.

## Files

- `triggers/substack_ingest.py` — Fix 1 (10s timeout on `fetch_full_message`) + Fix 3 (tighten `_LIST_ID_RE` to `\bpost\.natesnewsletter\.substack\.com\b`)
- `scripts/backfill_nate_substack.py` — Fix 2 (`MAX_PAGES = 200` guard)
- `tests/test_substack_ingest.py` — 3 new tests (one per fix)

## Ship gate

- Literal `pytest tests/test_substack_ingest.py -v` output in PR body. **18 passed** required (15 existing + 3 new).
- Syntax check per QC1.
- `bash scripts/check_singletons.sh` clean.
- `python3 scripts/backfill_nate_substack.py --dry-run --days 7` runs without traceback.
- Reply to deputy on ship (CC lead). Deputy gates + merges per AH2 deputy lane (Director-ratified 2026-05-24).

## Constraint reminders

- Do NOT touch `scripts/extract_gmail.py` or `triggers/email_trigger.py`. Patch is scoped to the 2 ingest files + tests only.
- Do NOT add a `--max-pages` CLI flag (scope creep).
- The existing 15 tests MUST still pass — verify after each edit.
