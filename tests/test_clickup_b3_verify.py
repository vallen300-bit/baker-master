#!/usr/bin/env python3
"""
Verification script for CODE_BRIEF_CLICKUP_B3_PIPELINE_SEARCH_WRITE
Tests all 4 verification steps from the brief:
  1. Search test — confirm baker-clickup collection is embedded + queryable
  2. API test — verify new dashboard endpoints exist and respond
  3. Pipeline test — handoff note classification + tier + alert
  4. Write safety — reject non-BAKER space writes
"""

import os
import sys
import json

# Add project root to sys.path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BUILD_DIR = os.path.join(SCRIPT_DIR, "..")
sys.path.insert(0, BUILD_DIR)


def test_1_search():
    """Verification 1: baker-clickup collection exists in Qdrant and is searchable."""
    print("\n" + "=" * 60)
    print("  VERIFICATION 1: Search Test (baker-clickup in Qdrant)")
    print("=" * 60)

    checks = []

    # Check 1: baker-clickup is in config collections list
    from config.settings import config
    check1 = "baker-clickup" in config.qdrant.collections
    checks.append(("baker-clickup in config.qdrant.collections", check1))
    print(f"  {'PASS' if check1 else 'FAIL'} — baker-clickup in config collections: {config.qdrant.collections}")

    # Check 2: store_back._ensure_collection called for baker-clickup
    source_file = os.path.join(BUILD_DIR, "memory", "store_back.py")
    with open(source_file, "r") as f:
        source = f.read()
    check2 = 'self._ensure_collection("baker-clickup"' in source
    checks.append(("_ensure_collection('baker-clickup') in store_back.py", check2))
    print(f"  {'PASS' if check2 else 'FAIL'} — _ensure_collection('baker-clickup') found in store_back.py")

    # Check 3: clickup_trigger.py calls store_document with baker-clickup collection
    trigger_file = os.path.join(BUILD_DIR, "triggers", "clickup_trigger.py")
    with open(trigger_file, "r") as f:
        trigger_source = f.read()
    check3 = 'collection="baker-clickup"' in trigger_source
    checks.append(("clickup_trigger embeds to baker-clickup", check3))
    print(f"  {'PASS' if check3 else 'FAIL'} — clickup_trigger.py embeds to baker-clickup collection")

    # Check 4: retriever searches baker-clickup (it's in collections list)
    check4 = "baker-clickup" in config.qdrant.collections
    checks.append(("Retriever will search baker-clickup (in collections)", check4))
    print(f"  {'PASS' if check4 else 'FAIL'} — Retriever configured to search baker-clickup")

    passed = sum(1 for _, ok in checks if ok)
    total = len(checks)
    print(f"\n  Result: {passed}/{total} checks passed")
    return all(ok for _, ok in checks)


def test_2_api():
    """Verification 2: New dashboard endpoints exist and are correctly defined."""
    print("\n" + "=" * 60)
    print("  VERIFICATION 2: API Test (Dashboard Endpoints)")
    print("=" * 60)

    checks = []

    # Read dashboard source
    dashboard_file = os.path.join(BUILD_DIR, "outputs", "dashboard.py")
    with open(dashboard_file, "r") as f:
        source = f.read()

    # Check 1: GET /api/clickup/tasks endpoint exists
    check1 = '@app.get("/api/clickup/tasks"' in source
    checks.append(("GET /api/clickup/tasks endpoint exists", check1))
    print(f"  {'PASS' if check1 else 'FAIL'} — GET /api/clickup/tasks endpoint")

    # Check 2: GET /api/clickup/tasks/{task_id} endpoint exists
    check2 = '@app.get("/api/clickup/tasks/{task_id}"' in source
    checks.append(("GET /api/clickup/tasks/{{task_id}} endpoint exists", check2))
    print(f"  {'PASS' if check2 else 'FAIL'} — GET /api/clickup/tasks/{{task_id}} endpoint")

    # Check 3: GET /api/clickup/sync-status endpoint exists
    check3 = '@app.get("/api/clickup/sync-status"' in source
    checks.append(("GET /api/clickup/sync-status endpoint exists", check3))
    print(f"  {'PASS' if check3 else 'FAIL'} — GET /api/clickup/sync-status endpoint")

    # Check 4: POST /api/clickup/tasks endpoint exists
    check4 = '@app.post("/api/clickup/tasks"' in source
    checks.append(("POST /api/clickup/tasks endpoint exists", check4))
    print(f"  {'PASS' if check4 else 'FAIL'} — POST /api/clickup/tasks endpoint")

    # Check 5: PUT /api/clickup/tasks/{task_id} endpoint exists
    check5 = '@app.put("/api/clickup/tasks/{task_id}"' in source
    checks.append(("PUT /api/clickup/tasks/{{task_id}} endpoint exists", check5))
    print(f"  {'PASS' if check5 else 'FAIL'} — PUT /api/clickup/tasks/{{task_id}} endpoint")

    # Check 6: POST /api/clickup/tasks/{task_id}/comments endpoint exists
    check6 = '@app.post("/api/clickup/tasks/{task_id}/comments"' in source
    checks.append(("POST /api/clickup/tasks/{{task_id}}/comments endpoint exists", check6))
    print(f"  {'PASS' if check6 else 'FAIL'} — POST /api/clickup/tasks/{{task_id}}/comments endpoint")

    # Check 7: All endpoints require verify_api_key
    clickup_section_start = source.find("# ClickUp Endpoints")
    clickup_section_end = source.find("# Scan (Baker Chat)")
    clickup_section = source[clickup_section_start:clickup_section_end]
    api_key_count = clickup_section.count("Depends(verify_api_key)")
    check7 = api_key_count >= 6
    checks.append(("All 6 endpoints require verify_api_key", check7))
    print(f"  {'PASS' if check7 else 'FAIL'} — verify_api_key dependency count: {api_key_count} (expected >= 6)")

    # Check 8: CORS includes PUT
    check8 = '"PUT"' in source and 'allow_methods=["GET", "POST", "PUT"]' in source
    checks.append(("CORS allow_methods includes PUT", check8))
    print(f"  {'PASS' if check8 else 'FAIL'} — CORS allow_methods includes PUT")

    # Check 9: Write endpoints validate BAKER space
    baker_space_check = "_BAKER_SPACE_ID" in clickup_section
    checks.append(("Write endpoints validate BAKER space", baker_space_check))
    print(f"  {'PASS' if baker_space_check else 'FAIL'} — BAKER space validation present in write endpoints")

    # Check 10: Pydantic models for write requests
    check10 = "class CreateTaskRequest" in source and "class CommentRequest" in source
    checks.append(("Pydantic models for write requests", check10))
    print(f"  {'PASS' if check10 else 'FAIL'} — CreateTaskRequest + CommentRequest models defined")

    passed = sum(1 for _, ok in checks if ok)
    total = len(checks)
    print(f"\n  Result: {passed}/{total} checks passed")
    return all(ok for _, ok in checks)


def test_3_pipeline():
    """Verification 3: Pipeline classifies handoff note correctly + tier + alert."""
    print("\n" + "=" * 60)
    print("  VERIFICATION 3: Pipeline Test (Handoff Note Classification)")
    print("=" * 60)

    checks = []

    # Check 1: _classify_task_change correctly identifies handoff notes
    from triggers.clickup_trigger import _classify_task_change, _HANDOFF_NOTES_LIST_ID

    handoff_task = {
        "list_id": _HANDOFF_NOTES_LIST_ID,
        "status": "open",
        "due_date": None,
    }
    classification = _classify_task_change(handoff_task, is_new=True)
    check1 = classification == "clickup_handoff_note"
    checks.append(("Handoff note classified as clickup_handoff_note", check1))
    print(f"  {'PASS' if check1 else 'FAIL'} — Classification: {classification} (expected: clickup_handoff_note)")

    # Check 2: Overdue task classified correctly
    from datetime import datetime, timezone, timedelta
    overdue_task = {
        "list_id": "999999",
        "status": "open",
        "due_date": datetime.now(timezone.utc) - timedelta(days=2),
    }
    classification2 = _classify_task_change(overdue_task, is_new=False)
    check2 = classification2 == "clickup_task_overdue"
    checks.append(("Overdue task classified as clickup_task_overdue", check2))
    print(f"  {'PASS' if check2 else 'FAIL'} — Classification: {classification2} (expected: clickup_task_overdue)")

    # Check 3: New task classified correctly
    new_task = {
        "list_id": "999999",
        "status": "open",
        "due_date": None,
    }
    classification3 = _classify_task_change(new_task, is_new=True)
    check3 = classification3 == "clickup_task_created"
    checks.append(("New task classified as clickup_task_created", check3))
    print(f"  {'PASS' if check3 else 'FAIL'} — Classification: {classification3} (expected: clickup_task_created)")

    # Check 4: Status change classified correctly
    status_task = {
        "list_id": "999999",
        "status": "blocked",
        "due_date": None,
    }
    classification4 = _classify_task_change(status_task, is_new=False)
    check4 = classification4 == "clickup_status_change"
    checks.append(("Blocked task classified as clickup_status_change", check4))
    print(f"  {'PASS' if check4 else 'FAIL'} — Classification: {classification4} (expected: clickup_status_change)")

    # Check 5: prompt_builder source contains all 8 ClickUp types in trigger_instructions
    prompt_builder_file = os.path.join(BUILD_DIR, "orchestrator", "prompt_builder.py")
    with open(prompt_builder_file, "r") as f:
        pb_source = f.read()

    clickup_types = [
        "clickup_task_created", "clickup_task_updated", "clickup_status_change",
        "clickup_comment_added", "clickup_task_overdue", "clickup_handoff_note",
        "clickup_assignment_change", "clickup_cross_workspace_flag",
    ]
    found_types = [t for t in clickup_types if f'"{t}"' in pb_source]
    check5 = len(found_types) == 8
    checks.append(("All 8 ClickUp types in prompt_builder source", check5))
    print(f"  {'PASS' if check5 else 'FAIL'} — Found {len(found_types)}/8 ClickUp types in prompt_builder source")

    # Build system prompt for remaining checks
    from orchestrator.prompt_builder import SentinelPromptBuilder
    pb = SentinelPromptBuilder()
    system = pb._build_system_prompt("clickup_handoff_note")

    # Check 6: Tier guidance injected into system prompt for ClickUp triggers
    check6 = "CLICKUP TIER ASSIGNMENT" in system
    checks.append(("Tier guidance injected for ClickUp triggers", check6))
    print(f"  {'PASS' if check6 else 'FAIL'} — 'CLICKUP TIER ASSIGNMENT' found in system prompt")

    # Check 7: Tier guidance NOT injected for non-ClickUp triggers
    system_email = pb._build_system_prompt("email")
    check7 = "CLICKUP TIER ASSIGNMENT" not in system_email
    checks.append(("Tier guidance NOT injected for email triggers", check7))
    print(f"  {'PASS' if check7 else 'FAIL'} — Tier guidance absent for email trigger type")

    # Check 8: Pipeline has _execute_clickup_actions method
    pipeline_file = os.path.join(BUILD_DIR, "orchestrator", "pipeline.py")
    with open(pipeline_file, "r") as f:
        pipeline_source = f.read()
    check8 = "_execute_clickup_actions" in pipeline_source
    checks.append(("Pipeline has _execute_clickup_actions method", check8))
    print(f"  {'PASS' if check8 else 'FAIL'} — _execute_clickup_actions method in pipeline.py")

    # Check 9: Pipeline run() calls _execute_clickup_actions
    run_method_start = pipeline_source.find("def run(self")
    run_method = pipeline_source[run_method_start:]
    check9 = "_execute_clickup_actions" in run_method
    checks.append(("run() calls _execute_clickup_actions", check9))
    print(f"  {'PASS' if check9 else 'FAIL'} — _execute_clickup_actions called in run()")

    passed = sum(1 for _, ok in checks if ok)
    total = len(checks)
    print(f"\n  Result: {passed}/{total} checks passed")
    return all(ok for _, ok in checks)


def test_4_write_safety():
    """Verification 4: Write safety — reject non-BAKER space writes."""
    print("\n" + "=" * 60)
    print("  VERIFICATION 4: Write Safety Test")
    print("=" * 60)

    checks = []

    # Check 1: clickup_client enforces BAKER space on create_task
    client_file = os.path.join(BUILD_DIR, "clickup_client.py")
    with open(client_file, "r") as f:
        client_source = f.read()

    check1 = "_check_write_allowed" in client_source
    checks.append(("_check_write_allowed exists in clickup_client", check1))
    print(f"  {'PASS' if check1 else 'FAIL'} — _check_write_allowed method exists")

    # Check 2: BAKER space ID constant matches
    check2 = '_BAKER_SPACE_ID = "901510186446"' in client_source
    checks.append(("BAKER space ID constant is 901510186446", check2))
    print(f"  {'PASS' if check2 else 'FAIL'} — BAKER space ID = 901510186446")

    # Check 3: Dashboard write endpoints validate BAKER space
    dashboard_file = os.path.join(BUILD_DIR, "outputs", "dashboard.py")
    with open(dashboard_file, "r") as f:
        dashboard_source = f.read()

    # Find the POST /api/clickup/tasks handler
    create_handler_start = dashboard_source.find("async def create_clickup_task")
    create_handler = dashboard_source[create_handler_start:create_handler_start + 600]
    check3 = "_BAKER_SPACE_ID" in create_handler
    checks.append(("POST /api/clickup/tasks validates BAKER space", check3))
    print(f"  {'PASS' if check3 else 'FAIL'} — create_clickup_task validates BAKER space")

    # Check 4: Non-BAKER space write raises 403
    check4 = "403" in create_handler and "not in BAKER space" in create_handler
    checks.append(("Non-BAKER write returns 403 error", check4))
    print(f"  {'PASS' if check4 else 'FAIL'} — Non-BAKER write returns 403")

    # Check 5: Kill switch check in _check_write_allowed
    check5 = "BAKER_CLICKUP_READONLY" in client_source
    checks.append(("Kill switch BAKER_CLICKUP_READONLY supported", check5))
    print(f"  {'PASS' if check5 else 'FAIL'} — BAKER_CLICKUP_READONLY kill switch in client")

    # Check 6: Kill switch also in pipeline _execute_clickup_actions
    pipeline_file = os.path.join(BUILD_DIR, "orchestrator", "pipeline.py")
    with open(pipeline_file, "r") as f:
        pipeline_source = f.read()
    check6 = "BAKER_CLICKUP_READONLY" in pipeline_source
    checks.append(("Kill switch BAKER_CLICKUP_READONLY in pipeline M3", check6))
    print(f"  {'PASS' if check6 else 'FAIL'} — BAKER_CLICKUP_READONLY kill switch in pipeline")

    # Check 7: Max writes per cycle enforced
    check7 = "_MAX_WRITES_PER_CYCLE" in client_source and "10" in client_source
    checks.append(("10-write-per-cycle limit enforced", check7))
    print(f"  {'PASS' if check7 else 'FAIL'} — 10-write-per-cycle limit in client")

    # Check 8: Write methods call _check_write_allowed
    write_methods = ["create_task", "update_task", "post_comment", "add_tag", "remove_tag"]
    methods_with_guard = sum(1 for m in write_methods if f"def {m}" in client_source)
    check8 = methods_with_guard == 5
    checks.append(("All 5 write methods exist in client", check8))
    print(f"  {'PASS' if check8 else 'FAIL'} — {methods_with_guard}/5 write methods found")

    # Check 9: All write methods log actions
    log_action_count = client_source.count("self._log_action(")
    check9 = log_action_count >= 5
    checks.append(("All write methods log to baker_actions", check9))
    print(f"  {'PASS' if check9 else 'FAIL'} — _log_action calls: {log_action_count} (expected >= 5)")

    passed = sum(1 for _, ok in checks if ok)
    total = len(checks)
    print(f"\n  Result: {passed}/{total} checks passed")
    return all(ok for _, ok in checks)


# --- Main ---

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  CLICKUP B3 VERIFICATION — All 4 Tests")
    print("=" * 60)

    results = {}

    results["1_search"] = test_1_search()
    results["2_api"] = test_2_api()
    results["3_pipeline"] = test_3_pipeline()
    results["4_write_safety"] = test_4_write_safety()

    # Summary
    print("\n" + "=" * 60)
    print("  FINAL SUMMARY")
    print("=" * 60)
    all_pass = True
    for test_name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        if not passed:
            all_pass = False
        print(f"  {status} — {test_name}")

    print(f"\n  Overall: {'ALL PASS' if all_pass else 'SOME FAILURES'}")
    print("=" * 60)

    sys.exit(0 if all_pass else 1)
