# Handover — AI Head — 2026-04-21 EVENING (Gate 1 one bridge-fix away)

**Date:** 2026-04-21 end of long session (started morning, ran through evening)
**From:** AI Head (outgoing — heavy context)
**To:** Fresh AI Head instance
**Director:** Dimitry Vallen
**Supersedes:** `briefs/_handovers/AI_HEAD_20260421.md` (morning handover)
**Your immediate job:** dispatch B2 for `BRIDGE_HOT_MD_MATCH_TYPE_REPAIR_1` — fixing that unblocks new signals and starts closing Gate 1.

---

## 🚨 READ BEFORE ANYTHING ELSE

**Durable rules (all ratified 2026-04-21; stored in `memory/`):**

1. **Bank model — Tier A/B/C execution authority.** `feedback_ai_head_communication.md`. Director authorizes, AI Head executes.

2. **Plain English only to Director.** `feedback_ai_head_plain_english_only.md`. No SHA / line numbers / SQL / env var names / test counts in chat.

3. **Chat format strict: bottom-line / recommendation / judgment items / fenced blocks for paste-to-agent ONLY.** `feedback_ai_head_chat_format.md`. Director added this mid-session after verbose responses — follow the four-part shape.

4. **Always include recommendation.** `feedback_always_recommend.md`. Every forced-choice ask gets an explicit "Recommendation:" line. Bare A/B/C asks trigger a "pls always add your recommendation" from Director.

5. **Standing Tier A: signal_queue recovery UPDATE** (same envelope as `status='processing' → pending`). `feedback_tier_a_recovery_update.md`. Runs without per-action ask. IF SQL shape deviates (different WHERE, different stage, different SET), escalate back to Tier B.

6. **Director is CEO not engineer — NEVER ask him to do technical tasks.** `feedback_director_is_ceo_not_engineer.md`. This is the sharpest feedback of the session. If you need a web toggle flipped, a config edited, a model pulled, an API key generated: **execute via browser MCP (`mcp__chrome__*`) / API + 1Password / SSH / B-code dispatch.** Never ask Director to click a UI button. Analogy he used: "I do not think that a human AI engineer comes to the company CEO and asks him to go the Cloudflare website to flip a toggle." Applies end-to-end.

7. **Research Agent 7-field handoff protocol.** `feedback_research_agent_handoff_protocol.md`. Research Agent runs in a separate Claude session. Director relays its output via 7-field template.

8. **Migration-vs-bootstrap DDL drift rule.** `feedback_migration_bootstrap_drift.md`. Every brief touching DB columns MUST grep `store_back.py` bootstrap DDL before landing. Four drift bugs landed today — this rule kills the class.

**Terminology:** "T1/T2/T3" = architecture layers (Render / Mac Mini / MacBook). "Tier 1/2/3" = alert urgency (Critical / High / Normal). Never conflate.

---

## Who you are

You are **AI Head** — orchestration + architecture-decision agent for Baker / KBL / Cortex T3.

**Your team:**

- **B1 (Code Brisen #1):** primary coder. Implements features + bug fixes. Writes most production code. Working dir `~/bm-b1`. Today: shipped PRs #30 + #31 + #32 (3 of 4 drift fixes), Cloudflare tunnel setup on Mac Mini.

- **B2 (Code Brisen #2):** coder + diagnostic specialist. Strong at DB drift investigation and silent-failure patterns. Working dir `~/bm-b2`. Today: diagnosed hot_md_match + finalize_retry_count root causes; shipped PR #32. 

- **B3 (Code Brisen #3):** reviewer. Reads B1/B2 PRs, produces APPROVE / REQUEST_CHANGES verdict, generates review reports in `briefs/_reports/B3_*.md`. Working dir `~/bm-b3`. Does not write production code. Today: reviewed + approved all 3 merged PRs.

- **Research Agent:** separate Claude session. Parallel to you. Produces analyses, ideas, proposals. Director relays via 7-field template. No reciprocal mailbox.

- **AI Dennis:** IT shadow agent in Cowork. Vault-equipped via Phase D MCP. Not in scope for pipeline work.

**Dispatch pattern.** You write thin fenced pointer blocks to `briefs/_tasks/CODE_{1,2,3}_PENDING.md`, commit, push. Director pastes a one-line shell command to the named B-code's terminal. B-code pulls, reads the mailbox, acts. Reports back via `briefs/_reports/B{N}_<topic>_<YYYYMMDD>.md`.

**You do NOT write production code.** B-codes do. You DO execute mechanical Tier B actions (DB UPDATEs, Render env ops, CF dashboard navigation via Chrome MCP, SSH to Mac Mini, 1Password fetches) after Director authorization per bank model.

---

## 🎯 What landed today (high-signal)

### 6 code blockers fixed, 3 PRs merged

| # | PR | What |
|---|----|------|
| 30 | baker-master | STEP_CONSUMERS_SIGNAL_CONTENT_SOURCE_FIX_1 — redirected step 1/2/3/5 reads from phantom `raw_content` column to `COALESCE(payload->>'alert_body', summary, '')` |
| 31 | baker-master | STEP1_TRIAGE_JSONB_CAST_FIX_1 — added `::jsonb` cast + `json.dumps` for `related_matters` write |
| 32 | baker-master | STEP6_FINALIZE_RETRY_COLUMN_FIX_1 — inline self-heal ADD COLUMN for `finalize_retry_count` |

### Infrastructure work (Tier B, Director-authorized; all logged in `actions_log.md`)

- **Render env:** `BAKER_VAULT_PATH=/opt/render/project/src/baker-vault-mirror` added.
- **Render env:** `OLLAMA_HOST=https://ollama-mini.brisen-infra.com` added.
- **Cloudflare Tunnel on Mac Mini:** new tunnel `ollama-mini-mac` proxies `127.0.0.1:11434` at `https://ollama-mini.brisen-infra.com`. LaunchAgent installed. Tunnel creds on Mac Mini filesystem (not git).
- **Cloudflare Configuration Rule:** "Disable BIC for Ollama tunnel (ollama-mini)" — disables Browser Integrity Check for the Ollama hostname so Render data-center POSTs reach origin. Rule ID `1e1efbf298544160afbd5c86df43af28`.
- **Mac Mini Ollama:** pulled `gemma2:2b` + aliased as `gemma2:8b` (Baker's hardcoded model name). Actual model file is gemma2:2b (1.6 GB), fast enough for Mac Mini hardware under the 30s default timeout.
- **Tailscale Funnel:** attempted first, failed with unexplained edge-403. Left armed on port 443 → 11434 so a future Tailscale fix requires only one env var flip back. Support ticket drafted in `briefs/_reports/B1_tailscale_funnel_403_diagnosis_20260421.md`.
- **5 recovery UPDATEs** on `signal_queue` to flip stranded rows. Stranding mechanic is the background bug — every time a step errors, rows get stuck at intermediate status. Follow-up brief queued: `PIPELINE_TICK_STRANDED_ROW_REAPER_1`.

### Memory files added this session

- `feedback_ai_head_chat_format.md` — bottom-line / recommendation / judgment / fences for agents only
- `feedback_tier_a_recovery_update.md` — standing auth for recovery UPDATE
- `feedback_director_is_ceo_not_engineer.md` — SHARP rule; read it first
- `feedback_migration_bootstrap_drift.md` — DB drift lesson with anchor incident
- Index updated in `MEMORY.md`

---

## 🔥 Current pipeline state (at handover)

### Infrastructure: ALL HEALTHY ✅

- Cloudflare tunnel live + BIC exempted
- Ollama reachable from Render (`https://ollama-mini.brisen-infra.com`)
- Model gemma2:8b (aliased to 2b) responds in ~2s warm
- Baker step consumers 1-6 all fixed
- Render deploy includes all 3 PRs merged today

### Pipeline: PARTIALLY WORKING ⚠️

- 16 test signals in signal_queue from earlier today's bridge cycles
- **All 16 advanced through Steps 1-5.** Triage summaries populated, step_5_decision=`skip_inbox`, opus_draft_markdown populated.
- **All 16 stuck at `status='awaiting_finalize'`** for two reasons:
  1. Architectural: `claim_one_signal` only picks up `status='pending'` rows. Once stranded at intermediate status, only recovery UPDATE can release.
  2. Content: Opus decided all 16 are out-of-scope (matters not aligned). They're destined for `routed_inbox` terminal state — **Step 7 never runs on them, so target_vault_path + commit_sha never populate, so Gate 1 criteria never met**.

### Bridge: BROKEN ❌

`alerts_to_signal_bridge` failing every tick (24+ errors in 10 min window) with:
```
bridge tick failed: invalid input syntax for type boolean: "Lilienmatt"
```

**Root cause (B2 diagnostic from afternoon, fix deferred):** `signal_queue.hot_md_match` column is BOOLEAN in live DB (pre-existing bootstrap in `memory/store_back.py:6213` from KBL-19 era) but PR #29's `ADD COLUMN IF NOT EXISTS hot_md_match TEXT` silently no-op'd. Bridge binds matter-name strings into a BOOLEAN column → every tick rolls back → no new signals land.

**Full diagnostic:** `briefs/_reports/B2_bridge_hot_md_match_drift_20260421.md`

**Fix direction (ratified):** TEXT. ALTER COLUMN TYPE + fix bootstrap DDL + add type-reconciliation helper. XS effort (<1h). Brief name: `BRIDGE_HOT_MD_MATCH_TYPE_REPAIR_1`.

**Why fix matters:** without it, no NEW signals reach signal_queue. And since the existing 16 will all terminate at routed_inbox, Gate 1 can't close on current inventory — needs fresh in-scope signals.

---

## 🎯 Cortex T3 Gate 1 — critical path

**Gate 1 criteria:** ≥5-10 signals reach Step 7 terminal state with `target_vault_path` + `commit_sha` populated.

**Path (hand this exactly to the new AI Head):**

1. **[Immediate]** Dispatch B2 for `BRIDGE_HOT_MD_MATCH_TYPE_REPAIR_1` — brief exists in B2's earlier diagnostic report. XS effort, dispatch via standard mailbox pattern.
2. **[~30 min]** B2 ships PR. Route to B3 for review. Tier A auto-merge on APPROVE.
3. **[~3 min]** Render deploy goes live.
4. **[Optional — decide based on watch]** Recovery UPDATE for bridge-stranded rows, if any.
5. **[Watch 1-2 hours]** Bridge heals. New signals flow in from email/WhatsApp/RSS sentinels. Mix of in-scope and out-of-scope. In-scope signals (Hagenauer, Cupials, MO Vienna, KBL, etc.) pass Opus gate → reach Step 6 → status='awaiting_commit'.
6. **[Mac Mini]** Poller on Mac Mini claims `awaiting_commit` rows, runs Step 7 (git commit to vault), populates `target_vault_path` + `commit_sha`, advances to `status='completed'`.
7. **[Gate 1]** Once ≥5-10 rows at `status='completed'` with both fields populated, Gate 1 closes.

### Post-Gate-1 briefs already queued (do NOT start before Gate 1)

- `STEP_SCHEMA_CONFORMANCE_AUDIT_1` — B3-endorsed CI lint rules for JSONB shape + column existence drift (would have caught all four of today's drift bugs)
- `PIPELINE_TICK_STRANDED_ROW_REAPER_1` — time-bounded auto-recovery for intermediate-status stranding (replaces the standing-auth recovery UPDATE pattern)
- Claim-transactionality fix (wrap claim + step-work in single transaction OR add idle-row reaper) — kills the recurring stranding bug that caused 5 recovery UPDATEs today

---

## 📁 Key files to read on refresh

| Path | Purpose |
|------|---------|
| `memory/actions_log.md` | Full Tier B paper trail — 9 entries from today, gives you context on what's deployed |
| `memory/feedback_director_is_ceo_not_engineer.md` | Most important durable rule added today — internalize before acting |
| `memory/feedback_ai_head_chat_format.md` | Chat-output shape you must follow |
| `memory/feedback_tier_a_recovery_update.md` | What you can run without asking; what still requires Tier B |
| `briefs/_reports/B2_bridge_hot_md_match_drift_20260421.md` | Complete diagnostic for the next brief you're dispatching |
| `briefs/BRIEF_SOT_OBSIDIAN_1_PHASE_D_VAULT_READ.md` | SOT Phase D context (earlier in day — completed) |

---

## ⚙️ Workflow patterns (unchanged)

### Code Brisen dispatch

- Tasks: `briefs/_tasks/CODE_{1,2,3}_PENDING.md` — overwrite, commit, push. Fenced block format.
- Reports: `briefs/_reports/B{N}_<topic>_<YYYYMMDD>.md`.
- Director pastes: `cd ~/bm-b{N} && git pull -q && cat briefs/_tasks/CODE_{N}_PENDING.md`
- Working dirs: `~/bm-b{N}` — NOT `/tmp/`.

### Tier B via 1Password

- Fetch Render API token: `TOKEN=$(op item get "API Render" --vault "Baker API Keys" --fields credential --reveal 2>/dev/null)`
- Reference: `memory/reference_render_api_ops.md` (Render patterns) + `memory/reference_1password_secrets.md` (vault layout).

### Auto-merge protocol

```bash
gh pr merge <N> --repo vallen300-bit/baker-master --squash --subject "<title> (#<N>)"
```

Gate: B3 APPROVE + CLEAN mergeable + no Director blockers.

### Recovery UPDATE (standing Tier A)

Only for `status='processing', stage='triage', triage_score IS NULL` pattern. Any deviation → Tier B.

---

## 🆕 Net-new tools you have (via ToolSearch)

This session used heavily:
- **`mcp__chrome__*`** — Chrome MCP. Navigate, take_snapshot, click, fill, wait_for. Used for Cloudflare dashboard navigation.
- **`mcp__baker__baker_raw_query` / `baker_raw_write`** — direct PG access.
- **`WebFetch`** — test URL reachability from Anthropic's network (off-tailnet validation).
- **Bash SSH to macmini** — alias in `~/.ssh/config`, works out of the box.

Load via ToolSearch on demand.

---

## 🧭 First 10 minutes of your session

1. Read this handover end to end (~10 min).
2. `cd /tmp && rm -rf /tmp/bm-draft && git clone https://github.com/vallen300-bit/baker-master.git /tmp/bm-draft && cd /tmp/bm-draft`
3. `git log --oneline -20` — confirm commits `078a004` (PR #32 merge), `7113b62` (#31), `20d7935` (#30), `c5a4f44` (B2 dispatch) are visible.
4. `gh pr list --repo vallen300-bit/baker-master --state open` — expect empty.
5. Read `briefs/_reports/B2_bridge_hot_md_match_drift_20260421.md` (the next brief's substrate).
6. Read `memory/feedback_director_is_ceo_not_engineer.md` — internalize.
7. Read `memory/MEMORY.md` index top to bottom — 5 new rules added today are all listed.
8. `curl -sS https://baker-master.onrender.com/health | jq '{status, scheduled_jobs}'` — expect healthy + 46 jobs.
9. `mcp__baker__baker_raw_query {"sql": "SELECT stage, status, COUNT(*) FROM signal_queue GROUP BY stage, status"}` — expect 16 at `triage / awaiting_finalize`.
10. Check bridge health: `mcp__baker__baker_raw_query {"sql": "SELECT COUNT(*), MAX(ts) FROM kbl_log WHERE component='alerts_to_signal_bridge' AND level='ERROR' AND ts > NOW() - INTERVAL '10 minutes'"}` — expect errors still present.

---

## 🎬 Status ping to Director after refresh

```
AI Head refreshed — evening handover read.

Infra: all healthy (Cloudflare tunnel + BIC exempt + Ollama gemma2:8b responding).
Pipeline: Steps 1-6 all fixed + deployed today.
Blocker for Gate 1: bridge `hot_md_match` BOOLEAN bug — no new signals landing.
Existing 16 signals: all destined for routed_inbox (Opus out-of-scope) — can't close Gate 1 on them.

Critical path: dispatch B2 for BRIDGE_HOT_MD_MATCH_TYPE_REPAIR_1 (diagnostic already shipped). 30 min B2 + 20 min B3 + 3 min deploy + 1-2h bridge catch-up + Mac Mini Step 7 picks up awaiting_commit rows → Gate 1 closes.

Standing by to dispatch B2 now. Paste block ready if you greenlight.
```

---

## ⚠️ Things NOT to do

- Do not ask Director to do anything web-UI-related. Use `mcp__chrome__*` or dispatch B1/B2/B3.
- Do not run the recovery UPDATE on `awaiting_finalize` rows — the 16 existing will all go to routed_inbox, wasting Ollama cost without advancing Gate 1.
- Do not touch `CHANDA.md` (Tier B, Director explicit yes required).
- Do not refresh `hot.md` — that's a Director-curated file.
- Do not commit credentials or tunnel .json files.
- Do not write SHA / line numbers / SQL / env var names in chat to Director.
- Do not proactively dispatch the post-Gate-1 briefs (STEP_SCHEMA_CONFORMANCE_AUDIT_1, PIPELINE_TICK_STRANDED_ROW_REAPER_1). Wait for Gate 1.

---

*Prepared 2026-04-21 evening. 9 Tier B actions logged. 6 code blockers fixed across 3 PRs. Infrastructure end-to-end proven. One bridge bug stands between today's work and Gate 1 closure.*
