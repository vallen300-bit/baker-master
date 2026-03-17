"""
Batch contact enrichment: classify 472 default-tier contacts using Haiku.

For each contact with interactions, sends interaction summary to Haiku,
gets back: tier (1-3), contact_type, role_context. Updates vip_contacts in bulk.

Usage:
  python3 scripts/enrich_contacts.py --dry-run   # Preview classifications
  python3 scripts/enrich_contacts.py --run        # Apply to DB
  python3 scripts/enrich_contacts.py --run --limit 50  # Process first 50
"""
import argparse
import json
import logging
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("enrich_contacts")


CLASSIFY_PROMPT = """You are classifying a business contact for a luxury real estate CEO's contact management system.

Given the contact name and their recent interaction subjects, classify this person.

Return a JSON object with exactly these fields:
- "tier": 1 (inner circle — family, close partners, key advisors), 2 (active business — regular counterparties, lawyers, brokers), or 3 (peripheral — one-off contacts, service providers, marketing)
- "contact_type": one of "partner", "advisor", "investor", "broker", "lawyer", "service_provider", "team_member", "connector", "family", "prospect"
- "role_context": a concise 5-15 word description of who this person is and their relationship (e.g. "Travel agent handling all flight bookings", "IT support managing office infrastructure")

Rules:
- If the person has frequent, substantive interactions (business discussions, deal-related), they are likely tier 2
- If interactions are mostly personal/family or show deep trust, they are likely tier 1
- If interactions are sparse or transactional, they are likely tier 3
- The contact_type should reflect their primary function
- If unclear, default to tier 3 and contact_type "connector"

Contact: {name}
Channels: {channels}
Interaction count: {count}
Recent interaction subjects:
{subjects}

Return ONLY the JSON object, no explanation."""


def get_store():
    from memory.store_back import SentinelStoreBack
    return SentinelStoreBack._get_global_instance()


def get_contacts_to_enrich(limit=500):
    """Get default-tier contacts that have interactions."""
    store = get_store()
    conn = store._get_conn()
    if not conn:
        return []
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT c.id, c.name,
                STRING_AGG(DISTINCT ci.channel, ', ') as channels,
                COUNT(ci.id) as interaction_count,
                ARRAY_AGG(DISTINCT LEFT(ci.subject, 100) ORDER BY LEFT(ci.subject, 100))
                    FILTER (WHERE ci.subject IS NOT NULL AND ci.subject != '') as subjects
            FROM vip_contacts c
            JOIN contact_interactions ci ON ci.contact_id = c.id
            WHERE c.tier = 3 AND c.contact_type = 'connector'
            GROUP BY c.id, c.name
            HAVING COUNT(ci.id) >= 2
            ORDER BY COUNT(ci.id) DESC
            LIMIT %s
        """, (limit,))
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        cur.close()
        return rows
    finally:
        store._put_conn(conn)


def classify_contact(client, contact):
    """Call Haiku to classify a single contact."""
    subjects = contact.get("subjects") or []
    # Limit to 30 subjects to stay within token budget
    subject_text = "\n".join(f"- {s}" for s in subjects[:30])

    prompt = CLASSIFY_PROMPT.format(
        name=contact["name"],
        channels=contact.get("channels", "unknown"),
        count=contact.get("interaction_count", 0),
        subjects=subject_text or "(no subject data)",
    )

    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        # Extract JSON from response
        if text.startswith("{"):
            return json.loads(text)
        # Try to find JSON in the response
        import re
        m = re.search(r'\{[^}]+\}', text, re.DOTALL)
        if m:
            return json.loads(m.group())
        logger.warning(f"Could not parse Haiku response for {contact['name']}: {text[:100]}")
        return None
    except Exception as e:
        logger.warning(f"Haiku call failed for {contact['name']}: {e}")
        return None


def update_contact(store, contact_id, classification):
    """Update a contact's tier, contact_type, and role_context."""
    conn = store._get_conn()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE vip_contacts
            SET tier = %s, contact_type = %s, role_context = %s
            WHERE id = %s
        """, (
            classification["tier"],
            classification["contact_type"],
            classification.get("role_context", ""),
            contact_id,
        ))
        conn.commit()
        cur.close()
        return True
    except Exception as e:
        conn.rollback()
        logger.warning(f"Update failed for contact {contact_id}: {e}")
        return False
    finally:
        store._put_conn(conn)


def main():
    parser = argparse.ArgumentParser(description="Batch contact enrichment via Haiku")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="Preview without writing")
    group.add_argument("--run", action="store_true", help="Apply classifications to DB")
    parser.add_argument("--limit", type=int, default=500, help="Max contacts to process")
    args = parser.parse_args()

    import anthropic
    client = anthropic.Anthropic()
    store = get_store()

    contacts = get_contacts_to_enrich(limit=args.limit)
    logger.info(f"Found {len(contacts)} contacts to enrich")

    results = {"classified": 0, "updated": 0, "failed": 0, "skipped": 0}
    tier_counts = {1: 0, 2: 0, 3: 0}
    type_counts = {}

    for i, contact in enumerate(contacts):
        logger.info(f"[{i+1}/{len(contacts)}] Classifying: {contact['name']} ({contact['interaction_count']} interactions)")

        classification = classify_contact(client, contact)
        if not classification:
            results["failed"] += 1
            continue

        tier = classification.get("tier", 3)
        ctype = classification.get("contact_type", "connector")
        role = classification.get("role_context", "")

        # Validate
        if tier not in (1, 2, 3):
            tier = 3
        valid_types = {"partner", "advisor", "investor", "broker", "lawyer",
                       "service_provider", "team_member", "connector", "family", "prospect"}
        if ctype not in valid_types:
            ctype = "connector"

        classification["tier"] = tier
        classification["contact_type"] = ctype

        tier_counts[tier] = tier_counts.get(tier, 0) + 1
        type_counts[ctype] = type_counts.get(ctype, 0) + 1
        results["classified"] += 1

        if args.dry_run:
            logger.info(f"  -> tier={tier}, type={ctype}, role={role}")
        else:
            if update_contact(store, contact["id"], classification):
                results["updated"] += 1
            else:
                results["failed"] += 1

        # Rate limiting: ~2 calls/sec to stay under Haiku limits
        if i < len(contacts) - 1:
            time.sleep(0.5)

    logger.info(f"\n{'='*60}")
    logger.info(f"Results: {results}")
    logger.info(f"Tier distribution: {tier_counts}")
    logger.info(f"Type distribution: {type_counts}")
    if args.dry_run:
        logger.info("(DRY RUN — no changes written)")


if __name__ == "__main__":
    main()
