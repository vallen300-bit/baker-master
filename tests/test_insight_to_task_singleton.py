"""
Regression test: create_tasks_from_insights must use the shared ClickUpClient
singleton, NOT a fresh per-call ClickUpClient().

A direct ClickUpClient() gets its own _cycle_write_count + rate-limit counters,
silently bypassing the 10-writes/cycle cap and the 100-req/min limiter that the
rest of the Cortex cycle shares via _get_global_instance(). See project hard rule
"Never instantiate ... directly — use _get_global_instance()" and the CI guard
scripts/check_singletons.sh (ClickUpClient arm).
"""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestInsightToTaskUsesSingleton(unittest.TestCase):
    def test_create_tasks_from_insights_uses_global_instance(self):
        from orchestrator.insight_to_task import create_tasks_from_insights

        # Patch the class so we can observe how it is accessed. _get_global_instance
        # returns a shared sentinel; calling the class directly (ClickUpClient())
        # would register on mock_cls itself and is what we assert never happens.
        mock_cls = MagicMock(name="ClickUpClient")
        singleton = mock_cls._get_global_instance.return_value
        singleton.create_task.return_value = {"id": "abc", "url": "http://x/abc"}

        with patch.dict("sys.modules", {"clickup_client": MagicMock(ClickUpClient=mock_cls)}):
            create_tasks_from_insights(
                tasks=[{"title": "Do thing", "description": "desc", "due_days": None}],
                capability_slug="ao-legal",
                matter_slug="ao",
            )

        # The singleton accessor was used...
        mock_cls._get_global_instance.assert_called_once_with()
        singleton.create_task.assert_called_once()
        # ...and a fresh ClickUpClient() was NEVER constructed directly.
        mock_cls.assert_not_called()


if __name__ == "__main__":
    unittest.main()
