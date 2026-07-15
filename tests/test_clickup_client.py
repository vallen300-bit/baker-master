"""
Unit tests for ClickUp client — write safety, kill switch, rate limiting.
"""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# Ensure the build directory is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestWriteSafety(unittest.TestCase):
    """Write methods must raise ValueError when space_id != 901510186446."""

    def _make_client(self):
        """Create a ClickUpClient with mocked HTTP."""
        # Patch config + httpx so __init__ doesn't need real credentials
        with patch.dict(os.environ, {"CLICKUP_API_KEY": "test_key_123"}):
            from clickup_client import ClickUpClient
            client = ClickUpClient.__new__(ClickUpClient)
            client._api_key = "test_key_123"
            client._base_url = "https://api.clickup.com/api/v2"
            client._client = MagicMock()
            client._request_count = 0
            client._rate_window_start = __import__("time").time()
            client._cycle_write_count = 0
        return client

    def test_create_task_wrong_space_raises(self):
        """create_task must raise ValueError for non-BAKER space."""
        client = self._make_client()
        # Mock _resolve_space_id_for_list to return a wrong space
        client._resolve_space_id_for_list = MagicMock(return_value="999999999")

        with self.assertRaises(ValueError) as ctx:
            client.create_task(list_id="fake_list", name="Test task")
        self.assertIn("Write attempted outside BAKER space", str(ctx.exception))

    def test_update_task_wrong_space_raises(self):
        """update_task must raise ValueError for non-BAKER space."""
        client = self._make_client()
        client._resolve_space_id_for_task = MagicMock(return_value="888888888")

        with self.assertRaises(ValueError) as ctx:
            client.update_task(task_id="fake_task", name="Updated")
        self.assertIn("Write attempted outside BAKER space", str(ctx.exception))

    def test_post_comment_wrong_space_raises(self):
        """post_comment must raise ValueError for non-BAKER space."""
        client = self._make_client()
        client._resolve_space_id_for_task = MagicMock(return_value="777777777")

        with self.assertRaises(ValueError) as ctx:
            client.post_comment(task_id="fake_task", comment_text="Hello")
        self.assertIn("Write attempted outside BAKER space", str(ctx.exception))

    def test_add_tag_wrong_space_raises(self):
        """add_tag must raise ValueError for non-BAKER space."""
        client = self._make_client()
        client._resolve_space_id_for_task = MagicMock(return_value="666666666")

        with self.assertRaises(ValueError) as ctx:
            client.add_tag(task_id="fake_task", tag_name="urgent")
        self.assertIn("Write attempted outside BAKER space", str(ctx.exception))

    def test_remove_tag_wrong_space_raises(self):
        """remove_tag must raise ValueError for non-BAKER space."""
        client = self._make_client()
        client._resolve_space_id_for_task = MagicMock(return_value="555555555")

        with self.assertRaises(ValueError) as ctx:
            client.remove_tag(task_id="fake_task", tag_name="urgent")
        self.assertIn("Write attempted outside BAKER space", str(ctx.exception))

    def test_write_allowed_for_baker_space(self):
        """_check_write_allowed must NOT raise for BAKER space."""
        client = self._make_client()
        # Should not raise
        client._check_write_allowed("901510186446", "create_task")


class TestKillSwitch(unittest.TestCase):
    """BAKER_CLICKUP_READONLY=true must block all writes."""

    def _make_client(self):
        with patch.dict(os.environ, {"CLICKUP_API_KEY": "test_key_123"}):
            from clickup_client import ClickUpClient
            client = ClickUpClient.__new__(ClickUpClient)
            client._api_key = "test_key_123"
            client._base_url = "https://api.clickup.com/api/v2"
            client._client = MagicMock()
            client._request_count = 0
            client._rate_window_start = __import__("time").time()
            client._cycle_write_count = 0
        return client

    def test_kill_switch_blocks_writes(self):
        """All writes raise RuntimeError when kill switch is on."""
        client = self._make_client()
        client._resolve_space_id_for_task = MagicMock(return_value="901510186446")

        with patch.dict(os.environ, {"BAKER_CLICKUP_READONLY": "true"}):
            with self.assertRaises(RuntimeError) as ctx:
                client.update_task(task_id="fake", name="Blocked")
            self.assertIn("kill switch", str(ctx.exception))

    def test_kill_switch_case_insensitive(self):
        """Kill switch should work with 'True', 'TRUE', etc."""
        client = self._make_client()
        client._resolve_space_id_for_task = MagicMock(return_value="901510186446")

        with patch.dict(os.environ, {"BAKER_CLICKUP_READONLY": "True"}):
            with self.assertRaises(RuntimeError):
                client.post_comment(task_id="fake", comment_text="Blocked")

    def test_kill_switch_off_allows_writes(self):
        """When kill switch is off/unset, writes to BAKER space proceed."""
        client = self._make_client()
        # Ensure kill switch is off
        with patch.dict(os.environ, {"BAKER_CLICKUP_READONLY": ""}, clear=False):
            # Should not raise for correct space
            client._check_write_allowed("901510186446", "create_task")


class TestRateLimiting(unittest.TestCase):
    """Rate limit counter logic."""

    def _make_client(self):
        with patch.dict(os.environ, {"CLICKUP_API_KEY": "test_key_123"}):
            from clickup_client import ClickUpClient
            client = ClickUpClient.__new__(ClickUpClient)
            client._api_key = "test_key_123"
            client._base_url = "https://api.clickup.com/api/v2"
            client._client = MagicMock()
            client._request_count = 0
            client._rate_window_start = __import__("time").time()
            client._cycle_write_count = 0
        return client

    def test_counter_increments(self):
        """Request counter should increment on each _request call."""
        client = self._make_client()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ok": True}
        client._client.request.return_value = mock_resp

        client._request("GET", "/test")
        self.assertEqual(client._request_count, 1)

        client._request("GET", "/test2")
        self.assertEqual(client._request_count, 2)

    def test_counter_resets_after_minute(self):
        """Counter should reset when 60s have passed."""
        client = self._make_client()
        client._request_count = 50
        # Simulate that the window started > 60s ago
        client._rate_window_start = __import__("time").time() - 61

        client._check_rate_limit()
        self.assertEqual(client._request_count, 0)

    def test_max_writes_per_cycle(self):
        """Exceeding max writes per cycle should raise RuntimeError."""
        client = self._make_client()
        client._cycle_write_count = 10  # at the limit

        with self.assertRaises(RuntimeError) as ctx:
            client._check_write_allowed("901510186446", "create_task")
        self.assertIn("Max writes per cycle", str(ctx.exception))

    def test_cycle_counter_reset(self):
        """reset_cycle_counter should reset the write counter."""
        client = self._make_client()
        client._cycle_write_count = 7
        client.reset_cycle_counter()
        self.assertEqual(client._cycle_write_count, 0)


class TestGetTasksRobustness(unittest.TestCase):
    """CLICKUP_GET_TASKS_ROBUSTNESS_1 — outage-vs-empty (F1) + pagination (F2)."""

    def _make_client(self):
        with patch.dict(os.environ, {"CLICKUP_API_KEY": "test_key_123"}):
            from clickup_client import ClickUpClient
            client = ClickUpClient.__new__(ClickUpClient)
            client._api_key = "test_key_123"
            client._base_url = "https://api.clickup.com/api/v2"
            client._client = MagicMock()
            client._request_count = 0
            client._rate_window_start = __import__("time").time()
            client._cycle_write_count = 0
        return client

    def test_ac1_outage_raises_clickup_unavailable(self):
        """_request None (outage/retries exhausted) => raise, NOT []."""
        from clickup_client import ClickUpUnavailable
        client = self._make_client()
        client._request = MagicMock(return_value=None)
        with self.assertRaises(ClickUpUnavailable):
            client.get_tasks("list-1")

    def test_ac2_genuine_empty_returns_empty_no_raise(self):
        """HTTP 200 with tasks:[] is a real empty list => [] (distinct from outage)."""
        client = self._make_client()
        client._request = MagicMock(return_value={"tasks": [], "last_page": True})
        self.assertEqual(client.get_tasks("list-1"), [])

    def test_ac3_pagination_all_pages_and_params_preserved(self):
        """>100-task list across pages fully returned; last_page terminates;
        include_closed + date_updated_gt + page preserved per request."""
        client = self._make_client()
        page0 = {"tasks": [{"id": str(i)} for i in range(100)], "last_page": False}
        page1 = {"tasks": [{"id": str(i)} for i in range(100, 150)], "last_page": True}
        calls = []

        def fake_request(method, path, **kwargs):
            calls.append(kwargs.get("params", {}))
            return page0 if len(calls) == 1 else page1

        client._request = fake_request
        tasks = client.get_tasks("list-1", date_updated_gt=1720000000000)
        self.assertEqual(len(tasks), 150)
        self.assertEqual(tasks[0]["id"], "0")
        self.assertEqual(tasks[-1]["id"], "149")
        self.assertEqual(len(calls), 2)
        for i, p in enumerate(calls):
            self.assertEqual(p.get("include_closed"), "true")
            self.assertEqual(p.get("date_updated_gt"), "1720000000000")
            self.assertEqual(p.get("page"), str(i))

    def test_ac4_page_cap_guard_fails_loud(self):
        """Malformed response (last_page never True) must not infinite-loop:
        the page cap raises after exactly _TASKS_PAGE_CAP requests."""
        from clickup_client import ClickUpUnavailable, _TASKS_PAGE_CAP
        client = self._make_client()
        full_no_flag = {"tasks": [{"id": "x"} for _ in range(100)]}  # no last_page
        client._request = MagicMock(return_value=full_no_flag)
        with self.assertRaises(ClickUpUnavailable):
            client.get_tasks("list-1")
        self.assertEqual(client._request.call_count, _TASKS_PAGE_CAP)

    def test_ac5_sibling_methods_unchanged_return_empty_on_none(self):
        """get_task_comments / search_tasks still swallow None -> [] (not raising)."""
        client = self._make_client()
        client._request = MagicMock(return_value=None)
        self.assertEqual(client.get_task_comments("t1"), [])
        self.assertEqual(client.search_tasks("ws1", "q"), [])


if __name__ == "__main__":
    unittest.main()
