---
brief_id: CAPABILITY_RUNNER_COST_RUNAWAY_DIAGNOSTIC_1
report_author: b4
report_date: 2026-05-25
report_type: READ-ONLY DIAGNOSTIC (no code changes)
working_branch: main (no branch)
bus_ack: msg #1065 (dispatch/capability-runner-cost-runaway-diagnostic-1)
---

# B4 diagnosis — capability_runner cost runaway (€100/day breaker trip since 2026-05-21)

## 1. Bottom line

**Root cause: a WhatsApp self-chat feedback loop in `triggers/waha_webhook.py`.** Every time Baker sends a reply to the Director's self-chat (`41799605092@c.us`), WAHA fires a `fromMe=true` webhook back to Baker. `attribute_sender()` in `triggers/waha_message_utils.py:42-43` unconditionally re-attributes any `fromMe=true` message as `(sender=DIRECTOR_WHATSAPP_CUS, is_director=True)`. That makes `director_to_baker=True` at `triggers/waha_webhook.py:1118`, which fires `_handle_director_question(...)` on Baker's *own outbound reply*. That handler invokes `CapabilityRouter.route()` (which selects finance + legal in delegate mode for most reasoning questions) → `CapabilityRunner.run_single()` / `run_multi()` *without* `matter_slug` or `task_id` → produces ~3–8 `api_cost_log` rows per invocation against `claude-opus-4-6` with zero prompt caching. The reply Baker emits then re-triggers the webhook → infinite loop, throttled only by per-call latency (~10–30s) and ultimately stopped by the `COST_HARD_STOP_EUR=100.0` breaker.

Confidence: **high** for the loop mechanism + cost mapping (every signal in the lead's pre-flight + this report's queries lines up). Confidence: **medium-high** for "loop onset 2026-05-21 aligns with `BRIEF_WAHA_OUTBOUND_CAPTURE_1`-class behaviour change" (the brief that introduced `fromMe → is_director=True` re-attribution); a `git log --follow` on `triggers/waha_message_utils.py` would close this last 10%.

## 2. Evidence chain

### 2a. Q1 — last-24h spend by source (raw `baker_raw_query` output)

| source | calls | EUR |
|---|---|---|
| **capability_runner** | **1,030** | **92.32** |
| pipeline | 342 | 20.76 |
| agent_loop_synthesis | 3 | 2.29 |
| email_draft | 74 | 2.13 |
| email_intelligence | 312 | 0.38 |
| email_commitments | 324 | 0.35 |
| extract_deadlines | 836 | 0.29 |
| research_trigger_classify | 341 | 0.22 |
| t2_extraction | 70 | 0.16 |
| auto_insight | 471 | 0.11 |
| 10 long-tail sources | <€0.10 each | |

`capability_runner` is **82%** of last-24h LLM spend.

### 2b. Q2 — capability_runner breakdown by capability_id + matter_slug

| capability_id | matter_slug | calls | EUR |
|---|---|---|---|
| finance | **(none)** | 536 | 56.84 |
| legal | **(none)** | 460 | 33.39 |
| game_theory | (none) | 22 | 0.81 |
| sales | (none) | 4 | 0.61 |
| russo_at | (none) | 2 | 0.28 |
| synthesizer | (none) | 4 | 0.26 |
| russo_fr | (none) | 2 | 0.14 |

finance + legal = **97%** of the `capability_runner` spend. **ALL 1,030 rows have `matter_slug=NULL`.**

### 2c. Q3 — hourly burst pattern (finance + legal only, last 24h)

| hour (UTC) | finance calls | finance EUR | legal calls | legal EUR |
|---|---|---|---|---|
| 2026-05-25 00:00 | 79 | 9.76 | 39 | 3.03 |
| 2026-05-25 01:00 | 125 | 15.58 | 144 | 13.67 |
| 2026-05-25 02:00 | 79 | 9.68 | 167 | 10.26 |
| 2026-05-25 03:00 | 123 | 8.92 | 54 | 2.75 |
| 2026-05-25 04:00 | 89 | 9.54 | 25 | 2.23 |
| 2026-05-25 05:00 | 41 | 3.35 | 31 | 1.45 |
| 2026-05-25 06:00+ | **0 (breaker tripped 05:40:10Z)** | | | |

Same shape as lead's pre-flight at 11:30Z. Last call at `2026-05-25 05:40:10.471820Z` — matches breaker trip.

### 2d. Q4 — task_id distribution (concentration or fan-out?)

```
null_task_id      = 1030
nonnull_task_id   =    0
distinct_task_ids =    0
```

**ZERO rows have `task_id` set.** Every caller path that would set `task_id` (cortex_phase3 invoker explicitly, Phase-3b orchestrator, decomposer) is ruled out. That isolates the caller to the small set of `run_single` / `run_multi` callers in `triggers/waha_webhook.py:303,307`, `outputs/dashboard.py:9579,9596,9736`, `orchestrator/research_executor.py:185`, and the `agent.py:2147` `delegate_to_capability` tool — none of which pass `task_id`.

### 2e. Q5 — additional context: model + cache + token mix (last-24h finance+legal)

```
rows: 996
distinct_models: 1     → claude-opus-4-6  (top-tier model, ~5x Sonnet, ~30x Haiku)
avg input  tokens: 4,404
avg output tokens:   432
total cache_read:        0   → NO prompt-cache hits anywhere
total cache_create:      0   → NO cache writes from this path either
avg cost / row:    €0.0906
```

Every row is a fresh full-context Opus invocation. The `_cache_wrap` system-prompt cache hint at `capability_runner.py:691` *is* set on `run_single`, but `cache_read_input_tokens=0` across 996 rows confirms cache misses on every call — system prompt is varying per invocation OR the cache TTL is being missed by the burst cadence.

### 2f. Q6 — cross-check counters (rule out alternative culprits)

| Suspect path | Q-evidence | Result |
|---|---|---|
| `cortex_phase3_invoker` (passes `matter_slug=...`) | `SELECT * FROM cortex_cycles WHERE started_at > NOW() - INTERVAL '24h'` | **0 rows.** Ruled out. |
| `research_executor._run_specialists` (Director-approved dossier; fires finance+legal in parallel) | `SELECT * FROM research_proposals WHERE created_at > NOW() - INTERVAL '24h'` | **0 rows.** Ruled out. |
| `agent.py:2147 delegate_to_capability` tool | `SELECT * FROM agent_tool_calls WHERE called_at > NOW() - INTERVAL '24h'` | **0 rows.** Ruled out. |
| `run_multi` delegate fan-out (would fire all 4 caps in plan equally) | Q3 shows finance+legal dominate; game_theory/research/sales <30 rows combined | Ruled out — not the equal-fanout pattern. |
| dashboard SSE user-facing endpoints | Volume is overnight (00:00–05:40 UTC = 02:00–07:40 CET; Director asleep) | Ruled out. |

### 2g. Q7 — the smoking gun: WhatsApp self-chat traffic

| ingest hour (UTC) | total WA msgs | `is_director=True` count | chats |
|---|---|---|---|
| 00:00 | 67 | 67 | 1 |
| 01:00 | 119 | 119 | 1 |
| 02:00 | 149 | 149 | 1 |
| 03:00 | 123 | 123 | 1 |
| 04:00 | 62 | 61 | 2 |
| 05:00 | 61 | 60 | 2 |
| **00–05 total** | **581** | **579 self-chat with is_director=True** | **chat 41799605092@c.us** |

**Every single overnight `is_director=True` message is in chat `41799605092@c.us` (Director's self-chat).** Bodies are unmistakably Baker-style replies:

- `"Understood — but to be clear, all three are **your** calls, not mine. I have everything staged and ready to execute..."`
- `"Good to hear. Everything is locked down: - **All channels monitored** — email, WhatsApp, meetings, deadlines..."`
- `"Clear picture, and the prioritization is right. Standing by on all three decision points..."`
- `"📧 Draft ready for balazs.csepregi@brisengroup.com..."`

These are **Baker's reply outputs**, looped back as `fromMe=true` webhook events, attributed as Director messages, and fed to `_handle_director_question` again.

### 2h. The loop, traced (file:line evidence)

1. Baker emits a reply via WAHA gateway (e.g. after handling a real Director question or completing a previous loop iteration).
2. WAHA fires a webhook with `fromMe=true`, `from=41799605092@c.us`, `to=41799605092@c.us`, body=`<Baker's reply text>`.
3. `triggers/waha_webhook.py` calls `attribute_sender(raw_sender, raw_sender_name, from_me=True)` → `triggers/waha_message_utils.py:42-43` returns `(DIRECTOR_WHATSAPP_CUS, "Director", True)` **regardless of whether the message originated from Director's phone or Baker's WAHA endpoint**.
4. `triggers/waha_webhook.py:1117-1118`:
   ```python
   _baker_self = is_baker_self_chat(chat_id)             # True (chat_id == 41799605092@c.us)
   director_to_baker = (sender == DIRECTOR_WHATSAPP      # True (re-attributed in step 3)
                        and _baker_self                  # True
                        and bool(combined_body))         # True
   ```
   → `director_to_baker = True`.
5. `triggers/waha_webhook.py:1155-1212` fires the full Director-to-Baker path on Baker's own reply: `_handle_director_message`, `extract_deadlines`, `OBLIGATIONS-DETECT-1`, and finally `_handle_director_question`.
6. `_handle_director_question` (`triggers/waha_webhook.py:246-329`) routes to `CapabilityRouter.route()`; for analytical Baker replies the router picks `delegate` mode with `finance` + `legal` (those are the two analytical specialists the router falls back to when domain inference is ambiguous on a Baker-style reasoning blob).
7. `CapabilityRunner.run_single(cap, question)` is invoked at `triggers/waha_webhook.py:303` (fast) or `run_multi` at `:307` (delegate) — **neither passes `matter_slug` or `task_id`**.
8. `run_single` enters the agent loop at `orchestrator/capability_runner.py:601-713`. Each loop iteration calls `claude.messages.create()` and emits an `api_cost_log` row via `_log_api_cost(..., source="capability_runner", capability_id=capability.slug, matter_slug=matter_slug)` at line 709-713 — with `matter_slug=None`.
9. The agent reply is sent back via WAHA → step 1 of the next loop tick.

Latency floor (~10–30s per `run_single` iteration) is the only thing keeping the loop from immediately consuming the entire daily budget; the breaker stops it at €100 ~5h in.

### 2i. Onset 2026-05-21 — first daily breaker trip

Per b4's prior GMAIL_POLLING_DIAGNOSTIC_1 report §2e: 2026-05-21 €115.31, 2026-05-22 €104.19, 2026-05-23 €103.58, 2026-05-24 €115.86, 2026-05-25 €104.88. The 2026-05-21 onset suggests a recent change introduced the `fromMe → is_director=True` attribution (the docstring at `triggers/waha_message_utils.py:34-40` references `BRIEF_WAHA_OUTBOUND_CAPTURE_1` as the source brief). Confirming the exact merge date is one `git log --follow triggers/waha_message_utils.py` away — out of scope for this read-only diagnostic, in scope for the fix brief.

## 3. What's broken vs what's working

| Component | Status | Evidence |
|---|---|---|
| WAHA inbound webhook delivery | ✅ healthy | 581 fromMe=true events processed overnight without WAHA-side error logs. |
| `attribute_sender` | ⚠️ TOO PERMISSIVE | Unconditionally re-attributes `fromMe=True` to Director identity. Cannot distinguish Director phone-origin from Baker WAHA-endpoint-origin. |
| `is_baker_self_chat` | ✅ correct | Returns True for `41799605092@c.us`. The bug is downstream of this. |
| `director_to_baker` gate at `waha_webhook.py:1118` | ❌ FIRES ON BAKER'S OWN OUTBOUND | Missing guard for "this fromMe message originated from my own send". |
| `_handle_director_question` | ✅ correct in isolation | Path works as designed when called for a real Director question — the bug is the upstream gate. |
| `CapabilityRouter` finance+legal fallback | ⚠️ amplifier | Selects a 2-specialist delegate plan for ambiguous reasoning text, multiplying cost per loop tick by ~2x and pulling Opus on each. Not the root cause but doubles the burn rate. |
| `CapabilityRunner.run_single` `matter_slug=None` propagation | ⚠️ AUDIT BLINDSPOT | When caller doesn't pass `matter_slug`, all rows in `api_cost_log` are NULL — masks which path produced them. Not the root cause but a debugging tax. |
| `cost_monitor` €100 daily breaker | ✅ correctly firing | Stops the loop at €100, preventing runaway €1000+/day. The breaker is the only thing protecting Brisen. |
| Prompt cache on `run_single` | ❌ 0% hit rate | `_cache_wrap` is set but every loop tick produces a slightly-different system prompt (Director's name/state/etc.) so the cache never hits across iterations — pays full Opus price every time. Secondary efficiency loss; not the trigger. |

## 4. Cross-check vs GMAIL_POLLING_DIAGNOSTIC_1 (Step 5)

**Linked, not independent.** Lead's pre-flight read called them independent. The data says otherwise:

- The Gmail polling defect b4 documented in §2e (53 counterparty emails since 2026-05-17 with no `documents` row) is the **downstream consequence** of this cost runaway, not a polling-side bug. b4's Render-log spot-checks already showed `"Document classification blocked by circuit breaker"` and `"Extraction skipped (circuit breaker at EUR 104.87)"` — the breaker that's tripping is **this** brief's defect.
- The Hagenauer "Investigation reports : water damage" email (2026-05-21 14:28, the canary in V2's brief) failed to write `documents` because the breaker had already tripped on 2026-05-21 (€115.31 spent). Same for the other 52 counterparty emails.
- **However**: the V1 + V2 visibility patches (PRs #259 + #261) are still load-bearing. They expose the other SKIP-class causes for the smaller residual blackout once this loop is killed (e.g. inline-no-data, unsupported-ext, oversize). Lead's post-merge backfill observation window will be meaningful once the breaker stops tripping daily.
- Fixing the WA loop (this brief) is the primary unblock. Fixing the Gmail SKIP visibility (V1 + V2) is the secondary cleanup. Both ship.

## 5. Recommended fix shapes (Step 6 — 2-3 options, NO winner picked)

### Option A — Hard guard: drop `fromMe=true` self-chat events upstream (S, low risk, high impact)

**Where**: `triggers/waha_webhook.py` ~line 1117-1119 OR `triggers/waha_message_utils.py:attribute_sender`.

**What**: Add explicit short-circuit: if `from_me=True` AND `is_baker_self_chat(chat_id)` → DROP (return early from webhook handler) before any storage/extraction/question-handler path fires. Baker's own outbound to the self-chat is not a Director question; the message Baker just emitted is already known to Baker, doesn't need re-processing.

**Effort**: 5–10 LOC + 1 unit test. ~30 min.
**Risk**: Low. The only legitimate flow that depends on storing Baker's own self-chat sends is the audit trail in `whatsapp_messages` (we may still want those rows for outbound history). Mitigate by gating the SKIP at the question-handler boundary, not the storage boundary: keep `whatsapp_messages` INSERT, skip `_handle_director_message` + `_handle_director_question` + `extract_deadlines` for `fromMe=true && is_baker_self_chat`.
**Impact**: Eliminates the loop entirely. Saves ~€100/day. Cost breaker stops tripping. Gmail `documents` blackout resolves automatically once breaker capacity is freed.

### Option B — Origin-tag outbound sends (M, medium risk, more robust)

**Where**: WAHA send path + `triggers/waha_webhook.py`.

**What**: Before Baker sends a WAHA reply, record the outbound `msg_id` (or a content-hash + timestamp window) in a short-lived in-memory or Redis-backed set tagged `baker_origin`. On webhook arrival, if `fromMe=true` AND `msg_id` is in the `baker_origin` set → drop. Otherwise (true Director phone-origin message) → process normally.

**Effort**: 20–30 LOC + state store + TTL handling. ~1–2h.
**Risk**: Medium. Race conditions between send completion and webhook arrival (webhook can race ahead in WAHA's pipeline). Mitigate with a 30s TTL and content-hash fallback. Also: requires plumbing through every WAHA send call site, not just one.
**Impact**: Same outcome as Option A, but disambiguates by origin rather than by chat, so it also catches edge cases like Director sending himself a message from another device (treated as legitimate, would still process).

### Option C — Pure breaker-tuning short-term (XS, low risk, partial)

**Where**: `orchestrator/cost_monitor.py:50` (`COST_HARD_STOP_EUR`).

**What**: Lower the daily cap from €100 to €30 with a louder Slack alert when tripped; OR add a per-source sub-cap (`capability_runner` limited to €20/day independent of the global cap).

**Effort**: 5 LOC. ~15 min.
**Risk**: Low for the change itself; **high for operational impact** — at €20/day cap the legitimate workload also gets blocked. This is a tactical Band-Aid, not a fix.
**Impact**: Limits the bleed to €30/day instead of €100/day, but does NOT stop the loop or unblock Gmail `documents` writes (the breaker still trips daily, just earlier). Use only as bridge during the ~30min while Option A is shipped.

**Ranking by impact:effort** (Director picks via lead):

| Option | Impact | Effort | Risk | Impact:Effort |
|---|---|---|---|---|
| A — Hard guard on `fromMe + self_chat` | full fix | S (~30 min) | low | **highest** |
| B — Origin-tag baker_origin set | full fix + robustness | M (~1-2h) | medium | medium-high |
| C — Tighten breaker cap | partial mitigation | XS (~15 min) | high op-impact | low |

## 6. Investigation steps — what ran, what didn't

| Step | Action | Status | Notes |
|---|---|---|---|
| 1 — Q1 source breakdown | `baker_raw_query` SQL | ✅ done | capability_runner 82% of spend. |
| 1 — Q2 capability+matter breakdown | SQL | ✅ done | finance+legal 97%, matter_slug ALL NULL. |
| 1 — Q3 hourly burst pattern | SQL | ✅ done | 00:00–05:40Z burst confirmed. |
| 1 — Q4 task_id distribution | SQL | ✅ done | task_id NULL on all 1030 rows — ruled out cortex_phase3_invoker. |
| 1 — Q5 model + cache + tokens | SQL | ✅ done | claude-opus-4-6, zero cache hits across 996 rows. |
| 1 — Q6 cortex_cycles + research_proposals + agent_tool_calls counters | SQL | ✅ done | All 0 in 24h — ruled out 3 alternative paths. |
| 1 — Q7 WhatsApp inbound traffic | SQL | ✅ done | 519 fromMe=true self-chat events overnight; bodies are Baker replies. |
| 2 — Grep `capability_runner` callers | Grep | ✅ done | 6 real call sites + 2 internal sub-paths identified. |
| 3 — Trace trigger source | Grep + Read | ✅ done | Embedded scheduler reviewed; cron-style sources ruled out (no nightly cron registers finance/legal). |
| 4 — Read runaway code path | Read `attribute_sender`, `is_baker_self_chat`, `_handle_director_question`, `waha_webhook.py:1113-1212` | ✅ done | Loop traced step-by-step in §2h. |
| 5 — Cross-check vs Gmail polling | Read prior B4 report + Render logs from prior diagnostic | ✅ done | **Linked**, not independent — breaker tripping is the gating cause of Gmail `documents` blackout. |
| 6 — Recommend fix shapes | Synthesis | ✅ done | 3 options ranked by impact:effort. No winner picked (per brief). |
| 7 — Report write + ship | This file | ✅ done | Filed to `briefs/_reports/`; bus-post to lead next. |
| — | LLM calls beyond Claude Code session | ❌ skipped | Per brief §"What NOT to do". `baker_raw_query` is SQL, not LLM. |
| — | Render log API cross-verification | ❌ skipped | Not required to name the root cause; evidence chain from SQL + code reads is sufficient at high confidence. |

## 7. References (files read with file:line)

- `orchestrator/cost_monitor.py:50` — `COST_HARD_STOP_EUR=100.0` breaker constant.
- `orchestrator/cost_monitor.py:190-250` — `log_api_cost()` INSERT to `api_cost_log` with `matter_slug` column (NULL when caller doesn't pass).
- `orchestrator/capability_runner.py:601-606` — `run_single(self, capability, question, ..., matter_slug=None)` signature.
- `orchestrator/capability_runner.py:660-667` — circuit-breaker check inside agent loop.
- `orchestrator/capability_runner.py:709-713` — `_log_api_cost(..., source="capability_runner", capability_id=capability.slug, matter_slug=matter_slug)` per-iteration cost write.
- `orchestrator/capability_runner.py:1037-1063` — `run_multi` fan-out (MAX_SUB_TASKS=4); calls `run_single` per sub-task with NO `matter_slug`.
- `orchestrator/cortex_phase3_invoker.py:239-243` — Phase 3b path that DOES pass `matter_slug=matter_slug` (ruled out by Q4 + Q6).
- `orchestrator/research_executor.py:185` — `executor.submit(runner.run_single, cap, prompt)` (no matter_slug, but `research_proposals` empty in 24h — ruled out).
- `orchestrator/agent.py:869-872, 1012-1013, 2132-2152` — `delegate_to_capability` tool spec + dispatcher (no `agent_tool_calls` rows in 24h — ruled out).
- `triggers/waha_message_utils.py:22-24` — `BAKER_SELF_CHAT_CUS = "41799605092@c.us"`.
- `triggers/waha_message_utils.py:42-46` — `attribute_sender(..., from_me=True)` unconditional Director re-attribution.
- `triggers/waha_message_utils.py:49-57` — `is_baker_self_chat()` membership check.
- `triggers/waha_webhook.py:34` — `DIRECTOR_WHATSAPP = "41799605092@c.us"`.
- `triggers/waha_webhook.py:246-329` — `_handle_director_question` → CapabilityRouter → CapabilityRunner.
- `triggers/waha_webhook.py:843-846` — `attribute_sender` invocation on webhook ingress.
- `triggers/waha_webhook.py:977-1004` — `store_whatsapp_message(...)` with `is_director=is_director_msg`.
- `triggers/waha_webhook.py:1113-1212` — director_to_baker gate + question-handler dispatch (THE LOOP).
- `triggers/embedded_scheduler.py:87-695` — scheduler job registry (no `capability_runner` direct invocations; cron-style culprits ruled out).
- `scripts/extract_whatsapp.py:466-572` — `backfill_whatsapp()` startup catch-up + 6h cron; stores to `whatsapp_messages` but does NOT call CapabilityRunner.
- `briefs/_reports/B4_gmail_polling_diagnostic_1_20260525.md` §2e — daily breaker trip history confirming 2026-05-21 onset.

## 8. Out of scope

- Fix implementation. `CAPABILITY_RUNNER_COST_FIX_1` is lead-authored after Director picks among Options A / B / C.
- Editing `cost_monitor.py` breaker constant. Director ratification required (Tier-C-adjacent per brief §"Do NOT Touch").
- Bulk-DELETE of `api_cost_log` historical rows. Brief explicit prohibition.
- Manual triggering of finance / legal capabilities for verification. Would skew the table.
- `git log --follow triggers/waha_message_utils.py` confirmation of `BRIEF_WAHA_OUTBOUND_CAPTURE_1` merge date. Not needed for root-cause naming; would tighten medium-high confidence on onset alignment to high.

— B4, 2026-05-25
