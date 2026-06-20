/* ============================================================================
   AI_HOTEL_V7 — content/data package: SECTIONS 5–8 (group: "case")
   Author: B3 · brief AI_HOTEL_V7_CONTENT_PACKAGE_SPEC.md + AI_HOTEL_DASHBOARD_V7_RESTRUCTURE_1.md
   ----------------------------------------------------------------------------
   Declarative data ONLY. No DOM, no fetch, no side effects (other than the
   guarded export at the bottom). B1 is the sole integrator: spread
   V7_SECTIONS_5_8 into the SECTIONS model in outputs/static/ai-hotel.html and
   render sections 1–12 through the one reusable presentation-section renderer.

   Schema per section (per spec):
     { id, order, group, num, title, kicker, summary, status, source,
       subsections:[ {label, body, empty, chips?} ], emptyText }
   Rules honoured:
     - body is a string OR an array of strings (bullets); never null/undefined.
     - every genuinely-empty subsection carries a visible `empty:` placeholder.
     - external-presentation register (NVIDIA / MO / investor / vendor audience).
     - no invented figures: where the brief says EMPTY, the empty-state ships.

   Folded-in constants (data preserved from current ai-hotel.html):
     - STAKEHOLDERS (1332–1408, 6 give/get parties) → §5
     - RESEARCH     (429–433, NVIDIA give/get precedents) → §8
     - COMPETITORS  (441–445, Rosewood hackathon) → §8

   Cross-links (`chips[].href` with '#<id>') are best-effort to sibling sections;
   B1 owns final anchor/nav wiring and may rewrite the hrefs to match its router.
   ========================================================================== */

const V7_SECTIONS_5_8 = [

  /* ---------------------------------------------------------------- §5 ---- */
  {
    id: 'stake-giveget',
    order: 5,
    group: 'case',
    num: '05',
    title: 'Stakeholder Give/Get',
    kicker: 'What each party gives, and what each party gets',
    summary: 'Six parties make the flagship work. Each gives something scarce and gets something it cannot buy elsewhere — the basis for every ask. Per-party current ask, status and next move are tracked where known.',
    status: 'partial',
    source: 'Brisen stakeholder map (ai-hotel.html STAKEHOLDERS)',
    subsections: [
      {
        label: 'NVIDIA — chips · models · ecosystem',
        body: [
          'Gives · Brand & lighthouse co-marketing: NVIDIA lends its name and co-marketing machine to a flagship "lighthouse" deployment — joint press, a named case study, stage time.',
          'Gives · Engineering support (strategic/lighthouse only): solution architects and engineers assigned free of charge to strategic, lighthouse-scale accounts as a sales investment.',
          'Gives · Priority GPU allocation: moves a partner to the front of the queue for newest GPUs in a supply-constrained market.',
          'Gives · Inception perks & connections: credits, support, and a pipeline of vetted AI startups Brisen can pull into the locked library.',
          'Gets · Hospitality validation: a working luxury-hotel deployment proves the stack in hospitality and de-risks the whole category.',
          'Gets · GPU & compute sales: every AI workload — and the vertical it unlocks — runs on NVIDIA GPUs and compute.',
          'Gets · Library & SDK / CUDA lock-in: building on NVIDIA libraries, SDKs and CUDA deepens platform dependence.',
          'Gets · A flagship showcase site: the named hotel NVIDIA can physically show prospects.',
          'Note: almost nothing NVIDIA gives actually costs it — so what we ask is cheap to grant. Architect support is conditional on the prize being big enough.'
        ],
        empty: 'NVIDIA give/get to be filled.',
        chips: [{ label: 'NVIDIA give/get precedents →', href: '#market-proof' }]
      },
      {
        label: 'Mandarin Oriental — brand & operator · MOHG',
        body: [
          'Gives · MO brand & service standards: the name and renowned luxury-service standards — the scarce asset that makes the hotel a credible luxury-AI proof point.',
          'Gives · The venue & operations: a real, operating hotel to deploy in, plus the staff to run the pilot day to day.',
          'Gives · Guest access & data: access to real luxury guests and their consented data.',
          'Gets · MO brand uplift: positions MO as the most innovative luxury brand.',
          'Gets · AI rolled to other MO hotels: proven solutions extended across the portfolio, serving its ~45 → 100+ growth goal.',
          'Gets · NVIDIA brand association: reflected credibility from partnering with NVIDIA.',
          'Gets · AUM growth & marketing halo: higher asset value and earned-media halo across the group.',
          'Note: MO’s brand is the scarce asset the whole project routes through. Protect it — wall off MO-specific AI from anything sold elsewhere, or its moat leaks.'
        ],
        empty: 'Mandarin Oriental give/get to be filled.'
      },
      {
        label: 'Brisen — developer & sponsor',
        body: [
          'Gives · The build & orchestration: Brisen assembles and runs the whole thing — partners, build and delivery.',
          'Gives · Capital & risk-bearing: puts in (or arranges) the money and carries development risk.',
          'Gives · The relationships: access to NVIDIA, MO and investors is itself the enabling asset.',
          'Gets · Platform & equity upside: the durable prize — owning the platform and equity in what is built, not just fees.',
          'Gets · US-market entry: a beachhead into the US market via Santa Clara.',
          'Gets · Development fees: current income from developing and delivering the project.',
          'Gets · Brand value: Brisen positioned as the builder of hospitality AI.',
          'Note: Brisen sits in two seats — developer and, likely, investor/owner. Its prize is the platform and equity, not the fees.'
        ],
        empty: 'Brisen give/get to be filled.'
      },
      {
        label: 'AI companies & start-ups — AI builders · locked library',
        body: [
          'Gives · Their AI into the locked library: startups contribute products into Brisen’s curated "locked" library for the hotel.',
          'Gives · Equity / lock-in: in return for validation and distribution, they give equity or accept lock-in terms.',
          'Gives · Integration & support: they do the integration work and support the live deployment.',
          'Gets · Real-hotel validation: live proof their product works in a real luxury hotel.',
          'Gets · MO + NVIDIA halo: reflected credibility from both brands at once.',
          'Gets · Distribution to hotels: a route to many hotel customers via the platform.',
          'Gets · Valuation lift: validation plus distribution lifts their valuation.',
          'Note: the library is Brisen’s aggregation play — startups validated in the flagship, then distributed through Brisen’s own platform, walled off from MO-specific data.'
        ],
        empty: 'AI start-up give/get to be filled.'
      },
      {
        label: 'Investor / owner / lender — capital (may be Brisen)',
        body: [
          'Gives · Capital & financing: provides the money — equity or debt — to build and own the asset.',
          'Gets · The asset: ownership of the hotel real estate itself.',
          'Gets · Platform stake: a share in the platform built on top of the hotel.',
          'Gets · Start-up equity: exposure to the upside of the library start-ups.',
          'Gets · NVIDIA brand: association with NVIDIA’s brand and ecosystem.',
          'Gets · Brisen brand value: reflected value from Brisen’s track record as builder.',
          'Note: the capital seat may be Brisen itself. Whoever holds it captures the most ranked value.'
        ],
        empty: 'Investor/owner/lender give/get to be filled.'
      },
      {
        label: 'Guests — end customers',
        body: [
          'Gives · Room spend: premium room rates and on-property spend.',
          'Gives · Data & consent: guests share, with consent, the data that personalises their service.',
          'Gets · A personalised luxury stay: a futuristic, deeply personalised experience.',
          'Gets · Service that anticipates them: AI lets staff anticipate needs before guests ask.',
          'Note: the guest experience is the proof the whole thesis rests on — no guest delight, no validation.'
        ],
        empty: 'Guest give/get to be filled.'
      },
      {
        label: 'City / community',
        body: '',
        empty: 'City & community give/get to be mapped — permitting goodwill, local hiring, civic profile, traffic/zoning impact.'
      },
      {
        label: 'Per-party current ask · status · next move',
        body: '',
        empty: 'Tracked per party — current ask, status and next move to be filled where known.'
      }
    ],
    emptyText: 'Stakeholder give/get map is not yet filled.'
  },

  /* ---------------------------------------------------------------- §6 ---- */
  {
    id: 'business-case',
    order: 6,
    group: 'case',
    num: '06',
    title: 'Business Case',
    kicker: 'Where the value comes from',
    summary: 'The economic logic in qualitative terms. Figures are deliberately not stated until diligence — described drivers only.',
    status: 'partial',
    source: '',
    subsections: [
      {
        label: 'Revenue uplift',
        body: [
          'Premium positioning as a luxury-AI flagship supports rate and occupancy.',
          'Personalisation and anticipatory service lift on-property spend — dining, spa, experiences.',
          'Earned-media halo from an NVIDIA × MO launch widens demand.',
          'Figures: — to be quantified —'
        ],
        empty: 'Revenue uplift to be described.'
      },
      {
        label: 'Cost reduction',
        body: [
          'Automation of routine guest and operations tasks frees staff time for guest-facing service.',
          'Predictive maintenance cuts unplanned downtime and justifies capex with evidence (HITEC vendor evidence).',
          'AI back-office — invoice OCR and accounts-payable matching — reduces administrative load.',
          'Figures: — to be quantified —'
        ],
        empty: 'Cost reduction to be described.'
      },
      {
        label: 'Platform upside',
        body: [
          'A locked library of validated AI startups, distributed through the Brisen platform.',
          'Equity in library companies plus recurring distribution to other MO hotels and the wider vertical.',
          'Aggregation play: validate once in the flagship, distribute many times.',
          'Figures: — to be quantified —'
        ],
        empty: 'Platform upside to be described.'
      },
      {
        label: 'Capex / development economics',
        body: '',
        empty: 'Build cost, fit-out and AI infrastructure capex — to be modelled.'
      },
      {
        label: 'Investor return',
        body: '',
        empty: 'IRR / equity-return case — to be modelled.'
      },
      {
        label: 'Valuation case',
        body: '',
        empty: 'Asset and platform valuation thesis — to be developed.'
      }
    ],
    emptyText: 'Business case is not yet filled.'
  },

  /* ---------------------------------------------------------------- §7 ---- */
  {
    id: 'tech-architecture',
    order: 7,
    group: 'case',
    num: '07',
    title: 'Technology Architecture',
    kicker: 'The NVIDIA-anchored stack',
    summary: 'How the flagship is built — NVIDIA compute at the base, an orchestration layer above, integrated into the hotel’s existing systems rather than replacing them.',
    status: 'partial',
    source: '',
    subsections: [
      {
        label: 'NVIDIA compute · GPU · CUDA · SDK lock-in',
        body: [
          'On-prem GPU servers in the hotel plus cloud GPU consumption for inference.',
          'Applications built on CUDA and NIM microservices; Omniverse / NeMo adoption.',
          'Standardising the stack on NVIDIA tooling deepens switching costs and platform dependence.'
        ],
        empty: 'NVIDIA compute layer to be described.'
      },
      {
        label: 'Digital twins & simulation',
        body: [
          'An Omniverse-class digital twin of the property for layout, operations and guest-flow simulation.',
          'Scenario testing before physical change — design, staffing and service-flow trials in simulation.'
        ],
        empty: 'Digital-twin layer to be described.'
      },
      {
        label: 'AI front-desk orchestration layer',
        body: [
          'An always-on AI front desk coordinating concierge, reservations, housekeeping and service requests across vendors.',
          'Routes guest intent to the right system or human — the integration spine of the guest experience.'
        ],
        empty: 'Orchestration layer to be described.'
      },
      {
        label: 'PMS / CRM / legacy integration',
        body: [
          'Layers on the systems a hotel already runs (e.g. Opera PMS, CRM, channel managers) rather than ripping them out.',
          'Floor evidence shows 90–100+ integration patterns are standard for hospitality vendors (see Vendor & Partner Pipeline).'
        ],
        empty: 'Integration approach to be described.',
        chips: [{ label: 'See Vendor & Partner Pipeline →', href: '#vendor-pipeline' }]
      },
      {
        label: 'Data architecture',
        body: '',
        empty: 'Data model, storage and flow design — to be specified.'
      },
      {
        label: 'Privacy / consent model',
        body: '',
        empty: 'Guest-data consent and privacy architecture — to be specified.'
      },
      {
        label: 'Build vs buy map',
        body: '',
        empty: 'Which capabilities are built, bought or partnered — to be mapped.'
      }
    ],
    emptyText: 'Technology architecture is not yet filled.'
  },

  /* ---------------------------------------------------------------- §8 ---- */
  {
    id: 'market-proof',
    order: 8,
    group: 'case',
    num: '08',
    title: 'Market Proof',
    kicker: 'Evidence the thesis holds',
    summary: 'External evidence that AI in luxury hospitality is real and moving — precedents, competitor signals and floor-scouted vendors.',
    status: 'partial',
    source: 'Researcher + Origination Desk + HITEC 2026 floor scout',
    subsections: [
      {
        label: 'NVIDIA give/get precedents',
        body: 'Five real cases where NVIDIA gave something — brand, solution engineers, co-marketing, named design-partner status — to gain a flagship reference and GPU/CUDA pull-through. Includes the smallest ask that has repeatedly worked, and whether NVIDIA ever invests capital. All citations verified live. (Researcher · 15 Jun 2026 · bus #3041)',
        empty: 'NVIDIA precedents to be summarised.',
        chips: [{ label: 'Open research →', href: '/static/nvidia-give-get-precedents.html' }]
      },
      {
        label: 'Competitor signal — Rosewood "Hospitality 2030" AI hackathon',
        body: 'A leading luxury operator ran what it billed as the sector’s first AI hackathon — at Rosewood Sand Hill in Silicon Valley, partnered with Anthropic and ElevenLabs. What the move means for our flagship, with the counter-case and watch items. (Origination Desk · 17 Jun 2026 · two-source verified)',
        empty: 'Competitor signal to be summarised.',
        chips: [{ label: 'Open analysis →', href: '/static/ai-hotel-competitors-rosewood.html' }]
      },
      {
        label: 'HITEC 2026 vendor evidence',
        body: 'Nine vendors scouted on the San Antonio show floor demonstrate live AI across guest service, revenue management, predictive maintenance, staff communication and property security — proof the tooling already exists in production.',
        empty: 'HITEC evidence to be summarised.',
        chips: [{ label: 'See Vendor & Partner Pipeline →', href: '#vendor-pipeline' }]
      },
      {
        label: 'Luxury hospitality AI benchmarks',
        body: '',
        empty: 'Named luxury-operator AI benchmarks — to be compiled.'
      },
      {
        label: 'Customer demand evidence',
        body: '',
        empty: 'Guest demand / willingness-to-pay evidence — to be gathered.'
      }
    ],
    emptyText: 'Market proof is not yet filled.'
  }

];

/* Guarded export — pure data handoff, no side effects beyond attach/export. */
if (typeof window !== 'undefined') { window.V7_SECTIONS_5_8 = V7_SECTIONS_5_8; }
if (typeof module !== 'undefined' && module.exports) { module.exports = V7_SECTIONS_5_8; }
