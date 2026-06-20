/* ============================================================================
 * _handoff/v7_sections_1-4.js  —  AI_HOTEL_V7 content package, sections 1–4
 * Author: B2 (declarative data only — does NOT edit outputs/static/ai-hotel.html)
 * Spec:   briefs/_tasks/AI_HOTEL_V7_CONTENT_PACKAGE_SPEC.md  (§ "B2 — sections 1–4")
 *         briefs/_tasks/AI_HOTEL_DASHBOARD_V7_RESTRUCTURE_1.md (LOCKED BUILD SHAPE)
 *
 * Group: narrative (sections 01–04). Pure data + render-hook markers. No DOM,
 * no fetch, no side effects. B1 (sole integrator) folds this array into the
 * SECTIONS model and wires the render hooks below.
 *
 * RENDER HOOKS B1 MUST WIRE (subsection.render === ...):
 *   'areasGrid'         §2 — render the existing AREAS[] use-case grid.
 *   'siteThesis'        §3 — B1 injects derived research_findings (notes 24/19/17)
 *                            site-thesis summary + chips back to §13. (agreed hook
 *                            per spec §3 + design verdict #3504.)
 *   'plannedFrontDesk'  §4 — render the existing renderPlanned() always-on
 *                            front-desk concept (PMS/CRM orchestration layer).
 *
 * Empty-state discipline (Director directive): every subsection carries a visible
 * `empty:` string. Where the design brief says EMPTY, body is '' and the
 * empty-state ships — copy is NOT invented. External-presentation register
 * (NVIDIA / Mandarin Oriental / investor / site-owner / vendor audience).
 * ========================================================================== */

const V7_SECTIONS_1_4 = [
  /* ---------------------------------------------------------------- §1 ---- */
  {
    id: 'exec',
    order: 1,
    group: 'narrative',
    num: '01',
    title: 'Executive Summary',
    kicker: 'The one-screen case',
    summary: '',
    status: 'draft',
    source: 'Brisen × NVIDIA × Mandarin Oriental',
    subsections: [
      {
        label: 'Project thesis',
        body: '',
        empty: 'Thesis to be written.',
        chips: []
      },
      {
        label: 'Why now',
        body: '',
        empty: 'Timing rationale to be written.',
        chips: []
      },
      {
        label: 'Partnership proposition',
        body: 'A flagship AI-native luxury hotel in Santa Clara, structured as a three-way partnership: NVIDIA as the compute and AI-platform partner, Mandarin Oriental as the luxury operator and brand, and Brisen as the capital and development partner.',
        empty: 'Partnership proposition to be written.',
        chips: []
      },
      {
        label: 'Current ask',
        body: '',
        empty: 'The current ask to be written.',
        chips: []
      }
    ],
    emptyText: 'This section is not yet filled.'
  },

  /* ---------------------------------------------------------------- §2 ---- */
  {
    id: 'why',
    order: 2,
    group: 'narrative',
    num: '02',
    title: 'Why AI Hotel',
    kicker: 'The case for an AI-native flagship',
    summary: 'AI lets a fast-growing luxury operator hold a consistent service standard across a portfolio that is more than doubling — by enhancing the human touch, not replacing it.',
    status: 'ready',
    source: 'Mandarin Oriental AI concept note (R. Bick, 22 May 2026)',
    subsections: [
      {
        label: 'The growth challenge',
        body: 'Mandarin Oriental is scaling from roughly 45 operating hotels toward a 100-plus property pipeline. Holding a consistent luxury standard across a portfolio that more than doubles is the operating challenge AI is meant to address.',
        empty: 'Growth-challenge framing to be written.',
        chips: []
      },
      {
        label: 'Guiding principle',
        body: 'AI enhances luxury service; it does not replace the human touch. Every use case keeps a person in the loop and frees staff for high-value, guest-facing engagement.',
        empty: 'Guiding principle to be written.',
        chips: []
      },
      {
        label: 'Existing AI use-case areas',
        body: 'Seven AI use-case areas are already mapped for the property: the flagship AI-native build, guest-service concierge and reservations, staff training and coaching, operations and personalization, design and development digital twins, AI discovery (search / GEO), and back-of-house robotics.',
        empty: 'AI use-case areas load from the concept note.',
        render: 'areasGrid',
        chips: []
      }
    ],
    emptyText: 'This section is not yet filled.'
  },

  /* ---------------------------------------------------------------- §3 ---- */
  {
    id: 'site',
    order: 3,
    group: 'narrative',
    num: '03',
    title: 'Santa Clara Site Thesis',
    kicker: 'Why Silicon Valley, why this site',
    summary: '',
    status: 'partial',
    source: 'Field Evidence — site research (notes 24 / 19 / 17)',
    subsections: [
      {
        label: 'Location rationale',
        body: '',
        empty: 'Location rationale to be written.',
        chips: []
      },
      {
        label: 'Demand drivers',
        body: [
          'Silicon Valley business and meeting demand',
          'Proximity to major technology-company campuses and their visitor traffic',
          'San José and San Francisco airport access',
          'Convention and conference draw',
          'A dense technology ecosystem that fits an AI-native hospitality flagship'
        ],
        empty: 'Demand drivers to be written.',
        chips: []
      },
      {
        label: 'Competitive set',
        body: '',
        empty: 'Competitive set to be written.',
        chips: []
      },
      {
        label: 'Scouted sites',
        body: '',
        empty: 'Site research summary loads from Field Evidence.',
        render: 'siteThesis',
        chips: []
      },
      {
        label: 'Owner, zoning, parcel, price & permits',
        body: '',
        empty: 'Owner / zoning / parcel / price / permits to be confirmed from site diligence.',
        chips: []
      }
    ],
    emptyText: 'This section is not yet filled.'
  },

  /* ---------------------------------------------------------------- §4 ---- */
  {
    id: 'experience',
    order: 4,
    group: 'narrative',
    num: '04',
    title: 'Guest & Staff Experience',
    kicker: 'What AI changes for guests and staff',
    summary: 'AI runs across the guest journey and behind the scenes — concierge and reservations, pre-arrival, personalization, staff copilots, an always-on front desk and multilingual staff communication.',
    status: 'ready',
    source: 'Mandarin Oriental AI concept note + planned features + HITEC 2026 vendor evidence',
    subsections: [
      {
        label: 'Guest concierge & reservations',
        body: 'Conversational booking and concierge that handles complex questions, recommends rooms and packages, recovers abandoned bookings, and always escalates to a human agent.',
        empty: 'Guest concierge & reservations copy to be written.',
        chips: []
      },
      {
        label: 'Pre-arrival planning',
        body: 'Pre-arrival planning that prepares the stay before the guest arrives, with a seamless hand-off to the human team.',
        empty: 'Pre-arrival planning copy to be written.',
        chips: []
      },
      {
        label: 'Personalization',
        body: 'Personalization across room, dining, spa and loyalty, drawn from connected, real-time guest data.',
        empty: 'Personalization copy to be written.',
        chips: []
      },
      {
        label: 'Staff training copilots',
        body: 'Training copilots and multilingual SOP assistants that bring front desk, concierge, housekeeping, spa and F&B to proficiency faster as the portfolio grows.',
        empty: 'Staff training copy to be written.',
        chips: []
      },
      {
        label: 'Always-on AI front desk',
        body: 'An always-on orchestration layer that sits on top of the existing PMS, CRM and even legacy desktop apps — one front desk across phone, email, text and WhatsApp for every department — debuting at the Santa Clara flagship.',
        empty: 'Always-on AI front-desk concept loads from planned features.',
        render: 'plannedFrontDesk',
        chips: []
      },
      {
        label: 'Staff communication & translation',
        body: 'Wearable push-to-talk staff communication with real-time translation for a multilingual team, and spoken alerts turned into actionable safety reports — drawn from HITEC 2026 vendor evidence (see §9 Vendor & Partner Pipeline).',
        empty: 'Staff communication & translation copy to be written.',
        chips: []
      }
    ],
    emptyText: 'This section is not yet filled.'
  }
];

/* Export for B1's integrator (browser global + CommonJS for node --check / tooling). */
if (typeof module !== 'undefined' && module.exports) { module.exports = V7_SECTIONS_1_4; }
