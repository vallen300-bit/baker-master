"""
A8: Insight-to-Task Chain (Session 27)

After a specialist run produces actionable findings, auto-create ClickUp
tasks + deadlines in the BAKER space. Haiku classifies whether the output
contains actionable items. If yes, extracts task titles + due dates and
creates them via clickup_client.

Called from dashboard.py after specialist capability runs complete.
Only fires for accepted/unrated specialist outputs (not rejected feedback).
"""
import logging
import json

logger = logging.getLogger("baker.insight_to_task")

# Minimum response length to consider for task extraction
_MIN_RESPONSE_LENGTH = 200

# BAKER space list ID for auto-created tasks
_BAKER_HANDOFF_LIST = "901521426367"


def extract_tasks_from_specialist(
    question: str,
    response: str,
    capability_slug: str,
    matter_slug: str = None,
) -> list:
    """Use Haiku to extract actionable tasks from a specialist response.

    Returns list of dicts: [{"title": str, "description": str, "due_days": int|None}]
    Empty list if no actionable items found.
    """
    if not response or len(response) < _MIN_RESPONSE_LENGTH:
        return []

    try:
        from orchestrator.gemini_client import call_flash

        prompt = f"""Analyze this specialist response and extract ONLY clearly actionable tasks that the Director should create as follow-up items.

Rules:
- Only extract tasks that require SPECIFIC ACTION (not general advice or observations)
- Each task must have a clear, concrete next step
- Maximum 3 tasks
- If there are no actionable items, return an empty array
- due_days: number of days from now the task should be due (null if no deadline implied)

Question asked: {question[:500]}
Specialist ({capability_slug}): {response[:3000]}

Respond with JSON only:
{{"tasks": [{{"title": "short imperative title", "description": "1 sentence context", "due_days": null}}]}}"""

        resp = call_flash(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300,
        )

        # Log cost
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost(
                "gemini-2.5-flash",
                resp.usage.input_tokens,
                resp.usage.output_tokens,
                source="insight_to_task",
            )
        except Exception:
            pass

        text = resp.text.strip()
        # Parse JSON from response (handle markdown code blocks)
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        data = json.loads(text)
        tasks = data.get("tasks", [])

        if tasks:
            logger.info(
                f"A8: Extracted {len(tasks)} actionable task(s) from {capability_slug} response"
            )
        return tasks[:3]  # cap at 3

    except Exception as e:
        logger.warning(f"A8: Task extraction failed (non-fatal): {e}")
        return []


def create_tasks_from_insights(
    tasks: list,
    capability_slug: str,
    matter_slug: str = None,
    baker_task_id: int = None,
):
    """Create ClickUp tasks + deadlines from extracted actionable items.

    Args:
        tasks: list of {"title", "description", "due_days"} from extract_tasks_from_specialist
        capability_slug: which specialist produced the insight
        matter_slug: optional matter context
        baker_task_id: optional baker_task ID for linking
    """
    if not tasks:
        return

    created = 0
    for task in tasks:
        title = task.get("title", "").strip()
        desc = task.get("description", "").strip()
        due_days = task.get("due_days")

        if not title:
            continue

        # Tag with source
        full_desc = f"{desc}\n\n---\n_Auto-created by Baker from {capability_slug} specialist analysis._"
        if matter_slug:
            full_desc += f"\n_Matter: {matter_slug}_"

        # Create ClickUp task in BAKER Handoff Notes list
        try:
            from clickup_client import ClickUpClient
            client = ClickUpClient()

            due_date_ms = None
            if due_days and isinstance(due_days, (int, float)):
                from datetime import datetime, timezone, timedelta
                due_dt = datetime.now(timezone.utc) + timedelta(days=int(due_days))
                due_date_ms = int(due_dt.timestamp() * 1000)

            result = client.create_task(
                list_id=_BAKER_HANDOFF_LIST,
                name=f"[{capability_slug}] {title}"[:200],
                description=full_desc,
                due_date=due_date_ms,
                tags=["baker-auto", capability_slug],
            )
            if result:
                created += 1
                logger.info(f"A8: Created ClickUp task: {title[:60]}")
        except Exception as e:
            logger.warning(f"A8: ClickUp task creation failed for '{title[:40]}': {e}")

        # Also create a Baker deadline if due_days is set
        if due_days and isinstance(due_days, (int, float)):
            try:
                from memory.store_back import SentinelStoreBack
                from datetime import datetime, timezone, timedelta
                store = SentinelStoreBack._get_global_instance()
                due_date = (datetime.now(timezone.utc) + timedelta(days=int(due_days))).strftime("%Y-%m-%d")
                store.create_deadline(
                    description=f"[{capability_slug}] {title}",
                    due_date=due_date,
                    priority="normal",
                    source_snippet=f"Auto-extracted from specialist analysis. Matter: {matter_slug or 'unknown'}",
                )
            except Exception:
                pass  # deadline creation is best-effort

    if created:
        logger.info(f"A8: Created {created} ClickUp task(s) from {capability_slug} insights")

    return created
