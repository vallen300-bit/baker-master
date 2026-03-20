# BRIEF: Auto-Research Trigger (ART-1)

**Status:** SCOPING
**Author:** AI Head (Claude Code)
**Date:** 2026-03-21

---

## Problem

When a VIP sends a WhatsApp with forwarded/pasted intelligence (about a person, company, or legal matter), the Director currently does 5-6 manual steps:

1. Read the message
2. Open Claude Code or Cowork
3. Manually ask 3-4 specialists (Research, Legal, People Intel, PR)
4. Wait for raw output
5. Ask Cowork to reformat in McKinsey style
6. Send to lawyers/team

**Target:** 1 tap. Baker detects, proposes, executes on approval.

---

## Architecture

```
VIP WhatsApp arrives (e.g., Edita forwards Neubauer text)
  │
  ├── Pipeline processes as usual (alert, store)
  │
  └── NEW: _classify_research_trigger(message)
        │
        ├── NOT a trigger → normal flow, stop
        │
        └── IS a trigger → create research_proposal
              │
              ├── Dashboard card + push notification:
              │   "Edita forwarded text about Michael Neubauer (ImmoFokus).
              │    Shall I run a full dossier?"
              │   [Run Dossier]  [Skip]  [Customize...]
              │
              └── Director taps "Run Dossier"
                    │
                    ├── Dispatch specialists (parallel):
                    │   ├── Baker Research (OSINT, web, Baker memory)
                    │   ├── Baker People Intel (contact profile)
                    │   ├── Baker Legal (legal exposure, disputes)
                    │   └── Baker PR/Branding (media, reputation)
                    │
                    ├── Synthesizer combines results
                    │
                    ├── Formatter applies McKinsey template:
                    │   ├── Executive Summary (1 paragraph)
                    │   ├── Background & Context
                    │   ├── Key Findings (by specialist)
                    │   ├── Risk Assessment (matrix)
                    │   └── Recommended Actions
                    │
                    ├── Save to Dropbox: /Baker-Feed/{Name}_Dossier.docx
                    │
                    └── Dashboard card:
                        "Neubauer Dossier ready (12 pages).
                         [Send to Ofenheimer]  [Send to Team]  [Download]"
```

---

## Trigger Detection

**Where:** `triggers/waha_webhook.py` — after pipeline processing, before return.

**How:** Haiku classification call on the message body:

```
Is this message forwarding intelligence about a person, company, or legal matter
that would benefit from a multi-specialist research dossier?

Criteria:
- Forwarded/copy-pasted content (not casual chat)
- About an identifiable person or company
- From a VIP contact (tier 1-2)
- Related to an active matter or counterparty
- Contains claims, legal actions, media coverage, or business intelligence

Return: { "is_trigger": true/false, "subject_name": "...", "subject_type": "person|company|legal_matter", "context": "...", "suggested_specialists": ["research", "legal", "profiling", "pr_branding"] }
```

**Cost:** ~EUR 0.01 per WhatsApp message (Haiku classification). Only runs on VIP messages with >200 chars.

---

## Research Proposal (new table)

```sql
CREATE TABLE research_proposals (
    id SERIAL PRIMARY KEY,
    trigger_source VARCHAR(20),       -- whatsapp, email, alert
    trigger_ref TEXT,                  -- message ID or alert ID
    subject_name TEXT NOT NULL,        -- "Michael Neubauer"
    subject_type VARCHAR(20),         -- person, company, legal_matter
    context TEXT,                      -- why this was triggered
    specialists JSONB,                -- ["research", "legal", "profiling", "pr_branding"]
    status VARCHAR(20) DEFAULT 'proposed',  -- proposed, approved, running, completed, skipped
    director_customization JSONB,     -- any overrides (add/remove specialists, recipients)
    deliverable_path TEXT,            -- Dropbox path when done
    deliverable_summary TEXT,         -- executive summary for dashboard card
    send_to JSONB,                    -- suggested recipients
    created_at TIMESTAMPTZ DEFAULT NOW(),
    approved_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);
```

---

## Execution Engine

**On approval:** Reuse `capability_runner.py` (already runs specialists).

1. Build specialist prompts with:
   - Original WhatsApp message text
   - Baker memory context (matter, contacts, prior interactions)
   - Subject-specific instructions per specialist

2. Run 3-4 specialists in parallel (`asyncio.gather`)

3. Synthesizer combines (existing `synthesizer` meta-capability)

4. **McKinsey Formatter** — new Haiku call with formatting template:
   - Executive Summary (3-5 sentences, bottom-line first)
   - Background & Context (who, what, when, why it matters)
   - Key Findings (organized by specialist domain)
   - Risk Assessment (2x2 matrix: likelihood vs impact)
   - Recommended Actions (numbered, specific, with owners)

5. Generate .docx via `document_generator.py` (already exists)

6. Save to Dropbox `/Baker-Feed/{Subject}_Dossier.docx`

7. Create dashboard card with:
   - Executive summary preview
   - "Send to Ofenheimer" / "Send to Team" / "Download" buttons
   - Link to full document

---

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/research-proposals` | List proposals (proposed/running/completed) |
| POST | `/api/research-proposals/{id}/approve` | Approve + start execution |
| POST | `/api/research-proposals/{id}/skip` | Skip this research |
| POST | `/api/research-proposals/{id}/customize` | Modify specialists/recipients before running |
| POST | `/api/research-proposals/{id}/send` | Send completed dossier to recipients |

---

## Mobile + Desktop UI

**Proposal card** (appears in both mobile Actions tab and desktop widget):
```
┌─────────────────────────────────────────┐
│ 🔍 RESEARCH  Research Trigger           │
│                                         │
│ Edita forwarded intelligence about      │
│ Michael Neubauer (ImmoFokus context)    │
│                                         │
│ ┌─────────────────────────────────────┐ │
│ │ Specialists: Research, Legal,       │ │
│ │ People Intel, PR/Branding          │ │
│ └─────────────────────────────────────┘ │
│                                         │
│ [Run Dossier]  [Skip]  [Customize...]   │
└─────────────────────────────────────────┘
```

**Completed card:**
```
┌─────────────────────────────────────────┐
│ ✅ READY  Neubauer Dossier (12 pages)   │
│                                         │
│ Executive Summary: Neubauer is editor   │
│ of ImmoFokus with history of critical   │
│ coverage of luxury residential...       │
│                                         │
│ [Send to Ofenheimer]  [Send to Team]    │
│ [Download]                              │
└─────────────────────────────────────────┘
```

---

## Cost Estimate

| Component | Cost per dossier |
|-----------|-----------------|
| Trigger classification (Haiku) | EUR 0.01 |
| 4 specialist runs (Opus) | EUR 2.00 |
| Synthesizer (Opus) | EUR 0.50 |
| McKinsey formatter (Haiku) | EUR 0.05 |
| Document generation | EUR 0.00 |
| **Total** | **~EUR 2.50** |

Expected frequency: 1-2 per week = EUR 10-20/month.

---

## Implementation Sequence

### Batch 1 — Trigger + Proposal (this session)
1. `_classify_research_trigger()` in waha_webhook.py
2. `research_proposals` table
3. Proposal card on mobile Actions tab + desktop widget
4. API endpoints for approve/skip

### Batch 2 — Execution Engine (next session)
5. Parallel specialist dispatch on approval
6. Synthesizer combination
7. McKinsey formatter prompt
8. Document generation + Dropbox save
9. "Send to..." flow (email draft with attachment)

### Batch 3 — Polish
10. Email trigger (same detection for forwarded emails)
11. "Customize..." flow (add/remove specialists)
12. Template library (dossier, legal memo, deal summary)

---

## Success Criteria

- Director goes from "receive WhatsApp" to "formatted dossier sent to lawyers" in **2 taps** (approve + send)
- Quality matches what 4 manual specialist queries + Cowork formatting produces
- Formatting is consistently McKinsey-style (no raw markdown)
- Works for people, companies, and legal matters
