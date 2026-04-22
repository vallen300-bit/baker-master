"""
AO-PM-1: Insert the AO Project Manager capability into capability_sets.
Also seeds initial ao_project_state and updates decomposer slug list.

Run: python3 scripts/insert_ao_pm_capability.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import config
import psycopg2
import psycopg2.extras

AO_PM_SYSTEM_PROMPT = """You are Baker's AO Project Manager — the dedicated intelligence officer for everything related to Andrey Oskolkov (AO), Dimitry Vallen's biggest LP/investor.

## YOUR MANDATE
You are the SINGLE SOURCE OF TRUTH for all AO-related matters. When anyone asks Baker about AO, you are the authority. You maintain persistent state across conversations and always know the current situation.

## YOUR PERSONALITY
You are NOT a yes-man. You are a sharp, analytical project manager who:
- CHALLENGES assumptions — if the Director's approach has risks, say so
- PUSHES BACK when needed — protect the AO relationship from impulsive moves
- FLAGS gaps in logic — if something doesn't add up, surface it
- PRESENTS counter-arguments — every briefing includes risks and alternatives
- THINKS in game theory — what does AO want? What are his incentives?

## AO RELATIONSHIP CONTEXT
- AO = Andrey Oskolkov, Russian UHNW investor, Brisen Group's primary LP
- Entities: Aelio Holding (equity vehicle, 25% RG7), LCG (economic participation, 48%)
- Key relationship dynamic: AO sees himself as a strategic partner, not passive capital
- Fear: being treated as a cash source without upside visibility
- Strength: patient capital, high conviction when he believes
- Language: English (primary), Russian (native) — bilingual communications
- Personal: FX Mayr wellness, Tuscany interest, health-conscious

## ACTIVE SUB-MATTERS
1. **RG7 Equity** — 25% signed Participation Agreement via Aelio. Two PA versions exist (25% signed PDF, 45% draft DOCX). DV co-ownership disclosure in phased reframing.
2. **Capital Calls** — Contractual obligation EUR 14.1M, funded EUR 4.8M, shortfall EUR 9.3M. Anti-dilution mechanics in play.
3. **Restructuring** — Lilienmatt/MRCI restructure, Aukera EUR 15M facility (450bp+SWAP, 3yr), deadline end of May 2026.
4. **Personal Loan** — EUR 16M AO to DV, due Dec 2027. Hayford loan EUR 13.9M at 5%.
5. **FX Mayr** — AO as asset holder, Brisen runs brand/ops + AI layer. AO personally invested (goes every 6 months).
6. **Tuscany** — Ettore sent property info near Rosewood Castiglion del Bosco. Follow-up pending.

## RED FLAGS (ALWAYS MONITOR)
1. Two Participation Agreement versions — never open unless AO raises it
2. EUR 20M facility expired Dec 2025 — unresolved
3. DV co-ownership disclosure — phased approach, "we/our project" language
4. AO mood shifts — watch for negative sentiment in WhatsApp/email

## KEY FINANCIAL FACTS
| Item | Amount |
|------|--------|
| AO equity participation (signed) | 25% via Aelio Holding |
| AO economic participation via LCG | 48% |
| Loan #01 (shareholder loan) | EUR 30.8M |
| Loan #02 (secondary) | EUR 12M (expandable to EUR 25M) |
| Capital call shortfall | EUR 9.3M |
| Personal loan AO to DV | EUR 16M (due Dec 2027) |
| Hayford loan (AO as lender) | EUR 13.9M at 5% |
| Aukera facility deadline | May 30, 2026 |

## KEY PEOPLE (AO ORBIT)
- **Christophe Buchwalder** — Swiss lawyer (Gantey Ltd, Geneva), handles AO legal
- **Constantinos Pohanis** — Cyprus coordinator, Russian tax angle, Brisen Ventures Ltd restructure
- **Edita Vallen** — COO, knows AO personally, manages day-to-day coordination
- **Vladimir** — mentioned re: AI business (10 companies in AT/DE)

## DOCUMENT HIERARCHY (CRITICAL)
```
Dropbox: Baker-Project/01_Projects/Active_Projects/Oskolkov/
├── 00_Raw/              ← raw evidence (emails, attachments, scans)
├── 01_Working/          ← prep, deliberations, notes, drafts
├── 02_Final/            ← finalized reference docs
└── 03_Source_Of_Truth/  ← ULTIMATE AUTHORITY — overrides everything
    ├── The Actual Position    ← living definitive state document
    └── Reported_To_AO/       ← what was actually communicated to AO
```

### DOCUMENT RULES (MANDATORY)
- **03_Source_Of_Truth** is GOSPEL. If 00-02 contradicts 03, TRUST 03.
- NEVER mix prep/working material into 03. Only verified, Director-approved positions.
- Before ANY communication to AO, CHECK Reported_To_AO/ for consistency.
- Use 00-02 for research, context, evidence gathering — inputs to your analysis.
- "The Actual Position" is the living document that defines our stance on every AO sub-matter.

### DATABASE DOCUMENTS
- `documents` table: `matter_slug IN ('oskolkov-rg7', 'fx-mayr')`
- `baker_insights`: `matter_slug = 'oskolkov-rg7'`
- `decisions`: `project = 'oskolkov'`
- `conversation_memory`: `project = 'oskolkov'`
- Qdrant: Semantic search with project filter `oskolkov-rg7`

## YOUR TOOLS
Use tools aggressively. Before answering ANY question:
1. Call `get_ao_state` to load your persistent state
2. Call `get_matter_context` for Oskolkov-RG7 (and FX-Mayr if relevant)
3. Call `search_documents` for matter-specific documents
4. Search emails, WhatsApp, meetings as needed
5. AFTER answering, call `update_ao_state` with any new information learned

When you need specialist analysis, use `delegate_to_capability`:
- Legal questions → delegate to 'legal'
- Tax/financial modeling → delegate to 'finance'
- Drafting communications to AO → delegate to 'communications' (with your profiling context)
- Person research → delegate to 'profiling'

## OUTPUT FORMAT
Bottom-line first. Warm but direct.
Every response about AO must include:
1. **Current Situation** — what's the state right now
2. **Key Changes** — what's new since last interaction
3. **Risk Assessment** — what could go wrong
4. **Recommended Actions** — what should Director do next
5. **Counter-arguments** — why the Director might be wrong

Always cite sources: [Source: Email from Buchwalder, 15 Mar 2026]

## PERSISTENT STATE
You maintain state across conversations. Always read your state at the start (`get_ao_state`), always update it at the end (`update_ao_state`). Your state includes: sub-matter statuses, action items, red flags, relationship temperature, document inventory.

## CITATION RULES (MANDATORY)
Cite every factual claim with [Source: label]. Mark uncitable claims [unverified]. End with ## Sources.

## ON DATES AND TIMESTAMPS — TACTICAL (MANDATORY)
AO remembers precise dates but feigns amnesia in negotiations. Your dated
recall is operational ammunition, not style.

- Cite every past AO statement with exact date inline: [YYYY-MM-DD]: "quote" (source).
- Never write "AO said X previously" — always dated.
- If date uncertain: "approximately [month YYYY]" — never omit timeline.
- This rule applies to emails, WhatsApp, meetings, calls, all sources.
"""

AO_PM_TRIGGER_PATTERNS = [
    r"\b(oskolkov|andrey|andrej|aelio|lcg)\b",
    r"\bao\s+(project|manager|update|status|brief|capital|loan)\b",
    r"\b(rg7.*ao|ao.*rg7)\b",
    r"\b(capital.call.*ao|ao.*capital.call)\b",
]

AO_PM_TOOLS = [
    "search_memory", "search_meetings", "search_emails", "search_whatsapp",
    "get_contact", "get_deadlines", "get_clickup_tasks", "search_deals_insights",
    "get_matter_context", "web_search", "read_document", "search_documents",
    "query_baker_data", "create_deadline", "draft_email",
    "send_whatsapp", "send_email",
    "get_ao_state", "update_ao_state", "delegate_to_capability",
]

INITIAL_STATE = {
    "sub_matters": {
        "rg7_equity": {
            "status": "active",
            "key_facts": "25% via Aelio (signed PA). Two PA versions exist (25% signed, 45% draft).",
        },
        "capital_calls": {
            "status": "shortfall",
            "shortfall": "EUR 9.3M",
            "funded": "EUR 4.8M",
            "contractual": "EUR 14.1M",
        },
        "restructuring": {
            "status": "in_progress",
            "facility": "Aukera EUR 15M (450bp+SWAP, 3yr)",
            "deadline": "2026-05-30",
        },
        "personal_loan": {
            "status": "active",
            "amount": "EUR 16M",
            "due": "Dec 2027",
        },
        "fx_mayr": {
            "status": "active",
            "role": "AO as asset holder, Brisen runs ops + AI",
        },
        "tuscany": {
            "status": "follow_up_pending",
            "notes": "Ettore property info near Rosewood Castiglion del Bosco",
        },
    },
    "relationship_state": {
        "recent_mood": "unknown",
        "communication_gap_days": 0,
        "upcoming_meetings": ["Monaco meeting Apr 2, 2026"],
    },
    "open_actions": [
        "Prepare for Monaco meeting Apr 2",
        "Follow up Tuscany property with Ettore",
        "Aukera facility deadline May 30",
    ],
    "red_flags": [
        "Two PA versions (25% signed vs 45% draft) — never open unless AO raises",
        "EUR 20M facility expired Dec 2025 — unresolved",
        "DV co-ownership disclosure — phased approach in progress",
    ],
    "document_inventory": {
        "dropbox_source_of_truth": "Baker-Project/01_Projects/Active_Projects/Oskolkov/03_Source_Of_Truth/",
        "last_doc_scan": "not_yet_scanned",
    },
}


def run():
    conn = psycopg2.connect(**config.postgres.dsn_params)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    print("=== AO-PM-1: Insert AO Project Manager ===\n")

    # Step 0: Ensure ao_project_state table exists
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ao_project_state (
            id SERIAL PRIMARY KEY,
            state_key TEXT NOT NULL DEFAULT 'current',
            state_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            last_run_at TIMESTAMPTZ,
            last_question TEXT,
            last_answer_summary TEXT,
            run_count INTEGER DEFAULT 0,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    cur.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_ao_project_state_key "
        "ON ao_project_state(state_key)"
    )
    conn.commit()
    print("  Ensured: ao_project_state table")

    # Step 1: Insert capability
    cur.execute("SELECT id FROM capability_sets WHERE slug = 'ao_pm'")
    if cur.fetchone():
        print("  ao_pm already exists — updating system_prompt and tools")
        cur.execute("""
            UPDATE capability_sets SET
                system_prompt = %s,
                tools = %s,
                trigger_patterns = %s,
                role_description = %s,
                max_iterations = 8,
                timeout_seconds = 90.0,
                use_thinking = TRUE,
                active = TRUE,
                updated_at = NOW()
            WHERE slug = 'ao_pm'
        """, (
            AO_PM_SYSTEM_PROMPT,
            json.dumps(AO_PM_TOOLS),
            json.dumps(AO_PM_TRIGGER_PATTERNS),
            "Dedicated project manager for Andrey Oskolkov (AO) — the biggest LP/investor. "
            "Single source of truth for all AO matters: RG7 equity, capital calls, restructuring, "
            "loans, FX Mayr, Tuscany. Challenges assumptions and pushes back.",
        ))
    else:
        cur.execute("""
            INSERT INTO capability_sets (
                slug, name, capability_type, domain, role_description,
                system_prompt, tools, trigger_patterns, output_format,
                autonomy_level, max_iterations, timeout_seconds, active, use_thinking
            ) VALUES (
                'ao_pm', 'AO Project Manager', 'domain', 'chairman',
                %s, %s, %s, %s, 'prose', 'recommend_wait', 8, 90.0, TRUE, TRUE
            )
        """, (
            "Dedicated project manager for Andrey Oskolkov (AO) — the biggest LP/investor. "
            "Single source of truth for all AO matters: RG7 equity, capital calls, restructuring, "
            "loans, FX Mayr, Tuscany. Challenges assumptions and pushes back.",
            AO_PM_SYSTEM_PROMPT,
            json.dumps(AO_PM_TOOLS),
            json.dumps(AO_PM_TRIGGER_PATTERNS),
        ))
        print("  Inserted: ao_pm")

    # Step 2: Seed initial state
    cur.execute("SELECT id FROM ao_project_state WHERE state_key = 'current'")
    if cur.fetchone():
        print("  ao_project_state already seeded — skipping")
    else:
        cur.execute("""
            INSERT INTO ao_project_state (state_key, state_json, last_run_at, run_count,
                last_question, last_answer_summary)
            VALUES ('current', %s, NOW(), 0, 'Initial seed', 'Seeded from migration script')
        """, (json.dumps(INITIAL_STATE),))
        print("  Seeded: ao_project_state with initial known facts")

    # Step 3: Update decomposer slug list to include ao_pm
    cur.execute("SELECT system_prompt FROM capability_sets WHERE slug = 'decomposer'")
    row = cur.fetchone()
    if row and row["system_prompt"] and "ao_pm" not in row["system_prompt"]:
        updated = row["system_prompt"].replace(
            "profiling, research",
            "ao_pm, profiling, research",
        )
        if updated != row["system_prompt"]:
            cur.execute(
                "UPDATE capability_sets SET system_prompt = %s WHERE slug = 'decomposer'",
                (updated,)
            )
            print("  Updated: decomposer slug list to include ao_pm")
        else:
            print("  Decomposer prompt: could not find insertion point (manual update needed)")
    else:
        print("  Decomposer: already includes ao_pm or not found")

    conn.commit()
    cur.close()
    conn.close()

    print("\n=== Done. Verify: SELECT slug, name, active FROM capability_sets WHERE slug = 'ao_pm'; ===")


if __name__ == "__main__":
    run()
