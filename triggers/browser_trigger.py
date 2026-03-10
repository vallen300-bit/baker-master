"""
Sentinel Trigger — Browser Web Monitoring (BROWSER-1)
Polls active browser_tasks from PostgreSQL, fetches web content via
simple HTTP or Browser-Use Cloud API, detects changes via content
hashing, and feeds changed content into the Sentinel pipeline.

Called by scheduler every 30 minutes.

Pattern: follows rss_trigger.py structure (lazy imports, module-level entry point).
"""
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from triggers.state import trigger_state

logger = logging.getLogger("sentinel.browser_trigger")


def _get_client():
    """Get the global BrowserClient singleton."""
    from triggers.browser_client import BrowserClient
    return BrowserClient._get_global_instance()


def _get_store():
    """Get the global SentinelStoreBack singleton."""
    from memory.store_back import SentinelStoreBack
    return SentinelStoreBack._get_global_instance()


# -------------------------------------------------------
# Main poll entry point
# -------------------------------------------------------

def run_browser_poll():
    """Main entry point — called by scheduler every 30 minutes."""
    from triggers.sentinel_health import report_success, report_failure, should_skip_poll

    if should_skip_poll("browser"):
        return

    logger.info("Browser trigger: starting poll...")

    from config.settings import config

    try:
        client = _get_client()
        store = _get_store()

        # 1. Load active browser tasks from PostgreSQL
        tasks = _get_active_tasks(store)
        if not tasks:
            logger.info("No browser tasks configured. Create via POST /api/browser/tasks")
            return

        tasks_polled = 0
        tasks_changed = 0
        tasks_unchanged = 0
        tasks_errored = 0

        # 2. Execute each task
        for task in tasks:
            task_id = task["id"]
            task_name = task["name"]
            task_url = task["url"]
            task_mode = task.get("mode", "simple")

            try:
                start_ms = int(time.time() * 1000)

                # 2a. Execute task (simple or browser mode)
                result = _execute_task(client, task)

                duration_ms = int(time.time() * 1000) - start_ms

                if result.get("error"):
                    logger.warning(f"Browser task '{task_name}' error: {result['error']}")
                    _increment_failures(store, task_id)
                    tasks_errored += 1
                    continue

                content = result.get("content", "")
                content_hash = result.get("content_hash", "")

                if not content:
                    logger.info(f"Browser task '{task_name}': empty result")
                    _update_last_polled(store, task_id)
                    tasks_polled += 1
                    continue

                # 2b. Change detection
                last_hash = task.get("last_content_hash")
                if content_hash == last_hash:
                    logger.info(f"Browser task '{task_name}': no change detected")
                    _update_last_polled(store, task_id)
                    tasks_unchanged += 1
                    tasks_polled += 1
                    continue

                # 2c. Content changed — store result
                _store_result(
                    store, task_id, content, content_hash,
                    mode_used=task_mode,
                    steps_count=result.get("steps", 0),
                    cost_usd=0,
                    duration_ms=duration_ms,
                    structured_data=result.get("extracted"),
                )

                # 2d. Embed to Qdrant
                _embed_result(store, content, task, config.browser.collection)

                # 2e. Feed to pipeline
                _feed_to_pipeline(content, task)

                # 2f. Update task state
                _update_content_hash(store, task_id, content_hash)
                _update_last_polled(store, task_id)
                _reset_failures(store, task_id)

                tasks_changed += 1
                tasks_polled += 1
                logger.info(f"Browser task '{task_name}': change detected and processed")

            except Exception as e:
                logger.error(f"Browser task '{task_name}' failed: {e}", exc_info=True)
                _increment_failures(store, task_id)
                tasks_errored += 1

        # 3. Summary
        report_success("browser")
        logger.info(
            f"Browser poll complete: {tasks_polled} polled, "
            f"{tasks_changed} changed, {tasks_unchanged} unchanged, "
            f"{tasks_errored} errors"
        )

    except Exception as e:
        report_failure("browser", str(e))
        logger.error(f"browser poll failed: {e}")


def run_single_task(task_id: int) -> dict:
    """Execute a single browser task by ID. Used by POST /api/browser/tasks/{id}/run."""
    client = _get_client()
    store = _get_store()

    from config.settings import config

    task = _get_task_by_id(store, task_id)
    if not task:
        return {"error": f"Task {task_id} not found"}

    start_ms = int(time.time() * 1000)
    result = _execute_task(client, task)
    duration_ms = int(time.time() * 1000) - start_ms

    if result.get("error"):
        return {"error": result["error"], "duration_ms": duration_ms}

    content = result.get("content", "")
    content_hash = result.get("content_hash", "")
    changed = content_hash != task.get("last_content_hash")

    if content:
        _store_result(
            store, task_id, content, content_hash,
            mode_used=task.get("mode", "simple"),
            steps_count=result.get("steps", 0),
            cost_usd=0,
            duration_ms=duration_ms,
            structured_data=result.get("extracted"),
        )
        _update_content_hash(store, task_id, content_hash)
        _update_last_polled(store, task_id)

        if changed:
            _embed_result(store, content, task, config.browser.collection)
            _feed_to_pipeline(content, task)

    return {
        "task_id": task_id,
        "content_length": len(content),
        "content_hash": content_hash,
        "changed": changed,
        "duration_ms": duration_ms,
        "mode": task.get("mode", "simple"),
    }


# -------------------------------------------------------
# Task execution dispatch
# -------------------------------------------------------

def _execute_task(client, task: dict) -> dict:
    """Dispatch to simple or browser mode based on task config."""
    mode = task.get("mode", "simple")
    url = task["url"]

    if mode == "browser":
        prompt = task.get("task_prompt", "Extract the main content from this page")
        return client.run_browser_task(prompt, url)
    else:
        css_selectors = task.get("css_selectors") or {}
        return client.fetch_simple(url, css_selectors if css_selectors else None)


# -------------------------------------------------------
# Database helpers
# -------------------------------------------------------

def _get_active_tasks(store) -> list:
    """Load active browser tasks from PostgreSQL."""
    conn = store._get_conn()
    if not conn:
        return []
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT id, name, url, mode, task_prompt, css_selectors,
                      category, last_polled, last_content_hash
               FROM browser_tasks
               WHERE is_active = TRUE
               ORDER BY id"""
        )
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        cur.close()
        return rows
    except Exception as e:
        logger.error(f"Failed to load browser tasks: {e}")
        return []
    finally:
        store._put_conn(conn)


def _get_task_by_id(store, task_id: int) -> dict:
    """Load a single browser task by ID."""
    conn = store._get_conn()
    if not conn:
        return None
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT id, name, url, mode, task_prompt, css_selectors,
                      category, last_polled, last_content_hash
               FROM browser_tasks WHERE id = %s""",
            (task_id,),
        )
        row = cur.fetchone()
        cur.close()
        if not row:
            return None
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))
    except Exception as e:
        logger.error(f"Failed to load browser task {task_id}: {e}")
        return None
    finally:
        store._put_conn(conn)


def _store_result(store, task_id, content, content_hash, mode_used="simple",
                  steps_count=0, cost_usd=0, duration_ms=0, structured_data=None):
    """Insert a result into browser_results."""
    conn = store._get_conn()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO browser_results
               (task_id, content_hash, content, structured_data, mode_used,
                steps_count, cost_usd, duration_ms)
               VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, %s)""",
            (
                task_id,
                content_hash,
                content[:50000],  # Cap stored content
                json.dumps(structured_data, default=str) if structured_data else None,
                mode_used,
                steps_count,
                cost_usd,
                duration_ms,
            ),
        )
        conn.commit()
        cur.close()
    except Exception as e:
        logger.warning(f"Failed to store browser result for task {task_id}: {e}")
    finally:
        store._put_conn(conn)


def _update_content_hash(store, task_id, content_hash):
    """Update last_content_hash on browser_tasks."""
    conn = store._get_conn()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE browser_tasks SET last_content_hash = %s, updated_at = NOW() WHERE id = %s",
            (content_hash, task_id),
        )
        conn.commit()
        cur.close()
    except Exception as e:
        logger.warning(f"Failed to update content hash for task {task_id}: {e}")
    finally:
        store._put_conn(conn)


def _update_last_polled(store, task_id):
    """Set last_polled timestamp."""
    conn = store._get_conn()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute("UPDATE browser_tasks SET last_polled = NOW() WHERE id = %s", (task_id,))
        conn.commit()
        cur.close()
    except Exception as e:
        logger.warning(f"Failed to update last_polled for task {task_id}: {e}")
    finally:
        store._put_conn(conn)


def _increment_failures(store, task_id):
    """Increment consecutive_failures. Disable task at 5."""
    conn = store._get_conn()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute(
            """UPDATE browser_tasks
               SET consecutive_failures = consecutive_failures + 1,
                   last_polled = NOW()
               WHERE id = %s
               RETURNING consecutive_failures""",
            (task_id,),
        )
        row = cur.fetchone()
        if row and row[0] >= 5:
            cur.execute(
                "UPDATE browser_tasks SET is_active = FALSE WHERE id = %s", (task_id,)
            )
            logger.warning(f"Browser task {task_id} disabled after 5 consecutive failures")
        conn.commit()
        cur.close()
    except Exception as e:
        logger.warning(f"Failed to update failure count for task {task_id}: {e}")
    finally:
        store._put_conn(conn)


def _reset_failures(store, task_id):
    """Reset consecutive_failures to 0 on success."""
    conn = store._get_conn()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE browser_tasks SET consecutive_failures = 0 WHERE id = %s", (task_id,)
        )
        conn.commit()
        cur.close()
    except Exception as e:
        logger.warning(f"Failed to reset failures for task {task_id}: {e}")
    finally:
        store._put_conn(conn)


# -------------------------------------------------------
# Qdrant embedding
# -------------------------------------------------------

def _embed_result(store, content, task, collection):
    """Embed browser result into Qdrant baker-browser collection."""
    task_name = task.get("name", "")
    url = task.get("url", "")
    category = task.get("category", "")

    embed_text = f"[Browser: {task_name}]\nURL: {url}\n{content[:3000]}".strip()

    metadata = {
        "source": "browser",
        "task_name": task_name[:200],
        "url": url[:2000],
        "category": category or "",
        "content_type": "browser_result",
        "label": f"browser:{task_name[:80]}",
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }

    try:
        store.store_document(embed_text, metadata, collection=collection)
    except Exception as e:
        logger.warning(f"Failed to embed browser result '{task_name}' to Qdrant: {e}")


# -------------------------------------------------------
# Pipeline feed
# -------------------------------------------------------

def _feed_to_pipeline(content, task):
    """Feed changed browser content into Sentinel pipeline."""
    try:
        from orchestrator.pipeline import SentinelPipeline, TriggerEvent

        task_name = task.get("name", "")
        url = task.get("url", "")
        category = task.get("category", "")

        trigger = TriggerEvent(
            type="browser_change",
            content=(
                f"[Browser Sentinel: {task_name}]\n"
                f"URL: {url}\n"
                f"Category: {category}\n\n"
                f"{content[:2000]}"
            ),
            source_id=f"browser:{task.get('id', 0)}",
            contact_name=None,
        )

        pipeline = SentinelPipeline()
        pipeline.run(trigger)
    except Exception as e:
        logger.warning(f"Pipeline feed failed for browser task '{task.get('name', '?')}': {e}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")
    run_browser_poll()
