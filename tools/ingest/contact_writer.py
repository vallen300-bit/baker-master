"""Baker AI — Contact writer for business card ingestion.

Writes extracted contact data to BOTH:
1. PostgreSQL contacts table (structured, dedup by email/phone)
2. Qdrant baker-people collection (vector search)

Atomic: if Qdrant upsert fails after PG write, rolls back PG.
"""
import json
import logging
from typing import Optional

import psycopg2
import psycopg2.extras
import voyageai
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct

from config.settings import config
from scripts.bulk_ingest import ensure_collection, make_point_id

logger = logging.getLogger("baker.ingest.contact_writer")


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


def write_contact(card_data: dict, source_file: str) -> dict:
    """Write a business card contact to PostgreSQL + Qdrant.

    Args:
        card_data: Dict with keys: name, company, role, email, phone, address, website, notes.
        source_file: Original filename (for metadata).

    Returns:
        Dict with: contact_id, name, action ('created'|'updated'|'skipped'), collection.
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

    # --- PostgreSQL write with dedup ---
    pool = None
    conn = None
    try:
        pool = psycopg2.pool.SimpleConnectionPool(
            minconn=1, maxconn=2, **config.postgres.dsn_params
        )
        conn = pool.getconn()
        cur = conn.cursor()

        # Check for existing contact (dedup by email/phone)
        existing = _find_existing_contact(cur, name, email, phone)
        action = "updated" if existing else "created"

        if existing:
            # Update existing contact — merge fields
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
            logger.info("Updated existing contact: %s (matched by %s)",
                         existing["name"], "email" if email else "phone")
        else:
            # Insert new contact
            cur.execute(
                """
                INSERT INTO contacts (name, email, phone, company, role, metadata, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, NOW())
                RETURNING id
                """,
                (name, email, phone, company, role, json.dumps(metadata) if metadata else "{}"),
            )
            contact_id = str(cur.fetchone()[0])
            logger.info("Created new contact: %s → %s", name, contact_id)

        conn.commit()

        # --- Qdrant write ---
        try:
            _upsert_contact_vector(card_data, source_file)
        except Exception as e:
            # Rollback PG if Qdrant fails (atomic guarantee)
            logger.error("Qdrant upsert failed, rolling back PG: %s", e)
            conn.rollback()
            if not existing:
                cur2 = conn.cursor()
                cur2.execute("DELETE FROM contacts WHERE id = %s", (contact_id,))
                conn.commit()
                cur2.close()
            raise

        cur.close()
        return {
            "contact_id": contact_id,
            "name": name,
            "action": action,
            "collection": "baker-people",
        }

    except Exception as e:
        if conn:
            conn.rollback()
        logger.error("write_contact failed for '%s': %s", name, e)
        return {"contact_id": None, "name": name, "action": "error", "collection": "baker-people"}
    finally:
        if pool and conn:
            pool.putconn(conn)
        if pool:
            pool.closeall()


def _upsert_contact_vector(card_data: dict, source_file: str):
    """Embed and upsert contact into baker-people Qdrant collection."""
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
