# Baker — Master Backlog v2
### The Best AI Chief of Staff in the Universe
**Updated:** Session 27, 2026-03-19 | **Author:** AI Head

---

## Scorecard — What's Shipped

**27 of 48 items shipped** (56%). The foundation is solid. What remains is what separates a good assistant from a world-class Chief of Staff.

| Domain | Total | Shipped | Killed | Blocked | Remaining |
|--------|-------|---------|--------|---------|-----------|
| A. Mind | 8 | 4 | 1 | — | 3 |
| B. Memory | 6 | 3 | — | — | 3 |
| C. People | 8 | 0 | — | 4 | 4 |
| D. UX | 8 | 4 | — | — | 4 |
| E. Mobile | 8 | 2 | — | — | 6 |
| F. Intelligence | 7 | 4 | — | — | 3 |
| G. Health | 6 | 2 | 1 | — | 3 |
| H. Integrations | 6 | 0 | — | 3 | 3 |

### Shipped Items
A1 (agent write tools), A2 (risk detector), A3 (calendar write), A6 (feedback loop), A7 (structured query),
B1 (conversation embeddings), B2 (recency decay), B3 (decision injection),
D1 (push alerts), D2 (document browser), D7 (morning brief v2), E1 (iOS Shortcuts), E2 (mobile alerts),
F1 (compounding risk), F2 (news matching), F3 (cadence tracker), F5 (weekly digest), F7 (meeting gap detection),
G6 (data freshness). ALERT-BATCH-1 (noise reduction).

### Killed
A5 (health-aware scheduling — Whoop killed), G1 (Whoop OAuth — killed)

### Blocked
C1/C3/C7/C8 (LinkedIn enrichment — Proxycurl dead, evaluating Netrows/PDL),
H1 (M365 — tenant migration), H6 (Banking — API access)

---

## The Gap: Good Assistant → World-Class Chief of Staff

Baker is currently **reactive with intelligence**. It answers well, monitors continuously, and flags risks. But the best Chief of Staff in the world doesn't wait to be asked. They:

1. **Prepare you before you know you need it** — dossier on your desk before the meeting
2. **Close the loop** — don't just flag a risk, draft the response
3. **Remember patterns across months** — "last time you negotiated with X, you gave in on Y and regretted it"
4. **Reach you wherever you are** — push, voice, not just when you open a tab
5. **Get better every week** — learn from what worked, stop doing what didn't

---

## Remaining Backlog — Prioritized by Chief of Staff Impact

### Tier 1: The Director Should Never Have to Think About These
*These are the items where Baker not having them means the Director is doing work Baker should do.*

| # | Item | What | Effort | Why it matters |
|---|------|------|--------|---------------|
| **E3** | **Push notifications** | Service Worker + Web Push. T1 alerts reach phone even when app closed | M | A Chief of Staff who can only reach you when you open the app isn't a Chief of Staff. This is the single biggest UX gap. |
| **A8** | **Task-from-insight chain** | Specialist discovers something actionable → auto-create ClickUp task + deadline | M | Intelligence without action is just noise. Baker finds things but leaves the Director to manually create tasks. |
| **C1** | **LinkedIn enrichment API** | Replace dead Proxycurl with Netrows or PDL. Professional profiles for contacts | S | Meeting prep without knowing who you're meeting is half-blind. Unblocks 4 other items. **Evaluate Netrows first.** |
| **D6** | **Knowledge base search** | Unified search across emails, meetings, docs, WA from one bar | M | The Director asks "what did we discuss about X?" and Baker has to piece it together from 5 collections. One search bar changes everything. |
| **G5** | **Render health ping** | External uptime monitor. Alert Director via WA if Baker goes down | S | A Chief of Staff who disappears without warning is worse than none. UptimeRobot → WAHA webhook, 30 min to build. |

### Tier 2: Baker Gets Smarter
*These make Baker's intelligence genuinely useful, not just impressive.*

| # | Item | What | Effort | Why it matters |
|---|------|------|--------|---------------|
| **B4** | **Memory consolidation** | Weekly job: compress old interactions into per-matter executive summaries | L | As corpus grows past 10K items, retrieval degrades. Consolidation keeps Baker sharp without losing history. |
| **F4** | **Financial signal detection** | Haiku scans emails/docs for unusual amounts, payment delays, budget gaps | M | "Invoice 3x historical average" or "payment 30 days overdue" — these patterns are invisible until it's too late. |
| **F6** | **Trend detection** | Monthly: "Alert volume on Hagenauer up 40%, Aukera response rate down 25%" | L | Point-in-time alerts don't show direction. Trends do. This is what separates reactive from strategic. |
| **C2** | **Relationship health scoring** | Auto-score: recency × frequency × channel diversity × sentiment. Warming/cooling dashboard | M | F3 cadence tracker detects silence. C2 gives a holistic score across all channels. Together they're a relationship radar. |
| **C4** | **Contact deduplication** | "Andrei Oskolkov" vs "A. Oskolkov" vs "oskolkov@email" → merge | M | 519 contacts, likely 50+ duplicates. Fragmented profiles = fragmented intelligence. |
| **B6** | **Document extraction backfill** | Haiku classify+extract on 5,188 existing docs. One-time ~$130 | S | 3,665 docs stored but most lack structured extraction. This is untapped intelligence sitting in the database. |

### Tier 3: Surfaces & Reach
*How the Director interacts with Baker — making it effortless.*

| # | Item | What | Effort | Why it matters |
|---|------|------|--------|---------------|
| **E5** | **Voice input (Whisper STT)** | Hold-to-talk → Whisper transcription → Baker | M | Fastest input for a CEO in a car, walking, between meetings. iOS dictation works but STT is more reliable for domain terms. |
| **E4** | **Trip cards on mobile** | 6 trip intelligence cards in mobile layout | M | Director travels frequently. Trip intelligence exists on desktop but not where he needs it most — his phone. |
| **E8** | **Mobile file upload** | Send PDFs from iPhone Files/share sheet to Baker | S | "Analyze this contract" from your phone. Currently desktop only. |
| **D3** | **Obligation bulk triage** | Card-deck interface: swipe dismiss/confirm/reschedule 77 soft obligations | M | Gamified cleanup of accumulated soft obligations. Currently requires manual DB or chat commands. |
| **D4** | **Dashboard customization** | Pin/reorder tabs. Promote "Travel" during trip week, "Fires" during crisis | S | Small UX win. Director sees what matters most without scrolling. |
| **D5** | **Inline alert editing** | Edit alert title, reassign matter, add notes in Fires tab | S | Currently alerts are read-only cards. Editing requires chat. |
| **D8** | **Commitments tab retirement** | Remove stale tab (all migrated to Obligations/Deadlines) | S | Dead UI cleanup. Confuses new users. |

### Tier 4: Deep Intelligence
*Baker as a strategic advisor, not just an assistant.*

| # | Item | What | Effort | Why it matters |
|---|------|------|--------|---------------|
| **C3** | **Conference attendee intelligence** | Upload attendee CSV → Baker matches against contacts, flags "who you know" + "who you should meet" | M | Blocked on C1. But when it works: "3 contacts at IHIF, 2 potential LPs you've never met" before you walk in. |
| **C8** | **Outreach draft generation** | Auto-draft personalized emails before meetings/conferences based on relationship history | M | Blocked on C1. The Chief of Staff doesn't just tell you who to meet — they prepare the outreach. |
| **B5** | **Episodic memory linking** | Graph edges between related memories: "this email → same negotiation as that meeting" | L | Most ambitious memory feature. Enables "give me everything about the Cupial negotiation" with zero missed connections. |
| **C6** | **Contact location backfill** | Primary city for 500+ contacts. "Who's in Berlin this week?" | S | Location-aware intelligence. Useful for travel planning + conference prep. |
| **G3** | **Agent observability** | Log every tool call. Per-agent latency, error rates, cost | M | Baker doesn't know which tools are slow, expensive, or failing. Can't optimize what you can't measure. |
| **G4** | **Parallel agent execution** | asyncio.gather for multi-tool calls in agent loop | M | Agent currently calls tools sequentially. Parallel = 2-3x faster specialist responses. |
| **G2** | **Cost dashboard v2** | Daily cost chart, per-capability breakdown, €15/day alert | S | Currently only total cost is tracked. No visibility into which capabilities are expensive. |

### Tier 5: Expansion (Blocked or Low Priority)
*These wait for external dependencies or are nice-to-haves.*

| # | Item | What | Effort | Blocker |
|---|------|------|--------|---------|
| H1 | M365/Outlook | Corporate email + calendar | L | Tenant migration |
| H6 | Banking/ERP | Live financial data | L | API access |
| H2 | LinkedIn monitoring | Track VIP profile changes | M | C1 (LinkedIn API) |
| C7 | Org chart awareness | Company hierarchies | L | C1 |
| H4 | Phone call transcription | Otter.ai integration | M | — |
| E7 | Offline cache | Service worker for planes | M | — |
| E6 | Specialist camera on mobile | Camera on specialist tab | S | — |
| H3 | Telegram | Connect if contacts use it | M | — |
| H5 | Twitter/X monitoring | Counterparty social activity | M | — |
| C5 | Network graph visualization | Interactive relationship graph | L | C2 |

---

## Recommended Next 3 Sessions

### Session 28: Reach & Reliability
> *Baker reaches you everywhere and never goes down silently.*

1. **E3** — Push notifications (M) — the #1 gap
2. **G5** — Render health ping (S) — 30 min, UptimeRobot + WAHA
3. **D8** — Commitments tab retirement (S) — dead UI cleanup
4. **C1** — Evaluate Netrows API, sign up if it fits (S)

### Session 29: Action & Intelligence
> *Baker doesn't just flag — it acts and remembers.*

5. **A8** — Task-from-insight chain (M)
6. **F4** — Financial signal detection (M)
7. **B6** — Document extraction backfill (S, ~$130)
8. **D6** — Knowledge base search (M)

### Session 30: People & Scale
> *Baker knows everyone and gets faster over time.*

9. **C2** — Relationship health scoring (M)
10. **C4** — Contact dedup (M)
11. **B4** — Memory consolidation (L)
12. **G4** — Parallel agent execution (M)

---

## What "Best in the Universe" Looks Like — Updated

When this backlog is complete, Baker will:

1. **Never let you walk into anything blind** — dossiers, gap analysis, talking points ready before every meeting, call, and conference
2. **Never let a risk compound** — cross-source correlation catches the 3-signal pattern, then auto-creates the task to fix it
3. **Never lose a relationship** — cadence-relative cooling detection, health scoring, and outreach drafts ready before you ask
4. **Never let an obligation slip** — extracted from every source, escalated on cadence, with one-click triage
5. **Reach you instantly** — push notifications, voice input, mobile-first, WhatsApp fallback
6. **Close the loop** — insights become tasks, risks become actions, cooling contacts become outreach drafts
7. **Get smarter every week** — feedback loops, memory consolidation, trend detection, cost optimization
8. **Know its own health** — external uptime monitoring, cost tracking, data freshness, circuit breaker recovery

The competitive moat: Baker has **context no other AI has** — 3,600+ interactions, 3,665 documents, 1,368 emails, 519 contacts, 109 deadlines, 89 conversation memories, and the institutional memory of 27 sessions of engineering. No off-the-shelf tool can replicate this.

---

*Backlog v1 archived. This is the working document.*
