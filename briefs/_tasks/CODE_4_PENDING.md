---
status: PENDING
brief: briefs/BRIEF_COCKPIT_ALERT_PROMPT_REWRITE_1.md
brief_id: COCKPIT_ALERT_PROMPT_REWRITE_1
target_repo: baker-master
matter_slug: baker-internal
cross_matter_usage: [all-matters — prompt change applies to every signal classified into an alert]
dispatched_at: 2026-05-20T14:32:00Z
dispatched_by: lead
director_auth: 2026-05-20 chat — "go for 3 ( prompt correction )" + "ratified, go" (5-item batch)
trigger_class: LOW
working_dir: ~/bm-b4
working_branch: b4/cockpit-alert-prompt-rewrite-1
expected_build_min: 30-45
acceptance_summary: |
  Rewrite BAKER_SYSTEM_PROMPT in orchestrator/prompt_builder.py to force
  4-element strategic-synthesis shape on alert body (interpretation /
  counterparty intent / risk if ignored / suggested move). Add 1-2 few-shot
  examples contrasting summary vs synthesis. Add tests/test_alert_prompt_strategic_synthesis.py.
  No model swap. No JSON shape change. Tier rules preserved verbatim.
ship_gate: |
  Literal `pytest tests/test_alert_prompt_strategic_synthesis.py -v` green.
  Plus `pytest tests/test_prompt_builder*.py tests/test_alert*.py` green for
  regression coverage. No pass-by-inspection.
reply_to: lead
notes: |
  Brief was authored after Slack DM-kill PR #233 merged. This brief is the
  surviving Cockpit-quality lever (DM is dead; Cockpit gets the prompt fix).
  Don't touch tier classification, model routing, or DM-posting paths —
  all out-of-scope per brief.
---

Read `briefs/BRIEF_COCKPIT_ALERT_PROMPT_REWRITE_1.md` for full spec.
