# Handover — AI Head — 2026-04-22 LATE (Gate 2 CLOSED, charter ratified, orphan-states brief queued)

**Date:** 2026-04-22 ~07:50 UTC (end of session spanning early 2026-04-22 02:30 UTC → 07:50 UTC)
**From:** AI Head (outgoing — Gate 2 close + autonomy charter ratification + 2 PRs merged + watchdog live)
**To:** Fresh AI Head instance
**Director:** Dimitry Vallen
**Supersedes:** `briefs/_handovers/AI_HEAD_20260422_EARLY.md`
**Your immediate job:** watch B1 land `CLAIM_LOOP_ORPHAN_STATES_2` (mailbox waiting), route to B3, merge, read watchdog output for anomalies.

---

## 🚨 READ BEFORE ANYTHING ELSE — THE CHARTER

**NEW THIS SESSION, RATIFIED:** The AI Head autonomy charter. Read it first — it supersedes a lot of older asking patterns.

**Canonical:** `/Users/dimitry/baker-vault/_ops/processes/ai-head-autonomy-charter.md`
**Mirror:** `memory/feedback_ai_head_autonomy_charter.md`

**TL;DR:** Director is CEO. AI Head is dept-head. AI Head executes **all technical work autonomously** — brief drafting, B-code dispatch, PR merges, DB recoveries within pre-authorized scope, Render ops, memory writes. Director is consulted ONLY on the 13 named Cortex Design prerogatives in §4. Bank model Tier B per-action authorization for technical matters is **retired**.

### Charter §6 communication rules (what changed)

- Post-facto plain-English reports, not pre-ask phrasing.
- Trigger lines in fenced blocks for paste-to-agent — framed as "trigger:" not "authorize + paste."
- **No re-explanation of ratified rules in chat.** One-line confirmation ("charter filed, active now") is enough. Details live in the file.
- **Report on close, not mid-flight.** Details compiled at milestone close.

### Charter §6A brief-drafting route

All B-code briefs now follow `/write-brief` skill (6-step: EXPLORE → PLAN → WRITE → REVIEW → PRESENT → CAPTURE LESSONS). Canonical skill file: `_ops/processes/write-brief.md`. Freehand briefs only for (a) emergency hot-fix, (b) continuation-of-work, (c) explicit Director skip.

### Durable rules (all at `memory/` or `_ops/processes/`)

1. **AI Head autonomy charter** — this session's new top rule.
2. Plain English only to Director (`feedback_ai_head_plain_english_only.md`).
3. Chat format: bottom-line / recommendation / judgment / fences for paste-to-agent (`feedback_ai_head_chat_format.md`).
4. Always include recommendation on §4 asks (`feedback_always_recommend.md`).
5. Director is CEO not engineer (`feedback_director_is_ceo_not_engineer.md`) — reinforced by charter.
6. **No ship without full green pytest** (`feedback_no_ship_by_inspection.md`). REQUEST_CHANGES any ship report saying "by inspection."
7. Migration-vs-bootstrap DDL drift (`feedback_migration_bootstrap_drift.md`).
8. 1Password secret access (`reference_1password_secrets.md`).
9. Baker MCP live (`reference_baker_mcp_live.md`).
10. Render API ops (`reference_render_api_ops.md`).

---

## Who you are

AI Head — orchestration + architecture-decision agent. Team: B1 (primary coder, `~/bm-b1`), B2 (coder + diagnostic, `~/bm-b2`), B3 (reviewer only, `~/bm-b3`). Research Agent = separate Claude session.

Dispatch pattern: write fenced pointers to `briefs/_tasks/CODE_{1,2,3}_PENDING.md`, commit + push. Director pastes one-line shell to the named B-code's tab. **AI Head does NOT ask Director to authorize the dispatch itself** (charter §3). B-code pulls, reads, acts, reports back via `briefs/_reports/B{N}_<topic>_<YYYYMMDD>.md`.

You do NOT write production code. B-codes do. You DO execute Tier B ops autonomously now (DB UPDATEs within pre-authorized matter scope, Render API, Chrome MCP, SSH to Mac Mini, 1Password fetches).

---

## 🎯 What landed this session (high-signal)

### 2 PRs merged

| # | PR | What | Result |
|---|----|------|--------|
| #37 | STEP4_HOT_MD_PARSER_FIX_1 | Section regex + multi-slug combo bullet parser in `kbl/steps/step4_classify.py`. Live hot.md now yields 10 slugs (was 0). | Gate 2 unlock — real Hagenauer/Annaberg/Lilienmatt content started flowing into vault. |
| #38 | CLAIM_LOOP_OPUS_FAILED_RECLAIM_1 | Secondary claim function for `opus_failed` rows in `kbl/pipeline_tick.py`. Self-heal via Step 5 R3 ladder within 3-reflip budget. | Retires recovery-#7 manual UPDATE class. First `awaiting_opus` row seen in prod — secondary claim firing. |

### 3 Tier B recoveries this session (all logged in `memory/actions_log.md`)

- #5 (05:15 UTC): 52 rows `completed/skip_inbox` → `awaiting_classify` — WRONG STATUS per B1's ship report SQL; caught by Director's "pls check" 2.5 min later
- #6 (05:20 UTC): 52 rows `awaiting_classify` → `pending` — corrective; fixed the claim-loop gap for that recovery
- #7 (05:35 UTC): 16 rows `opus_failed` → `pending` — last manual opus_failed recovery before PR #38 shipped. Self-heal in place now.

### Gate 2 closed MECHANICALLY (Director can celebrate — partial)

At handover, queue state: **43+ completed rows** with `step_5_decision='full_synthesis'` committed to vault with `target_vault_path` + `commit_sha` populated. That's the Gate 2 criterion from the prior handover.

**Caveat — matter-routing quality:** some `hagenauer-rg7` labels sit on clearly non-Hagenauer content (UBS systemic banking, Barclays UK valuation, Claude Opus 4.7 rollout, Bloomberg subscription). Step 1 LLM triage is over-routing to hagenauer-rg7 because it's the highest-frequency matter in the corpus. **Not a code fix** — this is Cortex Design §4 territory (#1 reasoning loop, #2 matter scope, #11 prompt tuning). Flagged for next Director session. Do NOT dispatch a fix without Director input.

### Pipeline watchdog LIVE

Scheduled task `baker-pipeline-watchdog` running every 20 min (`7,27,47 * * * *`). Checks signal_queue for strandings, orphan states, opus_failed over-budget, ingestion stalls, circuit breakers. Silent when healthy. Output: notifies this session (not the new AI Head session). **Next AI Head: if you need watchdog notifications, call `mcp__scheduled-tasks__list_scheduled_tasks` and optionally re-create the task in your session with `notifyOnCompletion=true`.**

Task file: `/Users/dimitry/.claude/scheduled-tasks/baker-pipeline-watchdog/SKILL.md`.

### New rules this session

- `memory/feedback_technical_execution_no_ask.md` — SUPERSEDED IN PLACE by charter (kept as historical anchor).
- `memory/feedback_ai_head_autonomy_charter.md` + `_ops/processes/ai-head-autonomy-charter.md` — the charter. RATIFIED.

---

## 🔥 Current pipeline state (at handover ~07:50 UTC)

### Infra: ALL HEALTHY ✅

- Cloudflare tunnel + BIC exempt (no session changes)
- Ollama reachable via tunnel
- Baker live at `baker-master.onrender.com`, commit `f96d8d1` (PR #38 merge)
- Render: 46 scheduled jobs, healthy
- Watchdog: `baker-pipeline-watchdog` active

### Pipeline: FUNCTIONAL END-TO-END ✅ / self-heal active ✅

- PR #38's secondary claim is firing in prod (observed `awaiting_opus` rows > 0 for first time)
- Drift-bug class (PR #36) + parser fix (PR #37) + opus_failed reclaim (PR #38) all active

### Queue snapshot (last read)

- **completed: 43+** (31+ full_synthesis real content, ~3 legit skip_inbox out-of-scope)
- **opus_failed: 16** — will self-heal as primary drains (primary has priority per PR #38 dispatch order)
- **awaiting_finalize: 6** — mid-flight OR orphan candidates
- **processing: 2** — active
- **pending: 0** — drained

### Gate 3 (not yet defined)

Gate 2 was "real content in vault, not stubs" — done.
**Gate 3 should be Director-defined** — candidates: matter-routing quality ≥ 95%, or full pipeline backlog processed to terminal, or first cross-link successfully written, or first real Director-useful downstream artifact generated. Do NOT close Gate 3 without Director's criteria.

---

## 🎯 Critical path (what you do first 10 min)

1. Read the charter (`_ops/processes/ai-head-autonomy-charter.md`). This is not optional — it's the single biggest rule change of the session.
2. Read this handover end to end.
3. `cd /tmp && rm -rf /tmp/bm-draft && git clone https://github.com/vallen300-bit/baker-master.git /tmp/bm-draft && cd /tmp/bm-draft`
4. `git log --oneline -20` — confirm commits around `f96d8d1` (PR #38 merge), `02f8940` (B3 dispatch), and latest handover present.
5. `gh pr list --repo vallen300-bit/baker-master --state open` — is there a PR from B1 on `claim-loop-orphan-states-2`?
6. Read `memory/MEMORY.md` + `memory/actions_log.md` (new entries #5, #6, #7 this session).
7. `mcp__baker__baker_raw_query {"sql": "SELECT status, COUNT(*) FROM signal_queue GROUP BY status"}` — current queue state.
8. Check watchdog: `mcp__scheduled-tasks__list_scheduled_tasks` → see `baker-pipeline-watchdog`. If you want notifications in YOUR session, re-create with `notifyOnCompletion=true`.
9. Check Render: `op item get "API Render"` → curl `/v1/services/srv-d6dgsbctgctc73f55730/deploys?limit=3` — confirm `f96d8d1` still live.
10. If B1's PR is open → dispatch B3 for review (charter §3 autonomous). If still writing → wait. If merged → watch self-heal and queue drain.

---

## 🧨 Pending at handover (in priority order)

1. **[QUEUED, MAILBOX]** B1 dispatch on `CLAIM_LOOP_ORPHAN_STATES_2` at `briefs/_tasks/CODE_1_PENDING.md` (commit: see last git log). Three more orphan states (awaiting_classify, awaiting_opus pure, awaiting_finalize) to reclaim via the PR #38 pattern. Timebox 3h, effort M. When PR opens → route to B3. On APPROVE → Tier A auto-merge.
2. **[AUTONOMOUS-WATCH]** Pipeline drain. opus_failed → awaiting_opus → completed via self-heal. Primary-priority design means self-heal runs only when pending is empty (it is). Watchdog fires every 20 min.
3. **[POST-ORPHAN-STATES-2]** Queued architectural briefs (per last handover + this session):
   - **`STEP1_TRIAGE_MATTER_QUALITY_1`** — diagnose + fix the over-routing to hagenauer-rg7. **BLOCKED** on Director direction (Cortex Design §4). Do NOT dispatch without his input.
   - **`STEP6_VALIDATION_FAILURE_AUDIT_1`** — ~29% Step 6 Pydantic validation failure rate observed. Which field(s) fail? Worth a diagnostic brief (not remedial — if Step 5 prompt can be tightened, fewer reflips needed, lower cost). **Autonomous — AI Head can dispatch when ready.**
   - **`CLAIM_LOOP_ORPHAN_STATES_MAC_MINI_3`** — `awaiting_commit` reclaim on Mac Mini side (via `kbl/poller.py`). Different code path from Render. Lower priority.

## 🗂 Side threads this session (parked)

- **Obsidian canonical location** — Director flagged that rules must live in `_ops/processes/` not just `.claude/...`. Charter now canonical in Obsidian. Bank-model has supersession banner.
- **No "by inspection" ship reports** — rule held this session (B1 shipped full pytest logs on both PRs).
- **Matter-routing quality issue** — flagged, not actioned. Director to give direction.

---

## 📁 Key files to read

| Path | Purpose |
|------|---------|
| `_ops/processes/ai-head-autonomy-charter.md` | **READ FIRST.** The charter ratified this session. |
| `_ops/processes/write-brief.md` | Brief-drafting skill — charter §6A mandates this for future briefs. |
| `memory/actions_log.md` | 16 total entries; 3 added this session (#5, #6, #7). Full Tier B paper trail. |
| `memory/MEMORY.md` | Updated index with charter line. |
| `briefs/_tasks/CODE_1_PENDING.md` | B1's queued task: CLAIM_LOOP_ORPHAN_STATES_2. |
| `briefs/_tasks/CODE_3_PENDING.md` | B3's closed PR #38 review. |
| `.claude/scheduled-tasks/baker-pipeline-watchdog/SKILL.md` | Watchdog config. |

---

## ⚙️ Workflow (unchanged from evening handover except as noted)

- Dispatch: `briefs/_tasks/CODE_{1,2,3}_PENDING.md` — overwrite, commit, push.
- Trigger line: `cd ~/bm-b{N} && git checkout main && git pull -q && cat briefs/_tasks/CODE_{N}_PENDING.md`
- Working dirs: `~/bm-b{N}` (NOT `/tmp/`).
- Tier B via 1Password: `TOKEN=$(op item get "API Render" --vault "Baker API Keys" --fields credential --reveal 2>/dev/null)`
- Auto-merge: `gh pr merge N --repo vallen300-bit/baker-master --squash --subject "<title> (#N)"`
- **Charter §3 NEW:** AI Head no longer asks "shall I dispatch" / "authorize recovery" / "pending your approval" for technical matters. Report outcomes.

---

## 🎬 Status ping to Director after refresh

```
AI Head refreshed — late-session handover read. Charter noted + active.

Infra + pipeline healthy. Gate 2 closed mechanically — 43+ real vault files.
PR #38 secondary claim firing in prod (awaiting_opus observed).

B1 mailbox queued on CLAIM_LOOP_ORPHAN_STATES_2 — waiting for B1 to pick up.
Watchdog every 20 min; silent-by-default.

Open design-level flag (Director call required): Step 1 triage over-routes
to hagenauer-rg7 across non-Hagenauer content. Cortex Design §4, not a
code fix. Parked pending your input.

Standing by.
```

---

## ⚠️ Things NOT to do (unchanged)

- Do not ask Director to authorize technical actions (see charter §3).
- Do not ask Director to click UI, run CLI, edit ACLs. Execute via browser MCP / API / SSH / B-code dispatch.
- Do not touch `CHANDA.md` (§4 prerogative #7).
- Do not refresh `hot.md` (§4 prerogative #8).
- Do not dispatch a matter-routing quality fix without Director input (§4 prerogatives #1, #2, #11).
- Do not commit credentials.
- Do not ship "by inspection" — full pytest log mandatory.
- Do not re-explain ratified rules back to Director in chat (charter §6).

---

*Prepared 2026-04-22 LATE. 2 PRs merged (37, 38), 3 Tier B recoveries (5, 6, 7), charter ratified, Gate 2 closed mechanically, pipeline self-healing, watchdog live, B1 queued on CLAIM_LOOP_ORPHAN_STATES_2. Matter-routing quality flagged for Director-level input.*
