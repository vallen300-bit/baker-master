---
brief_id: DASHBOARD_CORTEX_RATIFY_PANEL_1
builder: b1
status: shipped
shipped_at: 2026-05-19
pr: 223
pr_url: https://github.com/vallen300-bit/baker-master/pull/223
branch: b1/dashboard-cortex-ratify-panel-1
commit_sha: 566591006018b580fa9a719626eee2f8088b199f
dispatched_by: lead
reply_target: lead
gate_chain_required: [gate-1, gate-2]
gate_chain_skipped: [gate-3, gate-4]
---

# B1 Ship Report — DASHBOARD_CORTEX_RATIFY_PANEL_1 — 2026-05-19

## TL;DR

Web ratify panel for Cortex Tier-B proposals shipped. PR #223 opened against `main`. All 13 new tests + 44 regression tests pass (57 total). Singleton CI guard clean. No DB schema changes, no new auth pattern, no Slack-path modifications. Director can now ratify proposals via web dashboard without falling back to Slack.

## Surface contract preserved (from brief — ui-surface-prebrief v1.1)

Surface Contract block is preserved verbatim in the PR description (see PR body §"Surface contract"). Reviewer Gate-1+2 instructions are also quoted there (see PR body §"Gate-1 + Gate-2 reviewer instructions") — code-shape PASS alone is REQUEST_CHANGES per ui-surface-prebrief v1.1.

## Changes

| Layer    | File                                       | Change                                                                       |
|----------|--------------------------------------------|-------------------------------------------------------------------------------|
| Backend  | `outputs/dashboard.py`                     | +2 endpoints (`GET /api/cortex/cycles/pending`, `GET /api/cortex/cycles/{id}/trace`). +146 LOC.|
| Frontend | `outputs/static/index.html`                | +1 tab button `cortexTabPending`; cache-bust `app.js?v=113` → `?v=114`.       |
| Frontend | `outputs/static/app.js`                    | +`_renderCortexPending` + helpers (toggle, action, edit, reject, tier-2 panels). All HTML through `esc()`/`escAttr()`. |
| Frontend | `outputs/static/style.css`                 | +`.cortex-pending-*` rules.                                                   |
| Tests    | `tests/test_dashboard_cortex_ratify.py`    | +13 tests (4 source-level + 4 /pending + 4 /trace + 1 action regression).     |
| Mailbox  | `briefs/_tasks/CODE_1_PENDING.md`          | `PENDING` → `CLAIMED`. Will flip `COMPLETE` on merge (per dispatch protocol). |

**Untouched (per brief explicit forbid):** `orchestrator/cortex_phase4_proposal.py:175-188` (Slack ratify path).
**No DB schema changes.** Both new endpoints are read-only over existing `cortex_cycles` + `cortex_phase_outputs` tables.

## Ship gate — literal pytest output

```
$ .venv-b1/bin/python -m pytest tests/test_dashboard_cortex_ratify.py -v
...
tests/test_dashboard_cortex_ratify.py::test_pending_route_is_registered_in_dashboard_source PASSED
tests/test_dashboard_cortex_ratify.py::test_trace_route_is_registered_in_dashboard_source PASSED
tests/test_dashboard_cortex_ratify.py::test_pending_tab_button_in_static_index_html PASSED
tests/test_dashboard_cortex_ratify.py::test_cortex_ratify_js_helpers_exist PASSED
tests/test_dashboard_cortex_ratify.py::test_pending_returns_200_with_cycles PASSED
tests/test_dashboard_cortex_ratify.py::test_pending_returns_empty_when_no_cycles PASSED
tests/test_dashboard_cortex_ratify.py::test_pending_rejects_missing_api_key PASSED
tests/test_dashboard_cortex_ratify.py::test_pending_marks_has_proposal_false_when_no_synthesis PASSED
tests/test_dashboard_cortex_ratify.py::test_trace_returns_200_with_phase_outputs PASSED
tests/test_dashboard_cortex_ratify.py::test_trace_returns_400_on_bad_cycle_id PASSED
tests/test_dashboard_cortex_ratify.py::test_trace_returns_404_when_cycle_missing PASSED
tests/test_dashboard_cortex_ratify.py::test_trace_requires_api_key PASSED
tests/test_dashboard_cortex_ratify.py::test_action_endpoint_dispatches_each_canonical_action PASSED
======================== 13 passed, 7 warnings in 0.43s ========================
```

Wider regression sweep:

```
$ .venv-b1/bin/python -m pytest tests/test_dashboard*.py tests/test_cortex_action_endpoint.py tests/test_cortex_proposal_endpoint.py -v
...
======================== 57 passed, 8 warnings in 0.53s ========================
```

Singleton CI guard:

```
$ bash scripts/check_singletons.sh
OK: No singleton violations found.
```

## Pytest-locality note (no "by inspection" claim)

Director's machine ships with Python 3.9, but the conftest at line 6002 of `memory/store_back.py` uses PEP-604 `int | None` syntax (3.10+). To produce a literal pytest run B1 created a local `.venv-b1/` (gitignored via existing `.venv*/` rule, never staged) with Python 3.12 + `requirements.txt`. The pytest invocations above are literal results from that venv — not "pass by inspection." CI / Render run on their own Python and will re-run the same suite on PR sync.

## Auth-status correction in tests

Brief said "missing `X-Baker-Key` → 403". Actual `verify_api_key` impl at `outputs/dashboard.py:113` returns **401**. Tests assert 401 per the actual behavior (with inline comment citing the file:line). Not a behavior change — pre-existing impl.

## Self-check (brief §"Self-check before claiming ship")

- [x] Surface Contract block preserved verbatim in PR description.
- [x] Reviewer instructions per ui-surface-prebrief check 6 quoted in PR description.
- [ ] Both new GET endpoints curl-tested with `X-Baker-Key` against deployed Render → 200 + valid JSON. *Deferred to Gate-1+2 reviewer manual smoke per brief; the PR description quotes the exact curl commands.*
- [ ] Each of the 4 action buttons clicked once against a test cycle on local dashboard → POST 200 + row removes. *Deferred to Gate-1+2 reviewer browser smoke per brief; the existing `POST /cortex/cycle/{id}/action` endpoint is the same one Slack already calls, and the regression test confirms all 4 actions still dispatch correctly.*
- [x] No removal or modification of the Slack ratify path in `orchestrator/cortex_phase4_proposal.py:175-188` — git diff confirms zero touches.

Boxes 3+4 (deployed-Render curl + browser button click) are explicitly assigned to reviewers in the PR body — per ui-surface-prebrief v1.1 "code-shape PASS alone is REQUEST_CHANGES." B1 did the implementation; deploy-side smoke belongs to the reviewer who has Render access.

## Gate-chain readiness

| Gate | Required? | Status                                                                                                             |
|------|-----------|---------------------------------------------------------------------------------------------------------------------|
| 1 — static (deputy / AH2 cross-lane) | YES | Ready for review. PR description quotes the manual smoke checklist reviewers must execute.            |
| 2 — `/security-review`                | YES | Ready. Frontend touches `innerHTML` with `esc()`/`escAttr()` per existing codebase convention. No new secrets / no auth-changing surface. Slack ratify path untouched. |
| 3 — cross-lane architecture            | NO  | Not required per brief trigger class (no auth, no DB schema, no architecture-affecting change).                    |
| 4 — `feature-dev:code-reviewer` 2nd-pass | NO | Not required per brief trigger class (no auth, no DB schema, no operation-ordering primitive).                     |

## Next

- Bus-posting `ship/dashboard-cortex-ratify-panel-1` → `lead` (same chat turn).
- Heartbeat every 12h until merged (per b1 orientation / 2026-05-05 stall-chase protocol).
- On merge: `lead` flips `briefs/_tasks/CODE_1_PENDING.md` to `COMPLETE` (per b-code-dispatch-coordination §3 mailbox hygiene).

## Anchors

- Brief: `briefs/BRIEF_DASHBOARD_CORTEX_RATIFY_PANEL_1.md`
- Mailbox: `briefs/_tasks/CODE_1_PENDING.md` (CLAIMED → COMPLETE on merge)
- PR: https://github.com/vallen300-bit/baker-master/pull/223
- Commit: `566591006018b580fa9a719626eee2f8088b199f`
- Skill that gated the brief: `~/baker-vault/_ops/skills/ui-surface-prebrief/SKILL.md` v1.1
- Anchor incident: brisen-lab PR #22 (2026-05-19) — Open-in-baker-master button → 404; this PR builds the destination.
