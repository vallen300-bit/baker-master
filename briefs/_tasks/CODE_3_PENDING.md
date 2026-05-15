---
status: PENDING
brief: briefs/BRIEF_BAKER_WA_DIRECTOR_FILTER_1.md
trigger_class: MEDIUM (external-surface helper edit + >10 files; mandatory 2nd-pass)
dispatched_at: 2026-05-15T18:35:00Z
dispatched_by: ai-head-2 (AH2)
target: b3
prior_brief_complete: |
  CORTEX_TIER_B_RUNTIME_V1 (PR #179 merged 2026-05-10) + DEADLINE_FEEDBACK_LOOP_1
  (PR #203 merged 2026-05-15 09:37Z). This dispatch supersedes prior content.
director_ratification: |
  Director 2026-05-15 ~18:30Z (in-chat to AH2): "Ratified." in response to
  AH2's proposal for outbound WhatsApp allowlist + chokepoint enforcement.
  Anchor: Director "I stopped even reading messages now from Baker on
  WhatsApp. ... Why do I need to know this?" — generalisation of the
  scheduler-watchdog Phase A kill to all infra-class WA sends.
priority: P0 (Director quality-of-life; signal-to-noise on the Director's
              primary alert channel)
phase: 1 of 1
expected_pr_count: 1
expected_branch: b3/baker-wa-director-filter-1
expected_complexity: medium (~2-3h: 10+ call sites to audit + tag, chokepoint, CI guard, 5 tests)
mandatory_2nd_pass: TRUE (per SKILL.md §"Code-reviewer 2nd-pass Protocol" trigger #4 — external-surface helper)
hard_ship_gate: |
  1. `python3 -c "import py_compile; py_compile.compile('outputs/whatsapp_sender.py', doraise=True)"` clean.
  2. `pytest tests/test_wa_director_filter.py -v` — 5 passed (literal stdout in ship report).
  3. `bash scripts/check_wa_director_kinds.sh` exits 0 after all callers tagged (literal in ship report).
  4. Step 2 audit table in ship report — every call site listed with classification + 1-line justification.
  5. AH2 cross-lane review + /security-review + picker-architect + feature-dev:code-reviewer 2nd-pass all clear.
  6. Post-merge 24h: `SELECT action_type, COUNT(*) FROM baker_actions WHERE action_type IN ('whatsapp_send','whatsapp_blocked') AND created_at > NOW() - INTERVAL '24 hours' GROUP BY 1` — paste result in ship report addendum.
ship_report_to: |
  Bus-post to `deputy` on PR open + ship.
---

# CODE_3_PENDING — Baker WhatsApp Director filter — 2026-05-15

**Dispatched by:** AH2 (deputy) under Director directive 2026-05-15 ~18:30Z
**Working dir:** `~/bm-b3`
**Branch:** `b3/baker-wa-director-filter-1` off `main`

Pre-flight:
1. `git pull --ff-only origin main` in `~/bm-b3`.
2. Read `briefs/BRIEF_BAKER_WA_DIRECTOR_FILTER_1.md` end-to-end.

---

## Scope

Add a `kind=` parameter + allowlist enforcement to `outputs/whatsapp_sender.py:266`. Calls that resolve to Director's number (`chat_id=DIRECTOR_WHATSAPP`) must pass an allowlisted `kind=` value or get blocked at the chokepoint (returns False + logs to `baker_actions.whatsapp_blocked`). Non-Director chat_ids are unaffected.

Allowlist: `counterparty / legal_threat / deadline / vip_signal / financial / director_inbound`.

Audit + tag the 10+ existing `send_whatsapp(` call sites per the brief's Step 2 table. Infra-only ones get replaced with `logger.warning(...)` (mirroring Phase A pattern at `outputs/dashboard.py`). Director-relevant ones get tagged with the right `kind=` value.

Add `scripts/check_wa_director_kinds.sh` as a pre-push hook to fail-fast if any future caller forgets the tag.

## Background context (read before starting)

- Director cited Phase A (`SCHEDULER_WATCHDOG_WA_KILL_1`, PR #206 merged 15:57Z) as the pattern: stop infra-class WA to Director. This brief generalises the rule.
- Phase A only fixed ONE call site (the scheduler-watchdog at `outputs/dashboard.py`). Several infra-class call sites still default to Director's number — most obviously `triggers/sentinel_health.py` (3 sites: WAHA silent / WAHA session down / general sentinel health).
- Director's concrete frustration: "I stopped even reading messages now from Baker on WhatsApp." The signal-to-noise is gone. Restore it by silencing everything that isn't an entity outside Baker.
- Director ratification of THIS brief is implicit in his "Ratified." reply. No further authorization needed for the implementation.

## Reporting

- Bus-post `deputy` on PR open + ship per `_ops/processes/agent-bus-posting-contract.md`.
- Cite the audit table (Step 2 of the brief) in the ship report — every classification decision must have a 1-line justification (DON'T classify without reading the trigger code).

## Co-Authored-By

```
Co-authored-by: Code Brisen #3 <b3@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
