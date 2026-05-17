---
status: SHIPPED
pr: https://github.com/vallen300-bit/baker-master/pull/216
branch: b3/render-env-write-guard-1
commit: 7611276
shipped_at: 2026-05-17T15:00:00Z
ship_report: briefs/_reports/B3_render_env_write_guard_1_20260517.md
brief: briefs/BRIEF_RENDER_ENV_WRITE_GUARD_1.md
brief_id: RENDER_ENV_WRITE_GUARD_1
trigger_class: LOW-MEDIUM (new operator-side tooling; no runtime path; mandatory 2nd-pass NOT triggered unless tests touch external surface)
target_branch: b3/render-env-write-guard-1
matter_slug: baker-internal
cross_matter_usage: [baker-internal]
dispatched_at: 2026-05-17T14:40:00Z
dispatched_by: AH1
director_auth: 2026-05-17 chat — "dispatch" (post Tier-B bundle authorization + brief review)
prior_brief_complete: |
  BAKER_WA_DIRECTOR_FILTER_1 shipped as PR #208 (merge_commit 8ca850e,
  2026-05-16T13:19:28Z, ah1_merge_msg bus #303). This dispatch
  overwrites the mailbox slot with the new brief.
---

# Dispatch: RENDER_ENV_WRITE_GUARD_1

B3 — full brief at `briefs/BRIEF_RENDER_ENV_WRITE_GUARD_1.md`.

**TL;DR:** Add a safe Python utility for Render env-var writes that forces single-key merge-mode PUT and rejects array-form PUT. Prevents recurrence of today's catastrophic env-var wipe on `baker-master` (32 vars → 0). New `tools/render_env_guard.py` + tests + rules-doc update.

**Working dir:** `~/bm-b3`
**Branch:** `b3/render-env-write-guard-1` off `main`
**Estimated touch:** 2 prod files (~80 LOC: new module + rules-doc update) + 1 test file (~50 LOC).
**Trigger class:** LOW-MEDIUM (no runtime path; operator-side tooling; touches Render API surface concept but not Render API itself).
**Estimated time:** ~2-3 hours.

## Pre-flight

1. `cd ~/bm-b3 && git fetch origin main && git checkout main && git pull --ff-only`.
2. Read `briefs/BRIEF_RENDER_ENV_WRITE_GUARD_1.md` end-to-end.
3. Read `.claude/rules/python-backend.md` to see existing rule entry being pointed to.
4. Read `_ops/agents/ai-head/LONGTERM.md` Render section to see canonical pattern this utility codifies.

## Ship gate

Literal `pytest tests/test_render_env_guard.py -v` output in ship report. NO "by inspection".

## Reporting

- Bus-post `lead` (AH1) on PR open with topic `pr-open/render-env-write-guard-1`.
- AH1 runs cross-lane review chain (AH2 static + judgment call on `/security-review`). Trigger-class LOW-MEDIUM — if AH1 judgment fires the 2nd-pass `feature-dev:code-reviewer`, it'll be parallel with AH2 static.

## Co-Authored-By

```
Co-authored-by: Code Brisen #3 <b3@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
