---
status: OPEN
brief: briefs/BRIEF_AUTOPOLL_PATCH_1.md
trigger_class: LOW
dispatched_at: 2026-04-28T06:45:00Z
dispatched_by: ai-head-b
claimed_at: null
claimed_by: null
last_heartbeat: null
blocker_question: null
ship_report: null
autopoll_eligible: false
---

# CODE_2_PENDING — B2: AUTOPOLL_PATCH_1 — 2026-04-28

**Dispatcher:** AI Head B (M2 lane)
**Brief:** [`briefs/BRIEF_AUTOPOLL_PATCH_1.md`](../BRIEF_AUTOPOLL_PATCH_1.md)
**Trigger class:** LOW (no auth, DB writes, secrets, or external API; pure helper-script + protocol-doc patch)
**Branch:** `autopoll-patch-1` (cut from `main` post PR #69 merge `af97a86`)
**Estimated time:** ~30-45min
**Authority:** AI Head A cross-team review of PR #69 surfaced 3 OBS findings ([review comment](https://github.com/vallen300-bit/baker-master/pull/69#issuecomment-4331292374)). Director merged PR #69 as `af97a86` 2026-04-28T06:40:45Z. Patch must ship BEFORE startup blocks paste (A's hard gate).

## What you're building

3 surgical fixes to the just-merged autopoll v1:

1. **OBS-1 (HIGH)** — idle-counter persistence via per-B-code state file `~/.autopoll_state/{b_code}.yaml`. Q2 stop condition #2 (3 consecutive idle wakes → STOP) was structurally unimplementable as written.
2. **OBS-2 (MEDIUM)** — `git reset --hard origin/main` on push reject before `git pull --rebase`. Fixes deadlock when local frontmatter mutation conflicts with concurrent writer (LWW Q6).
3. **OBS-3 (LOW)** — `_split_frontmatter` converts `yaml.YAMLError` → `ValueError` so existing catchers in `read_state` and `find_stale_claims` continue to work on malformed YAML.

## Self-PR rule reminder

This branch is on `vallen300-bit/baker-master` (not a fork). Same canonical pattern as PR #67/#69/#70: open PR, post `/security-review` verdict as PR comment, AI Head B Tier-A direct squash-merge.

## Files modified

- [`scripts/autopoll_state.py`](../../scripts/autopoll_state.py) — add 3 functions + patch `_split_frontmatter`
- [`_ops/processes/b-code-autopoll-protocol.md`](../../_ops/processes/b-code-autopoll-protocol.md) — Phase 1/2/3 idle-counter integration + Phase 3 step 8 reset+pull
- [`tests/test_autopoll_state.py`](../../tests/test_autopoll_state.py) — add 5 new tests

## Files NOT to touch

Per brief §"Files NOT to Touch" — `outputs/slack_notifier.py`, `config/settings.py`, `_ops/processes/b-code-autopoll-startup.md`, dispatch coordination doc, all production Cortex / capability / sentinel code, sibling `CODE_*_PENDING.md` mailboxes.

## Ship gate (literal pytest mandatory — Lesson #47)

```bash
cd ~/bm-b2
pytest tests/test_autopoll_state.py -v 2>&1 | tail -50
```

Paste literal stdout into ship report. **All 25 tests must pass** (20 existing + 5 new). NO "by inspection."

## /security-review (Lesson #52 mandatory pre-merge)

Trigger class LOW — solo lane-owner pass sufficient (no second-pair-review per b1-situational-review-trigger). Run `/security-review` skill yourself before declaring done; post verdict as PR comment.

## Verification

Per brief §"Verification" — paste smoke-test stdout into ship report:
```
AUTOPOLL_PATCH_1 verified
```

## Process

Per brief §"Process" steps 1-12.

## Co-Authored-By

```
Co-authored-by: Code Brisen #2 <b2@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
