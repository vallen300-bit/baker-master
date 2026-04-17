# KBL 3T Phase 1 — Roadmap

**Status:** Active plan
**Date:** 2026-04-17
**Decision:** 3T architecture (Option B), NOT 2T. Mac Mini becomes Tier 2 runtime after hardening.
**Reference docs:**
- `briefs/ARCHITECTURE_CORTEX_3T_KBL_UNIFIED.md` — 59 locked decisions (architecture)
- `briefs/KBL-A_INFRASTRUCTURE_2T_CODE_BRIEF.md` (in Dropbox/pm/briefs/) — 2T fallback brief (NOT CURRENT PATH)
- `briefs/KBL-A_INFRASTRUCTURE_CODE_BRIEF.md` (in Dropbox/pm/briefs/) — original 3T brief (needs rewrite, see step 4)
- `CHANDA.md` — architectural intent (to be created by KBL-A dispatch)

---

## Why 3T (recap)

The unified architecture review found 4 BLOCKER contradictions in 3T as originally written. Director chose to fix the Mac Mini hardening gaps rather than retreat to 2T. Value lost in 2T: Claude Code harness with 200K context on Mac Mini, warm Ollama (saves cost), local Obsidian cockpit, file watchers for Gold promotion. Director values the cockpit feel — hence 3T.

---

## Mac Mini Hardening Status (2026-04-17)

### Completed
- [x] Tailscale on MacBook + Mac Mini (tailnet `tail4c0b32.ts.net`)
- [x] SSH config updated to Tailscale hostname — `ssh macmini` works from any network
- [x] Stale SSH sessions cleaned (load 6.3 → 2.8, RAM freed ~670 MB)
- [x] baker-code pulled to main `42ecb8b` (was 3 weeks stale)
- [x] Uncommitted local state stashed as `macmini-cleanup-20260417`
- [x] Ollama installed (v0.20.7), running as Homebrew service (auto-start on boot)
- [x] Gemma 4 8B pull (9.6 GB) — completing at time of writing
- [x] 1Password CLI installed (`op` v2.34.0)
- [x] baker-vault cloned to `~/baker-vault/` from `vallen300-bit/baker-vault`
- [x] Vault already has auto-backup cron (latest commit `vault backup: 2026-04-16 13:26:25`)
- [x] Power: `autorestart=1`, `sleep=0`, `womp=1`, `powernap=1`

### Deferred (tracked, not blocking Phase 1)
- [ ] **Secret migration Plan A** — rotate ANTHROPIC_API_KEY + DATABASE_URL, move 5 plaintext env vars from `~/.zshrc` into 1Password via `op read`. Scheduled between step 10 and step 13 below.
- [ ] **UPS (APC BE600 ~€150)** — offline purchase task
- [ ] **Close Mac Mini workstation apps** (ClickUp, Chrome, Mail, Claude desktop, Wispr Flow, VM) to free RAM for Ollama + `claude -p` batches. Director uses them via Supremo from MacBook — running on both is redundant.

---

## The Plan: Gemma Verification → Hagenauer Live

### Today (next ~2 hours)

| Step | What | Who | Time |
|---|---|---|---|
| 1 | **Verify Gemma 4 8B** loads in Mac Mini Ollama, API responds | AI Head via SSH | 5 min |
| 2 | **Re-run KBL triage benchmark on Mac Mini** — confirm steady-state latency + 5/5 baseline with entity-map prompt | AI Head via SSH | 10 min |
| 3 | **Verify `claude -p` on Mac Mini** can read vault + baker-code together (200K context check) | AI Head via SSH | 5 min |
| 4 | **Rewrite KBL-A brief for 3T.** 2T brief becomes the fallback/graduation-target reference. Adds back: `wiki_staging` table, signal_queue GET/PUT endpoints, `tier2_heartbeat` deadman switch, canary synthetic for silent-failure detection, `FOR UPDATE SKIP LOCKED` concurrency control. Resolves all 4 BLOCKERs from the unified review. | AI Head | 60-90 min |

### This Week

| Step | What | Who | Time |
|---|---|---|---|
| 5 | **Dispatch KBL-A 3T infrastructure** to Code Brisen on Mac Mini | Code Brisen | 6-8 h |
| 6 | **Write KBL-B brief** — the 8-step pipeline. Gemma for 1-4, Opus for 5, Sonnet for 6, code for 7-8. 15-min cron via LaunchAgent. Cost circuit-breaker. Dual-write to vault + `wiki_pages` cache for dashboard. | AI Head | 90-120 min |
| 7 | **Dispatch KBL-B pipeline** | Code Brisen | 8-12 h |
| 8 | **Write KBL-C brief** — interface layer. Ayoniso alerts via WhatsApp, Gold promotion detection (file-watcher on vault), feedback ledger reader, hot.md reader, Scan-to-vault bridge. | AI Head | 90-120 min |
| 9 | **Dispatch KBL-C interface** | Code Brisen | 6-8 h |

### Phase 1 Go-Live (end of this week / early next)

| Step | What | Who | Time |
|---|---|---|---|
| 10 | **Seed Hagenauer in vault** — populate `hot.md` with current priorities; migrate existing 14 `wiki_pages` to `baker-vault/wiki/` as Silver | AI Head + Director review | 60 min |
| 11 | **Secret migration + rotation** (deferred item). 1Password Plan A: rotate ANTHROPIC_API_KEY + DATABASE_URL, migrate 5 secrets to `op`. | AI Head + Director | 30-45 min |
| 12 | **UPS delivered + connected** | Director | 1 day shipping |
| 13 | **Flip `KBL_PIPELINE_ENABLED=true`** on Render — pipeline goes live in **shadow mode** for Hagenauer only (KBL-25) | AI Head via Render MCP | 2 min |

### Phase 1 Validation (2 weeks after go-live)

| Step | What | Who |
|---|---|---|
| 14 | **Shadow-mode observation** — pipeline processes all Hagenauer signals, logs which would have been filtered. No writes to wiki yet. | automated |
| 15 | **Daily review** — Director scans shadow log, AI Head flags anomalies, calibrate `TRIAGE_THRESHOLD` empirically | Director + AI Head |
| 16 | **First Silver → Gold promotions** — Director edits `author: director` on 5-10 cards, validate file-watcher commits + cetasika cascade works | Director |
| 17 | **First ayoniso alerts** — test with forced contradiction (hot.md deprioritizes Hagenauer, signal says court filing) — validate WhatsApp alert lands, no autonomous override | AI Head (test) |
| 18 | **Phase 1 success criteria check:** ≥90% vedanā accuracy, zero false Gold overwrites, ayoniso FP rate <20%, cost <$10/day, clean 2-week shadow | metrics + Director |

### Phase 2 — Scale (post-validation)

- Extend matters: Cupial, Mo-Vie, AO, MORV, Lilienmatt, Wertheimer
- Migrate remaining wiki_pages content
- Per-matter threshold tuning
- Scan-to-vault bridge for ad-hoc Director research captures
- Revisit Baker SLM (parked) if volume justifies

---

## Decision Gates (AI Head will ASK before crossing)

1. **After step 4** — review KBL-A 3T brief with Director before dispatch
2. **After step 6** — Director approves cost ceiling + circuit-breaker values
3. **Before step 13** — final go/no-go with Director
4. **Mid-shadow-mode (step 15)** — if threshold calibration suggests big changes
5. **End of Phase 1 validation** — go/no-go for Phase 2 scale

---

## Known Gaps Already Flagged (resolved in step 4 rewrite)

From the unified review — all must be addressed in KBL-A 3T brief:

1. **Concurrency control** — `FOR UPDATE SKIP LOCKED` on pipeline signal claim (avoid cron overlap double-processing)
2. **Gold-promotion detection mechanism** — file watcher on vault vs explicit endpoint vs diff-on-pull. Pick and spec.
3. **Cost circuit-breaker** — daily Anthropic spend cap enforced before Step 5/6 API calls
4. **Canary synthetic** — inject heartbeat signal every 30 min; alert if not `done` within 2 cron cycles (KBL silent-failure detector, WAHA-SILENT-GUARD analog)
5. **Authoritative single-writer clarification** — single-writer means only Mac Mini commits to `wiki/` synthesized layer; `raw/` is append-only multi-writer; Gold promotions are Director-only via frontmatter flag in separate commit
6. **Tier-separated PG roles** — `render_rw` and `macmini_rw` with scoped grants; not a shared `DATABASE_URL`
7. **`KBL_PIPELINE_ENABLED` feature flag** — rollback guarantee

---

## Critical Path Totals

- Code Brisen work: **~25-35 hours** (3 dispatches)
- AI Head brief-writing: **~6-8 hours**
- Director review time: **~2 hours**
- 2-week shadow mode validation
- **Target: Hagenauer in production early next week** if no blockers

---

## Rollback Path

If Phase 1 regresses Cortex V2: `KBL_PIPELINE_ENABLED=false` on Render — pipeline halts, Cortex V2 keeps running. Mac Mini Tier 2 is idle, not decommissioned (can re-enable when fix ready). Vault and signal_queue state preserved.

---

*Prepared by AI Head (Claude Opus 4.7) 2026-04-17. Next edit: after step 4 (KBL-A 3T brief complete).*
