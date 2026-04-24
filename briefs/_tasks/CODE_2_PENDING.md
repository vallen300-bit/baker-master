# CODE_2_PENDING — PROACTIVE_PM_SENTINEL_1 — 2026-04-24

**Dispatcher:** AI Head #2 (Team 2)
**Working dir:** `~/bm-b2`
**Brief:** `briefs/BRIEF_PROACTIVE_PM_SENTINEL_1.md` (1507 lines — read end-to-end before implementing)
**Target branch:** `proactive-pm-sentinel-1`
**Complexity:** Medium–High (~11–17h)

**Supersedes:** prior `CAPABILITY_THREADS_1` + fix-back task (shipped as PR #57, merged squash `a7a437c` 2026-04-24 09:00 UTC, deploy verified green). Mailbox reset.

**Context fit rationale (Director call):** B2 has fresh context on `capability_threads` + `capability_turns` + `pm_state_history` — the exact tables this brief reads from. Phase 3 is the downstream consumer of the Phase 2 schema B2 just built. "Just shipped" is advantage, not liability. Fallback B-code: B5 (dormant, would need fresh context).

---

## ⚠️ B1 SITUATIONAL REVIEW REQUIRED

Per the ratified B1 trigger rule (`memory/feedback_ai_head_b1_review_triggers.md` + `_ops/ideas/2026-04-24-b1-situational-review-trigger.md`), this PR hits **two** triggers:

- **§2.1 Authentication** — new `@app.post("/api/sentinel/feedback")` route with `dependencies=[Depends(verify_api_key)]`; new client-side auth-header handling through `bakerFetch()` wrapper; integration with Phase 2's auth-gated `/api/pm/threads/re-thread`.
- **§2.2 Database migrations** — new `migrations/<YYYYMMDD>_sentinel_schema.sql` adds `capability_threads.sla_hours` + `alerts.dismiss_reason` + one partial index. Touches `capability_threads` which has >0 rows post-Phase-2.

**Flow:** B2 ships → AI Head #2 runs `/security-review` → **B1 second-pair-of-eyes review** (triggers §2.1 + §2.2) → merge only on BOTH green. Fix-backs route to B2 (implementation lane), never to B1.

---

## Why this brief

Phase 3 of the **AO PM Continuity Program** (ratified 2026-04-23; source `/Users/dimitry/baker-vault/_ops/ideas/2026-04-23-ao-pm-continuity-program.md` §7, §10 Q7). Adds the *proactive voice* — AO PM speaks without being asked — plus a **smart triage surface** that turns every Director click into tuning signal via `baker_corrections`.

**Program sequence:**
- Phase 0 Amendment H — canonical 2026-04-23.
- Phase 1 — shipped PR #50/#54/#56.
- Phase 2 — shipped PR #57 (squash `a7a437c`) + deployed 2026-04-24 09:05 UTC. Deploy gate CP1-4 + H4 surface CP13 GREEN. CP5-8 organic observation in progress (doesn't block Phase 3 dispatch per Director 2026-04-24).
- **Phase 3 (this brief)** — dispatch gate now open.
- Trigger 2 (Gmail draft-lint) deferred to Monday audit scratch §D1.

**Director ratifications (all 3 stand as designed):**
1. Feature 1 SLA default — `sla_hours INTEGER DEFAULT NULL`; PM-level defaults hard-coded in `DEFAULT_SLA_HOURS` Python dict at Feature 2 (brief line ~173).
2. Feature 5 Dismiss enum — 6 presets (`waiting_for_counterparty / offline / low_priority / wrong_thread / not_actionable / other`). `wrong_thread` chains into Phase 2's `POST /api/pm/threads/re-thread`.
3. Reject verdict → `baker_corrections.correction_type='sentinel_false_positive'` with 5-cap + 90-day expiry; 14-day pattern surface (Upgrade 2) reads these rows.

---

## Working-tree setup (B2)

```bash
cd ~/bm-b2 && git fetch origin && git pull --rebase origin main
git checkout -b proactive-pm-sentinel-1
```

Pre-merge verification (paste outputs into PR body per lesson #40). The brief at §"Pre-merge verification" (line ~1411) has the full checklist; highlights:

```bash
# 1. Phase 2 tables live (hard dependency)
curl -s -X POST "https://baker-master.onrender.com/mcp?key=bakerbhavanga" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"baker_raw_query","arguments":{"sql":"SELECT COUNT(*) FROM capability_threads; SELECT COUNT(*) FROM capability_turns"}}}'
# Expected: both queries return rows (may be 0 — tables exist is what matters)

# 2. Phase 2 endpoint live + auth-gated
curl -s -o /dev/null -w "HTTP:%{http_code}\n" https://baker-master.onrender.com/api/pm/threads/ao_pm
# Expected: 401 (auth enforced post-PR #57 fix-back)

# 3. alerts.snoozed_until already present (no DDL needed for Upgrade 1)
curl -s -X POST "https://baker-master.onrender.com/mcp?key=bakerbhavanga" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"baker_raw_query","arguments":{"sql":"SELECT column_name FROM information_schema.columns WHERE table_name='"'"'alerts'"'"' AND column_name IN ('"'"'snoozed_until'"'"','"'"'dismiss_reason'"'"','"'"'exit_reason'"'"')"}}}'
# Expected: snoozed_until + exit_reason present; dismiss_reason ABSENT pre-merge.

# 4. baker_corrections table + store_correction signature
grep -n "^def store_correction\|class SentinelStoreBack\|^    def store_correction" memory/store_back.py | head -5
# Expected: store_correction signature at memory/store_back.py:664 (per brief citation)

# 5. No duplicate /api/sentinel/feedback endpoint
grep -n '/api/sentinel/feedback' outputs/dashboard.py
# Expected: 0 pre-existing

# 6. Singleton check hook
bash scripts/check_singletons.sh
# Expected: pass

# 7. JSONResponse import (lesson #18 spot-check)
sed -n '23p' outputs/dashboard.py
# Expected: 'JSONResponse' appears
```

---

## Acceptance criteria

- All 12 Quality Checkpoints (brief §Quality Checkpoints, line ~1375) verifiably pass
- §H5 cross-surface continuity test **green** (brief §Part H / Feature 6 — triage-roundtrip integration test with `needs_live_pg` fixture)
- Literal `pytest` output pasted into PR body — no "pass by inspection"
- `/api/sentinel/feedback` decorator carries `dependencies=[Depends(verify_api_key)]` (Feature 4, brief line ~618)
- Feature 5 JS uses `bakerFetch()` wrapper on both `/api/sentinel/feedback` and `/api/pm/threads/re-thread` (brief lines ~906 + ~943)
- Migration file name sort-orders AFTER `20260424_capability_threads.sql`
- All 16 lessons pre-applied (brief line ~1468) verified via the pre-merge grep checks

---

## Ship gate (local, before push)

```bash
# Syntax + singletons
python3 -c "import py_compile
for f in ['orchestrator/proactive_pm_sentinel.py','triggers/embedded_scheduler.py','outputs/dashboard.py','outputs/static/app.js' if False else '/dev/null']:
    if f != '/dev/null': py_compile.compile(f, doraise=True)
print('OK')"

bash scripts/check_singletons.sh

# Dedicated test suite (literal pytest; no pass-by-inspection)
python3 -m pytest tests/test_proactive_pm_sentinel.py tests/test_proactive_pm_sentinel_h5.py -v

# Full-suite regression delta vs main baseline (same pattern as PR #57)
# capture +N passes, 0 new failures
```

---

## Ship report

Append new entry to `briefs/_reports/CODE_2_RETURN.md` (keep the fix-back §9 from PR #57 intact as history; add `## PROACTIVE_PM_SENTINEL_1 ship report — <date>`). Same 8-check format as PR #57 ship report (`ba4f114`): literal ship-gate output, full-suite regression delta, per-feature summary, Files Modified cross-check, Do NOT Touch verified, SKILL rule compliance, pre-merge verification outputs, non-blocking observations.

---

## Handoff

PR link → AI Head #2 on push + ship report.
AI Head #2 runs `/security-review` → on PASS, forwards PR link + trigger reasons (§2.1 + §2.2) to B1 for second-pair-of-eyes → merge only on both green.
Fix-backs (if any) route to B2 (implementation lane), never to B1.

— AI Head #2
