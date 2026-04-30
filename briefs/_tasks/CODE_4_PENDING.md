# CODE_4 — PENDING (CORTEX_NOTIFICATION_DEFER_1)

**Status:** PENDING — B4 build
**Brief:** `briefs/BRIEF_CORTEX_NOTIFICATION_DEFER_1.md`
**From:** AI Head A — dispatched 2026-04-30 (Wave 2 #3 — demoted from #1 per Director ratification 2026-04-30 ~05:35Z; F-2 Scan UI render took priority and shipped first as PR #90 + #91)
**Wave:** 2 / Track 3 (V3 rev 4 roadmap)
**Trigger class:** LOW (per-invoke + per-matter notification opt-out; no auth / migration / financial / external API surface beyond suppressing one outbound Slack post)

**Prior CODE_4 task** CORTEX_MULTI_MATTER_GATE_1 — PR #85 merged Wave 1 2026-04-29 (`ad06824`). Mailbox overwritten per §3 hygiene.

## Scope (TL;DR)

Director's V7 directive: "per-matter or per-invoke flag suppresses Slack DM cost-gate prompt; Director runs Cortex silently with cost gate auto-approving. Default ON (today's behavior); opt-out at runtime."

Two opt-out surfaces gating the cost-warn Slack DM at `outputs/dashboard.py:4329-4345`:

1. **Per-invoke** — `defer_notification: bool = False` on `CortexRunRequest`
2. **Per-matter** — `notification_defer: true` in `cortex-config.md` frontmatter, read by new helper `matter_notification_deferred()` in `triggers/cortex_pre_review_gate.py` (mirrors `_read_cost_estimate` line-based YAML-free pattern)

If either flag is true → Slack DM suppressed, but `logger.info` STILL fires for observability. No new env vars, no DDL, no DB writes.

## Working branch

```
b4/cortex-notification-defer-1
```

## Pre-flight

```bash
cd ~/bm-b4
git fetch origin && git checkout main && git pull --ff-only origin main
git checkout -b b4/cortex-notification-defer-1
```

Verify the cost-warn block is at the line numbers cited (file may have drifted post-merge of PR #91):

```bash
grep -n "Cost guardrail\|cost-warn Slack\|specialist_calls_today" outputs/dashboard.py | head -5
grep -n "_read_cost_estimate\|matter_has_cortex_config\|DIRECTOR_DM_CHANNEL" triggers/cortex_pre_review_gate.py | head -5
grep -n "class CortexRunRequest" outputs/dashboard.py
```

If any line shifted, update brief citations BEFORE coding (Lesson §3b — file:line citation verification).

## Hard rules / RA-24 trigger classes (review path)

- Trigger class: **LOW** — notification opt-out only. Not in any of the 7 RA-24 trigger classes (auth / DB-migration / Director-override / secrets / external API / financial / cross-capability state writes).
- **Review path:** AI Head A solo `/security-review` + standard PR review. **No** RA-24 dual-clear required.
- **Self-PR rule:** AI Head A reviews + merges directly via squash-merge.

## Acceptance criteria

1. `pytest tests/test_cortex_run_endpoint.py tests/test_cortex_pre_review_gate.py tests/test_cortex_run_stream.py tests/test_scan_cortex_intent.py -v` — literal green output (paste tail in ship report; no "pass by inspection")
2. `bash scripts/check_singletons.sh` clean
3. `python -c "from outputs.dashboard import app; print('OK')"` clean (catches import errors before deploy)
4. Curl smoke A (per-invoke suppress): `defer_notification: true` body field → 200 + Render logs show `cost-warn Slack DM suppressed matter=... defer_invoke=True ...`
5. Curl smoke B (regression check): no `defer_notification` field → fall-through to original Slack DM path (200 + DM fires if threshold hit)
6. JS console clean (zero frontend impact expected)
7. **Logger trail preserved** — `cortex_run cost-warn matter=...` info-line fires on every threshold breach regardless of suppression

## Ship report fields (mandatory)

Save to `briefs/_reports/B4_cortex_notification_defer_1_<date>.md`:

- Files changed (with LOC delta) — expect `outputs/dashboard.py` +~25 / -~13, `triggers/cortex_pre_review_gate.py` +~30, both test files +~80 each
- `pytest` literal tail showing all 4 targeted suites green
- Singleton check output
- Import smoke output
- Manual curl outputs (200 with + 200 without `defer_notification`)
- Frontmatter-parse smoke (one-shot `python -c "from triggers.cortex_pre_review_gate import matter_notification_deferred; print(matter_notification_deferred('hagenauer-rg7'))"` — expect `False` since none of the Wave-1/2 configs have the field set)
- Any deviations from brief (with rationale)

## Director paste / PR

When done, push branch + open PR titled:
`feat(cortex): per-invoke + per-matter Slack DM cost-warn opt-out (CORTEX_NOTIFICATION_DEFER_1)`

Body must include the V7 anchor:
> Closes Wave 2 #3 per Director ratification 2026-04-30. Adds two opt-out surfaces (CortexRunRequest.defer_notification + cortex-config.md notification_defer frontmatter) gating the cost-warn Slack DM. Default behavior unchanged. Logger preserves observability when DM is suppressed.

## Reference docs

- Brief: `briefs/BRIEF_CORTEX_NOTIFICATION_DEFER_1.md` (the contract)
- V7 snapshot: `memory/project_session_state_20260430_v7.md` — Wave 2 framing (originally #1, demoted to #3)
- Cost-warn block source: `outputs/dashboard.py:4327-4345` (verified at brief authoring time)
- Helper template: `triggers/cortex_pre_review_gate.py:_read_cost_estimate` (line 80) — mirror its line-based YAML-free pattern for the new `matter_notification_deferred()` helper
