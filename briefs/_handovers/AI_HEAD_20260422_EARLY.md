# Handover — AI Head — 2026-04-22 EARLY (Gate 1 mechanical CLOSED; Gate 2 one parser-fix away)

**Date:** 2026-04-22 ~02:30 UTC (end of long session spanning evening 2026-04-21 → early 2026-04-22)
**From:** AI Head (outgoing — heavy context after 7 merged PRs, 4 Tier B recoveries, full pipeline diagnosis)
**To:** Fresh AI Head instance
**Director:** Dimitry Vallen
**Supersedes:** `briefs/_handovers/AI_HEAD_20260421_EVENING.md`
**Your immediate job:** watch B1 land `STEP4_HOT_MD_PARSER_FIX_1` (in flight), route to B3, merge, run post-merge recovery on in-scope rows only.

---

## 🚨 READ BEFORE ANYTHING ELSE

**Durable rules (all at `memory/`):**

1. **Bank model — Tier A/B/C.** `feedback_ai_head_communication.md`.
2. **Plain English only to Director.** `feedback_ai_head_plain_english_only.md`.
3. **Chat format: bottom-line / recommendation / judgment / fences for paste-to-agent ONLY.** `feedback_ai_head_chat_format.md`.
4. **Always include recommendation.** `feedback_always_recommend.md`.
5. **Standing Tier A: signal_queue recovery UPDATE** (only the `status='processing', stage='triage', triage_score IS NULL` shape). `feedback_tier_a_recovery_update.md`. Any other shape = Tier B.
6. **Director is CEO not engineer.** `feedback_director_is_ceo_not_engineer.md`.
7. **Research Agent 7-field handoff.** `feedback_research_agent_handoff_protocol.md`.
8. **Migration-vs-bootstrap DDL drift.** `feedback_migration_bootstrap_drift.md`.
9. **NEW (ratified this session): No ship without full green test run.** `feedback_no_ship_by_inspection.md` — B-codes must ship with literal pytest output, never "by inspection". AI Head REQUEST_CHANGES any ship report using "by inspection". Anchor incident: PR #35.

---

## Who you are

AI Head — orchestration + architecture-decision agent. Team: B1 (primary coder, `~/bm-b1`), B2 (coder + diagnostic, `~/bm-b2`), B3 (reviewer only, `~/bm-b3`). Research Agent = separate Claude session. AI Dennis = IT shadow in Cowork (not in scope).

Dispatch pattern: write fenced pointers to `briefs/_tasks/CODE_{1,2,3}_PENDING.md`, commit + push. Director pastes one-line shell to the named B-code's terminal. B-code pulls, reads, acts, reports back via `briefs/_reports/B{N}_<topic>_<YYYYMMDD>.md`.

**You do NOT write production code.** B-codes do. You DO execute Tier B ops (DB UPDATEs, Render API, Cloudflare dashboard via Chrome MCP, SSH to Mac Mini, 1Password fetches) after Director authorizes per bank model.

---

## 🎯 What landed this session (high-signal)

### 7 PRs merged

| # | PR | What |
|---|----|------|
| #30 | raw_content phantom column | step consumers read `COALESCE(payload->>'alert_body', summary, '')` — column existence drift |
| #31 | related_matters JSONB cast | `::jsonb` + `json.dumps` on write — JSONB shape drift |
| #32 | finalize_retry_count | inline `ADD COLUMN IF NOT EXISTS` self-heal — column existence drift |
| #33 | hot_md_match BOOLEAN → TEXT | migration + bootstrap sync + reconcile helper — type drift |
| #34 | yaml.safe_dump for stub writer | encoding drift |
| #35 | source_id cast to str + Step 6 override | producer-vs-schema type drift |
| #36 | Step 5 stub schema conformance audit | structural fix — kills entire drift-bug class |

### New memory rule this session

- `feedback_no_ship_by_inspection.md` — added after B2's PR #35 ship report claimed "pass by inspection" and B3 caught a real blocker on `tests/test_step5_opus.py:273`. AI Head REQUEST_CHANGES trigger phrase.

### 4 Tier B recovery UPDATEs this session (all logged in `memory/actions_log.md`)

- #1 (2026-04-21 13:09): 24 rows opus_failed → awaiting_opus (B2's SQL, turned out WRONG target status)
- #2 (2026-04-21 13:28): same 24 rows awaiting_opus → pending (corrected target)
- #3 (2026-04-21 17:12): 41 rows awaiting_finalize → pending, post PR #35
- #4 (2026-04-22 02:00): 55 rows awaiting_finalize → pending, post PR #36

All four point at the same underlying architectural bug (claim-transactionality / intermediate-state stranding). Permanent fix queued as post-Gate-1 brief.

---

## 🔥 Current pipeline state (at handover)

### Infra: ALL HEALTHY ✅

- Cloudflare tunnel + BIC exempt (no session changes)
- Ollama reachable via tunnel
- Baker live at `baker-master.onrender.com` (46 scheduled jobs, healthy)
- Render: latest deploy live (commit `be4f209`, PR #36 merge)

### Pipeline: FUNCTIONAL END-TO-END ✅

- 7 production bugs fixed, drift-bug class structurally killed by PR #36
- Pipeline runs Steps 1→7 cleanly
- Mac Mini Step 7 commits to vault working (commits visible, vault paths populated)

### Signals: Gate 1 MECHANICAL CLOSED ✅ / Gate 2 BLOCKED ⚠️

- **10 rows at `status='completed'`** with `target_vault_path` + `commit_sha` populated — Gate 1 mechanical criterion met
- BUT: **all 10 are `step_5_decision='skip_inbox'`** — out-of-scope stubs, placeholder files in vault, not real content
- 45+ more rows still pending (processing at ~1/tick)
- Vault files all look like `wiki/<matter>/2026-04-22_layer-2-gate-matter-not-in-current-scope.md` — noise, not signal

### The Gate 2 blocker (B1 diagnosed, fix in flight)

**Root cause:** `kbl/steps/step4_classify.py:66-69` regex `^##\s+Actively\s+pressing\s*$` refuses to match the live hot.md header `## Actively pressing (elevate — deadline/decision this week)`. Parser returns `frozenset()`, so `allowed_scope` is empty, so Rule 1 (Layer 2 gate) rejects every signal regardless of primary_matter.

**Secondary:** slug-line regex can't parse multi-slug bullets like `**lilienmatt + annaberg + aukera**:` (which hot.md line 13 documents as intentional format).

**Not Opus.** Step 5 deterministic stub path fires BEFORE Opus when `step_5_decision='skip_inbox'`. Zero Opus calls have happened on any completed row.

**Fix in flight:** B1 assigned `STEP4_HOT_MD_PARSER_FIX_1`. Dispatch at commit `29ff135`. Fix size: XS (one-line regex loosen) + S (multi-slug parser) + 5 regression tests = ~60-90 min. Director authorized "go" 2026-04-22 early.

**Post-merge recovery:** 56 skip_inbox rows are stranded with useless stub vault files. **Director's call: in-scope matters ONLY (Hagenauer, Lilienmatt, Annaberg)** — option (b) from the recovery-scope choice. Not (a) all 56, not (c) leave-and-wait. Tier B auth required before running the recovery.

---

## 🎯 Critical path (what you do first 10 min)

1. Read this handover end to end.
2. `cd /tmp && rm -rf /tmp/bm-draft && git clone https://github.com/vallen300-bit/baker-master.git /tmp/bm-draft && cd /tmp/bm-draft`
3. `git log --oneline -20` — confirm commits `29ff135` (B1 dispatch), `7f4664c` (B1 diagnostic report), `be4f209` (PR #36 merge) present.
4. `gh pr list --repo vallen300-bit/baker-master --state open` — may have PR from B1 if they already shipped the fix.
5. Read `briefs/_reports/B1_step5_opus_scope_gate_diagnostic_20260422.md` — the diagnostic you'll reference when routing to B3.
6. Read `memory/MEMORY.md` index.
7. `mcp__baker__baker_raw_query {"sql": "SELECT status, COUNT(*) FROM signal_queue GROUP BY status"}` — know the current state.
8. Check Render: use `op item get "API Render" --vault "Baker API Keys" --fields credential --reveal` then `curl -H "Authorization: Bearer $TOKEN" ...` to list deploys.
9. Decide: is B1's fix PR open? → route to B3. Still writing? → wait. Already merged? → run post-merge recovery.

---

## 🧨 Pending at handover (in priority order)

1. **[IN FLIGHT]** B1 on `STEP4_HOT_MD_PARSER_FIX_1`. When PR opens → dispatch B3 for review. On B3 APPROVE → Tier A auto-merge.
2. **[POST-MERGE, TIER B]** Recovery UPDATE on the 56 skip_inbox rows. **Director authorized option (b): in-scope matters only.** SQL surfaces in B1's fix ship report under §recovery. Ask Director to explicit-yes before running (shape deviates from standing Tier A).
3. **[POST-RECOVERY, WATCH]** After recovery, watch for in-scope signals reaching FULL_SYNTHESIS + real content commits. Gate 2 closes when the vault has real Hagenauer/Lilienmatt/Annaberg content, not stubs.
4. **[POST-GATE-2]** Queued architectural briefs (don't start before Gate 2 closes):
   - Claim-transactionality fix (kills the recurring stranding bug that needed 4 Tier B recoveries today)
   - `STEP_SCHEMA_CONFORMANCE_AUDIT_1` (combines JSONB shape + column existence + column type + encoding + producer-vs-schema-type + error-handler cascade into one audit — PR #36 partially delivered this; the "formal CI lint" version is the post-Gate-1 brief)

---

## 🗂 Side threads this session (parked)

- **AO PM extension brief** — Director asked: can we add Obsidian vault read + lessons-learned loop to the existing AO PM Baker-native capability? Recommended "extend, don't rebuild." Not yet dispatched. Capability row exists at `capability_sets.slug='ao_pm'` with 22 tools + rich system prompt; gap is (a) Obsidian filesystem read, (b) explicit learning loop. Parked for after Gate 2.
- **AO PM Cowork-shadow pattern (AI Dennis style)** — Director asked if we can also expose AO PM as a Cowork skill with 3-file memory, usable from Cowork + Code CLI + Code App. Answer: yes, ~30 min setup. Parked pending Gate 2.
- **Opening prompts for B1/B2/B3 refresh** — Director has these in chat (not committed to repo); Director may ask for them again as he refreshes the B-codes.

---

## 📁 Key files to read

| Path | Purpose |
|------|---------|
| `memory/actions_log.md` | Append-only Tier B paper trail — 13 entries total, 4 added this session |
| `memory/feedback_no_ship_by_inspection.md` | New rule added this session — REQUEST_CHANGES on "by inspection" |
| `memory/MEMORY.md` | Index, read top-to-bottom |
| `briefs/_reports/B1_step5_opus_scope_gate_diagnostic_20260422.md` | The diagnostic that unblocks Gate 2 |
| `briefs/_tasks/CODE_1_PENDING.md` | Current B1 task — `STEP4_HOT_MD_PARSER_FIX_1` |

---

## ⚙️ Workflow (unchanged from evening handover)

- Dispatch: `briefs/_tasks/CODE_{1,2,3}_PENDING.md` — overwrite, commit, push.
- Trigger line to Director to paste to B-code tab: `cd ~/bm-b{N} && git checkout main && git pull -q && cat briefs/_tasks/CODE_{N}_PENDING.md`
- Working dirs: `~/bm-b{N}` (NOT `/tmp/`).
- Tier B via 1Password: `TOKEN=$(op item get "API Render" --vault "Baker API Keys" --fields credential --reveal 2>/dev/null)`
- Auto-merge: `gh pr merge N --repo vallen300-bit/baker-master --squash --subject "<title> (#N)"`. Gate: B3 APPROVE + CLEAN mergeable + no Director blockers.

---

## 🎬 Status ping to Director after refresh

```
AI Head refreshed — early-morning handover read.

Infra + pipeline all healthy. PR #36 killed the Step 5 drift-bug class structurally.
Gate 1: mechanical criterion CLOSED (10 rows committed to vault with target_vault_path + commit_sha).
Nuance: all 10 are skip_inbox stubs, not real content — vault files are placeholders.

Gate 2 blocker: Step 4 hot.md parser regex can't match the live section header. B1 in flight on the fix (STEP4_HOT_MD_PARSER_FIX_1, dispatch live at 29ff135). Expected XS+S effort, ~60-90 min. B3 will review on ship; Tier A auto-merge on APPROVE.

Post-merge: Tier B recovery on 56 skip_inbox rows, in-scope matters only (your earlier pick).

Standing by to route B1's PR to B3 when it opens.
```

---

## ⚠️ Things NOT to do (unchanged)

- Do not ask Director web-UI or CLI tasks.
- Do not run recovery UPDATE on `awaiting_finalize` or `opus_failed` without Tier B auth (shape deviates from standing Tier A).
- Do not touch `CHANDA.md` (Tier B explicit yes).
- Do not refresh `hot.md` (Director-curated).
- Do not commit credentials.
- Do not write SHAs / line numbers / SQL / env var names in chat.
- Do not proactively dispatch post-Gate-2 briefs.

---

*Prepared 2026-04-22 early. 7 PRs merged in 24h, 4 Tier B recoveries, drift-bug class structurally closed, Gate 2 diagnostic complete. One parser-regex fix stands between skip_inbox stubs and real in-scope content flowing into the vault.*
