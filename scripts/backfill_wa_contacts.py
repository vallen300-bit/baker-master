"""
One-time backfill: create contacts from whatsapp_messages senders.

Scans whatsapp_messages table for unique senders, deduplicates against
existing contacts (by whatsapp_id and name), and creates new entries
in both the `contacts` and `vip_contacts` tables.

Usage:
  python3 scripts/backfill_wa_contacts.py --dry-run   # Preview what would be created
  python3 scripts/backfill_wa_contacts.py --run        # Create contacts
"""
import argparse
import logging
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("backfill_wa_contacts")

# Director's WhatsApp ID — skip (already known)
DIRECTOR_WA_ID = "41799605092@c.us"

# Skip group chats (contain '-' before @g.us) and status broadcasts
SKIP_SUFFIXES = ("@g.us", "@broadcast", "@lid")


def get_conn():
    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack._get_global_instance()
    return store, store._get_conn()


def get_unique_senders():
    """Get distinct WA senders with their latest sender_name and message count."""
    store, conn = get_conn()
    if not conn:
        logger.error("No DB connection")
        return []

    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT
                sender,
                MAX(sender_name) AS sender_name,
                COUNT(*) AS msg_count,
                MAX(timestamp) AS last_msg
            FROM whatsapp_messages
            WHERE sender IS NOT NULL
              AND is_director = FALSE
            GROUP BY sender
            ORDER BY COUNT(*) DESC
        """)
        rows = cur.fetchall()
        cur.close()
    finally:
        store._put_conn(conn)

    # Filter out groups, broadcasts, and Director
    senders = []
    for sender, sender_name, msg_count, last_msg in rows:
        if not sender:
            continue
        if sender == DIRECTOR_WA_ID:
            continue
        if any(sender.endswith(s) for s in SKIP_SUFFIXES):
            continue
        # Clean up sender_name: if it's just a phone number, keep as-is
        display_name = sender_name or sender.split("@")[0]
        senders.append({
            "whatsapp_id": sender,
            "name": display_name,
            "msg_count": msg_count,
            "last_msg": last_msg,
        })

    return senders


def get_existing_contacts():
    """Get existing contacts and VIP contacts for dedup."""
    store, conn = get_conn()
    if not conn:
        return set(), set(), set()

    try:
        cur = conn.cursor()

        # VIP contacts with whatsapp_id
        cur.execute("SELECT LOWER(name), whatsapp_id FROM vip_contacts WHERE whatsapp_id IS NOT NULL")
        vip_by_wa = {r[1]: r[0] for r in cur.fetchall()}

        # VIP contacts by name (for name-based dedup)
        cur.execute("SELECT LOWER(name) FROM vip_contacts")
        vip_names = {r[0] for r in cur.fetchall()}

        # General contacts by name
        cur.execute("SELECT LOWER(name) FROM contacts")
        contact_names = {r[0] for r in cur.fetchall()}

        # General contacts with phone (for phone-based dedup)
        cur.execute("SELECT phone FROM contacts WHERE phone IS NOT NULL")
        contact_phones = {r[0] for r in cur.fetchall()}

        cur.close()
    finally:
        store._put_conn(conn)

    return vip_by_wa, vip_names, contact_names, contact_phones


def run(dry_run=True):
    senders = get_unique_senders()
    logger.info(f"Found {len(senders)} unique WA senders (excluding Director, groups, broadcasts)")

    vip_by_wa, vip_names, contact_names, contact_phones = get_existing_contacts()
    logger.info(f"Existing: {len(vip_by_wa)} VIPs with WA ID, {len(vip_names)} VIP names, {len(contact_names)} contact names")

    to_create = []
    skipped_existing = 0
    skipped_phone_only = 0

    for s in senders:
        wa_id = s["whatsapp_id"]
        name = s["name"]
        phone = wa_id.split("@")[0]  # Extract phone from JID

        # Skip if WA ID already in VIP contacts
        if wa_id in vip_by_wa:
            skipped_existing += 1
            continue

        # Skip if name already in VIP contacts or general contacts (case-insensitive)
        if name.lower() in vip_names or name.lower() in contact_names:
            skipped_existing += 1
            continue

        # Skip if phone matches existing contact phone
        if phone in contact_phones or f"+{phone}" in contact_phones:
            skipped_existing += 1
            continue

        # If name is just a phone number (no real name), still create but flag
        is_phone_only = name.replace("+", "").replace(" ", "").isdigit()
        if is_phone_only:
            skipped_phone_only += 1
            # Still create — these are real contacts, just without names yet

        to_create.append({
            "name": name,
            "whatsapp_id": wa_id,
            "phone": phone,
            "msg_count": s["msg_count"],
            "last_msg": s["last_msg"],
            "is_phone_only": is_phone_only,
        })

    print(f"\n{'='*60}")
    print(f"  WA CONTACTS BACKFILL {'(DRY RUN)' if dry_run else ''}")
    print(f"{'='*60}")
    print(f"  Total unique WA senders:  {len(senders)}")
    print(f"  Already in contacts/VIP:  {skipped_existing}")
    print(f"  Phone-only names:         {skipped_phone_only}")
    print(f"  To create:                {len(to_create)}")
    print()

    # Show top 20
    print(f"  Top senders to create:")
    for c in to_create[:20]:
        flag = " (phone-only)" if c["is_phone_only"] else ""
        print(f"    {c['name']:30s}  {c['msg_count']:4d} msgs  last: {str(c['last_msg'])[:10]}{flag}")
    if len(to_create) > 20:
        print(f"    ... and {len(to_create) - 20} more")
    print(f"{'='*60}\n")

    if dry_run:
        logger.info("Dry run complete. Use --run to create contacts.")
        return

    # Create contacts
    store, conn = get_conn()
    if not conn:
        logger.error("No DB connection for writes")
        return

    created_contacts = 0
    created_vips = 0
    errors = 0

    try:
        cur = conn.cursor()

        for c in to_create:
            try:
                # 1. General contacts — only for named contacts (skip phone-only)
                if not c["is_phone_only"]:
                    cur.execute("""
                        INSERT INTO contacts (name, phone, preferred_channel, last_contact)
                        VALUES (%s, %s, 'whatsapp', %s)
                        ON CONFLICT (name) DO UPDATE SET
                            phone = COALESCE(contacts.phone, EXCLUDED.phone),
                            preferred_channel = 'whatsapp',
                            last_contact = GREATEST(contacts.last_contact, EXCLUDED.last_contact),
                            updated_at = NOW()
                    """, (c["name"], c["phone"], c["last_msg"]))
                    created_contacts += 1

                # 2. VIP contacts — always create (for WA ID tracking/matching)
                cur.execute("""
                    INSERT INTO vip_contacts (name, whatsapp_id, communication_pref)
                    VALUES (%s, %s, 'whatsapp')
                """, (c["name"], c["whatsapp_id"]))
                created_vips += 1

                conn.commit()

            except Exception as e:
                conn.rollback()
                errors += 1
                logger.warning(f"  Failed to create {c['name']}: {e}")

        cur.close()
    finally:
        store._put_conn(conn)

    print(f"\n{'='*60}")
    print(f"  BACKFILL COMPLETE")
    print(f"{'='*60}")
    print(f"  Contacts created:     {created_contacts}")
    print(f"  VIP entries created:  {created_vips}")
    print(f"  Errors:               {errors}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill contacts from WhatsApp message senders")
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    parser.add_argument("--run", action="store_true", help="Create contacts")
    args = parser.parse_args()

    if args.dry_run or args.run:
        run(dry_run=not args.run)
    else:
        parser.print_help()
