"""
C4: Contact Deduplication (Session 27)

Detects duplicate contacts using exact name match + pg_trgm fuzzy similarity.
Merges duplicates: keeps the contact with more interactions, moves interactions
from the other, preserves the richer profile (email, role, location).

Run: python3 scripts/dedup_contacts.py [--dry-run] [--threshold 0.6]
"""
import logging
import sys
import argparse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("dedup_contacts")

sys.path.insert(0, ".")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Show duplicates without merging")
    parser.add_argument("--threshold", type=float, default=0.6, help="Similarity threshold (0-1)")
    args = parser.parse_args()

    from memory.store_back import SentinelStoreBack
    import psycopg2.extras

    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    if not conn:
        logger.error("No DB connection")
        return

    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Ensure pg_trgm extension exists
        try:
            cur.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
            conn.commit()
        except Exception:
            conn.rollback()

        # Find duplicate pairs: exact match + fuzzy similarity
        cur.execute("""
            SELECT a.id as id_a, a.name as name_a, a.email as email_a,
                   a.role as role_a, a.primary_location as loc_a, a.tier as tier_a,
                   b.id as id_b, b.name as name_b, b.email as email_b,
                   b.role as role_b, b.primary_location as loc_b, b.tier as tier_b,
                   SIMILARITY(LOWER(TRIM(a.name)), LOWER(TRIM(b.name))) as sim,
                   (SELECT COUNT(*) FROM contact_interactions WHERE contact_id = a.id) as interactions_a,
                   (SELECT COUNT(*) FROM contact_interactions WHERE contact_id = b.id) as interactions_b
            FROM vip_contacts a
            JOIN vip_contacts b ON a.id < b.id
            WHERE SIMILARITY(LOWER(TRIM(a.name)), LOWER(TRIM(b.name))) > %s
            ORDER BY sim DESC
        """, (args.threshold,))
        pairs = cur.fetchall()

        if not pairs:
            logger.info("No duplicates found")
            return

        logger.info(f"Found {len(pairs)} duplicate pairs (threshold={args.threshold})")
        merged = 0

        for pair in pairs:
            id_a, name_a = pair["id_a"], pair["name_a"]
            id_b, name_b = pair["id_b"], pair["name_b"]
            sim = float(pair["sim"])
            int_a = pair["interactions_a"]
            int_b = pair["interactions_b"]

            # Keep the one with more interactions (or richer profile)
            if int_a >= int_b:
                keep_id, keep_name = id_a, name_a
                merge_id, merge_name = id_b, name_b
                keep_data = {k: pair[f"{k}_a"] for k in ("email", "role", "loc", "tier")}
                merge_data = {k: pair[f"{k}_b"] for k in ("email", "role", "loc", "tier")}
            else:
                keep_id, keep_name = id_b, name_b
                merge_id, merge_name = id_a, name_a
                keep_data = {k: pair[f"{k}_b"] for k in ("email", "role", "loc", "tier")}
                merge_data = {k: pair[f"{k}_a"] for k in ("email", "role", "loc", "tier")}

            logger.info(
                f"  MERGE: '{merge_name}' (id={merge_id}, {min(int_a,int_b)} interactions) "
                f"→ '{keep_name}' (id={keep_id}, {max(int_a,int_b)} interactions) "
                f"[sim={sim:.2f}]"
            )

            if args.dry_run:
                continue

            # 1. Fill empty fields on keeper from mergee
            updates = []
            if not keep_data["email"] and merge_data["email"]:
                updates.append(("email", merge_data["email"]))
            if not keep_data["role"] and merge_data["role"]:
                updates.append(("role", merge_data["role"]))
            if not keep_data["loc"] and merge_data["loc"]:
                updates.append(("primary_location", merge_data["loc"]))
            if (not keep_data["tier"] or keep_data["tier"] == 3) and merge_data["tier"] and merge_data["tier"] < 3:
                updates.append(("tier", merge_data["tier"]))

            if updates:
                set_clause = ", ".join(f"{col} = %s" for col, _ in updates)
                values = [v for _, v in updates]
                cur.execute(
                    f"UPDATE vip_contacts SET {set_clause} WHERE id = %s",
                    values + [keep_id],
                )
                logger.info(f"    Updated keeper with: {[col for col, _ in updates]}")

            # 2. Move interactions from mergee to keeper
            cur.execute(
                "UPDATE contact_interactions SET contact_id = %s WHERE contact_id = %s",
                (keep_id, merge_id),
            )
            moved = cur.rowcount
            if moved:
                logger.info(f"    Moved {moved} interactions")

            # 3. Delete the mergee
            cur.execute("DELETE FROM vip_contacts WHERE id = %s", (merge_id,))
            conn.commit()
            merged += 1

        logger.info(f"Done: {merged} contacts merged out of {len(pairs)} pairs")

    except Exception as e:
        logger.error(f"Dedup failed: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        store._put_conn(conn)


if __name__ == "__main__":
    main()
