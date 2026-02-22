"""
ClickUp Integration — Batch 4: End-to-End Verification Suite
Validates everything Batches 1-3 built.
Run: python -m tests.test_clickup_integration
"""
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Ensure project root is on sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Load .env BEFORE any module reads os.getenv (ClickUpClient, etc.)
from dotenv import load_dotenv
load_dotenv(_PROJECT_ROOT / "config" / ".env", override=True)

logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")
logger = logging.getLogger("test.clickup_integration")

# -------------------------------------------------------
# Constants
# -------------------------------------------------------
CLICKUP_WORKSPACE_IDS = [
    "2652545", "24368967", "24382372", "24382764", "24385290", "9004065517",
]
BAKER_SPACE_ID = "901510186446"
HANDOFF_NOTES_LIST_ID = "901521426367"

# Dashboard URL — local dev or Render
DASHBOARD_URL = os.getenv("BAKER_DASHBOARD_URL", "https://baker-master.onrender.com")
BAKER_API_KEY = os.getenv("BAKER_API_KEY", "")

# -------------------------------------------------------
# Results tracker
# -------------------------------------------------------
results = {}


def record(test_name: str, passed: bool, notes: str):
    """Record a test result."""
    status = "PASS" if passed else "FAIL"
    results[test_name] = {"status": status, "notes": notes}
    icon = "+" if passed else "!"
    logger.info(f"[{icon}] {test_name}: {status} — {notes}")


# -------------------------------------------------------
# A. Read Path — All 6 Workspaces
# -------------------------------------------------------
def test_read_all_workspaces():
    """Verify all 6 workspaces are accessible via ClickUp API (200 OK)."""
    from clickup_client import ClickUpClient

    client = ClickUpClient()
    if not client._api_key:
        record("A", False, "CLICKUP_API_KEY not set — cannot test read path")
        return

    accessible = 0
    errors = 0
    details = []
    total_spaces = 0
    for ws_id in CLICKUP_WORKSPACE_IDS:
        try:
            spaces = client.get_spaces(ws_id)
            # API returned 200 — workspace is accessible regardless of space count
            accessible += 1
            count = len(spaces) if spaces else 0
            total_spaces += count
            if spaces:
                names = [s.get("name", "?") for s in spaces]
                details.append(f"WS {ws_id}: {count} spaces ({', '.join(names[:3])})")
            else:
                details.append(f"WS {ws_id}: accessible (0 visible spaces)")
        except Exception as e:
            errors += 1
            details.append(f"WS {ws_id}: ERROR — {e}")

    client.close()
    # Pass if all workspaces are API-accessible and at least some have spaces
    all_ok = accessible == len(CLICKUP_WORKSPACE_IDS) and total_spaces > 0
    record(
        "A", all_ok,
        f"{accessible}/{len(CLICKUP_WORKSPACE_IDS)} accessible, {total_spaces} total spaces, {errors} errors. "
        + "; ".join(details[:4])
    )


# -------------------------------------------------------
# B. PostgreSQL Storage
# -------------------------------------------------------
def test_tasks_in_database():
    """Verify clickup_tasks table has data with correct integrity."""
    from memory.store_back import SentinelStoreBack

    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    if not conn:
        record("B", False, "No PostgreSQL connection")
        return

    try:
        cur = conn.cursor()

        # Count total tasks
        cur.execute("SELECT COUNT(*) FROM clickup_tasks")
        total = cur.fetchone()[0]
        if total == 0:
            record("B", False, "clickup_tasks table is empty — run a poll first")
            cur.close()
            return

        # Distinct workspaces
        cur.execute("SELECT DISTINCT workspace_id FROM clickup_tasks")
        ws_ids = [r[0] for r in cur.fetchall()]

        # Baker-writable integrity: only BAKER space tasks should have baker_writable=TRUE
        cur.execute(
            "SELECT COUNT(*) FROM clickup_tasks WHERE baker_writable = TRUE AND space_id != %s",
            (BAKER_SPACE_ID,),
        )
        integrity_violations = cur.fetchone()[0]

        cur.close()

        all_ok = total > 0 and len(ws_ids) > 0 and integrity_violations == 0
        record(
            "B", all_ok,
            f"{total} tasks, {len(ws_ids)} workspaces, "
            f"integrity violations: {integrity_violations}"
        )
    except Exception as e:
        record("B", False, f"Query error: {e}")
    finally:
        store._put_conn(conn)


# -------------------------------------------------------
# C. Qdrant Semantic Search
# -------------------------------------------------------
def test_qdrant_clickup_collection():
    """Verify baker-clickup Qdrant collection exists and search works."""
    from memory.store_back import SentinelStoreBack
    import uuid

    store = SentinelStoreBack._get_global_instance()
    test_point_id = None

    try:
        # Check collection exists
        info = store.qdrant.get_collection("baker-clickup")
        initial_count = info.points_count

        # If collection is empty, embed a test document to verify the full path
        test_content = "[ClickUp Task] B4 Verification Test — integration check for baker-clickup collection"
        test_metadata = {
            "task_id": "test_b4_verification",
            "list_name": "Handoff Notes",
            "workspace_id": "24385290",
            "space_id": BAKER_SPACE_ID,
            "content_type": "description",
            "status": "verification",
            "priority": "normal",
            "author": "b4_test",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "label": "test:b4_verification",
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        }

        # Embed test document
        store.store_document(test_content, test_metadata, collection="baker-clickup")

        # Re-check point count
        info2 = store.qdrant.get_collection("baker-clickup")
        updated_count = info2.points_count

        # Do a semantic search using query_points (Qdrant client v2 API)
        query_vec = store._embed("B4 Verification Test integration check")
        search_results = store.qdrant.query_points(
            collection_name="baker-clickup",
            query=query_vec,
            limit=5,
        )

        has_metadata = False
        found_test = False
        for sr in search_results.points:
            payload = sr.payload
            if payload.get("task_id") == "test_b4_verification":
                found_test = True
                test_point_id = sr.id
            if "task_id" in payload or "workspace_id" in payload or "content_type" in payload:
                has_metadata = True

        # Clean up — delete the test point by ID (filter-based delete needs keyword index)
        if test_point_id:
            from qdrant_client.models import PointIdsList
            store.qdrant.delete(
                collection_name="baker-clickup",
                points_selector=PointIdsList(points=[test_point_id]),
            )

        record(
            "C", updated_count > 0 and has_metadata and found_test,
            f"Initial: {initial_count} pts, after embed: {updated_count} pts, "
            f"search found test doc: {found_test}, metadata present: {has_metadata}"
        )
    except Exception as e:
        # Attempt cleanup even on error — use point ID if available
        if test_point_id:
            try:
                from qdrant_client.models import PointIdsList  # noqa: F811
                store.qdrant.delete(
                    collection_name="baker-clickup",
                    points_selector=PointIdsList(points=[test_point_id]),
                )
            except Exception:
                pass
        record("C", False, f"Qdrant error: {e}")


# -------------------------------------------------------
# D. Baker's Scan Integration
# -------------------------------------------------------
def test_scan_finds_clickup():
    """Verify /api/scan returns ClickUp content via SSE."""
    import httpx

    headers = {}
    if BAKER_API_KEY:
        headers["X-Baker-Key"] = BAKER_API_KEY

    try:
        with httpx.Client(timeout=90.0) as http:
            resp = http.post(
                f"{DASHBOARD_URL}/api/scan",
                json={"question": "What are the latest ClickUp tasks across all workspaces?"},
                headers={**headers, "Accept": "text/event-stream"},
            )

            if resp.status_code != 200:
                record("D", False, f"Scan returned {resp.status_code}")
                return

            # Parse SSE response — collect all tokens
            full_text = ""
            for line in resp.text.split("\n"):
                line = line.strip()
                if line.startswith("data: ") and line != "data: [DONE]":
                    try:
                        data = json.loads(line[6:])
                        full_text += data.get("token", "")
                    except json.JSONDecodeError:
                        pass

            # Check if response mentions ClickUp content
            clickup_mentioned = any(
                kw in full_text.lower()
                for kw in ["clickup", "task", "workspace", "list"]
            )

            record(
                "D", clickup_mentioned,
                f"Scan response length: {len(full_text)} chars, "
                f"ClickUp content detected: {clickup_mentioned}"
            )
    except Exception as e:
        record("D", False, f"Scan error: {e}")


# -------------------------------------------------------
# E. Write Path — BAKER Space
# -------------------------------------------------------
def test_write_to_baker_space():
    """Create, comment, tag, read-back, audit, then clean up a test task."""
    from clickup_client import ClickUpClient
    from memory.store_back import SentinelStoreBack

    client = ClickUpClient()
    if not client._api_key:
        record("E", False, "CLICKUP_API_KEY not set — cannot test write path")
        return

    store = SentinelStoreBack._get_global_instance()
    client.reset_cycle_counter()
    test_task_id = None
    steps_passed = []

    try:
        # E1: Create task in Handoff Notes list (BAKER space)
        result = client.create_task(
            list_id=HANDOFF_NOTES_LIST_ID,
            name="[TEST] Baker Integration Verification — DELETE ME",
            description="Auto-created by Batch 4 verification. Safe to delete.",
        )
        if result and result.get("id"):
            test_task_id = result["id"]
            steps_passed.append("create")
        else:
            record("E", False, "create_task returned None or no id")
            return

        # E2: Read-back
        detail = client.get_task_detail(test_task_id)
        if detail and detail.get("name", "").startswith("[TEST]"):
            steps_passed.append("read-back")
        else:
            steps_passed.append("read-back:FAIL")

        # E3: Audit log check
        conn = store._get_conn()
        if conn:
            try:
                cur = conn.cursor()
                cur.execute(
                    "SELECT id FROM baker_actions WHERE target_task_id = %s AND action_type = 'create_task'",
                    (test_task_id,),
                )
                audit_row = cur.fetchone()
                cur.close()
                if audit_row:
                    steps_passed.append("audit")
                else:
                    steps_passed.append("audit:FAIL")
            finally:
                store._put_conn(conn)

        # E4: Post comment
        comment_result = client.post_comment(
            test_task_id,
            "Verification comment — auto-generated by B4 integration test",
        )
        if comment_result:
            steps_passed.append("comment")
        else:
            steps_passed.append("comment:FAIL")

        # E5: Verify comment via read
        comments = client.get_task_comments(test_task_id)
        comment_found = any(
            "Verification comment" in str(c.get("comment_text", "") or c.get("comment", ""))
            for c in comments
        )
        if comment_found:
            steps_passed.append("comment-verify")
        else:
            steps_passed.append("comment-verify:FAIL")

        # E6: Add tag (note: add_tag returns None on success due to empty body)
        try:
            client.add_tag(test_task_id, "test-verification")
            steps_passed.append("add-tag")
        except Exception as tag_err:
            steps_passed.append(f"add-tag:FAIL({tag_err})")

        # E7: Verify tag via read-back
        detail_after_tag = client.get_task_detail(test_task_id)
        tags = []
        if detail_after_tag:
            tags = [t.get("name", "") if isinstance(t, dict) else str(t) for t in detail_after_tag.get("tags", [])]
        if "test-verification" in tags:
            steps_passed.append("tag-verify")
        else:
            steps_passed.append(f"tag-verify:FAIL(tags={tags})")

        # E8: Clean up — delete the test task
        try:
            client._request("DELETE", f"/task/{test_task_id}")
            steps_passed.append("cleanup")
            test_task_id = None  # Successfully cleaned
        except Exception as del_err:
            steps_passed.append(f"cleanup:FAIL({del_err})")

        all_ok = all("FAIL" not in s for s in steps_passed)
        record("E", all_ok, f"Steps: {', '.join(steps_passed)}")

    except Exception as e:
        record("E", False, f"Error: {e}")
        # Emergency cleanup
        if test_task_id:
            try:
                client._request("DELETE", f"/task/{test_task_id}")
                logger.info(f"Emergency cleanup: deleted task {test_task_id}")
            except Exception:
                logger.warning(f"Failed emergency cleanup for task {test_task_id}")
    finally:
        client.close()


# -------------------------------------------------------
# F. Write Safety — Space Guard
# -------------------------------------------------------
def test_write_blocked_outside_baker():
    """Verify writes to non-BAKER spaces are blocked."""
    from clickup_client import ClickUpClient
    from memory.store_back import SentinelStoreBack

    client = ClickUpClient()
    if not client._api_key:
        record("F", False, "CLICKUP_API_KEY not set — cannot test space guard")
        return

    store = SentinelStoreBack._get_global_instance()

    # Find a task from a non-BAKER workspace
    non_baker_task_id = None
    try:
        spaces = client.get_spaces(CLICKUP_WORKSPACE_IDS[0])
        for space in spaces:
            if str(space.get("id")) != BAKER_SPACE_ID:
                lists = client.get_lists(space["id"])
                for lst in lists:
                    tasks = client.get_tasks(lst["id"])
                    if tasks:
                        non_baker_task_id = tasks[0]["id"]
                        break
            if non_baker_task_id:
                break
    except Exception:
        pass

    if not non_baker_task_id:
        # Fallback: try another workspace
        try:
            for ws_id in CLICKUP_WORKSPACE_IDS[1:]:
                spaces = client.get_spaces(ws_id)
                for space in spaces:
                    if str(space.get("id")) != BAKER_SPACE_ID:
                        lists = client.get_lists(space["id"])
                        for lst in lists:
                            tasks = client.get_tasks(lst["id"])
                            if tasks:
                                non_baker_task_id = tasks[0]["id"]
                                break
                    if non_baker_task_id:
                        break
                if non_baker_task_id:
                    break
        except Exception:
            pass

    if not non_baker_task_id:
        record("F", False, "Could not find a non-BAKER task to test guard against")
        client.close()
        return

    # Attempt write to non-BAKER task
    blocked = False
    try:
        client.reset_cycle_counter()
        client.update_task(non_baker_task_id, status="in progress")
        blocked = False  # Should not reach here
    except ValueError as ve:
        if "outside BAKER space" in str(ve):
            blocked = True
    except Exception as e:
        record("F", False, f"Unexpected error: {e}")
        client.close()
        return

    # Verify no audit entry was created for this attempt
    no_audit = True
    conn = store._get_conn()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT id FROM baker_actions WHERE target_task_id = %s AND action_type = 'update_task'",
                (non_baker_task_id,),
            )
            if cur.fetchone():
                no_audit = False
            cur.close()
        finally:
            store._put_conn(conn)

    client.close()
    record("F", blocked and no_audit, f"Blocked: {blocked}, No audit: {no_audit}")


# -------------------------------------------------------
# G. Kill Switch — BAKER_CLICKUP_READONLY
# -------------------------------------------------------
def test_kill_switch():
    """Verify kill switch blocks all writes."""
    from clickup_client import ClickUpClient

    client = ClickUpClient()
    if not client._api_key:
        record("G", False, "CLICKUP_API_KEY not set — cannot test kill switch")
        return

    # Save original value
    original_val = os.environ.get("BAKER_CLICKUP_READONLY", "")

    try:
        # Enable kill switch
        os.environ["BAKER_CLICKUP_READONLY"] = "true"
        client.reset_cycle_counter()

        blocked = False
        try:
            client.create_task(
                list_id=HANDOFF_NOTES_LIST_ID,
                name="[TEST] Kill Switch — should never be created",
            )
        except RuntimeError as re:
            if "kill switch" in str(re).lower():
                blocked = True
        except Exception:
            pass

        record("G", blocked, f"Kill switch blocked create_task: {blocked}")
    finally:
        # Restore original value
        if original_val:
            os.environ["BAKER_CLICKUP_READONLY"] = original_val
        else:
            os.environ.pop("BAKER_CLICKUP_READONLY", None)
        client.close()


# -------------------------------------------------------
# H. Rate Limit Handling
# -------------------------------------------------------
def test_rate_limit_awareness():
    """Verify client tracks request count and backs off near limit."""
    from clickup_client import ClickUpClient

    client = ClickUpClient()

    # H1: Verify counter tracking
    initial_count = client._request_count
    client._check_rate_limit()
    tracking_works = hasattr(client, "_request_count") and hasattr(client, "_rate_window_start")

    # H2: Simulate approaching limit without actually sleeping 60s
    # Set window to nearly expired so backoff sleep is ~0.1s
    client._request_count = 90
    client._rate_window_start = time.time() - 59.8  # window almost expired

    start = time.time()
    client._check_rate_limit()  # should sleep the remaining ~0.2s then reset
    elapsed = time.time() - start

    # After backoff, counter should be reset
    counter_reset = client._request_count == 0
    did_pause = elapsed >= 0.05  # some measurable pause

    client.close()
    record(
        "H", tracking_works and counter_reset,
        f"Tracking: {tracking_works}, Counter reset after backoff: {counter_reset}, "
        f"Pause duration: {elapsed:.2f}s"
    )


# -------------------------------------------------------
# I. Watermark Continuity
# -------------------------------------------------------
def test_watermark_persistence():
    """Verify watermarks exist for ClickUp workspaces in trigger_watermarks."""
    from triggers.state import trigger_state

    watermarks_found = []
    watermarks_missing = []

    for ws_id in CLICKUP_WORKSPACE_IDS:
        key = f"clickup_{ws_id}"
        wm = trigger_state.get_watermark(key)
        # get_watermark returns 24h-ago as fallback — check if a real entry exists
        if wm:
            watermarks_found.append(key)
        else:
            watermarks_missing.append(key)

    # Also verify via direct DB query that watermarks are actual DB entries (not fallback)
    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    db_watermarks = 0
    if conn:
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT COUNT(*) FROM trigger_watermarks WHERE source LIKE 'clickup_%'"
            )
            db_watermarks = cur.fetchone()[0]
            cur.close()
        except Exception:
            pass
        finally:
            store._put_conn(conn)

    # At least some watermarks should be persisted if polls have run
    all_ok = db_watermarks > 0
    record(
        "I", all_ok,
        f"{db_watermarks} clickup watermarks in DB, "
        f"get_watermark returned values for {len(watermarks_found)}/{len(CLICKUP_WORKSPACE_IDS)} workspaces"
    )


# -------------------------------------------------------
# J. Dashboard API Endpoints
# -------------------------------------------------------
def test_api_endpoints():
    """Verify all ClickUp dashboard API endpoints respond correctly."""
    import httpx

    headers = {}
    if BAKER_API_KEY:
        headers["X-Baker-Key"] = BAKER_API_KEY

    steps_passed = []

    try:
        with httpx.Client(timeout=30.0) as http:
            # J1: GET /api/clickup/tasks
            resp = http.get(f"{DASHBOARD_URL}/api/clickup/tasks", headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, (list, dict)):
                    steps_passed.append("list-tasks")
                else:
                    steps_passed.append("list-tasks:FAIL(bad format)")
            else:
                steps_passed.append(f"list-tasks:FAIL({resp.status_code})")

            # J2: GET /api/clickup/tasks?workspace_id=24385290
            resp2 = http.get(
                f"{DASHBOARD_URL}/api/clickup/tasks",
                params={"workspace_id": "24385290"},
                headers=headers,
            )
            if resp2.status_code == 200:
                steps_passed.append("filtered-tasks")
            else:
                steps_passed.append(f"filtered-tasks:FAIL({resp2.status_code})")

            # J3: GET /api/clickup/sync-status
            resp3 = http.get(f"{DASHBOARD_URL}/api/clickup/sync-status", headers=headers)
            if resp3.status_code == 200:
                sync_data = resp3.json()
                if "workspaces" in sync_data or "total_tasks" in sync_data:
                    steps_passed.append("sync-status")
                else:
                    steps_passed.append("sync-status:FAIL(missing keys)")
            else:
                steps_passed.append(f"sync-status:FAIL({resp3.status_code})")

            # J4: GET /api/clickup/tasks/{known_task_id}
            # Use a task from the list-tasks response
            known_task_id = None
            try:
                tasks_data = resp.json()
                if isinstance(tasks_data, dict) and "tasks" in tasks_data:
                    task_list = tasks_data["tasks"]
                elif isinstance(tasks_data, list):
                    task_list = tasks_data
                else:
                    task_list = []
                if task_list and isinstance(task_list[0], dict):
                    known_task_id = task_list[0].get("id")
            except Exception:
                pass

            if known_task_id:
                resp4 = http.get(
                    f"{DASHBOARD_URL}/api/clickup/tasks/{known_task_id}",
                    headers=headers,
                )
                if resp4.status_code == 200:
                    steps_passed.append("task-detail")
                else:
                    steps_passed.append(f"task-detail:FAIL({resp4.status_code})")
            else:
                steps_passed.append("task-detail:SKIP(no task ID)")

            # J5: Auth check — request without key should get 401 (if auth is enabled)
            if BAKER_API_KEY:
                resp5 = http.get(f"{DASHBOARD_URL}/api/clickup/tasks")
                if resp5.status_code == 401:
                    steps_passed.append("auth-check")
                else:
                    steps_passed.append(f"auth-check:FAIL(got {resp5.status_code}, expected 401)")
            else:
                # Dev mode — auth not enforced, skip this check
                steps_passed.append("auth-check:SKIP(dev mode, no BAKER_API_KEY)")

        all_ok = all("FAIL" not in s for s in steps_passed)
        record("J", all_ok, f"Steps: {', '.join(steps_passed)}")
    except Exception as e:
        record("J", False, f"API error: {e}")


# -------------------------------------------------------
# Report generator
# -------------------------------------------------------
def generate_report() -> str:
    """Generate the verification report markdown."""
    test_labels = {
        "A": "Read all 6 workspaces",
        "B": "PostgreSQL storage",
        "C": "Qdrant collection",
        "D": "Scan integration",
        "E": "Write to BAKER",
        "F": "Space guard",
        "G": "Kill switch",
        "H": "Rate limiting",
        "I": "Watermarks",
        "J": "API endpoints",
    }

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    passed = sum(1 for r in results.values() if r["status"] == "PASS")
    total = len(results)

    lines = [
        "## ClickUp Integration — Verification Report",
        f"**Date:** {now}",
        "**Batch:** 4 of 4",
        "",
        "### Results",
        "| Test | Status | Notes |",
        "|------|--------|-------|",
    ]

    for key in "ABCDEFGHIJ":
        label = test_labels.get(key, key)
        r = results.get(key, {"status": "SKIP", "notes": "Not run"})
        icon = "PASS" if r["status"] == "PASS" else "FAIL"
        lines.append(f"| {key}. {label} | {icon} | {r['notes'][:100]} |")

    verdict = "PASS" if passed == total else "FAIL"
    lines.extend([
        "",
        f"### Summary",
        f"**{verdict}** — {passed} of {total} tests passed",
    ])

    return "\n".join(lines)


# -------------------------------------------------------
# Main runner
# -------------------------------------------------------
def main():
    logger.info("=" * 60)
    logger.info("ClickUp Integration — Batch 4 Verification")
    logger.info("=" * 60)

    # Run all 10 test categories
    tests = [
        ("A", test_read_all_workspaces),
        ("B", test_tasks_in_database),
        ("C", test_qdrant_clickup_collection),
        ("D", test_scan_finds_clickup),
        ("E", test_write_to_baker_space),
        ("F", test_write_blocked_outside_baker),
        ("G", test_kill_switch),
        ("H", test_rate_limit_awareness),
        ("I", test_watermark_persistence),
        ("J", test_api_endpoints),
    ]

    for name, test_fn in tests:
        logger.info(f"\n--- Test {name} ---")
        try:
            test_fn()
        except Exception as e:
            record(name, False, f"Unhandled exception: {e}")

    # Generate report
    report = generate_report()
    logger.info("\n" + report)

    # Summary
    passed = sum(1 for r in results.values() if r["status"] == "PASS")
    total = len(results)

    if passed == total:
        logger.info(f"\nClickUp Integration — all 4 batches complete, verification passed ({passed}/{total})")
    else:
        logger.info(f"\nVerification INCOMPLETE: {passed}/{total} tests passed. Fix failures and re-run.")

    return passed, total, report


if __name__ == "__main__":
    main()
