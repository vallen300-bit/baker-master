---
status: PENDING
brief: briefs/BRIEF_RENDER_ENV_WIPE_PRECOMMIT_GUARD_1.md
brief_id: RENDER_ENV_WIPE_PRECOMMIT_GUARD_1
target_repo: baker-master
working_dir: ~/bm-b3
working_branch: b3/render-env-wipe-precommit-guard-1
matter_slug: baker-internal
cross_matter_usage: [all-matters — guards every Baker repo against env-wipe regressions]
dispatched_at: 2026-05-20T13:55:00Z
dispatched_by: lead
director_auth: 2026-05-20 chat — "go"
estimated_effort: ~45-60 builder-minutes
complexity: Low
priority: medium (closes the bypass gap left by 2026-05-17 runtime guard)
reply_target: lead (bus topic `ship/render-env-wipe-precommit-guard-1`)
---

# CODE_3_PENDING — RENDER_ENV_WIPE_PRECOMMIT_GUARD_1 — 2026-05-20

## What

Add **Part 4** to `.githooks/pre-commit` that blocks the 2026-05-17 env-wipe pattern (raw `PUT /v1/services/{id}/env-vars` with array body) at commit time. Layered above the runtime guard `tools.render_env_guard.safe_env_put()` (already shipped 2026-05-17 by you).

## Why you (B3)

You shipped the original runtime guard (`BRIEF_RENDER_ENV_WRITE_GUARD_1`, 2026-05-17). Same lane, same context. Estimated ~45-60 min.

## Brief

Full spec: `briefs/BRIEF_RENDER_ENV_WIPE_PRECOMMIT_GUARD_1.md` (read end-to-end before starting).

## Acceptance criteria (summary — full list in the brief)

1. `.githooks/pre-commit` gains Part 4 (insert AFTER Part 3's `fi`, BEFORE Part 1's `exec` — anything after the `exec` never runs).
2. New `tests/test_pre_commit_env_guard.py` covers 6 scenarios (3 positive — Python httpx array PUT, bash curl array PUT, single-key safe path baseline; 3 negative — `safe_env_put()` call, single-key URL, allowlisted file).
3. `.claude/rules/python-backend.md` Render env-vars rule gets a one-line append referencing Part 4.
4. Existing Parts 1-3 untouched + still functional (manual smoke on Part 2 OR Part 3 in ship report).
5. Literal `pytest tests/test_pre_commit_env_guard.py -v` green — paste full output in ship report.
6. Manual POSITIVE smoke on Part 4 itself — throwaway fixture blocks the commit, then cleaned up.

## Ship gate

- Literal pytest output in PR description (no "pass by inspection").
- Manual Part-4 POSITIVE smoke captured (throwaway fixture blocked → reverted) noted in ship report.
- `git config core.hooksPath` still returns `.githooks`.

## Reporting (bus reply-to-sender per Director-ratified 2026-05-17 rule)

On PR open, bus-post `lead` (per `dispatched_by: lead` above):

```bash
BAKER_ROLE=b3 ~/Desktop/baker-code/scripts/bus_post.sh lead \
  "ship/render-env-wipe-precommit-guard-1 — PR #<N> open; pytest <X/X> green; Part 4 smoke blocks the wipe pattern; Parts 1-3 still functional." \
  ship/render-env-wipe-precommit-guard-1
```

`lead` (AH1-Terminal, this brief's author) handles review + merge.

## Heartbeat cadence (per §B-code stall chase — Director-ratified 2026-05-05)

Minimum every 12h while actively building. Two consecutive 12h misses → AH1 auto-surfaces stall to Director. Heartbeat = (a) UPDATE entry in this mailbox file with ISO timestamp, OR (b) commit on working branch with `mailbox(b3): heartbeat <ISO> — <where>` pattern, OR (c) ship-report file write.

## Anchors

- Original runtime guard: `BRIEF_RENDER_ENV_WRITE_GUARD_1.md` + your ship at `briefs/_reports/B3_render_env_write_guard_1_20260517.md`.
- 2026-05-17 wipe + 2026-05-20 restoration lessons: `tasks/lessons.md` (search "env-var wipe" / "Render's array-form").
- Director ratification: 2026-05-20 chat "go" + "use /write-brief sop".
