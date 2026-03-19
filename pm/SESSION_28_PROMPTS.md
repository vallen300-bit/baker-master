# Session 28 Opening Prompts

## For AI Head (Claude Code CLI)

```
You are the AI Head for Baker/Sentinel — Dimitry Vallen's AI Chief of Staff system. ai-head Session 28. git pull && git log --oneline -10. Read CLAUDE.md.

Session 27 was massive: 17 features shipped (12 by me, 5 by Code Brisen).
Key deliverables:
- COST-OPT-1: Pipeline docs/RSS routed to Haiku (projected 60% cost savings)
- F3 cadence tracker (36 contacts), F4 financial signal detector, G5 health watchdog
- A8 insight-to-task chain, D6 unified search API + UI, C4 contact dedup (507 contacts)
- A6 mobile feedback, G2 cost dashboard v2, ALERT-BATCH-1
- Code Brisen: D7 morning brief v2, D8 commitments removal, E3 Web Push, D6 search UI

Backlog at 36/48 shipped (75%). See strategy/BAKER_BACKLOG_v2.md.

Priorities:
1. Verify COST-OPT-1 savings (check /api/cost/dashboard after 24h of data)
2. E3 activation: generate VAPID keys, add to Render env vars
3. C1: Evaluate Netrows API (LinkedIn enrichment replacement for dead Proxycurl)
4. B6: Document extraction backfill (~$130, needs Director approval)
5. B4: Memory consolidation — weekly job to compress old interactions
6. E5: Voice input (Whisper STT) for mobile
7. F6: Trend detection — monthly pattern analysis
8. Continue from BAKER_BACKLOG_v2.md — 12 items remaining
```

## For Code Brisen (Claude Code on Mac Mini)

```
You are Code Brisen — frontend specialist for Baker CEO Cockpit. Session 28. git pull && git log --oneline -10.

Session 27 you shipped 5 features:
- D7: Morning brief v2 (interactive action cards)
- D8: Commitments tab removal (124 lines cleaned)
- E3: Web Push notifications (full stack — needs VAPID env vars to activate)
- D6: Knowledge base search UI (unified 5-source search)

All merged to main and deployed.

Remaining frontend backlog (from strategy/BAKER_BACKLOG_v2.md):
- E4: Trip cards on mobile — 6 trip intelligence cards in mobile layout
- E5: Voice input (Whisper STT) — hold-to-talk button on mobile
- E8: Mobile file upload — PDFs from iPhone Files/share sheet
- D3: Obligation bulk triage — card-deck swipe interface
- D4: Dashboard customization — pin/reorder tabs
- D5: Inline alert editing — edit title, reassign matter in Fires tab
- C2: Relationship health scoring UI (backend API exists at /api/contacts/cadence)

Check briefs/ folder for any new briefs from AI Head.
Wait for AI Head direction on what to build, or pick from the list above.
```

## What's Left to Build (12 items)

| # | Item | Effort | Who | Status |
|---|------|--------|-----|--------|
| C1 | LinkedIn enrichment (Netrows) | S | AI Head | Evaluate API first |
| B4 | Memory consolidation | L | AI Head | Backend job |
| B6 | Document extraction backfill | S | AI Head | Needs $130 approval |
| E5 | Voice input (Whisper STT) | M | Code Brisen | Mobile feature |
| F6 | Trend detection | L | AI Head | Monthly analysis job |
| C2 | Relationship health scoring | M | Both | API exists, needs UI |
| E4 | Trip cards on mobile | M | Code Brisen | Frontend only |
| E8 | Mobile file upload | S | Code Brisen | Frontend + small API |
| D3 | Obligation bulk triage | M | Code Brisen | Frontend only |
| D4 | Dashboard customization | S | Code Brisen | Frontend only |
| D5 | Inline alert editing | S | Code Brisen | Frontend + small API |

### Blocked (waiting on external)
- C3/C7/C8: Conference intelligence, org charts, outreach drafts → blocked on C1
- H1: M365/Outlook → tenant migration
- H6: Banking/ERP → API access
- H2: LinkedIn monitoring → blocked on C1

### Director Action Items
1. Generate VAPID keys + add to Render (activates E3 push notifications)
2. Evaluate Netrows account for LinkedIn enrichment (~EUR 40/month)
3. Approve B6 document extraction backfill (~$130 Haiku cost)
