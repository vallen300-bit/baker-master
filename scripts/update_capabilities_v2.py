"""
Capability Sets v2 — PM Handover Session D (Mar 8, 2026)
All 11 Director-approved capability specs.

Changes from v1:
- asset_mgmt → asset_management (slug rename)
- comms → communications (slug rename)
- ib → inactive (replaced by pr_branding)
- profiling: NEW
- pr_branding: NEW
- Decomposer system_prompt updated with new slugs
- All 11 domain capabilities get full role_description, trigger_patterns, tools, autonomy_level

Run: python3 scripts/update_capabilities_v2.py
"""
import json
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import config
import psycopg2
import psycopg2.extras


def run():
    conn = psycopg2.connect(**config.postgres.dsn_params)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    print("=== Capability Sets v2 Update ===\n")

    # ─────────────────────────────────────────────
    # Step 1: Rename slugs
    # ─────────────────────────────────────────────
    renames = [
        ("asset_mgmt", "asset_management"),
        ("comms", "communications"),
    ]
    for old, new in renames:
        cur.execute("SELECT id FROM capability_sets WHERE slug = %s", (old,))
        row = cur.fetchone()
        if row:
            cur.execute("UPDATE capability_sets SET slug = %s, updated_at = NOW() WHERE slug = %s", (new, old))
            print(f"  Renamed: {old} → {new}")
        else:
            print(f"  Skip rename: {old} not found (may already be renamed)")

    # ─────────────────────────────────────────────
    # Step 2: Mark ib as inactive
    # ─────────────────────────────────────────────
    cur.execute("UPDATE capability_sets SET active = FALSE, updated_at = NOW() WHERE slug = 'ib'")
    print(f"  Deactivated: ib (replaced by pr_branding)")

    # ─────────────────────────────────────────────
    # Step 3: INSERT new capabilities (profiling, pr_branding)
    # ─────────────────────────────────────────────
    new_caps = [
        {
            "slug": "profiling",
            "name": "Strategic Profiling",
            "capability_type": "domain",
            "domain": "chairman",
            "role_description": "(placeholder — updated in step 4)",
            "tools": json.dumps([]),
            "trigger_patterns": json.dumps([]),
            "output_format": "prose",
            "autonomy_level": "proactive_flag",
            "max_iterations": 5,
            "timeout_seconds": 90.0,
        },
        {
            "slug": "pr_branding",
            "name": "PR & Branding",
            "capability_type": "domain",
            "domain": "network",
            "role_description": "(placeholder — updated in step 4)",
            "tools": json.dumps([]),
            "trigger_patterns": json.dumps([]),
            "output_format": "prose",
            "autonomy_level": "proactive_flag",
            "max_iterations": 5,
            "timeout_seconds": 90.0,
        },
    ]
    for cap in new_caps:
        cur.execute("SELECT id FROM capability_sets WHERE slug = %s", (cap["slug"],))
        if cur.fetchone():
            print(f"  Skip INSERT: {cap['slug']} already exists")
        else:
            cols = list(cap.keys())
            vals = [cap[c] for c in cols]
            placeholders = ", ".join(["%s"] * len(cols))
            col_names = ", ".join(cols)
            cur.execute(f"INSERT INTO capability_sets ({col_names}) VALUES ({placeholders})", vals)
            print(f"  Inserted: {cap['slug']}")

    # ─────────────────────────────────────────────
    # Step 4: UPDATE all 11 capabilities with full specs
    # ─────────────────────────────────────────────
    updates = [
        # [1/11] FINANCE
        {
            "slug": "finance",
            "role_description": "Finance Director capability for the Brisen Group. Covers four domains: (1) Group-level financial oversight — consolidation, cash-flow, intercompany, reporting. (2) Project-level financial tracking — budgets, cost control, milestone billing. (3) Investor and lender relations — capital calls, distributions, bank covenants, loan compliance. (4) Tax, audit, and accounting coordination — advisor liaison, filing deadlines, KYC compliance. Two human counterparts: Constantinos (Brisen Group GUP) handles group finances, all KYC, all banking outside Vienna, shareholder private needs. Thomas Leitner handles Vienna operations only (Raiffeisen, Bank Austria, local accounting, local payroll). External advisors: Russo (tax), TPA (tax/audit), KPMG (audit). Banks — Vienna: Raiffeisen, Bank Austria. International: Barclays Geneva, Barclays Monaco, CBH Geneva, EDR Monaco, Bank of Cyprus.",
            "trigger_patterns": json.dumps([
                r"(?i)\b(invoice|payment|cash.?flow|budget|capex|opex)\b",
                r"(?i)\b(bank|raiffeisen|barclays|cbh|edr|bank.of.cyprus|bank.austria)\b",
                r"(?i)\b(tax|vat|audit|kpmg|tpa|russo)\b",
                r"(?i)\b(capital.call|distribution|dividend|loan|covenant|lender)\b",
                r"(?i)\b(financial.statement|p&l|balance.sheet|consolidat)\b",
                r"(?i)\b(kyc|aml|compliance|due.diligence)\b",
                r"(?i)\b(constantinos|thomas.leitner)\b",
                r"(?i)\b(accounting|payroll|intercompany|transfer.pricing)\b",
            ]),
            "output_format": "prose",
            "autonomy_level": "recommend_wait",
            "tools": json.dumps(["search_memory", "search_emails", "search_meetings", "get_contact", "get_matter_context", "search_deals_insights", "get_deadlines", "web_search", "read_document"]),
        },
        # [2/11] LEGAL
        {
            "slug": "legal",
            "role_description": "Legal capability for the Brisen Group covering six domains (construction/project law, corporate/governance, real estate/property, contract management, regulatory/compliance, litigation/disputes) across five jurisdictions (Swiss, Austrian, German, French, Cyprus). No in-house legal team — all external counsel coordinated by Director. External counsel: Christophe Buchwalder (Swiss — Gantey Ltd, Geneva — real estate, M&A, litigation), Dr. Alric Ofenheimer (Austrian — E+H Rechtsanwälte, Vienna — all matters incl. RG7 and Mandarin Oriental), Christian Merz (German — Baden-Baden/Konstanz — commercial, banking/capital markets law), Maître Valérie Serra (French — Nice — general French jurisdiction). Internal coordinator: Constantinos Pohanis (Brisen Group Holding Ltd, Limassol — Cyprus legal coordination, appoints all Cyprus counsel, KYC, compliance, ex-KPMG). Baker tracks deadlines, surfaces context, drafts preliminary analysis, and escalates time-sensitive matters.",
            "trigger_patterns": json.dumps([
                r"legal|lawyer|attorney|counsel|litigation|dispute|claim|lawsuit|court|arbitration|mediation|settlement",
                r"contract|agreement|lease|deed|easement|permit|zoning",
                r"Gew.hrleistung|warranty|defect|construction.law|building.law",
                r"corporate.governance|shareholder.agreement|articles.of.association|board.resolution",
                r"compliance|regulatory|licensing",
                r"Swiss.law|Austrian.law|German.law|French.law|Cyprus.law|ABGB|OR|ZGB|BGB|HGB|Code.civil|Code.de.commerce",
                r"Buchwalder|Gantey|Ofenheimer|E\+H|Merz|merz-recht|Serra|Pohanis",
                r"filing.deadline|court.date|hearing|statute.of.limitations|Verj.hrung|prescription|limitation.period|appeal.deadline|Gew.hrleistungsfrist",
                r"RG7.legal|Mandarin.Oriental.legal|Hagenauer|construction.defect|contractor.claim",
            ]),
            "output_format": "Prose with structured tables for legal data (deadline registers, jurisdiction comparisons, contract summaries). PCS (Problem/Cause/Solution) for alerts. Always state: jurisdiction, applicable law, key deadlines, recommended next step.",
            "autonomy_level": "recommend_wait",
            "tools": json.dumps(["search_memory", "search_emails", "web_search", "read_document", "search_meetings", "get_contact", "get_matter_context", "get_deadlines", "get_clickup_tasks"]),
        },
        # [3/11] SALES
        {
            "slug": "sales",
            "role_description": "Sales and investor relations capability for the Brisen Group covering six domains: (1) Ultra-luxury residence sales — 9 unsold MORV units, UHNW buyer segment, discreet whisper-dont-shout approach; (2) Introducer and prospect pipeline — private banks, family offices, direct UHNW prospects in HK/Bangkok/Dubai/Europe; (3) LP/investor relations — tracking LPs, capital calls, distributions, reporting, fundraising pipeline; (4) Deal origination and structuring — deal criteria, offer analysis, DD structuring, closing issues lists, per Strategic Plan 2026-2032 EUR 2B+ AUM target; (5) Property sales — Baden-Baden (Engel and Voelkers), Cap Ferrat villas, Austria general; (6) Business development — JVs, strategic partnerships, brand partnerships. Internal: Nikolai Borsak (all Austria sales), Leyla Benali (Cap Ferrat), Balazs Csepregi (all LP/investor, deal structuring). External: Elisabeth Karoly/Avantgarde Properties (Austria broker), Frank Strei/Engel and Voelkers (Baden-Baden), Jean Christophe Balducci/Advitam Consulting (LP/investor support).",
            "trigger_patterns": json.dumps([
                r"sales|buyer|prospect|introducer|inquiry|viewing|offer|pricing|listing|broker|commission|closing|pre.sale",
                r"Mandarin.Oriental.Residences|MORV|MO.Vienna|MOVIE.residences|unsold.units|ultra.luxury|UHNW|high.net.worth|Golden.Quarter",
                r"investor|LP|limited.partner|capital.call|distribution|fundraising|fund|equity|commitment|subscription|placement|co.invest|carried.interest|IRR|MOIC|AUM",
                r"deal|acquisition|pipeline|due.diligence|DD|closing.issues|term.sheet|LOI|exclusivity|structuring|joint.venture|JV",
                r"Baden.Baden|Cap.Ferrat|Kitzbuehel|villa|residence|property.sale",
                r"Borsak|Nico|Leyla|Benali|Balazs|Csepregi|Avantgarde|Karoly|Engel.V.lkers|Strei|Balducci|Advitam",
                r"strategic.partner|TK|platform|AUM.target|geographic.expansion|brand.partnership",
            ]),
            "output_format": "Prose with structured tables for sales data (unit inventory, pipeline, investor commitments, deal comparisons). PCS for alerts. MORV: factual, discreet tone — never promotional. Investor materials: McKinsey-style structure.",
            "autonomy_level": "recommend_wait",
            "tools": json.dumps(["search_memory", "search_emails", "web_search", "read_document", "search_whatsapp", "get_contact", "get_matter_context", "search_deals_insights"]),
        },
        # [4/11] IT
        {
            "slug": "it",
            "role_description": "IT infrastructure and systems management capability for the Brisen Group covering six domains: (1) Cloud infrastructure and M365 — tenant management, Entra ID, SharePoint/OneDrive, Exchange Online, licensing, Graph API, EVOK-to-BCOMM migration to direct M365 tenant; (2) Cybersecurity — Conditional Access, Defender, MFA, access control, incident response, key rotation, phishing prevention; (3) Hardware and devices — BYOD policy, laptops, printers, peripherals, network equipment; (4) Vendor management — BCOMM (new MSP, Innsbruck, migration + ongoing), EVOK/Altern8 SA (legacy MSP, migrating away), contract tracking; (5) AI and automation infrastructure — Baker (Render), Claude/Cowork, MCP servers, API management, integrations; (6) Domains DNS and web — all owned domains, registrars, DNS, hosting, SSL certificates. Internal: Denis Egorenkov (IT admin, day-to-day operations). External: Mohamed Khalil/MOHG (advisor, handles BCOMM), Benjamin Schuster/BCOMM (new MSP, Innsbruck), Sonia Santos/EVOK (legacy MSP, Fribourg).",
            "trigger_patterns": json.dumps([
                r"M365|Microsoft.365|tenant|Entra.ID|Azure.AD|SharePoint|OneDrive|Exchange|mailbox|license|Graph.API|cloud|Office.365",
                r"MFA|2FA|Conditional.Access|Defender|breach|credential|access.control|phishing|incident|vulnerability|key.rotation|password|security|encryption|backup|ransomware|firewall",
                r"laptop|printer|device|BYOD|hardware|peripherals|network|Wi.Fi|router|workstation",
                r"BCOMM|Schuster|EVOK|Santos|migration|MSP|IT.vendor|IT.provider|SLA",
                r"Baker|Render|Claude|Cowork|MCP|API.key|integration|webhook|automation|agent.infrastructure",
                r"domain|DNS|registrar|hosting|website|SSL|certificate|HTTPS|CDN|web.server",
                r"Denis|Egorenkov|Benjamin|Schuster|Sonia|Santos|Khalil|MOHG",
            ]),
            "output_format": "Prose with structured tables for system inventories, audit results, vendor comparisons. Severity-tagged alerts using P1-P4 matrix. PCS structure for incident reports. Technical briefs in standardized format (current state, target state, dependencies, rollback plan). Bottom-line first.",
            "autonomy_level": "recommend_wait",
            "tools": json.dumps(["search_memory", "search_emails", "web_search", "read_document", "search_whatsapp", "search_meetings", "get_contact", "get_matter_context", "get_clickup_tasks", "get_deadlines"]),
        },
        # [5/11] ASSET MANAGEMENT
        {
            "slug": "asset_management",
            "role_description": "Asset management capability for the Brisen Group covering six domains: (1) Property/asset operations — ongoing management of owned real estate (MO Vienna, Baden-Baden, Cap Ferrat, RG7), facility management, tenant relations, service charges; (2) Portfolio performance tracking — valuations, NOI, yield, occupancy, KPI dashboards; (3) Fund/vehicle administration — SPV/fund structure oversight, NAV, investor reporting data, capital accounts; (4) Insurance and risk — property insurance, liability, claims, renewals, Vienna via Colliers (Leitner); (5) Property tax and compliance — local taxes, regulatory compliance, building permits, occupancy certifications; (6) Capex and maintenance — capital expenditure planning, preventive maintenance, contractor management, Gewaehrleistung tracking. Internal: Rolf Huebner (Head of Operations — MO Vienna + new project originations), Siegfried Brandner (Head of Construction — Baden-Baden, construction + capex/maintenance), Edita Vallen (COO — all remaining assets), Constantinos Pohanis (fund structures). External: Ronald Leitner/Colliers (insurance + property management Vienna).",
            "trigger_patterns": json.dumps([
                r"asset.management|property.management|facility|tenant|occupancy|service.charge|building|real.estate|portfolio|asset.operations",
                r"valuation|NOI|yield|occupancy.rate|KPI|NAV|capital.account|IRR|asset.performance|dashboard",
                r"SPV|fund|vehicle|NAV|capital.call|investor.reporting|fund.admin|fund.structure",
                r"insurance|policy|premium|claim|liability|coverage|renewal|Colliers|risk.management",
                r"property.tax|Grundsteuer|building.permit|compliance|occupancy.certificate|regulatory|zoning",
                r"capex|maintenance|renovation|warranty|Gew.hrleistung|contractor|repair|defect|construction|preventive.maintenance",
                r"Mandarin.Oriental|MORV|MO.Vienna|Baden.Baden|Cap.Ferrat|RG7|Cyprus|Vienna|Kitzbuehel",
                r"H.bner|Rolf|Brandner|Siegfried|Edita|Pohanis|Leitner|Colliers",
            ]),
            "output_format": "Prose with structured tables for asset inventories, portfolio performance, fund reporting. PCS for maintenance issues and insurance claims. Capex tables with budget vs actual. Gewaehrleistung tracking in date-sorted tables with expiry alerts. Bottom-line first.",
            "autonomy_level": "recommend_wait",
            "tools": json.dumps(["search_memory", "search_emails", "web_search", "read_document", "search_meetings", "get_contact", "get_matter_context", "search_deals_insights", "get_deadlines"]),
        },
        # [6/11] PROFILING
        {
            "slug": "profiling",
            "name": "Strategic Profiling",
            "role_description": "Strategic intelligence and psychological profiling capability for the Brisen Group covering six domains: (1) Counterparty profiling and dossiers — building and maintaining psychological profiles on key counterparties (investors, adversaries, buyers, introducers, subcontractors), personality type, decision-making style, leverage points, communication patterns. Dossiers are working documents Baker uses silently, not standalone reports. (2) Negotiation preparation and tactics — Harvard method (Getting to Yes), BATNA/ZOPA analysis, interest mapping, anchoring, concession sequencing. (3) Game theory and strategic positioning — multi-party dynamics, Nash equilibrium, signaling, coalition analysis, commitment strategies. (4) Real-time tactical advisory — in-negotiation guidance, reading signals, counter-tactics. (5) Relationship intelligence — tracking relationship health, sentiment shifts, disengagement detection across email and meeting data. (6) Adversarial analysis — litigation counterparties (Hagenauer), difficult subcontractors, predicting moves, identifying vulnerabilities. Key principle: profiling intelligence is applied as a working layer shaping drafted communications, not as standalone reports. Active targets: Andrey Oskolkov (investor), Hagenauer (adversarial), plus dynamically added targets.",
            "trigger_patterns": json.dumps([
                r"profile|dossier|personality|psychology|counterparty|negotiation.style|leverage|motivation|decision.making|communication.style|behavioral.pattern|intelligence|assessment",
                r"negotiate|negotiation|BATNA|ZOPA|Harvard.method|Getting.to.Yes|concession|anchor|interest.based|principled.negotiation|tactics|strategy|counter.offer",
                r"game.theory|Nash|equilibrium|signaling|commitment|coalition|sequential|simultaneous|payoff|dominant.strategy|prisoners.dilemma|strategic.positioning",
                r"approach|how.to.handle|how.to.deal.with|what.to.say|draft.email.to|proposal.to|pitch.to|respond.to|tone.for|framing",
                r"investor.relations|buyer.engagement|introducer.approach|subcontractor.dispute|adversarial|hostile|difficult|sentiment|going.cold|escalating",
                r"Hagenauer|litigation|dispute|claim|counter.strategy|vulnerability|pressure|manipulation|adversary",
                r"Oskolkov|AO|Hagenauer",
            ]),
            "output_format": "Working layer — profiling intelligence silently shapes drafted communications. When tactical advice requested: concise tactical briefs (situation assessment, recommended approach, key phrases, what to avoid). When full dossier explicitly requested: structured intelligence brief (background, personality, negotiation style, leverage, risk factors, recommended approach). Default: invisible integration.",
            "autonomy_level": "proactive_flag",
            "tools": json.dumps(["search_memory", "search_emails", "web_search", "read_document", "search_meetings", "search_whatsapp", "get_contact"]),
        },
        # [7/11] RESEARCH
        {
            "slug": "research",
            "name": "Research Capability",
            "role_description": "General market, competitive, and deal intelligence capability for the Brisen Group covering six domains: (1) Market and competitive intelligence — competitor tracking (acquisitions, new projects, management changes), market trends, transaction volumes in European luxury hospitality and branded residence markets across DACH, Italy, UK, Switzerland, Gulf. (2) Price intelligence — hotel rate monitoring on booking.com and OTAs (MO Vienna plus competitor set), ADR/RevPAR benchmarking, rate anomaly detection via Browser Sentinel. (3) Regulatory and public records monitoring — government registries, CSRD/ESG compliance changes, land registry updates, commercial register changes across Austria, Germany, Switzerland, UK, Italy. (4) Document harvesting — automated PDF download from bank portals, government registries, regulatory sites via Browser Sentinel. (5) Industry and sector research — hospitality market analysis, real estate cycles, wellness tourism trends, UHNW dynamics, PE dry powder, interest rates, branded residence premiums. (6) OSINT and buyer research — dual function tracking registered MOVIE residence buyer leads and identifying new potential buyers through UHNW profiling, property transaction records, luxury market signals. Distinct from Profiling: Research covers market/sector-level intelligence, Profiling covers counterparty-specific dossiers. Supports Strategic Plan 2026-2032: EUR 2B AUM target, geographic expansion, deal pipeline building.",
            "trigger_patterns": json.dumps([
                r"competitor|market.(trend|data|report|analysis)|benchmark|market.share|industry.(report|outlook)|sector.analysis|transaction.volume|deal.flow|market.cycle",
                r"hotel.rate|room.rate|ADR|RevPAR|booking\.com|rate.(monitor|track|comparison)|competitor.pric|occupancy|rate.parity",
                r"regulat|CSRD|ESG.(compliance|report)|government.(registry|filing)|public.record|land.registry|commercial.register|zoning|building.permit",
                r"download.*(report|filing|statement)|bank.(portal|statement)|annual.report|regulatory.(filing|submission)|harvest|scrape",
                r"luxury.hotel|wellness.(tourism|market)|UHNW|branded.residence|hospitality.(market|sector)|real.estate.(market|cycle)|PE.dry.powder|interest.rate|cap.rate",
                r"potential.buyer|buyer.(profile|research|identification)|prospect|lead.intelligence|property.(transaction|buyer)|UHNW.(profile|database)|residence.buyer|registered.interest",
                r"deal.(pipeline|sourcing|flow)|acquisition.target|investment.opportunit|off.market|property.(for.sale|listing)|deal.filter|cool.climate|wellness.resort",
                r"(Milan|Rome|London|Switzerland|Gulf|Kitzb|Baden.Baden|Vienna|DACH).*(market|opportunit|research|intel)",
                r"Mandarin.Oriental|MO.Vienna|MOVIE.residences|branded.residence",
            ]),
            "output_format": "Default: prose with data tables, bottom-line first. Alerts: PCS format. Buyer research: structured profiles. Market reports: executive summary plus detailed sections with methodology note. Browser Sentinel: concise digest (what changed, significance, action needed). Always state data source, date, and confidence level.",
            "autonomy_level": "proactive_flag",
            "tools": json.dumps(["web_search", "search_memory", "search_emails", "search_meetings", "get_contact", "get_matter_context", "search_deals_insights", "read_document", "get_clickup_tasks"]),
        },
        # [8/11] COMMUNICATIONS
        {
            "slug": "communications",
            "name": "Communications Capability",
            "role_description": "Communications drafting, management, and coordination capability for the Brisen Group covering six domains: (1) Email drafting and management — drafting, reviewing, and preparing emails on Director behalf, tone calibration per recipient using Profiling layer, multi-language (English, German, Russian), Director reviews and approves before send. (2) Investor communications — quarterly updates, capital call notices, performance reports, LP correspondence, institutional-grade formatting, coordinated with Balazs. (3) Proposal and pitch materials — investment proposals, partnership pitches, deal memos, McKinsey-style (logical, formatted, clean layout, ready to use), draws on Research and Profiling layers. (4) Internal team communications — instructions, briefings, project updates to Edita (COO), Rolf (MO Vienna), Siegfried (Baden-Baden), direct and action-oriented. (5) PR and external positioning — press releases, public statements, government and regulatory correspondence, coordinated with Legal. (6) Meeting preparation and follow-up — pre-meeting briefs with Fireflies integration, post-meeting summaries with action items within 24h. Key principle: all communications drafted in Director voice, Profiling layer silently shapes tone and framing, no external communication sent without Director approval. Languages: English, German, Russian.",
            "trigger_patterns": json.dumps([
                r"draft.email|write.email|reply.to|respond.to|follow.up.with|email.to|message.to|write.to|compose|send",
                r"investor.update|LP.letter|quarterly.report|capital.call|performance.report|investor.(letter|update|communication)|fund.report|NAV.update",
                r"proposal|pitch|investment.memo|deal.memo|presentation|deck|partnership.proposal|teaser|one.pager|executive.summary",
                r"team.update|instruct|brief.(Edita|Rolf|Siegfried|team)|internal.memo|standing.order|task.assignment|team.brief",
                r"press.release|public.statement|government.letter|regulatory.(response|submission)|media.(inquiry|response)|official.correspondence",
                r"meeting.(prep|brief|summary|notes|action.items)|Fireflies|follow.up.after|debrief|agenda|talking.points|minutes",
                r"translate|German|Russian|formal.tone|casual.tone|adjust.tone|rewrite|soften|make.more.direct|tone.for",
            ]),
            "output_format": "Emails: ready-to-send drafts, tone pre-calibrated via Profiling layer, Director approves before send. Proposals/pitches: McKinsey-style, logical, fully formatted, clean layout. Investor updates: formal, institutional-grade with performance tables. Internal comms: direct, concise, action-oriented. Meeting briefs: bullet format (attendees, objectives, talking points, context), one page max. All outputs: Director voice, bottom-line first, no filler.",
            "autonomy_level": "recommend_wait",
            "tools": json.dumps(["search_memory", "search_emails", "search_whatsapp", "search_meetings", "get_contact", "get_matter_context", "read_document", "web_search", "get_clickup_tasks"]),
        },
        # [9/11] PR & BRANDING
        {
            "slug": "pr_branding",
            "name": "PR & Branding",
            "role_description": "Brand strategy, reputation management, and public image capability for the Brisen Group covering six domains: (1) Brand strategy and positioning — how Brisen is positioned as luxury hospitality investment platform (not developer), brand narrative, value proposition, differentiation, supporting Strategic Plan transition to EUR 2B+ AUM by 2032. (2) Reputation management — monitoring perception of Brisen and Director, online presence, press coverage, sentiment tracking, damage control. (3) Media relations and thought leadership — industry press, speaking opportunities, conferences, article placements, positioning Director as thought leader in luxury hospitality and wellness. (4) Visual identity and brand assets — logo, design language, templates, deck aesthetics, website, brand guidelines enforcement. (5) Digital presence and content strategy — LinkedIn, website, social media, SEO, content calendar aligned with institutional credibility. (6) Investor and partner brand perception — how Brisen appears to strategic partners (TK-type, Western PE), LPs, institutional credibility, track record presentation, repositioning from operator to investment platform. Distinct from Communications: PR and Branding = strategic layer (how to be seen), Communications = execution layer (what to say).",
            "trigger_patterns": json.dumps([
                r"brand|branding|positioning|narrative|value.proposition|differentiation|identity|image|perception|brand.story",
                r"reputation|online.presence|sentiment|press.coverage|how.we.(look|appear)|damage.control|negative.mention|public.perception",
                r"media|press|journalist|conference|speaking|thought.leader|article|publication|interview|keynote|panel|industry.event",
                r"logo|design|template|visual|style.guide|brand.assets|website.design|deck.aesthetics|brand.consistency|design.language",
                r"LinkedIn|social.media|SEO|content.strategy|website.content|blog|newsletter|digital.footprint|content.calendar",
                r"credibility|institutional|how.investors.see|partner.perception|track.record|investment.platform|AUM.narrative|fund.branding",
            ]),
            "output_format": "Brand strategy: narrative documents and positioning statements with competitive analysis. Reputation monitoring: digest format (what is said, where, sentiment, significance, action needed). Media opportunities: brief recommendations (event, audience, relevance, effort, deadline). All outputs: bottom-line first, McKinsey-style where applicable.",
            "autonomy_level": "proactive_flag",
            "tools": json.dumps(["web_search", "search_memory", "search_emails", "search_meetings", "read_document", "get_contact"]),
        },
        # [10/11] MARKETING
        {
            "slug": "marketing",
            "name": "Marketing Capability",
            "role_description": "Marketing strategy, collateral production, and demand generation capability for the Brisen Group covering six domains: (1) Capability marketing — marketing Brisen track record in five-star hotel development, MO Vienna (EUR 250M, 10+ years) as flagship case study, positioning for strategic partnership conversations, demonstrating replicability (MOVIE to Baden-Baden to pipeline), supporting transition narrative from developer to EUR 2B+ AUM platform. (2) MO partnership leverage — using Mandarin Oriental brand as marketing asset, co-branding strategies, MO brand standards compliance, joint marketing through MO network, leveraging 33-47% branded residence premium. (3) Residence marketing and sales collateral — brochures, fact sheets, floor plans, virtual tours, lifestyle content for MOVIE residences and future projects (Baden-Baden, Kitzbuehel), UHNW buyer-facing materials. (4) Digital marketing and lead generation — campaigns, landing pages, UHNW outreach via luxury publications, wealth managers, family offices, brokerage networks, email funnels. (5) Event marketing — launch events, investor dinners, property viewings, roadshows. (6) Campaign analytics and ROI — spend tracking, lead attribution, conversion metrics, channel optimization. Two levels: marketing Brisen as platform to attract partners/capital, and marketing products (residences) to UHNW end-buyers. MO brand is central differentiator across both.",
            "trigger_patterns": json.dumps([
                r"Brisen.(capability|track.record|experience|portfolio)|five.star.(development|hotel)|MO.Vienna.case.study|development.capability|platform.marketing|capability.(deck|presentation|pitch)",
                r"Mandarin.Oriental.(marketing|brand|co.brand|partnership)|MO.(brand|guidelines|compliance|network)|co.brand|joint.marketing|brand.premium|branded.residence.marketing",
                r"residence.(marketing|brochure|collateral|material)|MOVIE.(marketing|sales.material)|buyer.(material|brochure|fact.sheet)|floor.plan|virtual.tour|property.(marketing|listing)|lifestyle.content",
                r"campaign|lead.generation|landing.page|UHNW.(outreach|targeting)|luxury.(publication|magazine)|wealth.manager|family.office|digital.marketing|email.(campaign|funnel)|paid.ads",
                r"launch.event|investor.dinner|property.viewing|roadshow|event.(marketing|planning|strategy)|open.house|showcase",
                r"marketing.(analytics|ROI|metrics|performance)|conversion.(rate|metrics)|lead.(source|attribution)|cost.per.lead|channel.performance|campaign.(results|report)",
            ]),
            "output_format": "Capability marketing: McKinsey-style pitch documents, case study format, data-backed. Residence collateral: premium UHNW quality, design briefs for production, content drafts. Campaign plans: structured strategy (target, channels, messaging, timeline, budget, KPIs). All outputs: bottom-line first, professional quality, MO brand compliance flagged.",
            "autonomy_level": "recommend_wait",
            "tools": json.dumps(["web_search", "search_memory", "search_emails", "read_document", "get_contact", "get_clickup_tasks", "search_meetings"]),
        },
        # [11/11] AI DEV
        {
            "slug": "ai_dev",
            "name": "AI Development Capability",
            "role_description": "AI strategy, development, and operations capability spanning two dimensions: (a) Brisen AI strategy including Project clAIm — acquiring vertical AI startups in construction/hospitality claims, and (b) Baker own development and maintenance. Six domains: (1) AI strategy and Project clAIm — strategic pivot into AI, three workstreams (WS1: EUR 10.5M claim POC targeting EUR 5-8M recovery at EUR 200K budget, WS2: data cleaning/tagging/AI licensing with 240K document data moat, WS3: EUR 12-15M acquisition pipeline targeting EUR 100M Year 3 exit), competitive landscape (ClaimFlow primary target, DisputeSoft Year 2, Docugami add-on), leveraging 240K document data moat as 20-50x advantage. (2) Baker system development — Code 300 codebase, Render deployment, PostgreSQL, scan/act/briefing loops. (3) Capability framework management — capability specs, capability_sets DB, trigger patterns, autonomy levels. (4) Tool and integration development — Browser Sentinel, MCP servers, API integrations. (5) Automation and workflow design — scheduled tasks, briefing pipeline, standing orders. (6) Performance monitoring and prompt engineering — quality tracking, error logging, system prompts, skill optimization. Mission: Development was our past. Hospitality is our present. AI is our future.",
            "trigger_patterns": json.dumps([
                r"Project.clAIm|clAIm|vertical.AI|AI.(acquisition|startup|strategy)|construction.(claims|AI)|data.moat|SymTerra|ClaimFlow|DisputeSoft|Docugami|nPlan|ALICE.Tech|AI.(holding|platform)|POC|proof.of.concept|claim.(generation|automation|recovery)|240K.documents",
                r"Baker|Code.300|codebase|architecture|deployment|Render|server|API|database|PostgreSQL|schema|migration",
                r"capability.spec|capability_sets|trigger.pattern|autonomy.level|new.capability|update.capability|slug|role_description",
                r"integration|MCP|Browser.Sentinel|Gmail.API|Calendar.API|ClickUp.API|Fireflies.API|WhatsApp.webhook|Slack.integration|tool.(onboarding|setup|connection)|API.(key|credential|token)",
                r"automation|workflow|scheduled.task|cron|morning.briefing|briefing.pipeline|standing.order|RSS.(ingestion|pipeline)|scan.loop|act.loop",
                r"performance|error|bug|latency|missed.trigger|prompt|system.prompt|skill.file|output.quality|monitoring|logging|self.improvement",
            ]),
            "output_format": "AI strategy: McKinsey-style, data-backed, acquisition analysis with comparison tables, DD checklists, financial projections. Technical specs: architecture with diagrams, API definitions, DB schema SQL. Code: Python, JavaScript, SQL — clean, commented, production-ready. Status/bug reports: concise, problem to root cause to fix to impact.",
            "autonomy_level": "recommend_wait",
            "tools": json.dumps(["search_memory", "search_emails", "search_meetings", "get_clickup_tasks", "get_matter_context", "web_search", "read_document"]),
        },
    ]

    for cap in updates:
        slug = cap.pop("slug")
        set_clauses = []
        values = []
        for col, val in cap.items():
            set_clauses.append(f"{col} = %s")
            values.append(val)
        set_clauses.append("updated_at = NOW()")
        values.append(slug)

        sql = f"UPDATE capability_sets SET {', '.join(set_clauses)} WHERE slug = %s"
        cur.execute(sql, values)
        rows = cur.rowcount
        status = "UPDATED" if rows > 0 else "NOT FOUND"
        print(f"  [{status}] {slug}")

    # ─────────────────────────────────────────────
    # Step 5: Update decomposer with new slug list
    # ─────────────────────────────────────────────
    new_slug_list = "sales, finance, legal, asset_management, profiling, research, communications, pr_branding, marketing, ai_dev"
    cur.execute("""
        UPDATE capability_sets
        SET system_prompt = REPLACE(
            system_prompt,
            'sales, finance, legal, asset_mgmt, research, comms, it, ib, marketing, ai_dev',
            %s
        ),
        updated_at = NOW()
        WHERE slug = 'decomposer'
    """, (new_slug_list,))
    print(f"  Updated decomposer system_prompt with new slugs")

    # ─────────────────────────────────────────────
    # Step 6: Verify
    # ─────────────────────────────────────────────
    cur.execute("SELECT slug, name, autonomy_level, active FROM capability_sets ORDER BY capability_type, slug")
    print(f"\n=== Final State ({cur.rowcount} capabilities) ===")
    for row in cur.fetchall():
        active = "ACTIVE" if row["active"] else "INACTIVE"
        print(f"  {row['slug']:20s} {row['autonomy_level']:18s} {active}")

    conn.commit()
    cur.close()
    conn.close()
    print("\nDone. All 11 capabilities updated.")


if __name__ == "__main__":
    run()
