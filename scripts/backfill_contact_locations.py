"""
C6: Contact Location Backfill (Session 27)

Extracts primary city/location for contacts from their interaction history
(email signatures, WhatsApp messages, meeting locations).

Uses Haiku to classify location from context. Batch-processes contacts
that have 3+ interactions but no primary_location set.

Run: python3 scripts/backfill_contact_locations.py [--limit 50] [--dry-run]
Cost: ~$0.01 per contact (Haiku), ~$2.50 for 250 contacts
"""
import logging
import sys
import time
import json
import argparse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("backfill_locations")

sys.path.insert(0, ".")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    from memory.store_back import SentinelStoreBack
    import psycopg2.extras
    import anthropic
    from config.settings import config

    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    if not conn:
        logger.error("No DB connection")
        return

    client = anthropic.Anthropic(api_key=config.claude.api_key, timeout=15.0)

    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Get contacts without location that have enough interaction data
        cur.execute("""
            SELECT vc.id, vc.name, vc.email, vc.role,
                   COUNT(ci.id) as interaction_count
            FROM vip_contacts vc
            LEFT JOIN contact_interactions ci ON ci.contact_id = vc.id
            WHERE (vc.primary_location IS NULL OR vc.primary_location = '')
            GROUP BY vc.id, vc.name, vc.email, vc.role
            HAVING COUNT(ci.id) >= 2
            ORDER BY COUNT(ci.id) DESC
            LIMIT %s
        """, (args.limit,))
        contacts = cur.fetchall()
        logger.info(f"Found {len(contacts)} contacts needing location extraction")

        updated = 0
        skipped = 0

        for i, contact in enumerate(contacts):
            cid = contact["id"]
            name = contact["name"]

            # Gather context: email signatures, WA messages, meeting locations
            context_parts = []

            # Email signatures (last 3 emails from this contact)
            try:
                cur.execute("""
                    SELECT subject, sender_email,
                           RIGHT(full_body, 500) as signature_area
                    FROM email_messages
                    WHERE sender_email = %s OR sender_name ILIKE %s
                    ORDER BY received_date DESC LIMIT 3
                """, (contact.get("email"), f"%{name}%"))
                for row in cur.fetchall():
                    sig = row.get("signature_area", "")
                    if sig:
                        context_parts.append(f"Email signature area: {sig[:300]}")
            except Exception:
                pass

            # WhatsApp messages (last 5 from this contact)
            try:
                cur.execute("""
                    SELECT full_text FROM whatsapp_messages
                    WHERE sender_name ILIKE %s
                    ORDER BY timestamp DESC LIMIT 5
                """, (f"%{name}%",))
                for row in cur.fetchall():
                    body = row.get("full_text", "")
                    if body:
                        context_parts.append(f"WhatsApp: {body[:200]}")
            except Exception:
                pass

            # Meeting locations
            try:
                cur.execute("""
                    SELECT title, full_transcript as transcript
                    FROM meeting_transcripts
                    WHERE participants ILIKE %s
                    ORDER BY meeting_date DESC LIMIT 2
                """, (f"%{name}%",))
                for row in cur.fetchall():
                    title = row.get("title", "")
                    if title:
                        context_parts.append(f"Meeting: {title[:200]}")
            except Exception:
                pass

            if not context_parts:
                skipped += 1
                continue

            # Ask Haiku to extract location
            context = "\n".join(context_parts[:8])
            prompt = f"""Based on these interactions, what is the PRIMARY CITY where this person is based?

Person: {name}
Email: {contact.get('email', 'unknown')}
Role: {contact.get('role', 'unknown')}

Context:
{context[:2000]}

Reply with ONLY the city name (e.g., "Vienna", "Zurich", "London").
If you cannot determine the city with reasonable confidence, reply "UNKNOWN".
Do NOT guess — only answer if there's clear evidence (address in signature, phone country code, meeting location pattern, explicit mention)."""

            if args.dry_run:
                logger.info(f"[DRY RUN] Would classify: {name} ({len(context_parts)} context items)")
                continue

            try:
                resp = client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=20,
                    messages=[{"role": "user", "content": prompt}],
                )
                location = resp.content[0].text.strip().strip('"').strip("'")

                # Log cost
                try:
                    from orchestrator.cost_monitor import log_api_cost
                    log_api_cost(
                        "claude-haiku-4-5-20251001",
                        resp.usage.input_tokens,
                        resp.usage.output_tokens,
                        source="location_backfill",
                    )
                except Exception:
                    pass

                if location and location.upper() != "UNKNOWN" and len(location) < 50:
                    cur.execute(
                        "UPDATE vip_contacts SET primary_location = %s WHERE id = %s",
                        (location, cid),
                    )
                    conn.commit()
                    updated += 1
                    logger.info(f"  {name} → {location}")
                else:
                    skipped += 1
                    logger.info(f"  {name} → UNKNOWN (skipped)")

                if (i + 1) % 10 == 0:
                    logger.info(f"Progress: {i + 1}/{len(contacts)} ({updated} updated, {skipped} skipped)")

                time.sleep(0.3)  # rate limit

            except Exception as e:
                logger.warning(f"  {name} → ERROR: {e}")
                skipped += 1

        logger.info(f"Done: {updated} updated, {skipped} skipped out of {len(contacts)} contacts")

    finally:
        store._put_conn(conn)


if __name__ == "__main__":
    main()
