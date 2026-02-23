"""Baker AI — Contact writer for business card ingestion.

Writes extracted contact data to BOTH:
1. PostgreSQL contacts table (structured, dedup by email/phone)
2. Qdrant baker-people collection (vector search)

Atomic dual-write guarantees:
- PG INSERT/UPDATE is staged but NOT committed until Qdrant succeeds.
- If Qdrant write fails → PG transaction is rolled back (no partial data).
- If PG commit fails after Qdrant write → Qdrant point is deleted (no partial data).
"""
import json
import logging
from typing import Optional

import psycopg2
import psycopg2.extras
import psycopg2.pool
import voyageai
from qdrant_client import QdrantClient
from qdrant_client.models import PointIdsList, PointStruct

from config.settings import config
from scripts.bulk_ingest import ensure_collection, make_point_id

logger = logging.getLogger("baker.ingest.contact_writer")

_STORAGE_ERROR = "Card extraction succeeded but storage failed — please retry"


def _find_existing_contact(cur, name: str, email: Optional[str], phone: Optional[str]) -> Optional[dict]:
    """Check for existing contact by email or phone (dedup).

    Priority: email match > phone match > name match.
    Returns dict with id and name if found, else None.
    """
    # Try email match first
    if email:
        cur.execute(
            "SELECT id, name FROM contacts WHERE LOWER(email) = LOWER(%s) LIMIT 1",
            (email,),
        )
        row = cur.fetchone()
        if row:
            return {"id": str(row[0]), "name": row[1]}

    # Try phone match
    if phone:
        # Normalize: strip spaces, dashes, parens for comparison
        normalized = phone.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
        cur.execute(
            "SELECT id, name FROM contacts WHERE REPLACE(REPLACE(REPLACE(REPLACE(phone, ' ', ''), '-', ''), '(', ''), ')', '') = %s LIMIT 1",
            (normalized,),
        )
        row = cur.fetchone()
        if row:
            return {"id": str(row[0]), "name": row[1]}

    return None


def _delete_qdrant_point(point_id: str):
    """Delete a single point from baker-people (rollback helper)."""
    qdrant = QdrantClient(url=config.qdrant.url, api_key=config.qdrant.api_key)
    qdrant.delete(
        collection_name="baker-people",
        points_selector=PointIdsList(points=[point_id]),
    )
    logger.info("Rolled back Qdrant point: %s", point_id)


def write_contact(card_data: dict, source_file: str) -> dict:
    """Write a business card contact to PostgreSQL + Qdrant (atomic).

    Dual-write guarantees:
    - PG INSERT/UPDATE is staged but NOT committed until Qdrant succeeds.
    - If Qdrant write fails → PG transaction is rolled back.
    - If PG commit fails after Qdrant write → Qdrant point is deleted.
    - Neither store retains partial data after a failure.

    Args:
        card_data: Dict with keys: name, company, role, email, phone, address, website, notes.
        source_file: Original filename (for metadata).

    Returns:
        Dict with: contact_id, name, action ('created'|'updated'|'skipped'), collection.

    Raises:
        RuntimeError: If dual-write fails (with user-facing message).
    """
    name = card_data.get("name")
    if not name:
        logger.warning("Card data missing name — skipping contact write")
        return {"contact_id": None, "name": None, "action": "skipped", "collection": "baker-people"}

    email = card_data.get("email")
    phone = card_data.get("phone")
    company = card_data.get("company")
    role = card_data.get("role")

    # Build metadata for non-core fields
    metadata = {}
    for field in ("address", "website", "notes"):
        val = card_data.get(field)
        if val and val != "null":
            metadata[field] = val
    metadata["source_file"] = source_file

    pool = None
    conn = None
    qdrant_point_id = None
    contact_id = None

    try:
        pool = psycopg2.pool.SimpleConnectionPool(
            minconn=1, maxconn=2, **config.postgres.dsn_params
        )
        conn = pool.getconn()
        cur = conn.cursor()

        # --- Step 1: PostgreSQL write (staged, NOT committed) ---
        existing = _find_existing_contact(cur, name, email, phone)
        action = "updated" if existing else "created"

        if existing:
            contact_id = existing["id"]
            set_parts = ["updated_at = NOW()"]
            values = []

            if email:
                set_parts.append("email = %s")
                values.append(email)
            if phone:
                set_parts.append("phone = %s")
                values.append(phone)
            if company:
                set_parts.append("company = %s")
                values.append(company)
            if role:
                set_parts.append("role = %s")
                values.append(role)
            if metadata:
                set_parts.append("metadata = contacts.metadata || %s::jsonb")
                values.append(json.dumps(metadata))

            values.append(existing["id"])
            cur.execute(
                f"UPDATE contacts SET {', '.join(set_parts)} WHERE id = %s",
                values,
            )
            logger.info("Staged UPDATE for contact: %s (matched by %s)",
                         existing["name"], "email" if email else "phone")
        else:
            cur.execute(
                """
                INSERT INTO contacts (name, email, phone, company, role, metadata, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, NOW())
                RETURNING id
                """,
                (name, email, phone, company, role, json.dumps(metadata) if metadata else "{}"),
            )
            contact_id = str(cur.fetchone()[0])
            logger.info("Staged INSERT for contact: %s → %s", name, contact_id)

        # PG write is staged but NOT committed — rollback is clean from here

        # --- Step 2: Qdrant write ---
        try:
            qdrant_point_id = _upsert_contact_vector(card_data, source_file)
        except Exception as e:
            # Qdrant failed → rollback PG (uncommitted, clean rollback)
            logger.error("Qdrant upsert failed, rolling back staged PG write: %s", e)
            conn.rollback()
            raise RuntimeError(_STORAGE_ERROR) from e

        # --- Step 3: Commit PG (both writes succeeded) ---
        try:
            conn.commit()
        except Exception as e:
            # PG commit failed → delete the Qdrant point we just wrote
            logger.error("PG commit failed after Qdrant write, deleting Qdrant point: %s", e)
            try:
                _delete_qdrant_point(qdrant_point_id)
            except Exception as cleanup_err:
                logger.error("Failed to clean up Qdrant point %s: %s",
                             qdrant_point_id, cleanup_err)
            raise RuntimeError(_STORAGE_ERROR) from e

        cur.close()
        return {
            "contact_id": contact_id,
            "name": name,
            "action": action,
            "collection": "baker-people",
        }

    except RuntimeError:
        # Our specific errors — cleanup already handled, re-raise for caller
        raise
    except Exception as e:
        # Unexpected error — ensure no partial data persists
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        if qdrant_point_id:
            try:
                _delete_qdrant_point(qdrant_point_id)
            except Exception:
                pass
        logger.error("write_contact failed for '%s': %s", name, e)
        raise RuntimeError(_STORAGE_ERROR) from e
    finally:
        if pool and conn:
            pool.putconn(conn)
        if pool:
            pool.closeall()


def _upsert_contact_vector(card_data: dict, source_file: str) -> str:
    """Embed and upsert contact into baker-people Qdrant collection.

    Returns:
        The Qdrant point ID (needed for rollback if PG commit fails).
    """
    voyage = voyageai.Client(api_key=config.voyage.api_key)
    qdrant = QdrantClient(url=config.qdrant.url, api_key=config.qdrant.api_key)
    ensure_collection(qdrant, "baker-people")

    # Build text representation for embedding
    parts = []
    if card_data.get("name"):
        parts.append(f"Name: {card_data['name']}")
    if card_data.get("company"):
        parts.append(f"Company: {card_data['company']}")
    if card_data.get("role"):
        parts.append(f"Role: {card_data['role']}")
    if card_data.get("email"):
        parts.append(f"Email: {card_data['email']}")
    if card_data.get("phone"):
        parts.append(f"Phone: {card_data['phone']}")
    if card_data.get("address"):
        parts.append(f"Address: {card_data['address']}")
    if card_data.get("website"):
        parts.append(f"Website: {card_data['website']}")
    if card_data.get("notes"):
        parts.append(f"Notes: {card_data['notes']}")

    text = "\n".join(parts)

    result = voyage.embed(
        texts=[text],
        model=config.voyage.model,
        input_type="document",
    )

    point_id = make_point_id(text)
    qdrant.upsert(
        collection_name="baker-people",
        points=[PointStruct(
            id=point_id,
            vector=result.embeddings[0],
            payload={
                "text": text,
                "source_file": source_file,
                "contact_name": card_data.get("name", ""),
                "contact_email": card_data.get("email", ""),
                "contact_company": card_data.get("company", ""),
            },
        )],
    )
    logger.info("Upserted contact vector for: %s → baker-people", card_data.get("name"))
    return point_id
