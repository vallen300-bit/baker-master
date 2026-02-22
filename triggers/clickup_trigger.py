"""
Sentinel Trigger — ClickUp (Multi-Workspace)
Polls all 6 ClickUp workspaces for updated tasks every 5 minutes.
Upserts results to clickup_tasks table via store_back.
Embeds task descriptions + comments to baker-clickup Qdrant collection.
Feeds updated tasks into the pipeline for classification + alert drafting.
Called by scheduler every 5 minutes.
"""
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

logger = logging.getLogger("sentinel.clickup_trigger")

# All 6 ClickUp workspaces to poll
CLICKUP_WORKSPACE_IDS = [
    "2652545",
    "24368967",
    "24382372",
    "24382764",
    "24385290",
    "9004065517",
]

# BAKER space — the only space Baker can write to
_BAKER_SPACE_ID = "901510186446"

# Handoff Notes list — direct communication, treat as high priority
_HANDOFF_NOTES_LIST_ID = "901521426367"


def _get_client():
    """Get the global ClickUpClient singleton."""
    from clickup_client import ClickUpClient
    return ClickUpClient._get_global_instance()


def _get_store():
    """Get the global SentinelStoreBack singleton."""
    from memory.store_back import SentinelStoreBack
    return SentinelStoreBack._get_global_instance()


def _watermark_key(workspace_id: str) -> str:
    """Watermark key for a given workspace."""
    return f"clickup_{workspace_id}"


def _parse_clickup_timestamp(ts) -> datetime:
    """Convert ClickUp millisecond timestamp to datetime, or return None."""
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(int(ts) / 1000, tz=timezone.utc)
    except (ValueError, TypeError, OSError):
        return None


def _build_task_data(task: dict, space_id: str, workspace_id: str) -> dict:
    """
    Transform a ClickUp API task response into the dict expected by
    store_back.upsert_clickup_task().
    """
    # Extract status name
    status_obj = task.get("status", {})
    status_name = status_obj.get("status") if isinstance(status_obj, dict) else None

    # Extract priority name
    priority_obj = task.get("priority")
    priority_name = None
    if isinstance(priority_obj, dict) and priority_obj:
        priority_name = priority_obj.get("priority")

    # Extract assignee names
    assignees_raw = task.get("assignees", [])
    assignees = []
    for a in assignees_raw:
        if isinstance(a, dict):
            assignees.append({
                "id": a.get("id"),
                "username": a.get("username"),
                "email": a.get("email"),
            })

    # Extract tag names
    tags_raw = task.get("tags", [])
    tags = []
    for t in tags_raw:
        if isinstance(t, dict):
            tags.append(t.get("name", ""))
        elif isinstance(t, str):
            tags.append(t)

    # List info
    list_obj = task.get("list", {})
    list_id = list_obj.get("id") if isinstance(list_obj, dict) else None
    list_name = list_obj.get("name") if isinstance(list_obj, dict) else None

    return {
        "id": task.get("id"),
        "name": task.get("name"),
        "description": (task.get("description") or "")[:5000],  # cap length
        "status": status_name,
        "priority": priority_name,
        "due_date": _parse_clickup_timestamp(task.get("due_date")),
        "date_created": _parse_clickup_timestamp(task.get("date_created")),
        "date_updated": _parse_clickup_timestamp(task.get("date_updated")),
        "list_id": list_id,
        "list_name": list_name,
        "space_id": space_id,
        "workspace_id": workspace_id,
        "assignees": assignees,
        "tags": tags,
        "comment_count": task.get("comment_count", 0),
        "baker_tier": None,
        "baker_writable": str(space_id) == _BAKER_SPACE_ID,
    }


def _classify_task_change(task_data: dict, is_new: bool) -> str:
    """
    Determine the ClickUp classification type for a task change.
    Returns one of the 8 classification types from prompt_builder.
    """
    list_id = task_data.get("list_id")
    status = (task_data.get("status") or "").lower()
    due_date = task_data.get("due_date")

    # Handoff Notes list = direct communication
    if str(list_id) == _HANDOFF_NOTES_LIST_ID:
        return "clickup_handoff_note"

    # Overdue check
    if due_date and isinstance(due_date, datetime) and due_date < datetime.now(timezone.utc):
        return "clickup_task_overdue"

    # New task
    if is_new:
        return "clickup_task_created"

    # Status change detection (blocked/closed/complete keywords)
    if status in ("complete", "closed", "blocked", "in progress", "review"):
        return "clickup_status_change"

    # Default: generic update
    return "clickup_task_updated"


def _embed_task_to_qdrant(store, task_data: dict):
    """Embed a task description into baker-clickup Qdrant collection."""
    description = task_data.get("description") or ""
    name = task_data.get("name") or ""
    if not description and not name:
        return

    content = f"[ClickUp Task] {name}\n{description}".strip()
    metadata = {
        "task_id": task_data.get("id"),
        "list_name": task_data.get("list_name"),
        "workspace_id": task_data.get("workspace_id"),
        "space_id": task_data.get("space_id"),
        "content_type": "description",
        "status": task_data.get("status"),
        "priority": task_data.get("priority"),
        "author": "clickup",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "label": f"task:{task_data.get('name', '')[:80]}",
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }
    try:
        store.store_document(content, metadata, collection="baker-clickup")
    except Exception as e:
        logger.warning(f"Failed to embed task {task_data.get('id')} to Qdrant: {e}")


def _embed_comments_to_qdrant(store, task_data: dict, comments: list):
    """Embed each comment into baker-clickup Qdrant collection."""
    for comment in comments:
        comment_text = ""
        # ClickUp comments have nested comment_text or text field
        if isinstance(comment, dict):
            comment_text = comment.get("comment_text") or comment.get("text_content") or ""
            # Some comments have nested comment array
            comment_items = comment.get("comment", [])
            if isinstance(comment_items, list):
                for item in comment_items:
                    if isinstance(item, dict) and item.get("text"):
                        comment_text += item["text"]

        if not comment_text.strip():
            continue

        author = "unknown"
        user_obj = comment.get("user", {})
        if isinstance(user_obj, dict):
            author = user_obj.get("username") or user_obj.get("email") or "unknown"

        content = f"[ClickUp Comment on {task_data.get('name', '?')}] {comment_text}".strip()
        metadata = {
            "task_id": task_data.get("id"),
            "list_name": task_data.get("list_name"),
            "workspace_id": task_data.get("workspace_id"),
            "space_id": task_data.get("space_id"),
            "content_type": "comment",
            "author": author,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "label": f"comment:{task_data.get('name', '')[:60]}",
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        }
        try:
            store.store_document(content, metadata, collection="baker-clickup")
        except Exception as e:
            logger.warning(f"Failed to embed comment for task {task_data.get('id')}: {e}")


def _feed_to_pipeline(task_data: dict, classification: str):
    """Feed an updated task into the Sentinel pipeline for classification + alerts."""
    try:
        from orchestrator.pipeline import SentinelPipeline, TriggerEvent

        # Build trigger content from task data
        content_parts = [
            f"Task: {task_data.get('name', '?')}",
            f"List: {task_data.get('list_name', '?')}",
            f"Status: {task_data.get('status', '?')}",
            f"Priority: {task_data.get('priority', 'none')}",
        ]
        if task_data.get("description"):
            content_parts.append(f"Description: {task_data['description'][:500]}")

        trigger = TriggerEvent(
            type=classification,
            content="\n".join(content_parts),
            source_id=f"clickup:{task_data.get('id', '?')}",
            contact_name=None,
        )

        pipeline = SentinelPipeline()
        pipeline.run(trigger)
    except Exception as e:
        logger.warning(f"Pipeline feed failed for task {task_data.get('id')}: {e}")


def _poll_workspace(client, store, workspace_id: str) -> int:
    """
    Poll a single workspace for updated tasks.
    Upserts to PostgreSQL, embeds to Qdrant, feeds pipeline.
    Returns number of tasks upserted.
    """
    watermark_key = _watermark_key(workspace_id)
    watermark_dt = trigger_state.get_watermark(watermark_key)
    watermark_ms = int(watermark_dt.timestamp() * 1000)

    tasks_upserted = 0

    try:
        spaces = client.get_spaces(workspace_id)
    except Exception as e:
        logger.error(f"Failed to get spaces for workspace {workspace_id}: {e}")
        return 0

    if not spaces:
        logger.info(f"Workspace {workspace_id}: no spaces returned")
        return 0

    for space in spaces:
        space_id = space.get("id")
        space_name = space.get("name", "?")

        try:
            lists = client.get_lists(space_id)
        except Exception as e:
            logger.error(f"Failed to get lists for space {space_name} ({space_id}): {e}")
            continue

        if not lists:
            continue

        for lst in lists:
            list_id = lst.get("id")
            list_name = lst.get("name", "?")

            try:
                tasks = client.get_tasks(list_id, date_updated_gt=watermark_ms)
            except Exception as e:
                logger.error(f"Failed to get tasks for list {list_name} ({list_id}): {e}")
                continue

            if not tasks:
                continue

            for task in tasks:
                task_data = _build_task_data(task, space_id, workspace_id)

                # Check if this is a new task (date_created == date_updated within 1 second)
                is_new = False
                dc = task_data.get("date_created")
                du = task_data.get("date_updated")
                if dc and du and isinstance(dc, datetime) and isinstance(du, datetime):
                    is_new = abs((du - dc).total_seconds()) < 2

                try:
                    result = store.upsert_clickup_task(task_data)
                    if result:
                        tasks_upserted += 1
                except Exception as e:
                    logger.error(f"Failed to upsert task {task.get('id')}: {e}")

                # Embed task description to Qdrant baker-clickup
                _embed_task_to_qdrant(store, task_data)

                # Fetch and embed comments
                comment_count = task.get("comment_count", 0)
                comments = []
                if comment_count and isinstance(comment_count, int) and comment_count > 0:
                    try:
                        comments = client.get_task_comments(task.get("id"))
                        _embed_comments_to_qdrant(store, task_data, comments)
                        logger.debug(
                            f"Task {task.get('id')}: {len(comments)} comments embedded"
                        )
                    except Exception as e:
                        logger.error(f"Failed to fetch/embed comments for task {task.get('id')}: {e}")

                # Classify and feed to pipeline
                classification = _classify_task_change(task_data, is_new)
                _feed_to_pipeline(task_data, classification)

    # Update watermark after successful processing
    trigger_state.set_watermark(watermark_key, datetime.now(timezone.utc))
    return tasks_upserted


def run_clickup_poll():
    """
    Main entry point — called by scheduler every 5 minutes.
    Polls all 6 ClickUp workspaces for updated tasks, upserts to PostgreSQL.
    """
    logger.info("ClickUp trigger: starting multi-workspace poll...")

    client = _get_client()
    store = _get_store()

    # Reset per-cycle write counter
    client.reset_cycle_counter()

    total_tasks = 0
    workspaces_processed = 0
    request_count_start = client._request_count

    for workspace_id in CLICKUP_WORKSPACE_IDS:
        try:
            tasks = _poll_workspace(client, store, workspace_id)
            total_tasks += tasks
            workspaces_processed += 1
            logger.info(f"Workspace {workspace_id}: {tasks} tasks upserted")
        except Exception as e:
            logger.error(f"ClickUp trigger: workspace {workspace_id} failed: {e}")
            # Continue to next workspace — never let one failure crash the poll

    requests_used = client._request_count - request_count_start

    logger.info(
        f"ClickUp poll complete: {total_tasks} tasks upserted across "
        f"{workspaces_processed} workspaces ({requests_used} API requests)"
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")
    run_clickup_poll()
