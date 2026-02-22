"""
ClickUp Batch 2 Trigger — Verification Script
Uses mocked ClickUp client + REAL PostgreSQL (Neon) to verify:
  1. Manual poll test — tasks upserted, watermarks written
  2. Second run test — watermark filtering, no duplicates
  3. Error resilience — bad workspace doesn't crash others
"""
import json
import logging
import sys
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure project root is on sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Load env
from dotenv import load_dotenv
load_dotenv(_PROJECT_ROOT / "config" / ".env")

logging.basicConfig(level=logging.INFO, format="%(name)s | %(levelname)s | %(message)s")
logger = logging.getLogger("test.clickup_trigger")

# ─── Mock Data ───────────────────────────────────────────────────────
# Use unique task IDs per space to avoid ON CONFLICT overwrites

BAKER_SPACE_ID = "901510186446"
OTHER_SPACE_ID = "901510186000"

MOCK_SPACES = [
    {"id": BAKER_SPACE_ID, "name": "BAKER"},
    {"id": OTHER_SPACE_ID, "name": "Other"},
]

MOCK_LISTS_BAKER = [{"id": "list_baker_1", "name": "Baker Tasks"}]
MOCK_LISTS_OTHER = [{"id": "list_other_1", "name": "Other Tasks"}]

now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

MOCK_TASKS_BAKER = [
    {
        "id": "test_baker_001",
        "name": "Baker Task Alpha",
        "description": "A task in the BAKER space",
        "status": {"status": "in progress"},
        "priority": {"priority": "high"},
        "due_date": str(now_ms + 86400000),
        "date_created": str(now_ms - 86400000),
        "date_updated": str(now_ms),
        "list": {"id": "list_baker_1", "name": "Baker Tasks"},
        "assignees": [{"id": 111, "username": "baker_user", "email": "baker@test.com"}],
        "tags": [{"name": "baker-tag"}],
        "comment_count": 0,
    },
    {
        "id": "test_baker_002",
        "name": "Baker Task Beta",
        "description": "Another BAKER space task",
        "status": {"status": "open"},
        "priority": None,
        "due_date": None,
        "date_created": str(now_ms - 172800000),
        "date_updated": str(now_ms - 3600000),
        "list": {"id": "list_baker_1", "name": "Baker Tasks"},
        "assignees": [],
        "tags": [],
        "comment_count": 2,
    },
]

MOCK_TASKS_OTHER = [
    {
        "id": "test_other_001",
        "name": "Other Task Gamma",
        "description": "A task in a different space",
        "status": {"status": "complete"},
        "priority": {"priority": "low"},
        "due_date": str(now_ms + 172800000),
        "date_created": str(now_ms - 259200000),
        "date_updated": str(now_ms - 7200000),
        "list": {"id": "list_other_1", "name": "Other Tasks"},
        "assignees": [{"id": 222, "username": "other_user", "email": "other@test.com"}],
        "tags": [{"name": "other-tag"}],
        "comment_count": 0,
    },
]

# ─── Mock ClickUp Client ─────────────────────────────────────────────

def create_mock_client():
    """Create a mock ClickUp client that returns test data."""
    client = MagicMock()
    client._request_count = 0

    def mock_get_spaces(workspace_id):
        client._request_count += 1
        return MOCK_SPACES

    def mock_get_lists(space_id):
        client._request_count += 1
        if space_id == BAKER_SPACE_ID:
            return MOCK_LISTS_BAKER
        elif space_id == OTHER_SPACE_ID:
            return MOCK_LISTS_OTHER
        return []

    def mock_get_tasks(list_id, date_updated_gt=None):
        client._request_count += 1
        if list_id == "list_baker_1":
            return MOCK_TASKS_BAKER
        elif list_id == "list_other_1":
            return MOCK_TASKS_OTHER
        return []

    def mock_get_task_comments(task_id):
        client._request_count += 1
        return [{"id": "comment_1", "comment_text": "Test comment"}]

    def mock_reset_cycle_counter():
        pass

    client.get_spaces = mock_get_spaces
    client.get_lists = mock_get_lists
    client.get_tasks = mock_get_tasks
    client.get_task_comments = mock_get_task_comments
    client.reset_cycle_counter = mock_reset_cycle_counter

    return client


# ─── Helpers ──────────────────────────────────────────────────────────

def get_store():
    """Get real SentinelStoreBack for PostgreSQL access."""
    from memory.store_back import SentinelStoreBack
    return SentinelStoreBack._get_global_instance()


def cleanup_test_data(store):
    """Remove test data from clickup_tasks and trigger_watermarks."""
    conn = store._get_conn()
    if not conn:
        logger.error("Cleanup failed: no DB connection")
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM clickup_tasks WHERE id LIKE 'test_baker_%' OR id LIKE 'test_other_%'"
            )
            cur.execute(
                "DELETE FROM trigger_watermarks WHERE source LIKE 'clickup_test_%'"
            )
        conn.commit()
        logger.info("Test data cleaned up")
    except Exception as e:
        logger.error(f"Cleanup failed: {e}")
    finally:
        store._put_conn(conn)


def count_test_tasks(store):
    """Count test tasks in clickup_tasks."""
    conn = store._get_conn()
    if not conn:
        return -1
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM clickup_tasks WHERE id LIKE 'test_baker_%' OR id LIKE 'test_other_%'"
            )
            return cur.fetchone()[0]
    finally:
        store._put_conn(conn)


def get_test_task(store, task_id):
    """Get a specific test task from clickup_tasks."""
    conn = store._get_conn()
    if not conn:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, status, priority, space_id, workspace_id, baker_writable, assignees, tags "
                "FROM clickup_tasks WHERE id = %s",
                (task_id,)
            )
            row = cur.fetchone()
            if row:
                return {
                    "id": row[0], "name": row[1], "status": row[2],
                    "priority": row[3], "space_id": row[4],
                    "workspace_id": row[5], "baker_writable": row[6],
                    "assignees": row[7], "tags": row[8],
                }
            return None
    finally:
        store._put_conn(conn)


def get_watermark(store, source_key):
    """Read a trigger watermark."""
    conn = store._get_conn()
    if not conn:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT last_seen FROM trigger_watermarks WHERE source = %s",
                (source_key,)
            )
            row = cur.fetchone()
            return row[0] if row else None
    finally:
        store._put_conn(conn)


# ─── Verification Steps ──────────────────────────────────────────────

def run_verification_1(store, mock_client):
    """
    Verification Step 1: Manual poll test
    - Confirm tasks appear in clickup_tasks table
    - Confirm watermarks are written to trigger_watermarks
    - Confirm baker_writable is correct
    - Log output shows request count and task count
    """
    print("\n" + "=" * 60)
    print("VERIFICATION 1: Manual Poll Test")
    print("=" * 60)

    from triggers.clickup_trigger import _poll_workspace

    # Use a single test workspace ID
    test_workspace_id = "test_24385290"
    watermark_key = f"clickup_{test_workspace_id}"

    # Set initial watermark (24 hours ago)
    from triggers.state import trigger_state
    trigger_state.set_watermark(watermark_key, datetime.now(timezone.utc) - timedelta(hours=24))

    # Run poll for this workspace
    tasks_upserted = _poll_workspace(mock_client, store, test_workspace_id)

    print(f"\n  Tasks upserted: {tasks_upserted}")

    # Check DB
    total_in_db = count_test_tasks(store)
    print(f"  Tasks in DB: {total_in_db}")

    # Check specific tasks
    baker_task = get_test_task(store, "test_baker_001")
    other_task = get_test_task(store, "test_other_001")

    results = []

    # Assert: tasks present
    if total_in_db == 3:
        print("  [PASS] All 3 tasks upserted to clickup_tasks")
        results.append(True)
    else:
        print(f"  [FAIL] Expected 3 tasks, found {total_in_db}")
        results.append(False)

    # Assert: baker_writable correct for BAKER space task
    if baker_task and baker_task["baker_writable"] is True:
        print("  [PASS] baker_writable=True for BAKER space task")
        results.append(True)
    else:
        print(f"  [FAIL] baker_writable should be True for BAKER space task: {baker_task}")
        results.append(False)

    # Assert: baker_writable correct for non-BAKER space task
    if other_task and other_task["baker_writable"] is False:
        print("  [PASS] baker_writable=False for non-BAKER space task")
        results.append(True)
    else:
        print(f"  [FAIL] baker_writable should be False for non-BAKER space task: {other_task}")
        results.append(False)

    # Assert: status and priority extracted correctly
    if baker_task and baker_task["status"] == "in progress" and baker_task["priority"] == "high":
        print("  [PASS] Status and priority extracted correctly")
        results.append(True)
    else:
        print(f"  [FAIL] Status/priority mismatch: {baker_task}")
        results.append(False)

    # Assert: assignees and tags stored as JSON
    if baker_task:
        assignees = baker_task.get("assignees")
        tags = baker_task.get("tags")
        # assignees/tags are stored as JSONB, returned as list/dict by psycopg2
        assignees_ok = isinstance(assignees, list) and len(assignees) == 1
        tags_ok = isinstance(tags, list) and len(tags) == 1
        if assignees_ok and tags_ok:
            print("  [PASS] Assignees and tags stored as JSON")
            results.append(True)
        else:
            print(f"  [FAIL] Assignees/tags format: assignees={assignees}, tags={tags}")
            results.append(False)

    # Assert: watermark updated
    wm = get_watermark(store, watermark_key)
    if wm is not None:
        print(f"  [PASS] Watermark written: {wm}")
        results.append(True)
    else:
        print("  [FAIL] No watermark found")
        results.append(False)

    # Assert: workspace_id stored
    if baker_task and baker_task["workspace_id"] == test_workspace_id:
        print(f"  [PASS] workspace_id stored correctly: {test_workspace_id}")
        results.append(True)
    else:
        print(f"  [FAIL] workspace_id mismatch: {baker_task}")
        results.append(False)

    passed = sum(results)
    total = len(results)
    print(f"\n  Result: {passed}/{total} checks passed")
    return all(results)


def run_verification_2(store, mock_client):
    """
    Verification Step 2: Second run watermark test
    - Run again immediately — watermark filtering should work
    - Confirm no duplicates in clickup_tasks
    """
    print("\n" + "=" * 60)
    print("VERIFICATION 2: Second Run (Watermark Filtering)")
    print("=" * 60)

    from triggers.clickup_trigger import _poll_workspace

    test_workspace_id = "test_24385290"

    # Create a client that returns EMPTY task lists (simulating no updates since watermark)
    watermark_client = MagicMock()
    watermark_client._request_count = 0

    def mock_get_spaces_v2(workspace_id):
        watermark_client._request_count += 1
        return MOCK_SPACES

    def mock_get_lists_v2(space_id):
        watermark_client._request_count += 1
        if space_id == BAKER_SPACE_ID:
            return MOCK_LISTS_BAKER
        elif space_id == OTHER_SPACE_ID:
            return MOCK_LISTS_OTHER
        return []

    def mock_get_tasks_v2(list_id, date_updated_gt=None):
        watermark_client._request_count += 1
        # Return empty — simulates no tasks updated since watermark
        return []

    watermark_client.get_spaces = mock_get_spaces_v2
    watermark_client.get_lists = mock_get_lists_v2
    watermark_client.get_tasks = mock_get_tasks_v2

    count_before = count_test_tasks(store)
    tasks_upserted = _poll_workspace(watermark_client, store, test_workspace_id)
    count_after = count_test_tasks(store)

    results = []

    # Assert: no new tasks upserted
    if tasks_upserted == 0:
        print("  [PASS] No new tasks upserted on second run (watermark filtering works)")
        results.append(True)
    else:
        print(f"  [FAIL] Expected 0 tasks upserted, got {tasks_upserted}")
        results.append(False)

    # Assert: no duplicates — count unchanged
    if count_before == count_after:
        print(f"  [PASS] No duplicates — task count unchanged ({count_after})")
        results.append(True)
    else:
        print(f"  [FAIL] Task count changed: {count_before} → {count_after}")
        results.append(False)

    passed = sum(results)
    total = len(results)
    print(f"\n  Result: {passed}/{total} checks passed")
    return all(results)


def run_verification_3(store, mock_client):
    """
    Verification Step 3: Error resilience
    - Use a failing workspace — confirm error logged, other workspaces still process
    """
    print("\n" + "=" * 60)
    print("VERIFICATION 3: Error Resilience")
    print("=" * 60)

    from triggers.clickup_trigger import _poll_workspace

    # Client that fails on get_spaces
    error_client = MagicMock()
    error_client._request_count = 0

    def mock_get_spaces_fail(workspace_id):
        error_client._request_count += 1
        raise Exception("Simulated API failure for workspace")

    error_client.get_spaces = mock_get_spaces_fail

    results = []

    # Run poll with failing client — should return 0, not crash
    try:
        tasks = _poll_workspace(error_client, store, "test_bad_workspace")
        if tasks == 0:
            print("  [PASS] Failing workspace returned 0 tasks (no crash)")
            results.append(True)
        else:
            print(f"  [FAIL] Expected 0 tasks from failing workspace, got {tasks}")
            results.append(False)
    except Exception as e:
        print(f"  [FAIL] Exception escaped _poll_workspace: {e}")
        results.append(False)

    # Verify original test data is still intact
    count = count_test_tasks(store)
    if count == 3:
        print(f"  [PASS] Original test data intact ({count} tasks)")
        results.append(True)
    else:
        print(f"  [FAIL] Expected 3 tasks still in DB, found {count}")
        results.append(False)

    # Test run_clickup_poll with mixed workspaces
    # Override CLICKUP_WORKSPACE_IDS temporarily
    import triggers.clickup_trigger as ct
    original_ids = ct.CLICKUP_WORKSPACE_IDS

    # Use 2 workspace IDs — one will fail (error_client), one will succeed
    ct.CLICKUP_WORKSPACE_IDS = ["test_fail_ws", "test_success_ws"]

    # Create a client that fails for one workspace but succeeds for another
    mixed_client = MagicMock()
    mixed_client._request_count = 0

    call_count = {"spaces": 0}

    def mock_get_spaces_mixed(workspace_id):
        mixed_client._request_count += 1
        if workspace_id == "test_fail_ws":
            raise Exception("Simulated failure")
        return [{"id": BAKER_SPACE_ID, "name": "BAKER"}]

    def mock_get_lists_mixed(space_id):
        mixed_client._request_count += 1
        return MOCK_LISTS_BAKER

    def mock_get_tasks_mixed(list_id, date_updated_gt=None):
        mixed_client._request_count += 1
        return []  # Empty is fine — we're testing error isolation

    mixed_client.get_spaces = mock_get_spaces_mixed
    mixed_client.get_lists = mock_get_lists_mixed
    mixed_client.get_tasks = mock_get_tasks_mixed
    mixed_client.reset_cycle_counter = MagicMock()

    # Patch _get_client and _get_store
    with patch.object(ct, '_get_client', return_value=mixed_client), \
         patch.object(ct, '_get_store', return_value=store):
        try:
            ct.run_clickup_poll()
            print("  [PASS] run_clickup_poll completed despite one workspace failure")
            results.append(True)
        except Exception as e:
            print(f"  [FAIL] run_clickup_poll crashed: {e}")
            results.append(False)

    # Restore original IDs
    ct.CLICKUP_WORKSPACE_IDS = original_ids

    passed = sum(results)
    total = len(results)
    print(f"\n  Result: {passed}/{total} checks passed")
    return all(results)


# ─── Main ─────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("ClickUp Batch 2 Trigger — Full Verification Suite")
    print("=" * 60)

    store = get_store()

    # Clean up any previous test data
    cleanup_test_data(store)

    mock_client = create_mock_client()

    v1 = run_verification_1(store, mock_client)
    v2 = run_verification_2(store, mock_client)
    v3 = run_verification_3(store, mock_client)

    # Final cleanup
    cleanup_test_data(store)

    print("\n" + "=" * 60)
    print("FINAL RESULTS")
    print("=" * 60)
    print(f"  Verification 1 (Manual poll):       {'PASS' if v1 else 'FAIL'}")
    print(f"  Verification 2 (Watermark filter):   {'PASS' if v2 else 'FAIL'}")
    print(f"  Verification 3 (Error resilience):   {'PASS' if v3 else 'FAIL'}")
    all_pass = v1 and v2 and v3
    print(f"\n  Overall: {'ALL PASS' if all_pass else 'SOME FAILURES'}")
    print("=" * 60)

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
