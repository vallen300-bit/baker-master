"""
B1 Backfill: Embed existing conversation_memory records into Qdrant baker-conversations.
Run once: python3 scripts/backfill_conversation_embeddings.py

New conversations are automatically embedded via log_conversation() (Session 26 B1 change).
"""
import logging
import sys
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("backfill_conversations")

sys.path.insert(0, ".")


def main():
    from memory.store_back import SentinelStoreBack
    import psycopg2.extras

    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    if not conn:
        logger.error("No DB connection")
        return

    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT id, question, answer, project, created_at
            FROM conversation_memory
            WHERE answer IS NOT NULL AND LENGTH(answer) > 50
            ORDER BY id
        """)
        rows = cur.fetchall()
        cur.close()
        logger.info(f"Found {len(rows)} conversations to embed")

        embedded = 0
        skipped = 0
        for i, row in enumerate(rows):
            try:
                text = f"Question: {row['question']}\n\nAnswer: {row['answer'][:4000]}"
                metadata = {
                    "source": "conversation",
                    "project": row.get("project") or "general",
                    "question": row["question"][:500],
                    "timestamp": row["created_at"].isoformat() if row.get("created_at") else "",
                }
                store.store_document(text, metadata, collection="baker-conversations")
                embedded += 1

                if (i + 1) % 10 == 0:
                    logger.info(f"Progress: {i + 1}/{len(rows)} ({embedded} embedded, {skipped} skipped)")

                # Rate limit: Voyage AI has limits
                time.sleep(0.5)

            except Exception as e:
                logger.warning(f"Failed to embed conversation {row['id']}: {e}")
                skipped += 1

        logger.info(f"Done: {embedded} embedded, {skipped} skipped out of {len(rows)} total")

    finally:
        store._put_conn(conn)


if __name__ == "__main__":
    main()
