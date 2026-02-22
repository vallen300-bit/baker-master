/* ============================================================
   Baker CEO Dashboard v2.2 — app.js
   3-layer role-based navigation with live Baker API connections
   ============================================================ */

// ═══ API CONFIG ═══
const BAKER_CONFIG = {
    apiKey: '076f4eccf86fe5e30f0a82ff17969afa08f3b151d1e1931154dc0936d49a9d82',
};

async function bakerFetch(url, options = {}) {
    const headers = {
        ...(options.headers || {}),
        'X-Baker-Key': BAKER_CONFIG.apiKey,
    };
    return fetch(url, { ...options, headers });
}

// ═══ LENS ICONS (placeholder — simple colored circles) ═══
const lensIcons = {
    clear: '/static/baker-face-green.svg',
    attentive: 'data:image/svg+xml,' + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22"><circle cx="11" cy="11" r="9" fill="%23f0b429" opacity="0.8"/></svg>'),
    alert: 'data:image/svg+xml,' + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22"><circle cx="11" cy="11" r="9" fill="%23f56565" opacity="0.8"/></svg>')
};

// ═══ ROLE METADATA ═══
const roleDescs = {
    private: 'Personal wealth, property, family & legal',
    chairman: 'Brisen Group governance & strategy',
    pm: 'Active project portfolio management',
    network: 'Key contacts, advisors & pipeline',
    travel: 'Business & personal travel logistics'
};

const roleNames = {
    private: 'Private',
    chairman: 'Chairman',
    pm: 'Projects',
    network: 'Network',
    travel: 'Travel'
};

// ═══ ROLE DATA (hierarchical) ═══
const roleData = {
    private: {
        title: 'Private',
        categories: [
            { id: 'wealth', icon: '', title: 'Wealth & Banking', badge: 'stable', badgeType: 'ok', colorClass: 'wealth',
              items: [
                { label: 'accounts', text: 'UBS, Raiffeisen, UniCredit — all accounts active, no flags.' },
                { label: 'structure', text: 'Swiss structure review — ongoing with tax advisor. ETA March 2026.' },
              ]
            },
            { id: 'property', icon: '', title: 'Property', badge: '3 assets', badgeType: 'ok', colorClass: 'property',
              items: [
                { label: 'Vienna', text: 'Primary residence — no outstanding items.' },
                { label: 'Cap Ferrat', text: 'MO Villa management — operations stable.' },
                { label: 'Baden', text: 'Balgerstrasse 7 — loan terms current.' },
              ]
            },
            { id: 'family', icon: '', title: 'Family', badge: 'ok', badgeType: 'ok', colorClass: 'family',
              items: [
                { label: 'status', text: 'No pending family-related items or obligations.' },
              ]
            },
            { id: 'subscriptions', icon: '', title: 'Subscriptions & Memberships', badge: 'active', badgeType: 'ok', colorClass: 'subscriptions',
              items: [
                { label: 'clubs', text: 'All memberships current. No renewals due within 60 days.' },
                { label: 'digital', text: 'Software and digital subscriptions — reviewed.' },
              ]
            },
            { id: 'legal-private', icon: '', title: 'Legal (Private)', badge: 'clear', badgeType: 'ok', colorClass: 'legal',
              items: [
                { label: 'status', text: 'No active private legal matters.' },
              ]
            }
        ]
    },
    chairman: {
        title: 'Chairman',
        categories: [
            { id: 'group-overview', icon: '', title: 'Group Overview', badge: 'stable', badgeType: 'ok', colorClass: 'group',
              items: [
                { label: 'entities', text: 'Brisen Group — all entities operational. No compliance flags.' },
                { label: 'KPIs', text: 'Quarterly KPIs on track. Next board review Q2 2026.' },
              ]
            },
            { id: 'board', icon: '', title: 'Board & Governance', badge: '2 items', badgeType: 'neutral', colorClass: 'board',
              items: [
                { label: 'next meeting', text: 'Board meeting — scheduled for March 2026.' },
                { label: 'minutes', text: 'Last meeting minutes filed and approved.' },
              ]
            },
            { id: 'group-finance', icon: '', title: 'Group Finance', badge: 'on track', badgeType: 'ok', colorClass: 'finance',
              items: [
                { label: 'cashflow', text: 'Group cash position healthy. No liquidity concerns.' },
                { label: 'audit', text: 'FY2025 annual accounts — preparation ongoing.' },
              ]
            },
            { id: 'legal-compliance', icon: '', title: 'Legal & Compliance', badge: 'clear', badgeType: 'ok', colorClass: 'legal',
              items: [
                { label: 'status', text: 'All regulatory filings current. No outstanding compliance items.' },
              ]
            },
            { id: 'key-people', icon: '', title: 'Key People', badge: 'stable', badgeType: 'ok', colorClass: 'people',
              items: [
                { label: 'team', text: 'Core team stable. No personnel changes pending.' },
              ]
            },
            { id: 'brisen2030', icon: '', title: 'Brisen 2030', badge: '6 tracks', badgeType: 'warn', colorClass: 'brisen2030',
              items: [
                { label: 'strategy', text: 'Long-term vision — 6 strategic tracks being developed.' },
                { label: 'status', text: 'Deck shared with key stakeholders. Feedback cycle ongoing.' },
              ],
              subIssues: [
                { id: 'b30-vision', icon: '', title: 'Vision & Mission', colorClass: 'brisen2030', items: [
                    { label: 'status', text: 'Mission statement finalized. Vision document v3 under review.' }
                ]},
                { id: 'b30-portfolio', icon: '', title: 'Portfolio Strategy', colorClass: 'brisen2030', items: [
                    { label: 'status', text: 'Asset allocation targets set. RE-heavy portfolio with AI diversification.' }
                ]},
                { id: 'b30-capital', icon: '', title: 'Capital Structure', colorClass: 'brisen2030', items: [
                    { label: 'status', text: 'Optimal leverage ratios defined. Implementation roadmap drafted.' }
                ]},
                { id: 'b30-talent', icon: '', title: 'Talent & Organization', colorClass: 'brisen2030', items: [
                    { label: 'status', text: 'Key hires identified for 2026. Organizational chart proposed.' }
                ]},
                { id: 'b30-digital', icon: '', title: 'Digital & AI', colorClass: 'brisen2030', items: [
                    { label: 'status', text: 'Baker AI operational. Next: integrate with deal pipeline.' }
                ]},
                { id: 'b30-impact', icon: '', title: 'Impact & ESG', colorClass: 'brisen2030', items: [
                    { label: 'status', text: 'ESG framework drafted. Sustainability metrics defined.' }
                ]}
              ]
            }
        ]
    },
    pm: {
        title: 'Projects',
        categories: [
            { id: 'hagenauer', icon: '', title: 'Hagenauer', badge: '8 tracks', badgeType: 'warn', colorClass: 'hagenauer',
              items: [
                { label: 'insolvency', text: 'Dr. Gaspar / S&K managing insolvency proceedings. Weekly updates.' },
                { label: 'construction', text: 'Construction progress tracked. Thomas Leitner as project lead.' },
              ],
              subIssues: [
                { id: 'hg-insolvency', icon: '', title: 'Insolvency Proceedings', colorClass: 'hagenauer', items: [
                    { label: 'status', text: 'S&K managing. Court dates and filings on track.' }
                ]},
                { id: 'hg-construction', icon: '', title: 'Construction Progress', colorClass: 'hagenauer', items: [
                    { label: 'status', text: 'Phase 2 underway. Thomas Leitner leading on-site coordination.' }
                ]},
                { id: 'hg-finance', icon: '', title: 'Project Finance', colorClass: 'hagenauer', items: [
                    { label: 'status', text: 'Budget tracking within parameters. No overruns flagged.' }
                ]},
                { id: 'hg-permits', icon: '', title: 'Permits & Approvals', colorClass: 'hagenauer', items: [
                    { label: 'status', text: 'All current permits valid. Next renewal Q3 2026.' }
                ]},
                { id: 'hg-sales', icon: '', title: 'Sales Strategy', colorClass: 'hagenauer', items: [
                    { label: 'status', text: 'Sales strategy defined. Initial buyer interest tracked.' }
                ]},
                { id: 'hg-legal', icon: '', title: 'Legal Issues', colorClass: 'hagenauer', items: [
                    { label: 'status', text: 'Active legal matters with Siegfried Gröschl oversight.' }
                ]},
                { id: 'hg-investors', icon: '', title: 'Investor Relations', colorClass: 'hagenauer', items: [
                    { label: 'status', text: 'Investor updates distributed monthly. No concerns raised.' }
                ]},
                { id: 'hg-timeline', icon: '', title: 'Master Timeline', colorClass: 'hagenauer', items: [
                    { label: 'status', text: 'Project timeline on schedule. Key milestones tracked.' }
                ]}
              ]
            },
            { id: 'moviesales', icon: '', title: 'Movie Sales', badge: '4 items', badgeType: 'ok', colorClass: 'moviesales',
              items: [
                { label: 'pipeline', text: 'Active sales pipeline — 4 properties in various stages.' },
              ],
              subIssues: [
                { id: 'ms-active', icon: '', title: 'Active Listings', colorClass: 'moviesales', items: [
                    { label: 'status', text: 'Current listings performing within expectations.' }
                ]},
                { id: 'ms-pipeline', icon: '', title: 'Sales Pipeline', colorClass: 'moviesales', items: [
                    { label: 'status', text: 'Pipeline healthy. Multiple inquiries in progress.' }
                ]},
                { id: 'ms-legal', icon: '', title: 'Contracts & Legal', colorClass: 'moviesales', items: [
                    { label: 'status', text: 'Standard contracts in use. No legal disputes.' }
                ]},
                { id: 'ms-marketing', icon: '', title: 'Marketing', colorClass: 'moviesales', items: [
                    { label: 'status', text: 'Marketing materials updated. Online presence active.' }
                ]}
              ]
            },
            { id: 'ao', icon: '', title: 'AO', badge: '7 items', badgeType: 'warn', colorClass: 'ao',
              items: [
                { label: 'operations', text: 'AO operations — multiple workstreams active in Baden-Baden.' },
              ],
              subIssues: [
                { id: 'ao-ops', icon: '', title: 'Operations', colorClass: 'ao', items: [
                    { label: 'status', text: 'Daily operations running smoothly.' }
                ]},
                { id: 'ao-finance', icon: '', title: 'Finance', colorClass: 'ao', items: [
                    { label: 'status', text: 'Financial tracking current. No budget concerns.' }
                ]},
                { id: 'ao-hr', icon: '', title: 'HR & Team', colorClass: 'ao', items: [
                    { label: 'status', text: 'Team stable. No open positions.' }
                ]},
                { id: 'ao-legal', icon: '', title: 'Legal', colorClass: 'ao', items: [
                    { label: 'status', text: 'No active legal matters.' }
                ]},
                { id: 'ao-it', icon: '', title: 'IT Systems', colorClass: 'ao', items: [
                    { label: 'status', text: 'Systems operational. O365 migration in progress.' }
                ]},
                { id: 'ao-reporting', icon: '', title: 'Reporting', colorClass: 'ao', items: [
                    { label: 'status', text: 'Monthly reports on schedule.' }
                ]},
                { id: 'ao-strategy', icon: '', title: 'Strategy', colorClass: 'ao', items: [
                    { label: 'status', text: 'Strategic review planned for Q2 2026.' }
                ]}
              ]
            },
            { id: 'annaberg', icon: '', title: 'Annaberg', badge: '5 items', badgeType: 'ok', colorClass: 'annaberg',
              items: [
                { label: 'project', text: 'Annaberg project — construction and planning on track.' },
              ],
              subIssues: [
                { id: 'ab-master', icon: '', title: 'Master Plan', colorClass: 'annaberg', items: [
                    { label: 'status', text: 'Master plan finalized. Implementation underway.' }
                ]},
                { id: 'ab-construction', icon: '', title: 'Construction', colorClass: 'annaberg', items: [
                    { label: 'status', text: 'Construction progress on schedule.' }
                ]},
                { id: 'ab-budget', icon: '', title: 'Project Budget', colorClass: 'annaberg', items: [
                    { label: 'status', text: 'Overall project budget — tracking within parameters.' }
                ]},
                { id: 'ab-baden', icon: '', title: 'Baden Baden / Aukera', colorClass: 'annaberg', items: [
                    { label: 'status', text: 'Aukera teaser sent to Antje Bonnewitz for Baden Baden.' }
                ]},
                { id: 'ab-lilienmatt', icon: '', title: 'Lilienmatt Company', colorClass: 'annaberg', items: [
                    { label: 'status', text: 'Lilienmatt Immobilien GmbH — company active, Conrad Weiss managing.' }
                ]}
              ]
            },
            { id: 'mrci', icon: '', title: 'MRCI Baden', badge: '8 items', badgeType: 'warn', colorClass: 'mrci',
              items: [
                { label: 'restructuring', text: 'MRCI & Lilienmatt restructuring — options table drafted.' },
                { label: 'tax', text: 'Steuerbescheide 2022 received. Financial statements in progress.' },
              ],
              subIssues: [
                { id: 'mr-restructure', icon: '', title: 'Restructuring', colorClass: 'mrci', items: [
                    { label: 'status', text: 'Restructuring options — table of options (Draft 1) prepared.' }
                ]},
                { id: 'mr-gmbh', icon: '', title: 'MRCI GmbH', colorClass: 'mrci', items: [
                    { label: 'status', text: 'Christian Merz meeting scheduled in Baden-Baden (07/2026).' }
                ]},
                { id: 'mr-lilienmatt', icon: '', title: 'Lilienmatt Immobilien', colorClass: 'mrci', items: [
                    { label: 'status', text: 'Conrad Weiss managing. Operations stable.' }
                ]},
                { id: 'mr-tax', icon: '', title: 'Tax Assessments', colorClass: 'mrci', items: [
                    { label: 'status', text: 'Steuerbescheide 2022 — received, review in progress.' }
                ]},
                { id: 'mr-fin', icon: '', title: 'Financial Statements', colorClass: 'mrci', items: [
                    { label: 'status', text: 'Statement drafts — preparation ongoing.' }
                ]},
                { id: 'mr-cashflow', icon: '', title: 'Cash Flow', colorClass: 'mrci', items: [
                    { label: 'status', text: 'Internal transfers — MRCI/Lilienmatt cash flows tracked.' }
                ]},
                { id: 'mr-loan', icon: '', title: 'Balgerstrasse 7 Loan', colorClass: 'mrci', items: [
                    { label: 'status', text: 'Property loan terms current.' }
                ]},
                { id: 'mr-o365', icon: '', title: 'O365 Migration', colorClass: 'mrci', items: [
                    { label: 'status', text: 'Dennis managing migration spreadsheet.' }
                ]}
              ]
            },
            { id: 'capferrat', icon: '', title: 'Cap Ferrat', badge: '5 items', badgeType: 'ok', colorClass: 'capferrat',
              items: [
                { label: 'villa', text: 'MO Villa management — operations stable.' },
              ],
              subIssues: [
                { id: 'cf-villa', icon: '', title: 'MO Villa', colorClass: 'capferrat', items: [
                    { label: 'status', text: 'Villa management — MOHG operating, performance on track.' }
                ]},
                { id: 'cf-upgrade', icon: '', title: 'Second Villa Upgrade', colorClass: 'capferrat', items: [
                    { label: 'status', text: 'Planning phase for second property upgrade.' }
                ]},
                { id: 'cf-tax', icon: '', title: 'SUNNY IMMO Tax', colorClass: 'capferrat', items: [
                    { label: 'status', text: 'Tax debts — SUNNY IMMO liabilities being resolved.' }
                ]},
                { id: 'cf-annabelle', icon: '', title: 'Annabelle Discussion', colorClass: 'capferrat', items: [
                    { label: 'status', text: 'Discussion ongoing regarding property.' }
                ]},
                { id: 'cf-party', icon: '', title: 'Opening Party', colorClass: 'capferrat', items: [
                    { label: 'status', text: 'Opening event — planning in progress.' }
                ]}
              ]
            },
            { id: 'originations', icon: '', title: 'Originations', badge: '9 tracks', badgeType: 'ok', colorClass: 'originations',
              items: [
                { label: 'pipeline', text: '9 active origination tracks across RE, AI, and brands.' },
                { label: 'highlight', text: 'FX Mayr brand investment most advanced.' },
              ],
              subIssues: [
                { id: 'or-fund', icon: '', title: 'RE Fund Management', colorClass: 'originations', items: [
                    { label: 'status', text: 'Ski Team Investors pitch and Fund Pitch materials prepared.' }
                ]},
                { id: 'or-fxmayr', icon: '', title: 'Brand: FX Mayr', colorClass: 'originations', items: [
                    { label: 'NDA', text: 'Henrik Huydts NDA signed for Stuttgart meeting.' },
                    { label: 'progress', text: 'Teaser sent, Stuttgart meeting completed, Maria Worth follow-up done.' }
                ]},
                { id: 'or-cashprod', icon: '', title: 'RE Cash Producing', colorClass: 'originations', items: [
                    { label: '6 Senses', text: '6 Senses Crans Montana — tracked.' },
                    { label: 'Hyatt', text: 'Hyatt Vienna — Eastdil presentations reviewed.' },
                    { label: 'MO Prague', text: 'MO Prague — CITIC docs reviewed.' }
                ]},
                { id: 'or-dev', icon: '', title: 'RE Development', colorClass: 'originations', items: [
                    { label: 'active', text: '5 dev opportunities: Bora Bora, Kitzbühel, Palais Corso, School, Venti.' }
                ]},
                { id: 'or-ai', icon: '', title: 'AI Investments', colorClass: 'originations', items: [
                    { label: 'construction', text: 'clAIm — AI construction technology tracked.' },
                    { label: 'hospitality', text: 'Hospitality R&D — AI applications in hospitality sector.' }
                ]}
              ]
            },
            { id: 'cupial', icon: '', title: 'Cupial', badge: '6 items', badgeType: 'warn', colorClass: 'cupial',
              items: [
                { label: 'handover', text: 'Open handover items tracked with Pagitsch.' },
                { label: 'legal', text: 'URGENT — legal matters requiring immediate attention.' },
              ],
              subIssues: [
                { id: 'cu-handover', icon: '', title: 'Handover Issues', colorClass: 'cupial', items: [
                    { label: 'status', text: 'Open handover items — punch list being resolved.' }
                ]},
                { id: 'cu-escrow', icon: '', title: 'Escrow Release', colorClass: 'cupial', items: [
                    { label: 'status', text: 'Escrow funds — release conditions being verified.' }
                ]},
                { id: 'cu-pagitsch', icon: '', title: 'Pagitsch Reconciliation', colorClass: 'cupial', items: [
                    { label: 'status', text: 'Cost reconciliation — Pagitsch review in progress.' }
                ]},
                { id: 'cu-special', icon: '', title: 'Special Requests', colorClass: 'cupial', items: [
                    { label: 'status', text: 'Additional works and modifications tracked.' }
                ]},
                { id: 'cu-legal', icon: '', title: 'Legal (URGENT)', colorClass: 'cupial', items: [
                    { label: 'status', text: 'URGENT legal matter — requires immediate attention.' }
                ]},
                { id: 'cu-ipd', icon: '', title: 'IPD Q4 Interest', colorClass: 'cupial', items: [
                    { label: 'status', text: 'Q4 interest payment — IPD obligation tracked.' }
                ]}
              ]
            }
        ]
    },
    network: {
        title: 'Network',
        categories: [
            { id: 'keycontacts', icon: '', title: 'Key Contacts', badge: 'active', badgeType: 'ok', colorClass: 'keycontacts',
              subIssues: [
                { id: 'investors', icon: '', title: 'Investors & Partners', colorClass: 'keycontacts', items: [
                    { label: 'active', text: 'John (UBS) — quarterly review scheduled.' },
                    { label: 'pending', text: 'Christophe Buchwalder — awaiting response on Brisen 2030 deck.' }
                ]},
                { id: 'board-net', icon: '', title: 'Board & Directors', colorClass: 'keycontacts', items: [
                    { label: 'contact', text: 'Siegfried Gröschl — active on Hagenauer and Cupial.' },
                    { label: 'contact', text: 'Rolf Hubner — advisory role, low-touch.' }
                ]},
                { id: 'family-net', icon: '', title: 'Family & Personal', colorClass: 'keycontacts', items: [
                    { label: 'contact', text: 'Vladimir & Mykola — operational team, daily contact.' },
                    { label: 'contact', text: 'Thomas Leitner — Hagenauer project lead.' }
                ]}
              ]
            },
            { id: 'advisors', icon: '', title: 'Advisors & Consultants', badge: '4 active', badgeType: 'neutral', colorClass: 'advisors',
              items: [
                { label: 'legal', text: 'Dr. Gaspar / S&K — insolvency proceedings. Weekly updates.' },
                { label: 'tax', text: 'Tax advisor (CH) — Swiss structure review. ETA March 2026.' },
                { label: 'financial', text: 'Auditor — FY2025 annual accounts in preparation.' },
              ]
            },
            { id: 'serviceproviders', icon: '', title: 'Service Providers', badge: 'stable', badgeType: 'ok', colorClass: 'serviceproviders',
              items: [
                { label: 'IT', text: 'IT / O365 — managed by Vladimir. Systems running normally.' },
                { label: 'banking', text: 'UBS / Raiffeisen / UniCredit — all account relationships active.' },
                { label: 'insurance', text: 'Insurance broker — policies current through 2026.' },
              ]
            },
            { id: 'pipeline-contacts', icon: '', title: 'Pipeline Contacts', badge: '5 warm', badgeType: 'warn', colorClass: 'pipeline',
              items: [
                { label: 'warm leads', text: '5 active pipeline contacts from originations deal flow.' },
                { label: 'follow-ups', text: '3 email follow-ups and 2 WhatsApp messages pending.' },
              ]
            }
        ]
    },
    travel: {
        title: 'Travel',
        categories: [
            { id: 'business-travel', icon: '', title: 'Business Travel', badge: 'no trips', badgeType: 'neutral', colorClass: 'travel',
              items: [
                { label: 'recent', text: 'Baden-Baden — completed 16-18 Feb (AO tasks).' },
                { label: 'upcoming', text: 'No upcoming business travel currently booked.' },
              ]
            },
            { id: 'personal-travel', icon: '', title: 'Personal Travel', badge: 'no trips', badgeType: 'neutral', colorClass: 'travel',
              items: [
                { label: 'upcoming', text: 'No upcoming personal travel currently booked.' },
              ]
            },
            { id: 'docs-visas', icon: '', title: 'Documents & Visas', badge: 'all clear', badgeType: 'ok', colorClass: 'travel',
              items: [
                { label: 'passports', text: 'All passports valid. No renewals due within 6 months.' },
                { label: 'visas', text: 'No pending visa applications.' },
              ]
            },
            { id: 'logistics', icon: '', title: 'Logistics & Preferences', badge: 'stable', badgeType: 'ok', colorClass: 'travel',
              items: [
                { label: 'airlines', text: 'Preferred: Swiss/Lufthansa. Miles accounts active.' },
                { label: 'hotels', text: 'No active reservations.' },
              ]
            }
        ]
    }
};

// ═══ STATE ═══
let currentRole = null;
let currentCatIndex = null;
let currentSubIndex = null;
let currentView = 'home';
let lensIndex = 0;
let takeVisible = false;

// Scan chat state
let scanHistory = [];
let scanStreaming = false;

// ═══ HELPERS ═══

function esc(str) {
    if (!str) return '';
    const d = document.createElement('div');
    d.textContent = str;
    return d.innerHTML;
}

function md(text) {
    if (!text) return '';
    let h = esc(text);
    h = h.replace(/^### (.+)$/gm, '<h3>$1</h3>');
    h = h.replace(/^## (.+)$/gm, '<h2>$1</h2>');
    h = h.replace(/^# (.+)$/gm, '<h1>$1</h1>');
    h = h.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    h = h.replace(/\*(.+?)\*/g, '<em>$1</em>');
    h = h.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
    h = h.replace(/^- (.+)$/gm, '<li>$1</li>');
    h = h.replace(/(<li>.*<\/li>\n?)+/g, '<ul>$&</ul>');
    h = h.replace(/\n/g, '<br>');
    return h;
}

function fmtDate(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
        + ' ' + d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
}

// ═══ INIT ═══
function init() {
    const now = new Date();

    // Greeting
    const hour = now.getHours();
    const greet = hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening';
    const dateStr = now.toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
    const greetEl = document.getElementById('homeGreeting');
    if (greetEl) greetEl.textContent = greet + ', Dimitry \u2014 ' + dateStr;

    // Last scan time
    updateScanTime();

    // Set initial lens
    const lensKeys = Object.keys(lensIcons);
    if (lensKeys.length > 0) {
        document.getElementById('lensImg').src = lensIcons[lensKeys[0]];
    }

    // Populate home sections
    populateHome();

    // Wire scan form
    const scanForm = document.getElementById('scanForm');
    if (scanForm) {
        scanForm.addEventListener('submit', (e) => {
            e.preventDefault();
            const input = document.getElementById('scanInput');
            if (input && input.value.trim()) {
                sendScanMessage(input.value.trim());
                input.value = '';
            }
        });
    }

    // Fetch system status
    fetchSystemStatus();
}

function updateScanTime() {
    const scanEl = document.getElementById('scanTime');
    if (scanEl) {
        const now = new Date();
        const hh = String(now.getHours()).padStart(2, '0');
        const mm = String(now.getMinutes()).padStart(2, '0');
        scanEl.textContent = 'last scan ' + hh + ':' + mm;
    }
}

// ═══ SYSTEM STATUS ═══
async function fetchSystemStatus() {
    try {
        const resp = await bakerFetch('/api/status');
        if (!resp.ok) throw new Error('Status ' + resp.status);
        const status = await resp.json();

        const dot = document.getElementById('scanDot');
        if (status.system === 'operational') {
            dot.style.background = '#34d058';
            dot.style.boxShadow = '0 0 10px rgba(52,208,88,0.5)';
        } else {
            dot.style.background = '#f56565';
            dot.style.boxShadow = '0 0 10px rgba(245,101,101,0.5)';
        }
    } catch (e) {
        console.warn('Status fetch failed:', e.message);
    }
}

// ═══ HOME POPULATION ═══
function populateHome() {
    const agendaList = document.getElementById('agendaList');
    const pendingList = document.getElementById('pendingList');

    // Agenda items (will be populated from API later; static for now)
    if (agendaList) {
        agendaList.innerHTML = '<div class="agenda-empty">No scheduled items for today.</div>';
    }

    // Pending items from API
    if (pendingList) {
        fetchPendingItems(pendingList);
    }
}

async function fetchPendingItems(container) {
    try {
        const resp = await bakerFetch('/api/alerts?tier=1');
        if (!resp.ok) throw new Error('API ' + resp.status);
        const data = await resp.json();
        const alerts = (data && data.alerts) ? data.alerts : [];

        if (alerts.length === 0) {
            container.innerHTML = '<div class="agenda-empty">No pending items. All clear.</div>';
            return;
        }

        let html = '';
        for (const a of alerts.slice(0, 5)) {
            html += `<div class="agenda-item">
                <span class="agenda-time" style="color:#ef4444;">T${a.tier || 1}</span>
                <span class="agenda-type task">alert</span>
                <span class="agenda-desc">${esc(a.title)}</span>
            </div>`;
        }
        container.innerHTML = html;
    } catch (e) {
        container.innerHTML = '<div class="agenda-empty">No pending items. All clear.</div>';
    }
}

// ═══ VIEW SWITCHING ═══
function showView(id) {
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    document.getElementById(id).classList.add('active');
    currentView = id;
}

function setRail(role) {
    document.querySelectorAll('.rail-btn').forEach(b => {
        b.classList.toggle('active', b.dataset.role === (role || 'home'));
    });
}

// ═══ HOME ═══
function goHome() {
    currentRole = null;
    currentCatIndex = null;
    currentSubIndex = null;
    setRail(null);
    showView('homeView');
    document.getElementById('takeBar').classList.remove('visible');
    closeTake();
}

// ═══ OPEN ROLE (Layer 2) ═══
function openRole(role) {
    currentRole = role;
    currentCatIndex = null;
    currentSubIndex = null;
    setRail(role);

    const data = roleData[role];
    if (!data) return;

    // Hero
    document.getElementById('catHeroIcon').textContent = data.icon || '';
    document.getElementById('catHeroTitle').textContent = data.title || roleNames[role];
    document.getElementById('catHeroDesc').textContent = data.subtitle || roleDescs[role];

    // Build category cards
    const grid = document.getElementById('catGrid');
    grid.innerHTML = '';

    const cats = data.categories || [];
    cats.forEach((cat, idx) => {
        const card = document.createElement('div');
        card.className = 'cat-card';
        card.dataset.role = role;
        card.style.animationDelay = (idx * 0.06) + 's';

        const countLabel = cat.subIssues
            ? cat.subIssues.length + ' sub-items'
            : (cat.items ? cat.items.length + ' items' : '');

        const actionLabel = cat.subIssues ? 'Review' : 'View';

        card.innerHTML =
            '<div class="cc-icon">' + (cat.icon || '') + '</div>' +
            '<div class="cc-title">' + cat.title + '</div>' +
            '<div class="cc-count">' + countLabel + '</div>' +
            '<span class="cc-action">' + actionLabel + '</span>';

        card.onclick = () => openCategory(role, idx);
        grid.appendChild(card);
    });

    showView('catView');

    // Show Baker's Scan bar
    document.getElementById('takeBar').classList.add('visible');
    document.getElementById('takeLabel').textContent = roleNames[role];
}

// ═══ OPEN CATEGORY (Layer 3) ═══
function openCategory(role, catIndex) {
    currentCatIndex = catIndex;
    currentSubIndex = null;
    const data = roleData[role];
    const cat = data.categories[catIndex];

    // Back button
    document.getElementById('detailBack').onclick = () => openRole(role);

    // Title & breadcrumb
    document.getElementById('detailTitle').textContent = cat.title;
    document.getElementById('detailBreadcrumb').textContent = roleNames[role] + ' \u2192 ' + cat.title;

    // Sub-tabs
    const tabsEl = document.getElementById('subTabs');
    tabsEl.innerHTML = '';

    if (cat.subIssues && cat.subIssues.length > 0) {
        cat.subIssues.forEach((sub, subIdx) => {
            const tab = document.createElement('button');
            tab.className = 'sub-tab' + (subIdx === 0 ? ' active' : '');
            tab.textContent = sub.title;
            tab.onclick = () => selectSub(role, catIndex, subIdx);
            tabsEl.appendChild(tab);
        });
        renderItems(cat.subIssues[0].items, role);
        currentSubIndex = 0;
    } else {
        renderItems(cat.items, role);
    }

    showView('detailView');
    document.getElementById('takeLabel').textContent = roleNames[role] + ' \u2192 ' + cat.title;
}

function selectSub(role, catIndex, subIndex) {
    currentSubIndex = subIndex;
    const cat = roleData[role].categories[catIndex];
    const sub = cat.subIssues[subIndex];

    document.querySelectorAll('.sub-tab').forEach((t, i) => t.classList.toggle('active', i === subIndex));
    renderItems(sub.items, role);
    document.getElementById('takeLabel').textContent = roleNames[role] + ' \u2192 ' + cat.title + ' \u2192 ' + sub.title;
}

function renderItems(items, role) {
    const container = document.getElementById('detailCards');
    container.innerHTML = '';
    if (!items || items.length === 0) {
        container.innerHTML = '<div style="padding:20px;color:rgba(0,0,0,0.3);font-size:13px;">No items yet.</div>';
        return;
    }
    items.forEach((item, i) => {
        const card = document.createElement('div');
        card.className = 'd-card';
        card.dataset.role = role;
        card.style.animationDelay = (i * 0.05) + 's';
        card.innerHTML =
            '<div class="d-label">' + item.label + '</div>' +
            '<div class="d-text">' + item.text + '</div>';
        container.appendChild(card);
    });
}

// ═══ BAKER'S SCAN (live SSE) ═══
function showTake() {
    const overlay = document.getElementById('takeOverlay');
    overlay.classList.add('visible');
    takeVisible = true;

    // Render existing messages
    const container = document.getElementById('scanMessages');
    if (container && container.children.length === 0 && scanHistory.length > 0) {
        for (const msg of scanHistory) {
            appendScanBubble(msg.role, msg.content);
        }
    }

    // Focus input
    const input = document.getElementById('scanInput');
    if (input) input.focus();
}

function closeTake() {
    document.getElementById('takeOverlay').classList.remove('visible');
    takeVisible = false;
}

function appendScanBubble(role, content, id) {
    const container = document.getElementById('scanMessages');
    if (!container) return;
    const div = document.createElement('div');
    div.className = 'scan-bubble scan-bubble-' + role;
    if (id) div.id = id;
    div.innerHTML = role === 'assistant' ? md(content) : esc(content);
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
    return div;
}

async function sendScanMessage(question) {
    if (scanStreaming || !question.trim()) return;
    scanStreaming = true;

    const sendBtn = document.getElementById('scanSendBtn');
    const input = document.getElementById('scanInput');
    if (sendBtn) sendBtn.disabled = true;
    if (input) input.disabled = true;

    // Add user bubble
    scanHistory.push({ role: 'user', content: question });
    appendScanBubble('user', question);

    // Add assistant placeholder
    const assistantId = 'scan-reply-' + Date.now();
    appendScanBubble('assistant', '', assistantId);
    const replyEl = document.getElementById(assistantId);

    let fullResponse = '';
    try {
        const resp = await bakerFetch('/api/scan', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                question: question,
                history: scanHistory.slice(-10),
            }),
        });

        if (!resp.ok) throw new Error('Scan API returned ' + resp.status);

        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop();

            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                const payload = line.slice(6).trim();
                if (payload === '[DONE]') continue;
                try {
                    const data = JSON.parse(payload);
                    if (data.token) {
                        fullResponse += data.token;
                        if (replyEl) replyEl.innerHTML = md(fullResponse);
                        const container = document.getElementById('scanMessages');
                        if (container) container.scrollTop = container.scrollHeight;
                    }
                    if (data.error) {
                        fullResponse += '\n[Error: ' + data.error + ']';
                        if (replyEl) replyEl.innerHTML = md(fullResponse);
                    }
                } catch (e) {
                    // skip unparseable
                }
            }
        }
    } catch (err) {
        fullResponse = 'Connection error: ' + err.message;
        if (replyEl) replyEl.innerHTML = esc(fullResponse);
    }

    scanHistory.push({ role: 'assistant', content: fullResponse });
    if (scanHistory.length > 20) scanHistory = scanHistory.slice(-20);

    scanStreaming = false;
    if (sendBtn) sendBtn.disabled = false;
    if (input) { input.disabled = false; input.focus(); }
}

// ═══ CONTACT SEARCH (live API) ═══
async function searchContact(e) {
    if (e) e.preventDefault();
    const input = document.getElementById('contactSearchInput');
    const resultEl = document.getElementById('contactSearchResult');
    if (!input || !resultEl) return;

    const name = input.value.trim();
    if (!name) return;

    resultEl.innerHTML = '<div class="contact-error">Searching...</div>';

    try {
        const resp = await bakerFetch('/api/contacts/' + encodeURIComponent(name));
        if (resp.status === 404) {
            resultEl.innerHTML = '<div class="contact-error">No contact found for "' + esc(name) + '"</div>';
            return;
        }
        if (!resp.ok) throw new Error('API error ' + resp.status);
        const contact = await resp.json();

        let html = '<div class="contact-result">';
        html += '<div class="contact-result-header">';
        html += '<span class="contact-result-name">' + esc(contact.name || name) + '</span>';
        if (contact.relationship_tier) {
            html += '<span class="badge-stage">Tier ' + esc(String(contact.relationship_tier)) + '</span>';
        }
        html += '</div>';

        html += '<div class="contact-fields">';
        const fields = [
            ['Company', contact.company],
            ['Role', contact.role],
            ['Email', contact.email],
            ['Phone', contact.phone],
            ['Timezone', contact.timezone],
            ['Style', contact.communication_style],
            ['Response', contact.response_pattern],
            ['Last Contact', contact.last_contact ? fmtDate(contact.last_contact) : null],
        ];
        for (const [label, value] of fields) {
            if (value) {
                html += '<span class="contact-field-label">' + esc(label) + '</span>';
                html += '<span class="contact-field-value">' + esc(String(value)) + '</span>';
            }
        }
        html += '</div>';

        if (contact.notes) {
            html += '<div style="margin-top:12px;font-size:0.8rem;color:var(--text-secondary);"><strong>Notes:</strong> ' + esc(contact.notes) + '</div>';
        }

        html += '</div>';
        resultEl.innerHTML = html;
    } catch (err) {
        resultEl.innerHTML = '<div class="contact-error">Error: ' + esc(err.message) + '</div>';
    }
}

// ═══ UTILITIES ═══
function cycleLens() {
    const keys = Object.keys(lensIcons);
    lensIndex = (lensIndex + 1) % keys.length;
    const state = keys[lensIndex];
    const el = document.getElementById('lensImg');
    el.src = lensIcons[state];

    const container = document.getElementById('lensContainer');
    if (container) container.title = 'Baker state: ' + state;

    const dot = document.getElementById('scanDot');
    const colorMap = { clear: '#34d058', attentive: '#f0b429', alert: '#f56565' };
    if (dot) {
        dot.style.background = colorMap[state] || '#34d058';
        dot.style.boxShadow = '0 0 10px ' + (colorMap[state] || '#34d058') + '80';
    }

    updateScanTime();

    el.style.transform = 'scale(1.15)';
    setTimeout(() => { el.style.transform = 'scale(1)'; }, 200);
}

function runScan() {
    const btn = document.querySelector('.refresh-btn');
    if (btn) {
        btn.style.transition = 'transform 0.5s ease';
        btn.style.transform = 'rotate(360deg)';
        setTimeout(() => { btn.style.transform = ''; btn.style.transition = ''; }, 500);
    }
    updateScanTime();
    fetchSystemStatus();

    const dot = document.getElementById('scanDot');
    if (dot) {
        dot.style.background = '#f0b429';
        dot.style.boxShadow = '0 0 10px rgba(240,180,41,0.5)';
        setTimeout(() => {
            dot.style.background = '#34d058';
            dot.style.boxShadow = '0 0 10px rgba(52,208,88,0.5)';
        }, 2000);
    }
}

// ═══ KEYBOARD ═══
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        if (takeVisible) { closeTake(); return; }
        if (currentView === 'detailView') { openRole(currentRole); return; }
        if (currentView === 'catView') { goHome(); return; }
    }
});

// ═══ START ═══
document.addEventListener('DOMContentLoaded', init);
