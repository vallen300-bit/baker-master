---
status: PENDING
brief: briefs/BRIEF_BAKER_WA_PULL_API_1.md
brief_id: BAKER_WA_PULL_API_1
trigger_class: MEDIUM (new external API surface exposing WhatsApp message bodies; mandatory 2nd-pass review + /security-review)
target_branch: b4/baker-wa-pull-api-1
matter_slug: baker-internal
cross_matter_usage: [ao, mo-vie-am, hagenauer-rg7, cupial, balgerstrasse, lilienmatt, origination]
dispatched_at: 2026-05-18T10:25:00Z
dispatched_by: AH1
director_auth: 2026-05-18 chat — Option A ratified (per AH2 bus #394)
brief_authored_by: AH2
prior_brief_complete: |
  REPORT_RENDERER_SLUG_HARDEN_1 shipped as PR #215 (commit 4296cbc, 2026-05-17T14:48Z).
  Ship report preserved in briefs/_reports/B4_REPORT_RENDERER_SLUG_HARDEN_1_20260517.md.
  This dispatch overwrites the mailbox slot.
---

# Dispatch: BAKER_WA_PULL_API_1

B4 — full brief at `briefs/BRIEF_BAKER_WA_PULL_API_1.md`.

**TL;DR:** Add `GET /api/whatsapp/messages` to `outputs/dashboard.py` — X-Baker-Key auth (reuse `Depends(verify_api_key)` exactly like `/api/whatsapp/backfill` line 959), parameterised SQL with LIMIT, JSON + Markdown response formats. Read-only endpoint over `whatsapp_messages` table. Unblocks AO Desk pulling Constantinos+Masha threads for Vladislav KYC pack (Director-ratified Option A 2026-05-18).

**Working dir:** `~/bm-b4`
**Branch:** `b4/baker-wa-pull-api-1` off `main`
**Estimated touch:** 1 prod file (`outputs/dashboard.py`, ~80 LOC added, no existing lines modified) + 1 new test file (`tests/test_whatsapp_pull_api.py`).
**Trigger class:** MEDIUM (new external API surface exposing message bodies → mandatory AH2 static review + `/security-review`; even though brief estimates 2-3h LOW complexity).
**Estimated time:** 2-3h.

## Pre-flight

1. `cd ~/bm-b4 && git fetch origin main && git checkout main && git pull --ff-only`.
2. Read `briefs/BRIEF_BAKER_WA_PULL_API_1.md` end-to-end.
3. Read `outputs/dashboard.py:959-1010` (`/api/whatsapp/backfill` — the auth + error-handling pattern to mirror).
4. **Verify the `media_path` column** actually exists on `whatsapp_messages` (brief acceptance §92): `python3 -c "from kbl.db import get_conn; c=get_conn(); cur=c.cursor(); cur.execute(\"SELECT column_name FROM information_schema.columns WHERE table_name='whatsapp_messages' ORDER BY ordinal_position\"); print([r[0] for r in cur.fetchall()])"`. If the column is named differently (`media_url`, `has_attachment`), adapt the SQL — note the actual column name in the PR description. If no media column exists at all, return `has_media: false` unconditionally per brief §92.
5. Read `.claude/rules/python-backend.md` to confirm try/except + `conn.rollback()` + LIMIT discipline.

## Mandatory per `.claude/rules/python-backend.md`

- Wrap DB call in try/except; `conn.rollback()` in except block before any further query.
- LIMIT clause non-optional (clamped via `Query(200, ge=1, le=1000)`).
- Fault-tolerant: endpoint returns `{"status": "error", "message": "..."}` with **200** on DB failure, not 500 (consistent with `/api/whatsapp/backfill` line 994).
- No f-string SQL — parameterised binds only.

## Ship gate

1. Literal `pytest tests/test_whatsapp_pull_api.py -v` output in ship report. NO "by inspection".
2. Literal `python3 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True)"` exit-0 line in ship report.
3. Do NOT smoke against Render in the ship report — AH1 owns post-merge Render smoke (brief acceptance §11 belongs to AH1, not B4).

## Reporting

- Bus-post `lead` (AH1) on PR open with topic `pr-open/baker-wa-pull-api-1`.
- AH1 runs cross-lane review chain: AH2 static review **mandatory** (MEDIUM trigger class); `/security-review` **mandatory** (exposes message bodies; PII surface). On AH2 PASS-WITH-NITS or PASS + `/security-review` clean, AH1 merges.

## Out of scope (do NOT do)

Per brief §111-118:
- Updating desk picker CLAUDE.md curl examples — AH1 dispatches a follow-up brief after Render smoke passes.
- Auth model changes — X-Baker-Key reuse is mandatory.
- Schema migrations — read-only endpoint.
- Caching layer.
- Media file streaming — `has_media` is a boolean flag only.

## Co-Authored-By

```
Co-authored-by: Code Brisen #4 <b4@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
