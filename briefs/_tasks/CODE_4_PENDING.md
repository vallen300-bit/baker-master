---
status: COMPLETE
brief: briefs/BRIEF_REPORT_RENDERER_SLUG_HARDEN_1.md
brief_id: REPORT_RENDERER_SLUG_HARDEN_1
trigger_class: LOW (single-function harden + 1 test; no auth/DB/external surface)
target_branch: b4/report-renderer-slug-harden-1
matter_slug: claimsmax
cross_matter_usage: [mo-vie-am, hagenauer-rg7, cupial, ao, baker-internal]
dispatched_at: 2026-05-17T14:35:00Z
dispatched_by: AH1
director_auth: 2026-05-17 chat — "go" (Tier-B fast-follow bundle authorization)
shipped_at: 2026-05-17T14:48:00Z
pr: https://github.com/vallen300-bit/baker-master/pull/215
commit: 4296cbc
ship_report: briefs/_reports/B4_REPORT_RENDERER_SLUG_HARDEN_1_20260517.md
prior_brief_complete: |
  CLAIMSMAX_API_CAPABILITY_1 shipped as PR #213 (merge_commit 3cbc287,
  2026-05-17T11:30:59Z, ah1_merge_msg bus #333). Ship report preserved in
  briefs/_reports/B4_CLAIMSMAX_API_CAPABILITY_1_20260517.md. This dispatch
  overwrites the mailbox slot with the fast-follow brief F1.
---

# Dispatch: REPORT_RENDERER_SLUG_HARDEN_1

B4 — full brief at `briefs/BRIEF_REPORT_RENDERER_SLUG_HARDEN_1.md`.

**TL;DR:** Tighten `_matter_slug_from_json_path` in `kbl/report_renderer.py` to pass the recovered slug through the existing `_validate_safe_slug` validator before returning. Fall back to `"misc"` on validation failure. One function, ~5 LOC change + ~4 test cases. Closes AH2 cross-lane review #331 LOW on PR #213.

**Working dir:** `~/bm-b4`
**Branch:** `b4/report-renderer-slug-harden-1` off `main`
**Estimated touch:** 1 prod file (~5 LOC) + 1 test file (~30 LOC).
**Trigger class:** LOW (single-function harden; no auth/DB/external surface).
**Estimated time:** ~15 min.

## Pre-flight

1. `cd ~/bm-b4 && git fetch origin main && git checkout main && git pull --ff-only`.
2. Read `briefs/BRIEF_REPORT_RENDERER_SLUG_HARDEN_1.md` end-to-end.
3. Read `kbl/report_renderer.py:70-95` (the existing `_validate_safe_slug` helper) + lines 314-326 (the function being hardened).

## Ship gate

Literal `pytest tests/test_report_renderer.py -v` output in ship report. NO "by inspection".

## Reporting

- Bus-post `lead` (AH1) on PR open with topic `pr-open/report-renderer-slug-harden-1`.
- AH1 runs cross-lane review chain (AH2 static review; `/security-review` skip-eligible per trigger-class LOW). If AH2 returns PASS-WITH-NITS or PASS, AH1 merges.

## Co-Authored-By

```
Co-authored-by: Code Brisen #4 <b4@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
