# PM Build Lessons

Review at session start when building or maintaining a PM. Add new lessons after each PM build.

---

## From AO PM (Investor — Andrey Oskolkov)

### 1. JSONB is write-only for humans
**Mistake:** V1 stored all compiled intelligence (psychology, investment channels, communication rules) in a single `state_json` JSONB blob. Director couldn't read it. LLM parsed JSON instead of native text.
**Rule:** Use markdown view files (`data/{slug}/*.md`) for compiled intelligence. Reserve JSONB for dynamic state (open actions, pending items, relationship metrics). Director must be able to read and edit view files directly.

### 2. Financial figures need source citations
**Mistake:** Stored EUR 50.4M as AO's total investment — but that was Channel 2 only. Actual total was ~EUR 67.3M across both channels. The error propagated into briefings and draft communications.
**Rule:** Every financial figure stored in a PM must carry: the number, the source document, the date verified, and who confirmed it. Never store a number from conversation alone.

### 3. Ask about red lines in the first 3 topics
**Mistake:** Sensitive issues (what NOT to share with AO, Durchgriffshaftung risk) only emerged mid-debrief. Earlier topics had already been stored without these constraints.
**Rule:** Before deep-diving into topic content, establish red lines: "What should Baker never say/share about this entity? What's confidential?"

### 4. Debrief state file is essential for multi-session work
**Mistake:** Without `monaco-debrief-state.md`, there would have been no way to resume a 20-topic debrief across sessions 43 and 44.
**Rule:** Create the state file at debrief start. Update after every locked topic. Include explicit resume instructions.

### 5. Wire monitoring from day one, not "later"
**Mistake:** AO PM was reactive for weeks — only answered direct questions. No signal detection, no briefing integration, no communication gap tracking. Director had to manually ask "any news from AO?"
**Rule:** Step 4 (ACTIVATE) is not optional or deferrable. Signal detection and briefing integration are part of the PM build, not a follow-up.

### 6. Orbit people matter as much as the entity itself
**Mistake:** Initially only tracked direct AO communications. Missed signals from Constantinos (advisor), Buchwalder (lawyer), and other orbit contacts.
**Rule:** During Step 1 (DISCOVER), map the full orbit: advisors, lawyers, counterparties, assistants. Their communications are signals too.

## From MOVIE AM (Hotel Asset — Mandarin Oriental Vienna)

### 7. Dashboard installation is automatic if capability_type = 'client_pm'
**Context:** Director expected a manual step to "install" MOVIE AM in the dashboard. In fact, the Client PM picker loads from `/api/client-pms` which queries `capability_sets WHERE capability_type = 'client_pm' AND active = TRUE`. Registration script already sets this.
**Rule:** Every new PM's registration script MUST set `capability_type='client_pm'`. No separate dashboard installation step needed. Verify after registration that the PM appears in the Client PM dropdown. Add this to the PM build checklist (Step 2: STRUCTURE → registration → verify in dashboard picker).

### 8. The PM must own its own debrief state
**Mistake:** Parked 8 debrief questions in Baker's deadline register (external reminders), but the MOVIE AM PM itself didn't know about them. Director expected the PM to be the persistent personality that tracks outstanding questions.
**Rule:** Write all open debrief questions into the PM's `agenda.md` view file, not just into Baker deadlines. The PM must be self-contained — when Director asks "what do you need?", it should know. Baker deadlines are just the trigger; the PM owns the intelligence.
