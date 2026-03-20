# Session 29 Opening Prompts

## For AI Head (Claude Code CLI)

```
You are the AI Head for Baker/Sentinel — Dimitry Vallen's AI Chief of Staff system. Session 29. git pull && git log --oneline -10. Read CLAUDE.md.

Session 28 was massive: 18 features across 14 commits.
Key deliverables:
- AUTONOMOUS-CHAINS-1 Batch 0 — first chain fired (EVOK M365, 3/6 steps)
- Chain improvements: context forwarding, Haiku write-step adaptation, 30s per-tool timeout, max 5 steps
- Weekly priority alignment (POST /api/priorities, injected into chains + morning briefs)
- Tactical meeting briefs (Opus negotiation guidance for counterparty meetings)
- C1 LinkedIn enrichment (enrich_linkedin tool #18, Netrows client, profiling capability updated)
- B4 Memory consolidation (20 summaries live, weekly Haiku compression)
- F6 Trend detection (March report: alerts +339%, 3 contacts gone quiet)
- Admin APIs (consolidate, trends, chains, memory-summaries)
- PATCH /api/deadlines + PATCH /api/alerts for inline editing
- OpenClaw/NemoClaw evaluation (NO-GO)
- Code Brisen: E4 trip cards mobile, E8 file upload, C2 relationship health, D3 obligation triage, D5 inline alerts, E5 voice input, D4 tab customization

Original backlog: 47/48 (98%). Only B6 ($130 doc backfill) remains.

Remarkable CoS Roadmap (strategy/REMARKABLE_COS_ROADMAP.md):
- Items 1+2 SHIPPED (priorities + tactical briefs)
- Item 3: Proactive initiative engine — daily: priorities + calendar + follow-ups → 2-3 proposals
- Item 4: Relationship sentiment trajectory — Haiku tone scoring on emails/WA
- Item 5: Cross-matter convergence detection — entity co-occurrence across matters

Priorities for Session 29:
1. Build Item 3: Proactive initiative engine (the "wow" feature)
2. Build Item 4: Relationship sentiment trajectory
3. Monitor chains — check /api/chains for new chain results, tune planning prompt
4. Check Netrows API key — if arrived, add LINKEDIN_API_KEY to Render, test enrichment
5. CHAINS-1 Batch 1 evaluation — if chains are working well, upgrade standing orders
6. B6 doc backfill — if Director approved $130
```

## For Code Brisen (Claude Code on Mac Mini)

```
You are Code Brisen — frontend specialist for Baker CEO Cockpit. Session 29. git pull && git log --oneline -10.

Session 28 you shipped 7 features — the entire remaining backlog:
- E4: Trip cards on mobile (6 collapsible cards)
- E8: Mobile file upload (paperclip + share sheet)
- C2: Relationship health scoring UI (health dots, summary bar)
- D3: Obligation triage card deck (swipe actions, undo)
- D5: Inline alert editing (pencil icon, PATCH API)
- E5: Voice input (Web Speech API, 3 languages)
- D4: Tab customization (drag-reorder, pin/hide, localStorage)

Original backlog: 47/48 complete (98%). Outstanding work is now the "Remarkable CoS" roadmap.

New backend features deployed by AI Head that may need frontend:
- GET /api/priorities — weekly priorities (could show in dashboard header)
- GET /api/chains — chain execution history (could be a new tab or section)
- GET /api/memory-summaries — consolidated memory per matter
- Tactical meeting briefs now append to meeting prep alerts
- POST /api/priorities — Director can set priorities from dashboard

Wait for AI Head direction on what to build, or propose UI for the new APIs above.
Check briefs/ folder for any new briefs.
```

## Remarkable CoS — Outstanding Items

| # | Item | Effort | Who | Impact |
|---|------|--------|-----|--------|
| 3 | Proactive initiative engine | 1 week | AI Head | Baker proposes actions daily |
| 4 | Relationship sentiment trajectory | 1 week | AI Head + Code Brisen (UI) | Baker reads between the lines |
| 5 | Cross-matter convergence detection | 1 week | AI Head | Baker connects dots across domains |

### Also Pending
- **Netrows API key** — check dvallen@brisengroup.com, add as LINKEDIN_API_KEY on Render
- **B6 doc backfill** — ~$130 Haiku cost, needs Director approval
- **CHAINS-1 Batch 1** — evaluate Batch 0 results (3-5 days), then upgrade standing orders
- **VAPID keys** — Cowork adding to Render (E3 push notifications)
- **Set weekly priorities** — Director should POST /api/priorities to activate the system
