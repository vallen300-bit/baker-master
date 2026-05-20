"""One-shot: normalize whatsapp_messages.chat_id from @lid to @c.us form.

Reads distinct @lid chat_ids, calls resolve_lid(), UPDATEs rows. Idempotent —
re-running on already-normalized rows is a no-op. Unresolvable LIDs remain
as-is (logged).

Anchor: BRIEF_WAHA_OUTBOUND_CAPTURE_1.

Usage (on Render shell OR local with DATABASE_URL set):
    cd /opt/render/project/src && python scripts/migrate_whatsapp_chat_id_normalize.py
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from memory.store_back import SentinelStoreBack  # noqa: E402
from triggers.waha_client import resolve_lid  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    if not conn:
        logger.error("No DB connection; aborting.")
        return 1

    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT DISTINCT chat_id
            FROM whatsapp_messages
            WHERE chat_id LIKE %s
            LIMIT 5000
            """,
            ("%@lid",),
        )
        lid_chats = [row[0] for row in cur.fetchall()]
        cur.close()
    except Exception as e:
        logger.error(f"Failed to enumerate @lid chat_ids: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        store._put_conn(conn)
        return 1

    logger.info(f"Found {len(lid_chats)} distinct @lid chat_ids to attempt normalization on.")

    resolved = 0
    unresolved = 0
    updated_rows = 0
    for lid_chat in lid_chats:
        phone = resolve_lid(lid_chat)
        if not phone:
            unresolved += 1
            logger.info(f"  unresolved: {lid_chat}")
            continue
        resolved += 1
        try:
            cur = conn.cursor()
            cur.execute(
                "UPDATE whatsapp_messages SET chat_id = %s WHERE chat_id = %s",
                (phone, lid_chat),
            )
            row_n = cur.rowcount
            updated_rows += row_n
            conn.commit()
            cur.close()
            logger.info(f"  normalized: {lid_chat} -> {phone} ({row_n} rows)")
        except Exception as e:
            logger.warning(f"UPDATE failed for {lid_chat}: {e}")
            try:
                conn.rollback()
            except Exception:
                pass

    store._put_conn(conn)
    logger.info(
        f"Migration complete: {resolved} resolved / {unresolved} unresolved / "
        f"{updated_rows} rows updated."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
