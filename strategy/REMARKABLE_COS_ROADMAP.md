# Baker: Remarkable Chief of Staff Roadmap

**From:** AI Head | **Date:** 20 March 2026
**Context:** Original 48-item backlog is 98% complete. This roadmap is about making Baker *indispensable*, not just functional.

---

## The Gap

Baker today is a **reactive sentinel with a good memory**. He watches, stores, retrieves, alerts, and (with chains) acts when triggered.

A remarkable Chief of Staff **anticipates, connects dots, prepares you to win, understands relationships, and initiates action without being asked.**

---

## 5 Capabilities That Close the Gap

### 1. Weekly Priority Alignment — SHIPPED (Session 28)
**Baker knows what matters THIS WEEK.**

- Director sets 3-5 priorities via `POST /api/priorities` or Scan/WhatsApp
- Morning briefs lead with priority updates
- Chains focus on priority matters
- Low-relevance alerts get deprioritized

**Impact:** Baker stops treating everything equally. A EUR 50M acquisition gets more attention than a EUR 200 expense report.

---

### 2. Tactical Meeting Briefs — SHIPPED (Session 28)
**Baker prepares you to WIN meetings, not just attend them.**

- Opus generates negotiation guidance for counterparty meetings
- Includes: your position, their likely position, opening move, concessions, red lines, leverage, talking points
- Enriched with past decisions and weekly priorities
- Appended to meeting prep alerts as a tactical section

**Impact:** Director walks into every meeting with a strategic playbook, not just background research.

---

### 3. Proactive Initiative Engine — SHIPPED (Session 29)
**Baker proposes actions, not just reports.**

Daily job combines:
- Weekly priorities (what matters)
- Calendar gaps (when you have time)
- Overdue follow-ups (what's slipping)
- Approaching deadlines (what's urgent)
- Relationship trends (who needs attention)

Output: 2-3 specific, actionable initiatives per day. Each one includes a chain Baker can execute on Director approval.

Example initiatives:
- "You have 2 free hours Thursday afternoon. I've blocked time for Kempinski LOI review — the counterparty deadline is Monday."
- "Wertheimer hasn't responded in 18 days (3x his normal gap). I've drafted a casual check-in email — shall I send?"
- "The Hagenauer Gewährleistungsfrist expires in 47 days. Ofenheimer hasn't received final claim instructions. I've prepared a briefing with 3 options."

**Effort:** 1 week. Builds on chains + priorities + cadence + deadlines.
**Cost:** ~EUR 1-2/day (1 Haiku analysis + initiative generation).

---

### 4. Relationship Sentiment Trajectory — SHIPPED (Session 29)
**Baker understands HOW relationships are evolving, not just WHEN.**

- Haiku scores the tone of each inbound email/WA message (1-5 scale: hostile → warm)
- Scores stored on contact_interactions table
- Cadence tracker computes trend: warming, stable, cooling, deteriorating
- Profiling specialist gets sentiment context: "Last 5 emails from Hassa have progressively shorter, more formal tone — possible disengagement signal"

Goes beyond cadence tracking (which only measures frequency). Sentiment trajectory measures *quality* — a contact who responds on time but with cold, terse messages is at risk even though the cadence looks healthy.

**Effort:** 1 week.
**Cost:** ~EUR 0.50/day (Haiku scores piggyback on existing email/WA pipeline).

---

### 5. Cross-Matter Convergence Detection — TO BUILD
**Baker connects dots across domains that humans miss.**

- Weekly job: extract key entities (people, companies, amounts, dates) from recent alerts + emails + documents across ALL matters
- Detect when the same entity appears in multiple unrelated matters
- Generate "convergence alerts" — these are the insights that make a CoS indispensable

Example convergences:
- "The contractor who filed for insolvency (Hagenauer matter) is the same subcontractor used in the ClaimsMax project. Your warranty claims on both projects are at risk."
- "Thomas Leitner appeared in 3 meetings this week across 2 different matters (Cupial + FX Mayr). He may be a connecting thread — worth understanding his role."
- "EUR 215K VAT payment for RG 7 + EUR 180K Hagenauer retention = EUR 395K outflow this month. Cash position needs review."

**Effort:** 1 week.
**Cost:** ~EUR 0.50/day (Haiku entity extraction on alerts).

---

## Sequencing

| Phase | What | When | Impact |
|-------|------|------|--------|
| **Done** | Weekly priorities + Tactical briefs | Session 28 | Baker focuses + prepares |
| **Done** | Proactive initiative engine | Session 29 | Baker proposes actions |
| **Done** | Relationship sentiment | Session 29 | Baker reads between lines |
| **Session 30** | Cross-matter convergence | Next session | Baker connects dots |

After all 5: Baker is no longer a tool you use. Baker is an advisor who *thinks for you*.

---

## What's NOT on This List (and Why)

- **Real-time meeting companion** — Requires live audio stream integration. Technically possible but architecturally complex. Revisit Q3 2026.
- **Autonomous email sending** — Baker drafts, Director approves. This safety rule stays. Trust is built incrementally.
- **Financial modeling** — Needs banking/ERP data (H6, blocked on API access). When available, Baker could monitor cash flow, flag liquidity issues, and project burn rates.
- **Multi-stakeholder simulation** — "If you do X, counterparty does Y" game theory. The profiling specialist has game theory capabilities but needs richer data (more interactions, outcome tracking) to be reliable.
