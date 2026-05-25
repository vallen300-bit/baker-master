---
status: PENDING
dispatched_at: 2026-05-25T16:05:00Z
dispatched_by: lead
target: b4
brief: briefs/BRIEF_BLOCK_BAKER_OUTBOUND_TO_DIRECTOR_1.md
brief_id: BLOCK_BAKER_OUTBOUND_TO_DIRECTOR_1
type: defense-in-depth backend guard (Director directive — belt-and-suspenders on top of PR #263)
target_repo: baker-master (single repo)
matter_slug: baker-internal
peer_brief: CAPABILITY_RUNNER_COST_FIX_1 (root-cause fix already merged today; this brief is the independent safety layer)
reply_target: lead (AH1)
expected_time: ~45 min (build 25-30 min + tests 10 min + gates 5-10 min)
complexity: Low (2 chokepoint files + 2 new test files)
heartbeat_cadence: 15 min (small brief — flag if not shipped within 1h)
gate_chain: Gate-1+2 lead | Gate-3 SKIP (≤50 LOC) | Gate-4 SKIP | Gate-5 lead merge after green pytest + env vars set | post-merge lead observes Render logs + verification SQL
---

# DISPATCH: BLOCK_BAKER_OUTBOUND_TO_DIRECTOR_1 → b4

Read brief at: `briefs/BRIEF_BLOCK_BAKER_OUTBOUND_TO_DIRECTOR_1.md`

Two env-flagged hard guards added to the existing send chokepoints:

1. `outputs/whatsapp_sender.py` — guard in `send_whatsapp()` BEFORE the existing kind-allowlist check. New `_BLOCK_WA_TO_DIRECTOR` module constant + `_log_director_hard_blocked()` audit helper + 7-line guard inside the function.
2. `outputs/email_alerts.py` — guard at top of `_send_raw_full()`. New `DIRECTOR_EMAILS` set covering both Director addresses + `_BLOCK_EMAIL_TO_DIRECTOR` module constant + `_log_email_director_hard_blocked()` audit helper + 6-line guard inside the function.

**Architecture:** strictly additive. When env flag flipped OFF, behavior identical to today (kind-allowlist for WA, `_EMAIL_ALERTS_DISABLED` for proactive emails). When ON (default), ALL Baker → Director outbound dropped + audited regardless of upstream path.

**Tests:** 5 new tests per file, 2 NEW test files. Run command + literal output required in ship report.

**Env vars:** AI Head A sets `BAKER_BLOCK_WA_TO_DIRECTOR=true` + `BAKER_BLOCK_EMAIL_TO_DIRECTOR=true` on Render via API as a pre-merge Tier-A action — you do NOT touch Render.

**3 reviewer invariants** (Gate-1/2/4 instructions at bottom of brief). All copy-pasteable code blocks have verified signatures against current `outputs/whatsapp_sender.py` lines 17/270-326/329 and `outputs/email_alerts.py` lines 32-38/67-93.

Ship report to lead via topic `ship/block-baker-outbound-to-director-1`. Literal pytest output required. Heartbeat every 15 min if >30 min.
