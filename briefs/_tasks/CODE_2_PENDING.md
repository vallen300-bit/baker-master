# CODE_2_PENDING — B2: WIKI_LINT_1 — 2026-04-26

**Dispatcher:** AI Head A (Build-lead)
**Working dir:** `~/bm-b2`
**Branch:** `wiki-lint-1` (create from main; B2 currently parked on stale `proactive-pm-sentinel-rethread-fix-1` post-merge — checkout main + pull first; untracked review report files in worktree are leftover from earlier session, leave alone).
**Brief:** `briefs/BRIEF_WIKI_LINT_1.md`
**Status:** OPEN
**Reviewer on PR:** AI Head B (cross-team)

**§2 pre-dispatch busy-check** (per `_ops/processes/b-code-dispatch-coordination.md`):
- Mailbox prior state: `COMPLETE — dispatch retired 2026-04-25` (PROMPT_CACHE_AUDIT_1 second-pair was duplicate; B2 never woken). Idle.
- Branch prior state: `proactive-pm-sentinel-rethread-fix-1` (old, merged remotely). Pre-execution `git checkout main && git pull -q` resolves.
- Other B-codes: B1 ← HAGENAUER_WIKI_BOOTSTRAP_1 (in flight, dispatched cd6cabf). B3 ← KBL_PEOPLE_ENTITY_LOADERS_1 (in flight, dispatched cd6cabf). No file overlap with B2 (see §6C note in brief).

**Dispatch authorisation:** Director cleared M1 parallel-3 in handover at 14:00 UTC 2026-04-25; B2 was held pending RA spec; RA delivered spec at `_ops/ideas/2026-04-26-wiki-lint-1-spec.md` 2026-04-26; AI Head A drafted brief + dispatched same day.

---

## Brief route (charter §6A)

`/write-brief` 6 steps applied:
1. EXPLORE — done by AI Head A:
   - Read RA spec (`_ops/ideas/2026-04-26-wiki-lint-1-spec.md`)
   - Verified `claude-haiku-4-5` referenced in `kbl/retry.py:105` + `kbl/cost.py:43-64` (Haiku live in stack)
   - Verified `_DEFAULT_MODEL = "claude-opus-4-7"` in `kbl/anthropic_client.py:51` (no haiku helper exists — brief adds `call_haiku()`)
   - Inspected `triggers/embedded_scheduler.py:679` `_ai_head_weekly_audit_job` registration pattern (mirror for `_wiki_lint_weekly_job`)
   - Confirmed `baker-vault/lint/` does NOT exist; CHANDA #9 carve-out documented as V1/V2 split
   - Confirmed slugs.yml retired entries at line 209+ (per spec check 1)
2. PLAN — embedded in brief.
3. WRITE — full brief at `briefs/BRIEF_WIKI_LINT_1.md`.
4. TRACK — this mailbox.
5. DOCUMENT — PR description MUST include V1/V2 carve-out + V2 question for Director ratification.
6. CAPTURE LESSONS — apply LONGTERM.md DDL-drift check; verify no DB write paths in lint module.

## RA's 3 Open Qs — decisions adopted by AI Head A

| Q | RA recommendation | AI Head A decision | Reasoning |
|---|---|---|---|
| Q1 LLM choice | Haiku 4.5 | **Haiku 4.5 ratified** | Stack consistency. `claude-haiku-4-5` already cited in retry + cost. Vendor diversification not in scope. |
| Q2 Action checkboxes | V1 = no | **V1 = no, ratified** | Simpler ship; auto-fix sentinels are V2 brief. |
| Q3 Threshold defaults | 60d/14d/90d, env-overridable | **Defaults ratified** | Spec aligns with M3 expectation (90d signal window for orphan = M3 cycle freshness). All overridable via env. |

These are §4-AI-Head-autonomy decisions per autonomy charter (parameter tuning + UX scoping + helper additions, not Cortex Design prerogatives). Director can override if needed.

## Code Brief Standards compliance

- API version: Anthropic Messages API + `claude-haiku-4-5` (verified active 2026-04-26 via existing references in repo).
- Deprecation check date: 2026-04-26 (no deprecation expected within M1 window).
- Fallback: `WIKI_LINT_ENABLED=false` default keeps scheduler dormant; flip after dry-run clean.
- DDL drift: zero DB writes; grep verification mandated in brief.
- Literal pytest output: required; ≥40 tests across 8 test files.

## Verification before shipping

Brief §"Verification criteria" (1-8 items). Items 4 (Hagenauer-first acceptance) and 7 (V1/V2 carve-out in PR) are non-negotiable.

## Ship report path

`briefs/_reports/B2_wiki_lint_1_<YYYYMMDD>.md`

## Cross-stream dependency

Brief is parallel-safe with B1 + B3. Acceptance test (item 4) depends on B1 having shipped HAGENAUER_WIKI_BOOTSTRAP_1, but graceful path documented: today's flat-pattern `wiki/hagenauer-rg7/` triggers grandfather-clause warn (NOT error) on check 2. B2 can ship before B1.

If B1 ships first AND its skeleton triggers errors on lint checks 1+2, that's a B1 problem (per spec §"Hagenauer-first acceptance test": "If the bootstrap output triggers errors on checks 1 or 2 (post-grandfather), bootstrap blocks merge"). AI Head A reviews B1 ship report against this gate.
