# BRIEF: Phase 4 — Scale & Optimize

**Author:** Code 300 (Session 13)
**Date:** 2026-03-08
**Status:** Scope document — ready for Director/PM review

---

## Where We Are

Baker is a **functional Chief of Staff** with:
- 10 data sources (Email, ClickUp, WhatsApp, Fireflies, Todoist, RSS, Whoop, Dropbox, Slack, Browser)
- 12 capability sets (10 domain + 2 meta)
- 7 standing orders (all functional)
- 16 scheduled jobs
- 50+ commitments tracked
- 3,400+ alerts processed
- 11-tab CEO Cockpit dashboard

**What's missing:** Baker works but doesn't know what it costs, can't learn from feedback, and runs everything sequentially. Phase 4 fixes that.

---

## Phase 4 Structure

Three sub-phases, ordered by value-to-effort ratio:

### 4A — Operational Hardening (HIGH priority)
*Make Baker reliable and cost-aware before scaling usage.*

| Item | What | Why | Effort |
|------|------|-----|--------|
| **Cost Monitor** | Track API costs per tool/capability/day. Circuit breaker at €5/day. Dashboard widget. | Baker makes ~50-100 Haiku calls/day + occasional Opus calls. No visibility on spend. One runaway loop could burn €50 before anyone notices. | ~200 lines |
| **Agent Observability** | `agent_tool_calls` table: tool name, latency, tokens, success/fail, capability_id. Dashboard tab. | Currently blind to which tools are slow, which fail, which cost most. Can't optimize what you can't measure. | ~300 lines |
| **Email Watermark Resilience** | Advance watermark floor when poll succeeds but finds no substantive emails. Separate "last_checked" from "last_email_seen". | Current design: watermark stays stale when inbox has only noise. Triggers false "unhealthy" alerts. Cosmetic but confusing. | ~30 lines |
| **Connection Pool Health** | Add `try/except/rollback` to all `_put_conn` returns. Log pool exhaustion. | Existing pattern returns connections without rollback on error. Works but fragile under load. | ~50 lines |

**Estimated total: ~580 lines, 1 session**

### 4B — Integration Expansion (MEDIUM priority)
*New data sources and channels.*

| Item | What | Status | Effort |
|------|------|--------|--------|
| **Browser Sentinel** | Web monitoring, change detection, hotel rate tracking | **SHIPPED** (Session 13) | Done |
| **Slack** | Polling + Events API webhook | **SHIPPED** (Session 13) | Done |
| **Calendar** | OAuth verified, prep job running | **WORKING** (Session 13) | Done |
| **M365/Outlook** | Email + Calendar from business tenant | **BLOCKED** — tenant not migrated (BCOMM project) | — |
| **Feedly → RSS upgrade** | Replace RSS polling with Feedly Pro+ API (richer metadata, AI summaries) | Feedly token expires 2026-03-14. Decision: renew or keep RSS. | ~150 lines |

**Estimated total: ~150 lines (Feedly only), rest blocked or done**

### 4C — Intelligence & Learning (LOWER priority, highest long-term value)
*Make Baker smarter over time.*

| Item | What | Why | Effort |
|------|------|-----|--------|
| **Learning Loop** | Director feedback on Baker responses → stored in `capability_feedback` table → Decomposer consults past feedback before routing. | Baker repeats mistakes. No mechanism to say "that was wrong, do it differently next time." | ~300 lines |
| **Parallel Execution** | `asyncio.gather` for multi-tool agent calls. Result caching (5-min TTL). | Agent loop runs tools sequentially. A 3-tool query takes 3x longer than needed. | ~200 lines |
| **Capability Specs** | Complete 8 remaining capability specs (PM-paced): Finance, Legal, Asset Mgmt, Research, Comms, Investment Banking, Marketing, AI Dev. | Only IT is fully specified. Others have skeleton prompts. Quality depends on domain-specific instructions. | PM work, not Code |
| **Dashboard Data Layer** | Cockpit frontend: commitment cards, browser results tab, cost widget, agent metrics charts. | Data exists but isn't visible in the UI. Director sees alerts but not commitments or costs. | ~500 lines |

**Estimated total: ~1,000 lines + PM work, 2-3 sessions**

---

## Recommended Execution Order

| Session | What | Delivers |
|---------|------|----------|
| **14** | 4A: Cost Monitor + Agent Observability | Baker knows what it spends, what's slow, what fails |
| **15** | 4A: Email resilience + Connection health | Removes false alarms, hardens DB layer |
| **15** | 4C: Learning Loop | Baker stops repeating mistakes |
| **16** | 4C: Parallel Execution | 2-3x faster agent responses |
| **16+** | 4C: Dashboard Data Layer | Director sees everything in Cockpit |
| **PM** | 4C: Capability Specs (8 remaining) | PM interviews Director per domain |

---

## What NOT to Build Yet

| Idea | Why not now |
|------|-----------|
| **Multi-user access** | Only Director uses Baker. No auth complexity needed. |
| **Mobile app** | Cockpit is responsive. WhatsApp is the mobile channel. |
| **Voice interface** | Adds complexity, low ROI vs. text chat. |
| **Custom LLM fine-tuning** | Baker accumulates experience as data, not model weights. Architecture decision from Session 9. |
| **Slack slash commands / modals** | Polling works. Events API ready. Interactive components are Phase 5+ if ever. |

---

## Decision Points for Director

1. **Cost circuit breaker threshold:** €5/day proposed. Too low? Too high? Should it alert-only or hard-stop?
2. **Feedly:** Token expires March 14. Renew Pro+ ($100/yr) or keep free RSS polling?
3. **Capability specs pace:** PM can interview Director for 1 domain per session. Which domain first after IT?
4. **Browser Sentinel first tasks:** Seed hotel rate monitoring? Which competitors? Which URLs?

---

## Files to Create/Modify (4A only — first session)

| Action | File | What |
|--------|------|------|
| CREATE | `orchestrator/cost_monitor.py` | Cost tracking, circuit breaker, daily aggregation |
| CREATE | `orchestrator/agent_metrics.py` | Tool call logging, latency tracking |
| MODIFY | `orchestrator/agent.py` | Instrument tool calls with metrics |
| MODIFY | `orchestrator/capability_runner.py` | Instrument capability runs with cost |
| MODIFY | `outputs/dashboard.py` | Cost + metrics API endpoints |
| MODIFY | `triggers/state.py` | `api_cost_log` + `agent_tool_calls` table DDL |
| MODIFY | `outputs/static/app.js` | Cost widget + metrics in Cockpit sidebar |
