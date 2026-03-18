# Baker — Master Backlog v1
### The Best AI Chief of Staff in the Universe
**Created:** Session 26, 2026-03-18 | **Author:** AI Head

---

## Vision

Baker isn't a chatbot. Baker is a **cognitive extension** of the Director — always on, always watching, always thinking one step ahead. The goal: Dimitry should never be surprised, never miss a deadline, never walk into a meeting unprepared, and never lose track of a relationship.

The backlog is organized into 8 capability domains. Within each domain, items are sequenced by impact-to-effort ratio. Dependencies are marked.

---

## A. MIND — How Baker Thinks & Decides

*Baker's reasoning, agent capabilities, and autonomous action.*

| # | Item | What it does | Effort | Impact | Dep |
|---|------|-------------|--------|--------|-----|
| A1 | **Agent write tools** | Agent can create deadlines, draft emails, send WhatsApp, create ClickUp tasks — directly from the agent loop, not just via intent routing | M | Critical | — |
| A2 | **Cross-source pattern detection** | Hourly job correlates signals across email + WA + ClickUp + deadlines. "This project has 3 overdue tasks, 2 unanswered emails, and a deadline in 48h" = compounding risk alert | L | Critical | — |
| A3 | **Calendar write tool** | Agent can block focus time, propose meeting slots, create events. "I'll block 30 min tomorrow to prep for this" | S | High | A1 |
| A4 | **Generalized VIP monitoring** | Extend AO mood detection + communication gap tracking to ALL T1 contacts (15), not just Oskolkov | S | High | — |
| A5 | **Health-aware scheduling** | Inject Whoop recovery score into calendar prep + meeting recommendations. Low recovery → suggest fewer meetings, block recovery time | S | Medium | G1 |
| A6 | **Learning from feedback** | Director thumbs-up/down on alerts and answers → tune Decision Engine weights, capability routing, and alert tier classification over time | L | High | — |
| A7 | **Structured data query tool** | Agent can answer "how many T1 alerts this week" or "what's my cost trend" by querying PostgreSQL directly | S | Medium | — |
| A8 | **Task-from-insight chain** | When specialist discovers something actionable, auto-create a ClickUp task + deadline, not just a baker_insight row | M | High | A1 |

**Effort:** S = 1-2 hours, M = half day, L = 1-2 days

---

## B. MEMORY — How Baker Remembers & Retrieves

*Storage, retrieval, consolidation, and learning from the past.*

| # | Item | What it does | Effort | Impact | Dep |
|---|------|-------------|--------|--------|-----|
| B1 | **Embed conversation memory** | Store past Baker Q&A into Qdrant `baker-conversations`. Agent can semantically find "you asked me this before" | S | High | — |
| B2 | **Memory decay / recency weighting** | Qdrant scoring: exponential decay by age. Yesterday's email outranks 6-month-old meeting transcript | M | Medium | — |
| B3 | **Decision injection** | Auto-inject relevant past decisions (from `conversation_memory` + `decisions` tables) into specialist prompts when the same matter comes up | S | Medium | — |
| B4 | **Memory consolidation job** | Weekly job: summarize + compress old interactions into "executive summaries" per matter. Keeps retrieval fast as corpus grows | L | Medium | — |
| B5 | **Episodic memory linking** | Link related memories: "this email is about the same negotiation as that meeting". Graph edges in PostgreSQL, used during retrieval expansion | L | Medium | — |
| B6 | **Document extraction backfill** | Run Haiku classify+extract on ~5,188 existing documents. One-time ~$130 cost | S | Medium | — |

---

## C. PEOPLE — Relationship Intelligence

*Knowing who matters, how relationships are evolving, and what to do about it.*

| # | Item | What it does | Effort | Impact | Dep |
|---|------|-------------|--------|--------|-----|
| C1 | **Proxycurl LinkedIn integration** | Professional profiles, employment history, mutual connections for all T1/T2 contacts. Pre-meeting dossiers become real | S | Critical | Account setup |
| C2 | **Relationship health scoring** | Auto-score each contact: recency × frequency × channel diversity × sentiment. Dashboard shows warming/cooling indicators | M | High | — |
| C3 | **Conference attendee intelligence** | Before a conference, pull attendee lists (manual CSV upload or web scrape), match against contacts, surface "who you know" and "who you should meet" | M | High | C1 |
| C4 | **Contact deduplication** | Detect "Andrei Oskolkov" vs "A. Oskolkov" vs "oskolkov@..." — merge profiles automatically | M | Medium | — |
| C5 | **Network graph visualization** | Interactive graph showing relationship clusters, deal connections, matter involvement. "Who connects to whom" | L | Medium | C2 |
| C6 | **Contact location backfill** | Primary city for 500+ contacts. Enables "who's in Berlin this week" queries | S | Medium | — |
| C7 | **Org chart awareness** | Map reporting relationships, company hierarchies. "Who at Mandarin Oriental reports to whom" | L | Low | C1 |
| C8 | **Outreach draft generation** | Before meetings/conferences, auto-draft personalized outreach emails based on relationship history + shared interests | M | High | C1, C3 |

---

## D. UX — Desktop Dashboard

*The CEO Cockpit — how the Director sees and interacts with Baker.*

| # | Item | What it does | Effort | Impact | Dep |
|---|------|-------------|--------|--------|-----|
| D1 | **Real-time push alerts** | WebSocket or SSE channel. New T1 alerts appear instantly with browser notification + sound. No more 5-min poll | M | High | — |
| D2 | **Document browser** | Browse 3,287+ documents by type, matter, date. Search, preview, link to extraction | M | High | — |
| D3 | **Obligation bulk triage UI** | "Review 77 soft obligations" mode: card deck interface, swipe dismiss/confirm/reschedule. Gamified cleanup | M | Medium | — |
| D4 | **Dashboard customization** | Pin/reorder tabs. Director can promote "Travel" during trip week, "Fires" during crisis | S | Medium | — |
| D5 | **Inline alert editing** | Edit alert title, reassign matter, add notes — directly in the Fires tab without going to chat | S | Medium | — |
| D6 | **Knowledge base browser** | Unified search across all stored content (emails, meetings, documents, WA) from one search bar | M | High | — |
| D7 | **Morning brief v2** | Interactive morning brief: not just text, but clickable action cards. "Approve this draft" / "Dismiss this deadline" / "Call this person" | L | High | A1 |
| D8 | **Commitments tab retirement** | Remove or repurpose the stale Commitments tab (all migrated to Obligations) | S | Low | — |

---

## E. MOBILE — iPhone Experience

*Baker in your pocket — the most-used surface.*

| # | Item | What it does | Effort | Impact | Dep |
|---|------|-------------|--------|--------|-----|
| E1 | **iOS Shortcuts live** | ~~Ask Baker + Baker Vision share sheet shortcuts~~ DONE — `/api/scan/quick` shipped. Test on device, iterate | S | High | — |
| E2 | **Mobile alerts view** | Swipeable alert cards on mobile. Swipe right = dismiss, swipe left = act. Badge tap opens the view | M | High | — |
| E3 | **Push notifications** | Service worker + Web Push API. T1 alerts push to phone even when app is closed | M | Critical | — |
| E4 | **Trip cards on mobile** | The 6 trip intelligence cards rendered in mobile-optimized layout | M | Medium | — |
| E5 | **Voice input (Whisper STT)** | Hold-to-talk microphone button → Whisper transcription → Baker. True voice, not iOS dictation | M | Medium | — |
| E6 | **Specialist camera on mobile** | Camera button on Specialist tab (currently Baker-only) | S | Low | — |
| E7 | **Offline cache** | Service worker caches last morning brief + recent alerts. App usable on planes | M | Low | — |
| E8 | **Mobile file upload** | Send PDFs/docs to Baker from iPhone Files app or share sheet | S | Medium | E1 |

---

## F. INTELLIGENCE — Proactive Pattern Recognition

*Baker thinking ahead, not just reacting.*

| # | Item | What it does | Effort | Impact | Dep |
|---|------|-------------|--------|--------|-----|
| F1 | **Compounding risk detector** | Hourly: for each active matter, count overdue tasks + unanswered messages + approaching deadlines. Score > threshold → T1 alert: "Matter X is deteriorating" | M | Critical | — |
| F2 | **News-to-counterparty matching** | RSS articles matched against matter keywords + VIP names. "Article about Kempinski operator change — relevant to your bid" | M | High | — |
| F3 | **Email response time tracking** | Track how fast each contact responds to Director. Surface "Piras usually replies in 2h, now 3 days — something changed" | M | High | — |
| F4 | **Financial signal detection** | Haiku scans new emails/docs for unusual amounts, payment delays, budget overruns. "Invoice 3x larger than historical average for this vendor" | M | Medium | — |
| F5 | **Weekly intelligence digest** | Sunday evening: "This week Baker detected 4 new risks, 2 opportunities, and 1 relationship cooling. Here's what to do Monday" | M | High | F1, F3 |
| F6 | **Trend detection** | Monthly: "Alert volume on Hagenauer matter up 40% this month. Email response rates from Aukera down 25%" | L | Medium | — |
| F7 | **Pre-meeting "what don't I know" check** | Before each meeting, identify gaps: "You've never discussed X topic with this person. Their company just announced Y. Consider raising Z" | M | High | C1 |

---

## G. HEALTH — System Reliability & Monitoring

*Baker watching itself — uptime, cost, data freshness.*

| # | Item | What it does | Effort | Impact | Dep |
|---|------|-------------|--------|--------|-----|
| G1 | **Whoop OAuth fix** | Re-authenticate Whoop API. 88+ consecutive failures since Feb 28 | S | Medium | — |
| G2 | **Cost dashboard v2** | Daily cost chart in Baker Data tab. Per-capability cost breakdown. Alert if daily spend exceeds €15 | S | Medium | — |
| G3 | **Agent observability** | Log every agent tool call to `agent_tool_calls` table. Per-agent latency, tool usage patterns, error rates | M | Medium | — |
| G4 | **Parallel agent execution** | `asyncio.gather` for multi-tool calls in agent loop. Result caching (5-min TTL) | M | Medium | — |
| G5 | **Render health ping** | External uptime monitor (UptimeRobot or similar). Alert Director via WA if Baker goes down | S | High | — |
| G6 | **Data freshness dashboard** | Visual timeline: when was each data source last polled, how many items ingested. Green/amber/red per source | S | Medium | — |

---

## H. INTEGRATIONS — Expanding Baker's Senses

*More data sources = better Chief of Staff.*

| # | Item | What it does | Effort | Impact | Dep |
|---|------|-------------|--------|--------|-----|
| H1 | **M365 / Outlook** | Email + calendar from corporate tenant. Currently blocked on tenant migration | L | High | Tenant migration |
| H2 | **LinkedIn monitoring** | Track VIP profile changes, job moves, company news | M | Medium | C1 |
| H3 | **Telegram** | Connect if any business contacts use it | M | Low | — |
| H4 | **Phone call transcription** | Otter.ai or similar → ingest call transcripts alongside Fireflies | M | Medium | — |
| H5 | **Twitter/X monitoring** | Track counterparty social activity, sentiment | M | Low | — |
| H6 | **Banking/ERP feed** | Live financial data (account balances, payment confirmations). Eliminates "is this invoice paid?" guesswork | L | High | API access |

---

## Recommended Execution Sequence

### Phase 5A — Immediate Impact (Next 2 Sessions)
> *Fix what's broken, ship what's nearly ready.*

1. **E1** — Test iOS Shortcuts on device, iterate (DONE — verify)
2. **G1** — Whoop OAuth fix (30 min)
3. **A4** — Generalize VIP monitoring to all T1 contacts (2h)
4. **B1** — Embed conversation memory into Qdrant (1h)
5. **C1** — Proxycurl account setup + integration (2h, needs Director action)
6. **D8** — Retire Commitments tab (30 min)

### Phase 5B — Intelligence Leap (2-3 Sessions)
> *Baker starts thinking ahead, not just answering.*

7. **F1** — Compounding risk detector (half day)
8. **A1** — Agent write tools — deadlines, email drafts, WA send (half day)
9. **A2** — Cross-source pattern detection (1 day)
10. **E3** — Push notifications on mobile (half day)
11. **D1** — Real-time push alerts on desktop (half day)
12. **F2** — News-to-counterparty matching (half day)

### Phase 5C — People Intelligence (2-3 Sessions)
> *Baker knows everyone the Director knows.*

13. **C2** — Relationship health scoring (half day)
14. **C3** — Conference attendee intelligence (half day)
15. **C8** — Outreach draft generation (half day)
16. **F3** — Email response time tracking (half day)
17. **F7** — Pre-meeting "what don't I know" check (half day)

### Phase 5D — Polish & Scale (Ongoing)
> *UX refinements, integrations, optimization.*

18. **D2** — Document browser (half day)
19. **D6** — Knowledge base search (half day)
20. **D7** — Morning brief v2 (1 day)
21. **E2** — Mobile alerts view (half day)
22. **F5** — Weekly intelligence digest (half day)
23. **B2** — Memory decay / recency (half day)
24. **G3** — Agent observability (half day)

### Blocked / Waiting
- **H1** — M365/Outlook (tenant migration)
- **H6** — Banking/ERP (API access)
- **C1** — Proxycurl (Director to create account)

---

## What "Best in the Universe" Looks Like

When this backlog is complete, Baker will:

1. **Never let a relationship go cold** — automatic cooling detection, outreach drafts ready
2. **Never let a risk compound silently** — cross-source correlation catches the 3-signal pattern no human would notice
3. **Never let the Director walk into a meeting blind** — dossiers, gaps flagged, talking points prepared
4. **Never let an obligation slip** — auto-extracted, auto-escalated, auto-reminded
5. **Be reachable from any surface** — desktop dashboard, mobile PWA, iOS Shortcuts, push notifications, WhatsApp
6. **Learn from every interaction** — feedback loops improve routing, ranking, and proactivity over time
7. **Know its own health** — cost tracking, uptime monitoring, data freshness visible at a glance

The competitive moat: Baker has **context no other AI has** — 3,600+ interactions, 3,200+ documents, 280+ emails, 500+ contacts, and the institutional memory of 26 sessions of engineering. No off-the-shelf tool can replicate this.
