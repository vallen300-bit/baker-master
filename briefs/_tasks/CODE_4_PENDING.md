---
status: COMPLETE
completed_at: 2026-05-25T10:12:00Z
completed_by: b4
deliverable: briefs/_reports/B4_gmail_polling_diagnostic_1_20260525.md (main d3c23bf)
bus_ship: lead msg #1023 (diag/gmail-polling-outage-1)
dispatched_at: 2026-05-25T09:35:00Z
dispatched_by: lead
target: b4
brief: briefs/BRIEF_GMAIL_POLLING_DIAGNOSTIC_1.md
brief_id: GMAIL_POLLING_DIAGNOSTIC_1
type: READ-ONLY DIAGNOSTIC (no code edits — diagnose + propose only)
target_repo: baker-master (single repo)
matter_slug: baker-internal
working_branch_baker_master: b4/gmail-polling-diagnostic-1
working_dir_baker_master: ~/bm-b4
reply_to: lead
also_cc: deputy
priority: MEDIUM (silent rot — not Tuesday-blocking but compounding)
estimated_time: 1-2h
trigger_class: SMALL (diagnostic, no PR)
anchor_bus: deputy #1006 (gmail-polling-outage-separate-defect)
gate_chain:
  diagnostic_only: no PR, no gate chain. Report file + bus-post to lead is the deliverable.
  follow_up: AH1 authors GMAIL_POLLING_FIX_1 after seeing b4's diagnosis. Fix gets its own gate chain.
ui_surface_prebrief: N/A — no UI surface
director_q_locks:
  - q1_scope: READ-ONLY. No code edits. Fix goes in separate brief. Lead recommendation — locked.
  - q2_cost_breaker_hypothesis: Cost monitor at €113 vs €100 hard stop is a strong candidate root cause; b4 must verify whether circuit breaker affects documents INSERT or only LLM extraction. Lead recommendation — locked.
  - q3_circuit_breaker_quick_fix: If circuit breaker is root cause, do NOT raise the cap as a fix — AH1 needs to understand WHY costs are at €113 first. Cap exists for a reason. Lead recommendation — locked.
prior_mailbox_state: CODE_4 COMPLETE on CLAIMSMAX_ASK_ENDPOINT_1 (PR #226 merged 2026-05-21). This file overwrites the prior PENDING state.
---

# CODE_4_PENDING — GMAIL_POLLING_DIAGNOSTIC_1 — 2026-05-25

**Brief:** `briefs/BRIEF_GMAIL_POLLING_DIAGNOSTIC_1.md`
**Type:** READ-ONLY DIAGNOSTIC. **NO code edits.** Fix lands in a separate brief.
**Target repo:** baker-master (single repo)
**Working dir:** `~/bm-b4` (baker-master)
**Pre-requisites:** Production PG access (`DATABASE_URL`) + Baker Gmail OAuth env (`BAKER_GMAIL_CLIENT_ID`, `BAKER_GMAIL_CLIENT_SECRET`, `BAKER_GMAIL_REFRESH_TOKEN`) in b4's shell. If either is missing surface as BLOCKER to lead immediately.

## Bottom line

`documents` table where `source_path LIKE 'email:%'` is 9 days stale (last entry 2026-05-16). Meanwhile the `email_poll` apscheduler job runs successfully every 5 min and updates its watermark — verified in live Render logs every 5 min. The break is between "poll fires" and "documents row written." Non-email pipeline is healthy (901 docs in last 12h from WhatsApp/transcripts/Substack). Hag-desk on-demand attachment read is live + working — Tuesday filing NOT blocked. This is silent rot in agent-DB reasoning over recent counterparty mail. Investigate, diagnose, write report, hand back to lead. Lead authors fix.

## Pre-flight (mandatory before edit)

1. `cd ~/bm-b4 && git fetch origin main && git checkout main && git pull --ff-only`
2. `cd ~/bm-b4 && git checkout -b b4/gmail-polling-diagnostic-1` (in case you need a sandbox branch for ad-hoc test scripts)
3. `git config core.hooksPath .githooks` (verify configured)
4. Confirm canonical brief on main: `git show main:briefs/BRIEF_GMAIL_POLLING_DIAGNOSTIC_1.md | head -10` should return frontmatter.
5. Verify env: `env | grep -E "BAKER_GMAIL|DATABASE_URL" | sed 's/=.*/=<set>/'` — all 4 expected.

## Scope (7 investigation steps per brief)

1. Confirm the disconnect via 4 SQL queries (brief §Investigation step 1)
2. Read the poll code path — map the chain from `check_new_emails()` → documents INSERT
3. Exercise `check_new_emails()` manually with DEBUG logging from b4 shell
4. Verify Gmail itself is receiving mail (via the just-shipped MCP tool against live Render OR via Director ad-hoc lookup)
5. Read git log 2026-05-14 to 2026-05-17 for poll-touching commits
6. Render-side 24h log scrape for `email_poll` lines — watermark progression + WARN/ERROR
7. Look for upstream `return` early-exit anti-pattern (Bluewin/Exchange failure killing Gmail branch)

## Hard constraints

- **HARD RULE: NO CODE EDITS.** This is investigation only. The fix goes in a separate brief (`GMAIL_POLLING_FIX_1`) that AH1 authors AFTER seeing b4's diagnosis. Reason: the polling code intersects with multiple systems; a naive fix in one spot can mask the real defect elsewhere.
- **DO NOT paste OAuth tokens, refresh tokens, API keys, or credential file contents** into the report. Redact + reference by env var name.
- **DO NOT raise the cost-monitor cap as a "fix"** if the circuit breaker turns out to be the root cause. Cap exists for a reason; understand WHY costs are at €113 first.
- **DO NOT touch `tasks/lessons.md`** — AH1 captures the lesson post-fix.
- **DO NOT write to production tables in unintended ways** — if you want to exercise the poll, use dry-run paths only.

## Acceptance criteria

Per brief §Acceptance criteria (AC1-AC5):

- **AC1:** Report file at `briefs/_reports/B4_gmail_polling_diagnostic_1_20260525.md` with all 6 required sections (bottom line, evidence chain, what's broken vs working table, recommended fix, risks of fix, fix-brief vs rolling-cleanup recommendation).
- **AC2:** All 7 investigation steps documented (or explicit "step skipped because X").
- **AC3:** Root cause named with confidence rank (high/medium/low); if low, top 3 hypotheses.
- **AC4:** Recommended fix specific enough for AH1 to dispatch a fix brief in <30 min.
- **AC5:** Bus-post to `lead` with topic `diag/gmail-polling-outage-1` summarizing root cause + confidence + fix effort.

## Ship gate

No PR. Deliverable is the report file + bus-post. Lead reads + decides next move (fix brief vs deferral vs ask for deeper dive).

## Reporting (bus reply-to-sender)

```bash
BAKER_ROLE=b4 ~/bm-b4/scripts/bus_post.sh lead \
  "diag/gmail-polling-outage-1 — report at briefs/_reports/B4_gmail_polling_diagnostic_1_20260525.md. Root cause: <X> (confidence <high/medium/low>). Top recommended fix: <Y>. Est fix effort: ~<Z>h. Full evidence + code path map in report." \
  diag/gmail-polling-outage-1
```

## References

- Brief: `briefs/BRIEF_GMAIL_POLLING_DIAGNOSTIC_1.md` (full 7-step investigation plan + diagnosis report format spec)
- Deputy bus #1006 (counter-finding that originally surfaced the gap — fact-finding by deputy)
- Lead bus #1004 (scheduler /health misdiagnosis correction earlier today — establishes that scheduler is fine; this is a separate defect)
- Gmail-attachment-read PR #257 (squash 89008e0a) — proves OAuth singleton works on read paths; isolates bug to write side
- Hag-desk LG Wien filing 2026-05-26/27 — NOT blocked by this (on-demand attachment read live + working)
- Cost monitor circuit breaker active at €113.26 — potential causal factor, verify

## Heartbeat cadence

Minimum every 12h while actively investigating. Given ~1-2h scope, no heartbeat expected unless DB or env-var access blocker hits.
