"""
Sentinel Trigger — Todoist (Read-Only)
Polls Todoist API v1 every 30 minutes for projects, tasks, sections, labels, comments.
Upserts results to todoist_tasks table via store_back.
Embeds task content + comments to baker-todoist Qdrant collection.
Feeds updated tasks into the pipeline for classification + alert drafting.
Called by scheduler every 30 minutes.
"""
import hashlib
import json
import logging
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Ensure project root is on sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from triggers.state import trigger_state

logger = logging.getLogger("sentinel.todoist_trigger")

# Todoist priority mapping: API value → human label
# Todoist: 1 = normal, 2 = medium, 3 = high, 4 = urgent
_PRIORITY_MAP = {
    1: "normal",
    2: "medium",
    3: "high",
    4: "urgent",
}

_WATERMARK_KEY = "todoist"


def _get_client():
    """Get the global TodoistClient singleton."""
    from triggers.todoist_client import TodoistClient
    return TodoistClient._get_global_instance()


def _get_store():
    """Get the global SentinelStoreBack singleton."""
    from memory.store_back import SentinelStoreBack
    return SentinelStoreBack._get_global_instance()


def _content_hash(content: str, description: str) -> str:
    """MD5 hash of content + description for change detection."""
    text = f"{content or ''}\n{description or ''}"
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def _build_task_data(task: dict, project_map: dict, section_map: dict,
                     status: str = "active") -> dict:
    """Transform Todoist API task response into storage dict.

    Joins project_name from project_map, section_name from section_map.
    Maps Todoist priority (1=normal, 4=urgent) to human labels.
    Extracts due date from task['due']['date'] or task['due']['datetime'].
    """
    content = task.get("content", "")
    description = task.get("description", "")

    # Extract due date
    due_obj = task.get("due")
    due_date = None
    if due_obj and isinstance(due_obj, dict):
        due_date = due_obj.get("datetime") or due_obj.get("date")

    # Map priority
    priority_val = task.get("priority", 1)
    priority_label = _PRIORITY_MAP.get(priority_val, "normal")

    # Get project/section names
    project_id = task.get("project_id", "")
    section_id = task.get("section_id", "")
    project_name = project_map.get(str(project_id), "")
    section_name = section_map.get(str(section_id), "")

    # Labels (list of strings in API v1)
    labels = task.get("labels", [])

    # Completed timestamp (only for completed tasks from Sync API)
    completed_at = task.get("completed_at") or task.get("completed_date")

    return {
        "todoist_id": str(task.get("id", task.get("task_id", ""))),
        "content": content,
        "description": (description or "")[:5000],  # cap length
        "project_id": str(project_id),
        "project_name": project_name,
        "section_id": str(section_id) if section_id else None,
        "section_name": section_name,
        "priority": priority_val,
        "priority_label": priority_label,
        "due_date": due_date,
        "labels": labels,
        "status": status,
        "created_at": task.get("created_at"),
        "completed_at": completed_at,
        "comment_count": task.get("comment_count", 0),
        "content_hash": _content_hash(content, description),
    }


def _embed_task_to_qdrant(store, task_data: dict):
    """Embed task content + description into baker-todoist Qdrant collection.

    Content format: '[Todoist] {project_name} > {content}\n{description}'
    """
    content = task_data.get("content") or ""
    description = task_data.get("description") or ""
    if not content and not description:
        return

    project_name = task_data.get("project_name", "")
    prefix = f"[Todoist] {project_name} > " if project_name else "[Todoist] "
    embed_content = f"{prefix}{content}\n{description}".strip()

    metadata = {
        "todoist_id": task_data.get("todoist_id"),
        "project_name": project_name,
        "section_name": task_data.get("section_name", ""),
        "priority": task_data.get("priority_label", "normal"),
        "labels": json.dumps(task_data.get("labels", [])),
        "due_date": task_data.get("due_date"),
        "status": task_data.get("status", "active"),
        "content_type": "task",
        "author": "todoist",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "label": f"task:{content[:80]}",
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }
    try:
        store.store_document(embed_content, metadata, collection="baker-todoist")
    except Exception as e:
        logger.warning(f"Failed to embed task {task_data.get('todoist_id')} to Qdrant: {e}")


def _embed_comments_to_qdrant(store, task_data: dict, comments: list):
    """Embed each comment into baker-todoist Qdrant collection.

    Content format: '[Todoist Comment on {task_content}] {comment_content}'
    """
    task_content = task_data.get("content", "?")

    for comment in comments:
        if not isinstance(comment, dict):
            continue

        comment_text = comment.get("content", "")
        if not comment_text.strip():
            continue

        embed_content = f"[Todoist Comment on {task_content}] {comment_text}".strip()

        # Extract poster info
        poster_id = comment.get("posted_by") or "unknown"

        metadata = {
            "todoist_id": task_data.get("todoist_id"),
            "project_name": task_data.get("project_name", ""),
            "content_type": "comment",
            "author": str(poster_id),
            "timestamp": comment.get("posted_at", datetime.now(timezone.utc).isoformat()),
            "label": f"comment:{task_content[:60]}",
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        }
        try:
            store.store_document(embed_content, metadata, collection="baker-todoist")
        except Exception as e:
            logger.warning(f"Failed to embed comment for task {task_data.get('todoist_id')}: {e}")


def _classify_task_change(task_data: dict, is_new: bool) -> str:
    """Classify for pipeline feed.

    Returns: 'todoist_task_created', 'todoist_task_updated',
             'todoist_task_completed', 'todoist_task_overdue'
    """
    status = task_data.get("status", "active")

    # Completed task
    if status == "completed":
        return "todoist_task_completed"

    # Overdue check
    due_date = task_data.get("due_date")
    if due_date:
        try:
            # Parse date or datetime
            if "T" in str(due_date):
                due_dt = datetime.fromisoformat(due_date.replace("Z", "+00:00"))
            else:
                due_dt = datetime.strptime(due_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            if due_dt < datetime.now(timezone.utc):
                return "todoist_task_overdue"
        except (ValueError, TypeError):
            pass

    # New task
    if is_new:
        return "todoist_task_created"

    # Default: update
    return "todoist_task_updated"


def _feed_to_pipeline(task_data: dict, classification: str):
    """Feed updated task into Sentinel pipeline."""
    try:
        from orchestrator.pipeline import SentinelPipeline, TriggerEvent

        content_parts = [
            f"Task: {task_data.get('content', '?')}",
            f"Project: {task_data.get('project_name', '?')}",
            f"Status: {task_data.get('status', '?')}",
            f"Priority: {task_data.get('priority_label', 'normal')}",
        ]
        if task_data.get("description"):
            content_parts.append(f"Description: {task_data['description'][:500]}")
        if task_data.get("due_date"):
            content_parts.append(f"Due: {task_data['due_date']}")

        trigger = TriggerEvent(
            type=classification,
            content="\n".join(content_parts),
            source_id=f"todoist:{task_data.get('todoist_id', '?')}",
            contact_name=None,
        )

        pipeline = SentinelPipeline()
        pipeline.run(trigger)
    except Exception as e:
        logger.warning(f"Pipeline feed failed for task {task_data.get('todoist_id')}: {e}")


def run_todoist_poll():
    """Main entry point — called by scheduler every 30 minutes.

    Algorithm:
    1. Fetch all projects → build project_map {id: name}
    2. Fetch all sections → build section_map {id: name}
    3. Fetch all labels (store for metadata enrichment)
    4. Fetch all active tasks
    5. For each task:
       a. Build task_data via _build_task_data()
       b. Upsert to PostgreSQL via store.upsert_todoist_task()
       c. Embed to Qdrant baker-todoist (if content changed)
       d. Fetch + embed comments (if comment_count > 0)
       e. Classify + feed to pipeline
    6. Fetch completed tasks since last watermark (API v1)
    7. For each completed task: same as steps 5a-5e
    8. Update watermark
    """
    logger.info("Todoist trigger: starting poll...")

    client = _get_client()
    store = _get_store()

    tasks_upserted = 0
    tasks_skipped = 0
    qdrant_writes = 0
    request_count_start = client._request_count

    # -------------------------------------------------------
    # Step 1: Fetch projects → build lookup map
    # -------------------------------------------------------
    try:
        projects = client.get_projects()
        project_map = {str(p["id"]): p.get("name", "") for p in projects}
        logger.info(f"Fetched {len(projects)} Todoist projects")
    except Exception as e:
        logger.error(f"Failed to fetch Todoist projects: {e}")
        return

    # -------------------------------------------------------
    # Step 2: Fetch sections → build lookup map
    # -------------------------------------------------------
    try:
        sections = client.get_sections()
        section_map = {str(s["id"]): s.get("name", "") for s in sections}
        logger.info(f"Fetched {len(sections)} Todoist sections")
    except Exception as e:
        logger.warning(f"Failed to fetch Todoist sections (non-fatal): {e}")
        section_map = {}

    # -------------------------------------------------------
    # Step 3: Fetch labels (for metadata, not critically needed)
    # -------------------------------------------------------
    try:
        labels = client.get_labels()
        logger.info(f"Fetched {len(labels)} Todoist labels")
    except Exception as e:
        logger.warning(f"Failed to fetch Todoist labels (non-fatal): {e}")
        labels = []

    # -------------------------------------------------------
    # Step 4-5: Fetch all active tasks and process
    # -------------------------------------------------------
    try:
        active_tasks = client.get_tasks()
        logger.info(f"Fetched {len(active_tasks)} active Todoist tasks")
    except Exception as e:
        logger.error(f"Failed to fetch Todoist tasks: {e}")
        return

    for task in active_tasks:
        task_data = _build_task_data(task, project_map, section_map, status="active")

        # Upsert to PostgreSQL — returns (task_id, changed) tuple
        try:
            result = store.upsert_todoist_task(task_data)
            if result:
                upserted_id, content_changed = result
                tasks_upserted += 1

                # Only re-embed to Qdrant if content actually changed
                if content_changed:
                    _embed_task_to_qdrant(store, task_data)
                    qdrant_writes += 1
                else:
                    tasks_skipped += 1
            else:
                tasks_skipped += 1
        except Exception as e:
            logger.error(f"Failed to upsert task {task_data.get('todoist_id')}: {e}")
            continue

        # Fetch and embed comments
        comment_count = task.get("comment_count", 0)
        if comment_count and isinstance(comment_count, int) and comment_count > 0:
            try:
                comments = client.get_comments(str(task["id"]))
                if comments:
                    _embed_comments_to_qdrant(store, task_data, comments)
                    qdrant_writes += len(comments)
            except Exception as e:
                logger.warning(f"Failed to fetch comments for task {task.get('id')}: {e}")

        # Classify and feed to pipeline (only for new/changed tasks)
        if result and result[1]:  # content_changed
            is_new = result and not result[1]  # first upsert = changed but no prior hash
            classification = _classify_task_change(task_data, is_new=False)
            _feed_to_pipeline(task_data, classification)

    # -------------------------------------------------------
    # Step 6-7: Fetch completed tasks since last watermark
    # -------------------------------------------------------
    watermark_dt = trigger_state.get_watermark(_WATERMARK_KEY)
    since_str = watermark_dt.isoformat()

    completed_count = 0
    offset = 0
    while True:
        try:
            completed_tasks = client.get_completed_tasks(
                since=since_str, limit=200, offset=offset
            )
        except Exception as e:
            logger.warning(f"Failed to fetch completed tasks (offset={offset}): {e}")
            break

        if not completed_tasks:
            break

        for task in completed_tasks:
            task_data = _build_task_data(task, project_map, section_map, status="completed")

            try:
                result = store.upsert_todoist_task(task_data)
                if result:
                    upserted_id, content_changed = result
                    tasks_upserted += 1
                    if content_changed:
                        _embed_task_to_qdrant(store, task_data)
                        qdrant_writes += 1

                    classification = _classify_task_change(task_data, is_new=False)
                    _feed_to_pipeline(task_data, classification)
                    completed_count += 1
            except Exception as e:
                logger.error(f"Failed to process completed task {task_data.get('todoist_id')}: {e}")

        # Paginate
        if len(completed_tasks) < 200:
            break
        offset += 200

    # -------------------------------------------------------
    # Step 8: Update watermark
    # -------------------------------------------------------
    trigger_state.set_watermark(_WATERMARK_KEY, datetime.now(timezone.utc))

    requests_used = client._request_count - request_count_start

    logger.info(
        f"Todoist poll complete: {tasks_upserted} upserted, {tasks_skipped} skipped (unchanged), "
        f"{qdrant_writes} Qdrant writes, {completed_count} completed tasks "
        f"({requests_used} API requests)"
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")
    run_todoist_poll()
