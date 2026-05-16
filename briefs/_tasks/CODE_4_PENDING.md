---
status: PENDING
brief: briefs/BRIEF_CLAIMSMAX_API_CAPABILITY_1.md
brief_id: CLAIMSMAX_API_CAPABILITY_1
trigger_class: MEDIUM (new external API surface + new MCP tools + new migration; mandatory 2nd-pass review)
target_branch: b4/claimsmax-api-capability-1
matter_slug: claimsmax
cross_matter_usage: [mo-vie-am, hagenauer-rg7, cupial, ao, baker-internal]
dispatched_at: 2026-05-16T20:55:00Z
dispatched_by: AH1
director_auth: 2026-05-16 chat — "Please go ahead and write it into Baker's as a permanent capability"
prior_brief_complete: |
  PM_STATE_UPDATE_PATCH_NOT_PARALLEL_1 shipped as PR #209 (merge_commit
  a13b2c9, 2026-05-16T13:30:00Z, ah1_merge_msg bus #305). Ship report
  preserved in briefs/_reports/B4_PM_STATE_UPDATE_PATCH_NOT_PARALLEL_1_20260516.md.
  This dispatch overwrites the mailbox slot with the new brief.
---

# Dispatch: CLAIMSMAX_API_CAPABILITY_1

B4 — full brief at `briefs/BRIEF_CLAIMSMAX_API_CAPABILITY_1.md`.

**TL;DR:** Wire the ClaimsMax v1 REST API (`https://brisen.claimsmax.co.uk/api/v1/`) into Baker as a permanent capability. New client in `kbl/claimsmax_client.py`, 4 MCP tools in `tools/claimsmax.py`, capability-set migration, tests, doc update. Auth via `CLAIMSMAX_API_KEY` env var (AH1 sets in Render before merge). Skip `/ask` — vendor bug pending Ellie Technologies fix.

**Working dir:** `~/bm-b4`
**Branch:** `b4/claimsmax-api-capability-1` off `main`
**Estimated touch:** ~8 files, ~400 LOC including tests + migration.
**Trigger class:** MEDIUM (mandatory 2nd-pass review per gate protocol — `/security-review` mandatory).

## Pre-flight

1. `git pull --ff-only origin main` in `~/bm-b4`.
2. Read `briefs/BRIEF_CLAIMSMAX_API_CAPABILITY_1.md` end-to-end.
3. Read `~/Desktop/ClaimsMaxAPI.md` for the full API spec.

## Reporting

- Bus-post `lead` (AH1) on PR open with topic `pr-open/claimsmax-api-capability-1`.
- AH1 runs `/security-review` (mandatory per Lesson #52 and trigger-class MEDIUM) + `/code-review`.
- AH1 sets Render env var `CLAIMSMAX_API_KEY` before merge (separate Tier B action).
- AH1 merges on green; runs one live smoke test against prod deploy.

## Co-Authored-By

```
Co-authored-by: Code Brisen #4 <b4@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
