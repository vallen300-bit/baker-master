# Handover — AI Head #1 — 2026-04-24 MORNING (Team 1 mid-flight, 3 briefs dispatched)

**Date:** 2026-04-24 ~01:15 UTC
**From:** AI Head #1 (outgoing — Team 1, meta-persistence lane)
**To:** Fresh AI Head #1 instance
**Director:** Dimitry Vallen
**Supersedes:** `briefs/_handovers/AI_HEAD_20260423_MORNING.md`
**Your immediate job:** monitor 3 in-flight Team 1 dispatches. Route B3 reviews when ships land. Then M1 wiki seed window opens.

---

## 🚨 Charter unchanged. SKILL.md unchanged.

Canonical: `/Users/dimitry/baker-vault/_ops/processes/ai-head-autonomy-charter.md`. SKILL.md `_ops/skills/ai-head/SKILL.md` has 9 §Brief Authoring rules (rules 7-9 added 2026-04-23 MOVIE AM session).

**Bank-client frame (charter §2) remains the dominant rule.** Director invoked "See for yourself what works better" 2026-04-23 + corrected arbitrary b5/b1 lane split. Decide autonomously on everything inside charter §3 zone; flag §4 prerogatives only.

**Parallel-teams pattern still active.** Team 1 (you) = meta + M0 quintet + post-M0 sequencing. Team 2 = domain-feature work (MOVIE AM closed; CAPABILITY_THREADS_1 is their new Phase-2 AO-PM-Continuity dispatch — see `a9941f3` on main). Triplet write authority: Team 1. Don't touch Team 2's work.

---

## 🎯 What shipped since last handover (2026-04-23 MORNING → 2026-04-24 ~01:15 UTC)

**Team 1 merged:**
- PR #51 `LEDGER_ATOMIC_1` — CHANDA detector #2 runtime DB txn wrapper.
- PR #52 `KBL_SCHEMA_1` — schema templates + people.yml + entities.yml + VAULT.md rules (B/A/A design calls applied).
- PR #53 `MAC_MINI_WRITER_AUDIT_1` — CHANDA detector #9 documentation + monthly audit runbook.
- PR #55 `KBL_INGEST_ENDPOINT_1` (merged `c578b58`) — POST `/api/kbl/ingest` single wiki-write chokepoint (CHANDA #2 atomic + Gold mirror).

**Team 2 merged (don't touch):**
- PR #56 `PM_EXTRACTION_MAX_TOKENS_2` (merged `281661d`) — Opus ceiling 1500→3000 + output_tokens telemetry.

**Side-task executed (charter §3 Tier A, 2026-04-24 ~00:50 UTC):**
- Signal 104 (stuck `processing` 32h, legacy Owner's Lens) → flipped to `awaiting_triage`, `started_at=NULL`.
- Signal 128 (`commit_failed` — Cyprus Holding Structure / Mac Mini dirty index 2026-04-23 17:06 UTC) → flipped to `awaiting_commit` for retry.
- Sentinel liveness: all 8 alive. Ingestion stall = quiet period.
- `kbl_pipeline_tick` 4 errors in 24h — informational flag, low priority.

**Dispatched, not yet shipped (3 Team 1 in flight):**
- B1 on `PROMPT_CACHE_AUDIT_1` (M0 row 4, ~3h budget, started 2026-04-24 post PR #55 merge). Parallel to B3.
- B3 on `CITATIONS_API_SCAN_1` (M0 row 5, independent scope).
- B5 on `CHANDA_PLAIN_ENGLISH_REWRITE_1` (paired with shipped ENFORCEMENT_1, ~30–45 min). **First actual ship for b5** — prior GUARD_1 dispatch was re-routed b5 → b1 by Director 2026-04-23.

---

## 🔥 Current state at handover (~01:15 UTC)

### PRs: **0 open** (all 3 dispatches still in B-code build phase; PRs will be opened on ship-report commit).

### Brisens
| Brisen | State | Task | Working dir |
|---|---|---|---|
| **b1** | BUSY | PROMPT_CACHE_AUDIT_1 (audit script + top-3 cache_control + 24h hit-rate telemetry) | `~/bm-b1` |
| **b2** | BUSY | CAPABILITY_THREADS_1 (Team 2 — Phase 2 AO PM Continuity) | `~/bm-b2` |
| **b3** | BUSY | CITATIONS_API_SCAN_1 (Anthropic Citations API adoption in Scan endpoint) | `~/bm-b3` |
| **b5** | BUSY | CHANDA_PLAIN_ENGLISH_REWRITE_1 (pure-replace CHANDA.md) | `~/bm-b5` |

### Infra
- **baker-master main:** `1e227a6` (last commit = my B5 dispatch).
- **baker-vault main:** current tip ~`e6027d0` (yesterday) + Research Agent pre-mortem + any Team 2 scratch pushes.
- **Render:** live, auto-deploys on push to main.
- **Weekly audit cron** (PR #44): Mon 09:00 UTC first fire `2026-04-27T09:00:00Z` (~60h out).
- **Sentinel cron** (PR #48): Mon 10:00 UTC first fire. Clean confirm silent; miss → Slack DM `D0AFY28N030`.
- **CHANDA #4 hook** (PR #49): LIVE on Mac Mini `~/baker-vault/.git/hooks/pre-commit` (3562 bytes, smoke-tested). Baker-master belt-and-braces install still deferred to Director-local.

### Queue health (2026-04-24 ~00:50 UTC post-recovery)
- completed: 138
- awaiting_commit: 2 (signal 128 retry + 1 prior backlog — Step 7 will self-heal)
- awaiting_triage: 1 (signal 104 post-recovery — Step 1 will re-claim)

---

## 🎯 Critical path (your first 15 minutes)

1. Read the charter (unchanged).
2. Read OPERATING.md at `/Users/dimitry/baker-vault/_ops/agents/ai-head/OPERATING.md`.
3. Skim ARCHIVE Session 2 (2026-04-23 Team 1 + Team 2 composite — `/Users/dimitry/baker-vault/_ops/agents/ai-head/ARCHIVE.md`).
4. Read this handover end to end.
5. `cd "/Users/dimitry/Vallen Dropbox/Dimitry vallen/Baker-Project/15_Baker_Master/01_build" && git pull -q && git log --oneline -10`
6. `gh pr list --repo vallen300-bit/baker-master --state open --json number,title`
   - If 0 PRs → B-codes still building; stand by.
   - If 1+ PRs from B1/B3/B5 → route B3 review via CODE_3_PENDING.md (pattern: see recent B3 review dispatches on main).
7. Queue health check:
   ```
   mcp__baker__baker_raw_query {"sql": "SELECT status, COUNT(*) FROM signal_queue GROUP BY status ORDER BY COUNT(*) DESC"}
   ```
   Expect: 138+ completed, a handful of awaiting_* transients. Anything >24h stuck → Tier A recovery (see side-task pattern in actions_log.md 2026-04-24 ~00:50Z entry).

---

## 🧨 Pending at handover

### In flight — monitor these (no action until B-code returns)

1. **B1 PROMPT_CACHE_AUDIT_1** — on ship, dispatch B3 review + merge on APPROVE (Tier A).
2. **B3 CITATIONS_API_SCAN_1** — on ship, dispatch B2 review (B3 is busy on his own brief; route to B2 or wait for B3 idle). On APPROVE, Tier A merge.
3. **B5 CHANDA_PLAIN_ENGLISH_REWRITE_1** — on ship, dispatch B3 review + merge on APPROVE. b5's first actual ship; verify exec path works.

### Queued autonomous after M0 closes (no Director ask needed)

4. **M1 wiki seed** — once M0 rows 4+5 ship + CHANDA_REWRITE merges, M0 is CLOSED. M1 window opens.
   - `BRIEF_KBL_SEED_1` — Phase 1 migration script (~60–90 .md files from Dropbox `memory/` + CLAUDE.md tables + Postgres profile rows, validated through KBL ingest endpoint just shipped).
   - Per Cortex-3T roadmap `_ops/ideas/2026-04-21-cortex3t-production-roadmap.md` M1 scope.

5. **Queue health follow-ups** — check signals 104 + 128 within 4h of session resume:
   - Signal 104: `awaiting_triage` → should reach `classified-deferred` or `completed` on next ticks.
   - Signal 128: `awaiting_commit` → Step 7 retry should succeed (Mac Mini index clean now).
   - If either still stuck after 4h, escalate per §4 matter-routing parked item OR treat as another commit-failed class.

### Queued Director-gated (§4)

6. **`BRIEF_CORTEX3T_MVP_HAGENAUER_1`** — M3 window after M1+M2 land. Must bundle TIER_B_BUDGET_1 + S5_RUNTIME_1 as mandatory deliverables (NOT separate briefs) per Research Agent's 2026-04-23 pre-mortem (`_ops/ideas/2026-04-23-cortex3t-premortem.md`). 5 post-M3 mitigations named in pre-mortem but DO NOT pre-stage.
7. **Cortex-3T reasoning-loop design session** — still pending (roadmap open Q#1).
8. **Matter-routing quality** — Step 1 over-routes to `hagenauer-rg7`. Parked §4 #1/#2/#11. Not blocking until M6 fanout.

### Parked Monday 2026-04-27 audit

9. **Baker Health survey migration** — Cowork → Baker APScheduler consolidation. Director flagged 2026-04-24. Not urgent; fits natural weekly audit rhythm alongside `ai_head_weekly_audit` first-fire.

---

## ⚠️ Known gotcha — `baker_raw_write` status='pending' guard

**Surfaced 2026-04-24 ~00:45 UTC during signal 104 recovery.** `baker_raw_write` rejects `UPDATE signal_queue SET status='pending'` with a misleading "cannot execute UPDATE in a read-only transaction" error. Same tool/same connection accepts `status='awaiting_triage'` and any other `awaiting_*` state on the same row.

**Hypothesis:** intentional safety guard against reverting to the raw-ingest `pending` state (which would indicate "something bigger is wrong"). Error message is wrong; behavior is right.

**Rule for recoveries:** use `awaiting_triage` for re-claim (stuck `processing`), `awaiting_commit` for re-claim (stuck commit_failed), etc. Don't use `pending` as a recovery target. Full context in `actions_log.md` 2026-04-24 ~00:50Z entry.

---

## 📁 Key files to read (★ = new this session)

| Path | Purpose |
|------|---------|
| `/Users/dimitry/baker-vault/_ops/processes/ai-head-autonomy-charter.md` | Charter (unchanged) |
| `/Users/dimitry/baker-vault/_ops/skills/ai-head/SKILL.md` | §Brief Authoring rules 1-9 (7-9 scar-tissue from MOVIE AM) |
| `/Users/dimitry/baker-vault/_ops/agents/ai-head/OPERATING.md` | Refreshed last session; needs re-write at this session close |
| `/Users/dimitry/baker-vault/_ops/agents/ai-head/ARCHIVE.md` | Session 2 block (2026-04-23 composite) |
| `memory/actions_log.md` | ★ Extensive 2026-04-24 entries: side-task Tier A (signal 104/128, sentinel liveness), PR merges |
| `briefs/BRIEF_CHANDA_PLAIN_ENGLISH_REWRITE_1.md` | ★ NEW — in flight on b5 |
| `_ops/ideas/2026-04-23-cortex3t-premortem.md` | Ratified — M3 constraint (TIER_B_BUDGET_1 + S5_RUNTIME_1 mandatory inside CORTEX3T_MVP_HAGENAUER_1) |
| `_ops/ideas/2026-04-21-cortex3t-production-roadmap.md` | 6-milestone roadmap — M1 wiki seed is next after M0 closes |

---

## ⚙️ Workflow (unchanged)

- Dispatch via `briefs/_tasks/CODE_{1,3,5}_PENDING.md` — overwrite, commit, push.
- Trigger: `cd ~/bm-b{N} && git checkout main && git pull -q && cat briefs/_tasks/CODE_{N}_PENDING.md`
- Auto-merge: `gh pr merge N --repo vallen300-bit/baker-master --squash --subject "<title> (#N)"`
- Pre-merge rebase on PR branch only if GitHub reports CONFLICTING (use `--force-with-lease`, never force-push main).
- SSH to Mac Mini: `ssh macmini` (confirmed working).
- Route to proven + idle Brisen. **Don't invent lane models** (lesson from 2026-04-23 Director correction).

---

## 🎬 Status ping to Director after refresh

```
[TEAM-1] AI Head #1 refreshed — morning handover read. Charter active.

3 in-flight Team 1 dispatches (B1 PROMPT_CACHE, B3 CITATIONS, B5 CHANDA
rewrite). 0 open PRs — all in B-code build phase. Queue healthy post
side-task recovery (signal 104 + 128). Weekly audit first-fire Mon
09:00 UTC ~60h out.

Standing by for first PR from B1/B3/B5. On ship: route B3/B2 review
per charter §3 Tier A.
```

---

## ⚠️ Things NOT to do (carried + this-session additions)

### Charter-rooted
- Do not ask Director to authorize technical actions (charter §3).
- Do not re-explain ratified rules in chat (charter §6).
- Do not touch `CHANDA.md` without `Director-signed:` marker in commit message (invariant #4 forward-compatible pattern).
- Do not dispatch matter-routing quality fix without Director (§4 #1/#2/#11).
- Do not pre-stage post-M3 pre-mortem mitigations (Director: "premature").

### Session-captured additions
- **Do NOT use `status='pending'` in signal_queue recoveries** — use `awaiting_triage` or other `awaiting_*` state. `baker_raw_write` silently blocks pending-recovery with misleading error.
- **Do NOT touch Team 2 work** — CAPABILITY_THREADS_1 (B2) is their dispatch.
- **Do NOT force-push main.** PR branch rebase-and-force-with-lease when conflicting — that's it.
- **Do NOT skip SKILL.md rules 7-9** — file:line cite verify / singleton `_get_global_instance()` / post-merge `git pull --rebase`.
- **Do NOT preempt in-flight B-code work** with new dispatches unless genuinely independent scope.

---

## 🗒️ Session lessons (captured in actions_log.md + SKILL rules)

1. `baker_raw_write` has `status='pending'` guard — use `awaiting_*` states for recoveries.
2. Director's bank-client frame (charter §2) dominates — before asking, run the 3-check: (a) CEO-worthy? (b) what-not-how? (c) reversible?
3. M0 row 2 (CHANDA_DETECTORS_TOP3) decomposed into 4 sub-briefs per Research's engineering matrix — all shipped by this handover (ENFORCEMENT_1 + GUARD_1 + LEDGER_ATOMIC_1 + MAC_MINI_WRITER_AUDIT_1).
4. CHANDA_PLAIN_ENGLISH_REWRITE_1 needs `Director-signed:` commit marker as forward-compat pattern (baker-master hook deferred to Director-local install).
5. Signal-queue mechanical recovery is standing Tier A; log to actions_log post-facto — no per-action ask needed.

---

*Prepared 2026-04-24 MORNING. 3 Team 1 briefs in flight (PROMPT_CACHE_AUDIT_1, CITATIONS_API_SCAN_1, CHANDA_PLAIN_ENGLISH_REWRITE_1). 0 open PRs. Queue healthy. M0 quintet all dispatched (rows 4+5 in B-code phase; rows 1+2+3 shipped yesterday). Next after M0 closes: M1 wiki seed.*
