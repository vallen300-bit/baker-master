---
status: COMPLETE
brief: briefs/BRIEF_DEADLINE_MATTER_SLUG_BACKFILL_1.md
brief_id: DEADLINE_MATTER_SLUG_BACKFILL_1
trigger_class: TIER_B_BACKFILL_+_WRITE_PATH_CLOSURE
dispatched_at: 2026-05-13
dispatched_by: ai-head-1 (AH1)
target: b3
mandatory_2nd_pass: false
security_review_required: false
effort_estimate: ~3h
predecessor:
  brief: briefs/BRIEF_DEADLINE_ASSIGNED_TO_BACKFILL_1.md
  pr: 199
  merge_commit: 7e0751619621aba510c9c29bdbe5952871f4bfc3
director_ratification: |
  2026-05-13: "keep off, build a matter slug" — green light for the matter_slug
  capability (Scope A write-path closure + Scope B retroactive backfill). Scanner
  stays OFF (VAULT_SCANNER_ENABLED=false, flipped back from b3's post-merge true
  by AH1 in same Director turn). Scanner re-enables only after Director ratifies
  the Scope B dry-run M-bucket.
scope_summary:
  scope_a: |
    Wire _match_matter_slug() into 3 deadline write-paths currently bypassing it:
      A1. models/deadlines.insert_deadline() — add matter_slug param
      A2. models/cortex.cortex_create_deadline() — pass-through param
      A3. baker_mcp/baker_mcp_server.py baker_add_deadline — compute before MCP call
      A4. triggers/clickup_trigger.py — compute + add to direct INSERT
  scope_b: |
    scripts/backfill_matter_slug.py — dry-run-default backfill of 69 NULL rows.
    Mirror b3's prior backfill_assigned_to.py pattern (3 safety rails + idempotent
    WHERE matter_slug IS NULL). Per-row SAVEPOINT pattern fixes the predecessor
    v2_followup (mid-batch error drops prior successful UPDATEs).
  part_h: |
    Invocation-path audit table in brief enumerates all 10 doors with pre/post
    status. Scope A closes doors 5-8.
ship_gate: literal pytest -v output paste in ship report; check_singletons PASS
bus_topic: ship/DEADLINE_MATTER_SLUG_BACKFILL_1
---

# CODE_3_PENDING — DEADLINE_MATTER_SLUG_BACKFILL_1

Read `briefs/BRIEF_DEADLINE_MATTER_SLUG_BACKFILL_1.md` for full spec.

## Confirmation phrase

On session start, reply: `"B3 oriented. Read: CODE_3_PENDING.md, MEMORY.md."`

## Working dir
`~/bm-b3` — branch off `main` after `git pull --ff-only`. Suggested branch name: `b3-matter-slug-backfill`.

## What ships
1. **Scope A** — 4 file edits (models/deadlines.py, models/cortex.py, baker_mcp/baker_mcp_server.py, triggers/clickup_trigger.py) + new test file `tests/test_deadline_matter_slug_writepath.py` (≥4 tests).
2. **Scope B** — new `scripts/backfill_matter_slug.py` mirroring `scripts/backfill_assigned_to.py` with the per-row savepoint fix + new test file `tests/test_backfill_matter_slug.py` (≥4 tests).
3. **Dry-run executed** before opening PR. Proposal file committed at `briefs/_reports/B3_backfill_matter_slug_<UTC-ts>.md`.
4. **Ship report** at `briefs/_reports/B3_DEADLINE_MATTER_SLUG_BACKFILL_1_<date>.md` with literal pytest paste + bucket counts.

## What does NOT ship (AH1 owns)
- Executing `--apply` against production. AH1 surfaces M-bucket to Director, ratifies, then applies from a fresh `git pull --rebase origin main` checkout.
- Render env flip back to `VAULT_SCANNER_ENABLED=true`. AH1 executes after successful `--apply`.
- Vault append (deadline-system-contract-v1.md v1.6 execution log) — stage uncommitted; Mac-Mini / Director commits per CHANDA Inv 9.

## Bus post on ship
```bash
BAKER_ROLE=b3 ~/Desktop/baker-code/scripts/bus_post.sh lead \
  "PR #<N> OPEN — DEADLINE_MATTER_SLUG_BACKFILL_1 (Scope A write-path closure + Scope B backfill). <K>/<K> tests PASS. check_singletons PASS. Dry-run executed: bucket counts M=<m>/A=<a>/U=<u>. PR: https://github.com/vallen300-bit/baker-master/pull/<N>. Ship report: briefs/_reports/B3_DEADLINE_MATTER_SLUG_BACKFILL_1_<date>.md . Dry-run output preserved: briefs/_reports/B3_backfill_matter_slug_<ts>.md ." \
  ship/DEADLINE_MATTER_SLUG_BACKFILL_1
```

## Predecessor lessons carried forward
1. Per-row SAVEPOINT pattern (your prior v2_followup) — fixes mid-batch error drop bug
2. 3 safety rails on `--apply` (file <24h, all-rows-populated, env override) — copy verbatim from backfill_assigned_to.py
3. Idempotent WHERE clause (`matter_slug IS NULL`) — re-runnable safely
4. Singleton hook compliance — `SentinelStoreBack._get_global_instance()` only
5. No DDL — column exists already as TEXT nullable (verified models/deadlines.py:99)
6. /security-review NOT required (no external surface)
7. mandatory_2nd_pass FALSE (no auth, no DB schema, no operation-ordering primitive)
