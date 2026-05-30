---
dispatch: WAHA_SESSION_POLL_HARDEN_1
to: b1
from: lead
dispatched_by: lead
status: PENDING
dispatched_at: 2026-05-30T09:45:00Z
brief_version: v1 (codex PASS-WITH-NITS bus #1364, all 3 nits folded)
codex_pre_review: PASS-WITH-NITS bus #1364
prior_design_iterations:
  - v1 bus #1360 → codex FAIL-LIGHT #1362 (6 findings, all folded into v2)
  - v2 bus #1363 → codex PASS-WITH-NITS #1364 (3 nits, all folded into this brief)
authored: 2026-05-30
brief_path: /Users/dimitry/bm-aihead1/briefs/BRIEF_WAHA_SESSION_POLL_HARDEN_1.md
target_repo: baker-master
estimated_time: ~3h
complexity: Medium
reply_to: lead
ship_topic: ship/waha-session-poll-harden-1
anchor_chat: Director 2026-05-30 — Bick iPhone export caught 4× 2026-05-29 WAHA-missed messages; existing poll did not fire after 2026-05-29 19:19Z per codex prod-DB probe.
supersedes: BAKER_CAPTURE_BLINDSPOTS_1 (PR #270 shipped 7a4799c)
---

# b1 dispatch — WAHA_SESSION_POLL_HARDEN_1

Read `briefs/BRIEF_WAHA_SESSION_POLL_HARDEN_1.md` end-to-end before any code.

Brief landed after **two codex review iterations**. v1 → FAIL-LIGHT 6 findings → v2 → PASS-WITH-NITS 3 nits → final brief folds all 9. No further pre-write review; ship to AH1 + deputy gate chain as usual.

**Scope:** patch `triggers/sentinel_health.py:poll_waha_session()` + tighten `triggers/embedded_scheduler.py:501-509` cadence 30 min → 5 min + 12 pytest cases.

**Reply target:** lead (not deputy). Ship report to `briefs/_reports/B1_WAHA_SESSION_POLL_HARDEN_1_<YYYYMMDD>.md` + bus-post to `lead` with topic `ship/waha-session-poll-harden-1`.
