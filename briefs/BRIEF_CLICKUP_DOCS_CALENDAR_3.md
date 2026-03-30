# BRIEF: ClickUp Document Ingestion + ClickUp-to-Baker Deadline Sync

**Priority:** Medium — ClickUp attachments invisible to Baker, deadline sync prevents stale alerts
**Ticket:** CLICKUP-DOCS-CALENDAR-3
**Depends on:** CLICKUP-DROPDOWN-2 (write guard changes)

## Part A: ClickUp Attachment Ingestion

### Problem

Baker polls ClickUp tasks for titles, descriptions, statuses, and assignees. But file attachments on tasks (contracts, spec sheets, site photos, PDFs) are completely ignored. These documents are invisible to Baker and the Documents section.

### Fix

During the existing ClickUp poll, also check for attachments on tasks. Download and run through the existing classify → extract document pipeline.

### Change A1: Add get_task_attachments() to ClickUp client

**File:** `clickup_client.py`

```python
def get_task_attachments(self, task_id: str) -> list:
    """Fetch attachments for a ClickUp task. Returns list of dicts."""
    try:
        resp = self._get(f"task/{task_id}")  # Full task detail includes attachments
        return resp.get("attachments", [])
    except Exception as e:
        logger.debug(f"Failed to fetch attachments for task {task_id}: {e}")
        return []
```

**IMPORTANT:** Check the ClickUp API docs — attachments may be in the task detail response directly, or may need a separate endpoint. Check what the existing `_get()` method returns for a task. The attachment objects typically have: `id`, `title`, `url`, `extension`, `date`.

### Change A2: Process attachments during poll

**File:** `triggers/clickup_trigger.py`

After processing each task (inside the existing task loop), add attachment check:

```python
# After storing/updating the task in clickup_tasks table:
try:
    _process_task_attachments(client, task['id'], task.get('name', ''), matter_slug)
except Exception as e:
    logger.debug(f"ClickUp attachment processing failed for {task['id']}: {e}")
```

Add the processing function:

```python
def _process_task_attachments(client, task_id: str, task_name: str, matter: str):
    """Download and ingest ClickUp task attachments through document pipeline."""
    attachments = client.get_task_attachments(task_id)
    if not attachments:
        return

    import httpx
    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack._get_global_instance()

    for att in attachments:
        url = att.get("url")
        title = att.get("title") or att.get("name") or "untitled"
        source_id = f"clickup_att:{task_id}:{att.get('id', title)}"

        # Skip if already ingested (dedup by source_id)
        conn = store._get_conn()
        if not conn:
            continue
        try:
            cur = conn.cursor()
            cur.execute("SELECT id FROM documents WHERE source_id = %s LIMIT 1", (source_id,))
            if cur.fetchone():
                cur.close()
                continue  # Already ingested
            cur.close()
        finally:
            store._put_conn(conn)

        # Download
        try:
            resp = httpx.get(url, timeout=30, follow_redirects=True)
            if resp.status_code != 200:
                continue
        except Exception:
            continue

        # Feed through document pipeline
        try:
            from tools.document_pipeline import queue_document_job
            queue_document_job(
                content=resp.content,
                filename=title,
                source="clickup",
                source_id=source_id,
                matter=matter,
                metadata={
                    "clickup_task_id": task_id,
                    "clickup_task_name": task_name,
                }
            )
            logger.info(f"Queued ClickUp attachment: {title} from task {task_id}")
        except Exception as e:
            logger.debug(f"ClickUp attachment pipeline failed for {title}: {e}")
```

**IMPORTANT:** Check what the document pipeline entry point is. It might be `queue_document_job()`, `process_document()`, or something else. Look at how `triggers/dropbox_trigger.py` feeds documents into the pipeline and follow the same pattern.

### Change A3: Rate limit

Don't fetch attachments for every task on every poll cycle — that would be too many API calls. Add a simple guard:

```python
# Only check attachments for tasks updated in the last 24 hours
if task.get('date_updated'):
    updated_ms = int(task['date_updated'])
    updated_dt = datetime.fromtimestamp(updated_ms / 1000, tz=timezone.utc)
    if (datetime.now(timezone.utc) - updated_dt).total_seconds() < 86400:
        _process_task_attachments(client, task['id'], task.get('name', ''), matter_slug)
```

## Part B: ClickUp Due Date → Baker Deadline Sync

### Problem

Baker has its own `deadlines` table, and ClickUp tasks have due dates. These are two separate systems. When a ClickUp task is overdue, Baker's deadline system doesn't know about it unless someone manually created a matching Baker deadline. This causes missed alerts.

### Fix

During the ClickUp poll, sync task due dates to Baker's deadlines table. When a ClickUp task is completed, mark the corresponding Baker deadline as done.

### Change B1: Sync due dates during poll

**File:** `triggers/clickup_trigger.py`

After processing each task:

```python
# Sync ClickUp due dates to Baker deadlines
if task.get('due_date'):
    try:
        due_ms = int(task['due_date'])
        due_dt = datetime.fromtimestamp(due_ms / 1000, tz=timezone.utc)
        _sync_clickup_deadline(
            task_id=task['id'],
            task_name=task.get('name', 'Untitled'),
            due_date=due_dt,
            list_name=list_name,
            space_name=space_name,
            task_status=task.get('status', {}).get('status', ''),
        )
    except Exception as e:
        logger.debug(f"ClickUp deadline sync failed for {task['id']}: {e}")
```

### Change B2: Sync function

```python
def _sync_clickup_deadline(task_id, task_name, due_date, list_name, space_name, task_status):
    """Upsert a Baker deadline from a ClickUp task due date."""
    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    if not conn:
        return
    source_tag = f"clickup_deadline:{task_id}"
    try:
        cur = conn.cursor()

        # Check if ClickUp task is completed
        is_done = task_status.lower() in ('complete', 'closed', 'done', 'resolved')

        # Check if deadline already exists
        cur.execute("SELECT id, status FROM deadlines WHERE source_snippet = %s LIMIT 1", (source_tag,))
        existing = cur.fetchone()

        if existing:
            deadline_id, current_status = existing
            if is_done and current_status == 'active':
                # Task completed in ClickUp → mark Baker deadline done
                cur.execute("UPDATE deadlines SET status = 'completed' WHERE id = %s", (deadline_id,))
                logger.info(f"ClickUp deadline completed: {task_name}")
            elif not is_done:
                # Update due date if changed
                cur.execute("UPDATE deadlines SET due_date = %s WHERE id = %s AND due_date != %s",
                           (due_date, deadline_id, due_date))
        elif not is_done:
            # Create new deadline
            description = f"[{space_name}/{list_name}] {task_name}"
            cur.execute("""
                INSERT INTO deadlines (description, due_date, priority, source_snippet, status, confidence)
                VALUES (%s, %s, %s, %s, 'active', 'high')
            """, (description, due_date, 'normal', source_tag))
            logger.info(f"ClickUp deadline synced: {task_name} due {due_date}")

        conn.commit()
        cur.close()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.debug(f"ClickUp deadline sync DB error: {e}")
    finally:
        store._put_conn(conn)
```

**IMPORTANT:** Check the `deadlines` table schema first:
```sql
SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'deadlines';
```
Adapt column names to match. The `source_snippet` column is used as a unique tag for the ClickUp task ID — verify it exists and is the right field to use.

## Files to Modify

| File | Change |
|------|--------|
| `clickup_client.py` | get_task_attachments() method |
| `triggers/clickup_trigger.py` | Attachment processing + deadline sync in poll loop |

## Verification

Part A:
1. Find a ClickUp task with a PDF attachment
2. Wait for next ClickUp poll (5 min) or trigger manually
3. Check Documents section → document appears with source=clickup
4. "Ask Baker about [document name]" → Baker finds it

Part B:
1. Find a ClickUp task with a due date
2. Wait for next poll → check `deadlines` table for matching entry
3. Mark the ClickUp task as complete → next poll marks Baker deadline as completed
4. Promised To Do card no longer shows the completed item

## Rules

- Check all table schemas and existing methods before writing SQL/code
- `conn.rollback()` in all except blocks
- Rate limit: only process attachments for tasks updated in last 24h
- Syntax check all modified files before commit
- Never force push
- git pull before starting
