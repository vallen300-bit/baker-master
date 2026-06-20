/* ============================================================================
   AI_HOTEL_V7 — declarative content package, SECTIONS 9–12 (group: execution)
   Author: B4 · brief: AI_HOTEL_V7_CONTENT_PACKAGE_SPEC.md + LOCKED BUILD SHAPE
           (AI_HOTEL_DASHBOARD_V7_RESTRUCTURE_1.md, codex verdict #3504)

   Contract: pure data + optional pure render hints. NO DOM, NO fetch, NO side
   effects. B1 is the sole integrator of outputs/static/ai-hotel.html and folds
   this array into the SECTIONS model. Every missing subsection carries a visible
   `empty:` placeholder (Director directive) — no null/undefined bodies. External
   presentation register (NVIDIA / MO / investor / site-owner / vendor audience).
   Where the v7 design brief marks a subsection EMPTY, we ship the empty-state —
   we do NOT invent content.

   §9  Vendor & Partner Pipeline — folds VENDORS (8 HITEC booths) + adds the
       per-vendor `rank` / `nextAction` / `owner` / `followUp` fields. These four
       are §9-specific extensions on each subsection; B1 wires the pipeline render
       (`render:'vendorPipeline'`). `owner` is shipped as a visible empty-state —
       no Brisen owner has been assigned, so none is invented.
   §10 Execution Roadmap     — ALL empty per brief.
   §11 Risks & Governance    — MO brand-protection / moat-leakage WRITTEN from the
       known thesis; all other risk cards empty per brief.
   §12 The Ask               — NVIDIA ask + MO ask STATED; investor / site-owner /
       vendor asks empty per brief; COMMS draft letters folded as linked artifacts.
   ========================================================================== */

const V7_SECTIONS_9_12 = [

  /* ---------------------------------------------------------------- §9 ----- */
  {
    id: 'vendors',
    order: 9,
    group: 'execution',
    num: '09',
    title: 'Vendor & Partner Pipeline',
    kicker: 'Scouted on the floor — ranked by fit',
    summary: 'Vendors the Chairman met on the HITEC 2026 show floor (San Antonio, 17 Jun 2026), ranked by fit to the flagship, each with its next action, owner and follow-up status.',
    status: 'partial',
    source: 'Chairman HITEC field notes + badge / business-card photos · 17 Jun 2026',
    render: 'vendorPipeline',
    subsections: [
      {
        label: 'Hudini — High fit',
        rank: 1,
        body: [
          'What it is: a guest-facing in-room tablet and kiosk that becomes the hotel’s digital concierge — in-room dining (printed straight to the kitchen), restaurant and spa booking, housekeeping calls and concierge chat, all on one screen across many connected vendors.',
          'Why it matters: already finalising rollout at Mandarin Oriental Dubai and a Mandarin downtown property — the closest match to our flagship’s guest-service vision, and live inside our own operator’s estate today.',
          'Background: guest-experience and operations platform for luxury hotels (Mankara Technologies; US / Middle East / APAC), in business since ~2018. Omnichannel suite with 100+ integrations and live AI (intent-based messaging, request routing, AI upselling) at Royal Mansour Marrakech, Atlantis Dubai and SH Hotels. The Mandarin Oriental Dubai rollout heard on the floor is not yet confirmed in public sources.'
        ],
        nextAction: 'Confirm the Mandarin Oriental Dubai / downtown rollout through our operator and request a reference.',
        owner: '',
        followUp: 'Scouted at HITEC, San Antonio, 17 Jun 2026 — no outreach logged yet.',
        empty: 'Vendor detail to be filled.',
        chips: []
      },
      {
        label: 'Data Plus, Inc — High fit',
        rank: 2,
        body: [
          'What it is: two products — (1) AI accounts-payable that OCR-scans invoices, then AI agents match vendor and line-items against history, score confidence and flag doubt for a human; (2) a construction project-budgeting tool with full Gantt, ~200-task build breakdown, and original-vs-revised-vs-actual budget tracking pulling real spend from AP and the ledger. Cloud-hosted (Azure, Frankfurt region available).',
          'Why it matters: speaks directly to Brisen’s hotel-development business, not just operations — the construction-budgeting side is a rare find.',
          'Background: long-established US hospitality back-office vendor (Massachusetts, founded 1973; first hotel ERP 1986). USALI-compliant accounting, procurement and AP plus a capex/construction module. DP Invoice already applies AI/OCR (vendor claims ~99.5% accuracy); 1,200+ properties across ~15 countries (self-reported). President Bruce Bensetler is in the Hospitality Technology Hall of Fame.'
        ],
        nextAction: 'Scope a demo of the construction project-budgeting module against a live Brisen development.',
        owner: '',
        followUp: 'Scouted at HITEC, San Antonio, 17 Jun 2026 — no outreach logged yet.',
        empty: 'Vendor detail to be filled.',
        chips: [{ label: 'Bruce Bensetler — President', href: '' }]
      },
      {
        label: 'RoomPriceGenie — Swiss vendor',
        rank: 3,
        body: [
          'What it is: automated revenue management that layers on top of the systems a hotel already runs (Opera PMS, Lighthouse), reads market demand and pace, recommends a price, and pushes it back into the PMS automatically. Carries its own data API, so no separate Lighthouse subscription is needed.',
          'Why it matters: dynamic pricing without a heavy integration project; Swiss-founded (Brisen’s home turf), now across Europe, Asia and Canada.',
          'Background: Swiss revenue-management vendor (RoomPriceGenie GmbH, Steinhausen, Zug; since 2017). 90+ integrations, prices updated up to 24× a day, AI / algorithm-driven, 4,000+ hotels and a $75M growth round. Caveat: the base skews independent / budget — no named luxury customers surfaced, so the luxury fit is unproven.'
        ],
        nextAction: 'Ask for a named luxury-segment reference before any pilot; confirm Opera PMS fit.',
        owner: '',
        followUp: 'Scouted at HITEC, San Antonio, 17 Jun 2026 — no outreach logged yet.',
        empty: 'Vendor detail to be filled.',
        chips: [
          { label: 'Nuha Pancras', href: 'mailto:nuha@roompricegenie.com' },
          { label: 'Mike', href: 'mailto:mike@roompricegenie.com' }
        ]
      },
      {
        label: 'Relay — Worth a look',
        rank: 4,
        body: [
          'What it is: a wearable push-to-talk device for staff that runs on cellular (LTE) instead of two-way radios, so it keeps signal where radios die — basements, behind concrete. It translates in real time for a multilingual team and guests, with satellite and more AI on the roadmap.',
          'Why it matters: reliable staff communication plus live translation for a diverse luxury workforce; sold into property-management groups and full-service luxury resorts.',
          'Background: Relay, Inc. (Raleigh, NC), out of Republic Wireless (~2011; first Relay device 2018). 4G/5G + WiFi push-to-talk, panic alerts, indoor location, transcription and a web dashboard. Its TeamTranslate AI does real-time translation across 25–30+ languages (Fast Company 2025 World Changing Ideas). Deployed in hospitality today (Atrium Hospitality, Raleigh Marriott City Center); 4,000+ hotels/resorts/casinos self-reported.'
        ],
        nextAction: 'Trial TeamTranslate with a multilingual housekeeping team; check coverage in back-of-house dead zones.',
        owner: '',
        followUp: 'Scouted at HITEC, San Antonio, 17 Jun 2026 — no outreach logged yet.',
        empty: 'Vendor detail to be filled.',
        chips: [{ label: 'Abby DeForge — Sales (Lux)', href: '' }]
      },
      {
        label: 'aiOla (staff comms → actionable reports) — Idea to chase',
        rank: 5,
        body: [
          'What it is: the speech-to-actionable-report idea drawn out of a push-to-talk booth conversation — don’t just transcribe staff chatter, turn a spoken alert into a printed, actionable report (“gas leak in room 354” → an emergency report someone can act on).',
          'Why it matters: turns staff chatter into safety actions; the standout tip from the chat was aiOla for the speech-to-report piece — worth a direct look.',
          'Background: aiOla is an Israeli enterprise voice-AI company (Herzliya, since ~2019; ~$58M raised incl. United Airlines Ventures). Its “Jargonic” speech model targets noisy, jargon-heavy frontline work (claimed 95%+ accuracy, 120+ languages), producing structured data and automated reports. Caveat: deployed in aviation, manufacturing and logistics — NOT yet in hotels; hospitality fit is unproven.'
        ],
        nextAction: 'Open a direct conversation with aiOla and ask for a hospitality proof-of-concept.',
        owner: '',
        followUp: 'Scouted at HITEC, San Antonio, 17 Jun 2026 — no outreach logged yet.',
        empty: 'Vendor detail to be filled.',
        chips: [{ label: 'aiola.ai', href: 'https://aiola.ai' }]
      },
      {
        label: 'American Sentinel — Worth a look',
        rank: 6,
        body: [
          'What it is: AI-assisted property security — mobile deterrent towers (8–15 ft, 360°, ~600 ft visibility) that watch the grounds and can speak down to an intruder. A third-party human monitoring centre verifies every AI alert before acting, reads licence plates, and alerts the hotel’s contact or police. Two tiers: AI detection first, a human second.',
          'Why it matters: perimeter security and parking / licence-plate monitoring with a human in the loop, so guests aren’t hit with false alarms.',
          'Background: US property-security vendor (Pharr / McAllen, Texas; founded 2024). Solar-powered mobile surveillance towers, two-way speak-down audio, floodlights and cloud VMS, plus 24/7 human monitoring; AI threat / LPR / face recognition trigger human-verified dispatch. Caveat: documented use is construction, warehousing and campuses — no named hotel deployment, so hospitality use is unproven; young company, ask for references.'
        ],
        nextAction: 'Request hospitality references and a perimeter / parking pilot scope.',
        owner: '',
        followUp: 'Scouted at HITEC, San Antonio, 17 Jun 2026 — no outreach logged yet.',
        empty: 'Vendor detail to be filled.',
        chips: [
          { label: 'Christopher Gonzales', href: 'mailto:christopher.gonzales@amsentinel.com' },
          { label: 'amsentinel.com', href: 'https://amsentinel.com' }
        ]
      },
      {
        label: 'Hercules Solutions — Verify first',
        rank: 7,
        body: [
          'What it is: building-systems sensing and analytics — millions of lines of equipment data into the cloud to spot under-performing properties, detect leaks early, and justify capex with evidence; sensors run for years untouched and integrate into ticketing / PMS to auto-generate work orders.',
          'Why it matters: predictive maintenance plus a hard-numbers way to decide where capex goes across a portfolio; claims to be proven competitively in Las Vegas, runnable by a regular operator.',
          'Background: web verification could NOT confirm a company matching this description under the badge name and CEO (Kevin Kuhne). The closest online match — herculessolutionsllc.com — is a 2024 aquatic / pool-automation firm marketed as “AI-powered predictive maintenance,” with a different listed leader and no named hotel customers. Treat as a direct-follow-up lead — confirm identity and references first.'
        ],
        nextAction: 'Confirm company identity and references directly with Kevin Kuhne before any evaluation.',
        owner: '',
        followUp: 'Scouted at HITEC, San Antonio, 17 Jun 2026 — identity unverified, no outreach logged yet.',
        empty: 'Vendor detail to be filled.',
        chips: [{ label: 'Kevin Kuhne — CEO', href: '' }]
      },
      {
        label: 'Optacy — Thin fit',
        rank: 8,
        body: [
          'What it is: a data-privacy compliance tool that manages consumer data-privacy requests (DSAR / DSR) under GDPR, CCPA, US state laws and others — requests arrive via branded webforms, a toll-free hotline and email into one dashboard, with deadline tracking and automated notifications.',
          'Why it matters: flagged for the data-privacy angle, relevant to EU guest data (e.g. Mandarin Oriental Vienna); a niche compliance tool, not a hospitality platform.',
          'Background: data-privacy compliance vendor (Privacy Toll Free, LLC; Delaware; launched 2019). Caveat: NOT an AI product (only voicemail transcription); named customers are general enterprise (J.Crew, HPE, Bungie, J.D. Power), none in hospitality, and no Agilysys partnership is findable despite the lanyard. Relevant only as a niche EU-guest-data privacy tool.'
        ],
        nextAction: 'Park as a niche compliance option; revisit only if EU guest-data DSAR volume warrants.',
        owner: '',
        followUp: 'Scouted at HITEC, San Antonio, 17 Jun 2026 — no outreach logged yet.',
        empty: 'Vendor detail to be filled.',
        chips: [{ label: 'Julian Salama — Co-founder & CTO', href: '' }]
      }
    ],
    emptyText: 'Vendor pipeline to be filled.'
  },

  /* ---------------------------------------------------------------- §10 ---- */
  {
    id: 'roadmap',
    order: 10,
    group: 'execution',
    num: '10',
    title: 'Execution Roadmap',
    kicker: 'From decision to opening',
    summary: '',
    status: 'draft',
    source: '',
    subsections: [
      { label: 'First 30 days', body: '', empty: 'First-30-day plan to be written.', chips: [] },
      { label: 'First 90 days', body: '', empty: 'First-90-day plan to be written.', chips: [] },
      { label: 'Partner outreach sequence', body: '', empty: 'Partner outreach sequence to be written.', chips: [] },
      { label: 'Site diligence sequence', body: '', empty: 'Site diligence sequence to be written.', chips: [] },
      { label: 'Pilot plan', body: '', empty: 'Pilot plan to be written.', chips: [] },
      { label: 'Build / opening timeline', body: '', empty: 'Build and opening timeline to be written.', chips: [] }
    ],
    emptyText: 'Execution roadmap not yet filled.'
  },

  /* ---------------------------------------------------------------- §11 ---- */
  {
    id: 'risks',
    order: 11,
    group: 'execution',
    num: '11',
    title: 'Risks & Governance',
    kicker: 'What protects the brand and the moat',
    summary: 'The flagship’s first governance priority is protecting the Mandarin Oriental brand and the service moat; the remaining risk areas are still to be assessed.',
    status: 'partial',
    source: 'Brisen + MO concept thesis',
    subsections: [
      {
        label: 'MO brand protection & moat leakage',
        body: [
          'AI must enhance the Mandarin Oriental luxury service standard, never replace the human touch that defines the brand — the flagship is judged by MO’s bar, not by the technology.',
          'Every AI partner and vendor must be contractually bound so that MO’s proprietary service standards and guest-relationship data do not become a competitor’s training set or product feature — the service moat cannot leak through the supply chain.',
          'Co-marketing with NVIDIA and any vendor publicity must keep brand control with Mandarin Oriental, so the flagship reads as an MO property enhanced by AI, not as a technology showcase wearing the MO name.'
        ],
        empty: '',
        chips: []
      },
      { label: 'Guest-data consent', body: '', empty: 'Guest-data consent model to be assessed.', chips: [] },
      { label: 'AI hallucination / service failure', body: '', empty: 'Hallucination and service-failure controls to be assessed.', chips: [] },
      { label: 'Labour / staff acceptance', body: '', empty: 'Staff-acceptance plan to be assessed.', chips: [] },
      { label: 'Cost overrun', body: '', empty: 'Cost-overrun controls to be assessed.', chips: [] },
      { label: 'Vendor dependency', body: '', empty: 'Vendor-dependency mitigation to be assessed.', chips: [] },
      { label: 'Regulatory / zoning', body: '', empty: 'Regulatory and zoning risk to be assessed.', chips: [] }
    ],
    emptyText: 'Risk and governance assessment not yet filled.'
  },

  /* ---------------------------------------------------------------- §12 ---- */
  {
    id: 'ask',
    order: 12,
    group: 'execution',
    num: '12',
    title: 'The Ask',
    kicker: 'What we are asking each partner for',
    summary: 'The asks to NVIDIA and Mandarin Oriental are stated; investor, site-owner and vendor asks are still to be defined. Draft outreach letters are linked below.',
    status: 'partial',
    source: 'Brisen partnership concept + stakeholder map',
    subsections: [
      {
        label: 'NVIDIA ask',
        body: [
          'Co-marketing and named design-partner / flagship-reference status.',
          'Solution-engineering support to stand up the AI stack.',
          'GPU and compute priority, with CUDA / SDK access.',
          'NVIDIA Inception access for the AI startups in the pipeline.'
        ],
        empty: '',
        chips: []
      },
      {
        label: 'Mandarin Oriental ask',
        body: [
          'Use of the Mandarin Oriental brand for the flagship.',
          'An operating venue and MO’s operating partnership.',
          'MO service standards as the bar that AI must enhance, not replace.',
          'Guest-experience and consented data access to personalise and train.'
        ],
        empty: '',
        chips: []
      },
      { label: 'Investor ask', body: '', empty: 'Investor ask to be defined.', chips: [] },
      { label: 'Site-owner ask', body: '', empty: 'Site-owner ask to be defined.', chips: [] },
      { label: 'Vendor ask', body: '', empty: 'Vendor ask to be defined.', chips: [] },
      {
        label: 'Draft outreach letters',
        body: [
          'To NVIDIA — P. Storer letter: the cheap, lighthouse-scale ask drawn from the precedents research and the stakeholder map (draft pending).',
          'To Mandarin Oriental: outbound communication built from the stakeholder map and the AI-Hotel use-case areas (draft pending).'
        ],
        empty: 'Draft letters to be linked when ready.',
        chips: []
      }
    ],
    emptyText: 'The ask not yet filled.'
  }

];

if (typeof module !== 'undefined' && module.exports) { module.exports = V7_SECTIONS_9_12; }
if (typeof window !== 'undefined') { window.V7_SECTIONS_9_12 = V7_SECTIONS_9_12; }
