"""
Register MOVIE Asset Manager capability in Baker.
Uses generic pm_project_state table (PM Factory).
Run once: python scripts/insert_movie_am_capability.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
import psycopg2.extras

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL not set")
    sys.exit(1)

SLUG = "movie_am"
NAME = "MOVIE Asset Manager"

SYSTEM_PROMPT = """You are Baker's MOVIE Asset Manager — dedicated PM for Mandarin Oriental, Vienna.

## YOUR MANDATE
Single source of truth for MOVIE hotel operations, operator oversight, and asset
performance. You protect the Owner's interests under the HMA suite while maintaining
a productive relationship with MOHG.

## PERSONALITY
- ANALYTICAL: Track KPIs against targets and benchmarks. Numbers first, narrative second.
- PROACTIVE: Flag issues before they become problems. A warranty window closing in 60
  days is an alert TODAY, not in 55 days.
- PROTECTIVE: Owner's interests come first. If MO is underperforming, surface it. If
  fees seem high vs GOP, flag it. If budget is inflated, challenge it.
- PRAGMATIC: MOHG is a long-term partner, not an adversary. Push back WITH data, not
  emotion. The relationship needs to survive decades.

## WHAT YOU KNOW
- All 7 HMA documents (133K tokens) are in Baker's database (IDs 83200-83206).
- View files contain compiled intelligence (agreements, KPIs, obligations, contacts).
- Live state tracks current KPIs, open items, and operator signals.

## WHAT YOU DO
1. MONITOR: Monthly P&L review, KPI tracking, budget variance analysis
2. ALERT: Flag deviations, approaching deadlines, compliance gaps
3. PREPARE: Meeting agendas, budget review notes, negotiation positions
4. TRACK: Owner approvals pipeline, insurance renewals, warranty windows
5. ADVISE: Recommendations on operator performance, capex decisions, fee negotiations

## ESCALATION TIERS
- T3 (Baker auto-handles): Report receipt reminders, minor data requests
- T2 (Edita): Budget deviations, approval requests, routine compliance
- T1 (Director): Performance failures, strategic decisions, fee disputes, termination

## RULES
- Always cite the specific agreement clause when referencing contractual obligations.
- Never commit the Owner to expenditure without Director approval.
- Flag, don't fix: if you see a problem, surface it with data — don't autonomously
  negotiate with MO.
- Update your state after every interaction.
- Residences are a SEPARATE business line — do not mix MORV sales with hotel operations.
"""

TRIGGER_PATTERNS = json.dumps([
    r"\b(movie|mandarin\s*oriental|mo\s+vienna)\b",
    r"\b(hotel\s+management|operator\s+report)\b",
    r"\b(revpar|adr|occupancy|gop)\b.*\b(vienna|hotel)\b",
    r"\b(ffe|ff&e|reserve\s+account)\b",
    r"\b(mohg|mandarin\s*oriental\s*group)\b",
    r"\bowner.?s?\s+(approval|priority|return)\b",
])

TOOLS = json.dumps([
    "search_memory", "search_meetings", "search_emails", "search_whatsapp",
    "search_documents", "read_document", "query_baker_data",
    "get_contact", "get_deadlines", "get_clickup_tasks",
    "get_matter_context", "search_deals_insights",
    "get_pm_state", "update_pm_state",
    "get_pending_insights", "update_pending_insight",
    "create_deadline", "draft_email", "store_decision",
    "delegate_to_capability",
    "web_search",
])

INITIAL_STATE = json.dumps({
    "property": {
        "name": "Mandarin Oriental, Vienna",
        "status": "TBD",
        "opening_date": "TBD",
        "rooms": "TBD",
    },
    "kpi_snapshot": {
        "occupancy_pct": None,
        "adr_eur": None,
        "revpar_eur": None,
        "gop_eur": None,
        "gop_margin_pct": None,
        "noi_eur": None,
        "last_updated": None,
    },
    "open_approvals": [],
    "pending_reports": [],
    "insurance": {"policies": [], "next_renewal": None},
    "warranties": [],
    "upcoming_meetings": [],
    "red_flags": [],
    "open_actions": [],
    "relationship_state": {
        "last_inbound_channel": None,
        "last_inbound_from": None,
        "last_inbound_summary": None,
        "last_inbound_at": None,
        "operator_compliance_status": "unknown",
    },
})


def main():
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    try:
        cur = conn.cursor()

        # Step 1: Insert/Update capability_sets
        cur.execute("SELECT id FROM capability_sets WHERE slug = %s", (SLUG,))
        row = cur.fetchone()
        if row:
            cur.execute("""
                UPDATE capability_sets SET
                    name = %s,
                    capability_type = 'client_pm',
                    domain = 'chairman',
                    role_description = %s,
                    system_prompt = %s,
                    tools = %s,
                    trigger_patterns = %s,
                    output_format = 'prose',
                    autonomy_level = 'recommend_wait',
                    max_iterations = 8,
                    timeout_seconds = 90.0,
                    active = TRUE,
                    use_thinking = TRUE,
                    updated_at = NOW()
                WHERE slug = %s
            """, (
                NAME,
                "Dedicated asset manager for Mandarin Oriental, Vienna hotel operations. "
                "Tracks KPIs, operator compliance, owner obligations, and contractual deadlines.",
                SYSTEM_PROMPT, TOOLS, TRIGGER_PATTERNS, SLUG,
            ))
            print(f"  Updated: {SLUG} in capability_sets")
        else:
            cur.execute("""
                INSERT INTO capability_sets (
                    slug, name, capability_type, domain, role_description,
                    system_prompt, tools, trigger_patterns, output_format,
                    autonomy_level, max_iterations, timeout_seconds, active, use_thinking
                ) VALUES (%s, %s, 'client_pm', 'chairman', %s, %s, %s, %s,
                          'prose', 'recommend_wait', 8, 90.0, TRUE, TRUE)
            """, (
                SLUG, NAME,
                "Dedicated asset manager for Mandarin Oriental, Vienna hotel operations. "
                "Tracks KPIs, operator compliance, owner obligations, and contractual deadlines.",
                SYSTEM_PROMPT, TOOLS, TRIGGER_PATTERNS,
            ))
            print(f"  Inserted: {SLUG} into capability_sets")

        # Step 2: Seed initial state in pm_project_state (generic table)
        cur.execute(
            "SELECT id FROM pm_project_state WHERE pm_slug = %s AND state_key = 'current' LIMIT 1",
            (SLUG,)
        )
        if cur.fetchone():
            print(f"  pm_project_state already seeded for {SLUG} — skipping")
        else:
            cur.execute("""
                INSERT INTO pm_project_state (pm_slug, state_key, state_json,
                    last_run_at, run_count, last_question, last_answer_summary)
                VALUES (%s, 'current', %s, NOW(), 0, 'Initial seed',
                        'MOVIE AM registered — awaiting debrief')
            """, (SLUG, INITIAL_STATE))
            print(f"  Seeded: pm_project_state for {SLUG}")

        # Step 3: Update decomposer slug list
        cur.execute("SELECT system_prompt FROM capability_sets WHERE slug = 'decomposer' LIMIT 1")
        decomp_row = cur.fetchone()
        if decomp_row and decomp_row[0]:
            original = decomp_row[0]
            if SLUG not in original:
                updated = original.replace(
                    "ao_pm, profiling",
                    f"ao_pm, {SLUG}, profiling",
                )
                if updated != original:
                    cur.execute(
                        "UPDATE capability_sets SET system_prompt = %s WHERE slug = 'decomposer'",
                        (updated,)
                    )
                    print(f"  Updated: decomposer slug list (added {SLUG})")
                else:
                    print(f"  WARNING: Could not find insertion point in decomposer prompt")
            else:
                print(f"  Decomposer already includes {SLUG} — skipping")

        conn.commit()
        print(f"\n  SUCCESS: {SLUG} registered.")
        cur.close()

    except Exception as e:
        conn.rollback()
        print(f"  ERROR: {e}")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
