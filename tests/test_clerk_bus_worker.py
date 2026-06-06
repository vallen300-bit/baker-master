import httpx

from orchestrator.clerk_bus_worker import (
    ClerkBusWorker,
    ClerkBusWorkerConfig,
)


class _Response:
    def __init__(self, data, status_code=200, url="https://lab.test"):
        self._data = data
        self.status_code = status_code
        self.request = httpx.Request("POST", url)

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=self.request, response=httpx.Response(self.status_code))


class _HTTP:
    def __init__(self, messages=None, fail_reply=False):
        self.messages = messages or []
        self.fail_reply = fail_reply
        self.get_calls = []
        self.post_calls = []

    def get(self, url, **kwargs):
        self.get_calls.append({"url": url, **kwargs})
        return _Response(self.messages, url=url)

    def post(self, url, **kwargs):
        self.post_calls.append({"url": url, **kwargs})
        if self.fail_reply and url.endswith("/msg/lead"):
            return _Response({"error": "fail"}, status_code=500, url=url)
        if url.endswith("/msg/lead"):
            return _Response({"message_id": 9001, "thread_id": "thread-1"}, url=url)
        if url.endswith("/ack"):
            msg_id = int(url.rstrip("/").split("/")[-2])
            for msg in self.messages:
                if msg.get("id") == msg_id:
                    msg["acknowledged_at"] = "2026-06-06T10:00:00Z"
        return _Response({"ok": True}, url=url)


class _Store:
    def __init__(self, sessions=None):
        self.sessions = sessions or {}
        self.creates = []
        self.updates = []

    def get_session(self, session_id):
        row = self.sessions.get(session_id)
        return dict(row) if row else None

    def create_session_if_absent(self, session_id, task, source_meta):
        self.creates.append((session_id, task, source_meta))
        self.sessions.setdefault(
            session_id,
            {
                "session_id": session_id,
                "task": task,
                "status": "running",
                "result_json": {},
                "draft_content": None,
                "draft_path": None,
                "source_meta": source_meta,
                "error": None,
            },
        )

    def update_session(self, session_id, **fields):
        self.updates.append((session_id, fields))
        self.sessions.setdefault(
            session_id,
            {
                "session_id": session_id,
                "task": "",
                "status": "running",
                "result_json": {},
                "draft_content": None,
                "draft_path": None,
                "source_meta": {},
                "error": None,
            },
        ).update(fields)


class _FailReplyMarkerStore(_Store):
    def __init__(self):
        super().__init__()
        self.marker_failures = 0

    def update_session(self, session_id, **fields):
        result_json = fields.get("result_json")
        if isinstance(result_json, dict) and result_json.get("bus_reply_message_id"):
            self.marker_failures += 1
            if self.marker_failures == 1:
                raise RuntimeError("marker persist failed")
        super().update_session(session_id, **fields)


def _cfg(**overrides):
    base = {
        "enabled": True,
        "lab_url": "https://lab.test",
        "terminal_key": "clerk-key",
        "forge_key": "forge-key",
        "poll_limit": 7,
        "batch_cap": 3,
        "event_interval_s": 0,
        "dashboard_url": "https://baker.test",
    }
    base.update(overrides)
    return ClerkBusWorkerConfig(**base)


def _msg(msg_id=101, body="convert this", sender="lead", topic="dispatch/test"):
    return {
        "id": msg_id,
        "from_terminal": sender,
        "topic": topic,
        "body": body,
        "acknowledged_at": None,
    }


def test_ready_message_replies_then_acks_and_records_reply_id():
    http = _HTTP(messages=[_msg()])
    store = _Store()
    result = {
        "status": "ready",
        "answer": "Ready: /Baker-Feed/Clerk-Workbench/out.md / Source: test",
        "tool_calls": [{"name": "file_save", "input": {"content": "draft", "filename": "out.md"}}],
    }
    worker = ClerkBusWorker(
        cfg=_cfg(),
        http_client=http,
        store=store,
        run_clerk_task_fn=lambda task: result,
    )

    stats = worker.poll_once()

    assert stats == {"status": "ok", "fetched": 1, "processed": 1, "acked": 1, "errors": 0}
    assert http.get_calls[0]["params"] == {"limit": 7}
    post_urls = [c["url"] for c in http.post_calls]
    assert post_urls == [
        "https://lab.test/api/register",
        "https://lab.test/api/event",
        "https://lab.test/api/event",
        "https://lab.test/msg/lead",
        "https://lab.test/msg/101/ack",
    ]
    reply_payload = http.post_calls[3]["json"]
    assert reply_payload["parent_id"] == 101
    assert reply_payload["topic"] == "dispatch/test"
    assert "Edit: https://baker.test/clerk/edit/bus-101" in reply_payload["body"]
    assert "Draft preview:\ndraft" in reply_payload["body"]
    assert store.sessions["bus-101"]["status"] == "ready"
    assert store.sessions["bus-101"]["result_json"]["bus_reply_message_id"] == 9001


def test_existing_bus_reply_id_only_acks_without_rerun_or_reply():
    http = _HTTP(messages=[_msg()])
    store = _Store({
        "bus-101": {
            "session_id": "bus-101",
            "task": "convert this",
            "status": "ready",
            "result_json": {"status": "ready", "bus_reply_message_id": 123},
            "draft_content": "draft",
            "draft_path": "/Baker-Feed/Clerk-Workbench/out.md",
            "source_meta": {},
            "error": None,
        }
    })
    run_calls = []
    worker = ClerkBusWorker(
        cfg=_cfg(),
        http_client=http,
        store=store,
        run_clerk_task_fn=lambda task: run_calls.append(task) or {"status": "ready"},
    )

    stats = worker.poll_once()

    assert stats["acked"] == 1
    assert run_calls == []
    assert [c["url"] for c in http.post_calls] == ["https://lab.test/msg/101/ack"]


def test_pending_approval_status_replies_needs_approval_and_acks():
    http = _HTTP(messages=[_msg(body="send external email")])
    store = _Store()
    worker = ClerkBusWorker(
        cfg=_cfg(),
        http_client=http,
        store=store,
        run_clerk_task_fn=lambda task: {
            "status": "pending_approval",
            "reason": "external email requires Director approval",
        },
    )

    stats = worker.poll_once()

    assert stats["acked"] == 1
    reply_payload = next(c["json"] for c in http.post_calls if c["url"].endswith("/msg/lead"))
    assert "Status: pending_approval" in reply_payload["body"]
    assert "Needs approval/blocker: external email requires Director approval" in reply_payload["body"]


def test_reply_failure_leaves_inbound_unacked_for_retry():
    http = _HTTP(messages=[_msg()], fail_reply=True)
    store = _Store()
    worker = ClerkBusWorker(
        cfg=_cfg(),
        http_client=http,
        store=store,
        run_clerk_task_fn=lambda task: {"status": "ready", "answer": "Ready: /x"},
    )

    stats = worker.poll_once()

    assert stats["processed"] == 0
    assert stats["acked"] == 0
    assert stats["errors"] == 1
    assert "bus_reply_message_id" not in store.sessions["bus-101"]["result_json"]
    assert not any(c["url"].endswith("/msg/101/ack") for c in http.post_calls)


def test_reply_marker_persist_failure_still_acks_and_prevents_duplicate_reply():
    http = _HTTP(messages=[_msg()])
    store = _FailReplyMarkerStore()
    worker = ClerkBusWorker(
        cfg=_cfg(),
        http_client=http,
        store=store,
        run_clerk_task_fn=lambda task: {"status": "ready", "answer": "Ready: /x"},
    )

    first = worker.poll_once()
    second = worker.poll_once()

    reply_posts = [c for c in http.post_calls if c["url"].endswith("/msg/lead")]
    ack_posts = [c for c in http.post_calls if c["url"].endswith("/msg/101/ack")]
    assert first["processed"] == 1
    assert first["acked"] == 1
    assert first["errors"] == 0
    assert second["processed"] == 0
    assert len(reply_posts) == 1
    assert len(ack_posts) == 1
    assert http.messages[0]["acknowledged_at"] == "2026-06-06T10:00:00Z"


def test_batch_cap_bounds_processing():
    http = _HTTP(messages=[_msg(i) for i in range(1, 6)])
    store = _Store()
    worker = ClerkBusWorker(
        cfg=_cfg(batch_cap=2),
        http_client=http,
        store=store,
        run_clerk_task_fn=lambda task: {"status": "ready", "answer": "Ready: /x"},
    )

    stats = worker.poll_once()

    assert stats["fetched"] == 5
    assert stats["processed"] == 2
    assert sorted(store.sessions) == ["bus-1", "bus-2"]


def test_disabled_worker_has_no_side_effects():
    http = _HTTP(messages=[_msg()])
    worker = ClerkBusWorker(cfg=_cfg(enabled=False), http_client=http, store=_Store())

    assert worker.poll_once()["status"] == "disabled"
    assert http.get_calls == []
    assert http.post_calls == []


def test_scheduler_registers_clerk_bus_poll_with_liveness():
    src = open("triggers/embedded_scheduler.py", encoding="utf-8").read()

    assert "poll_clerk_bus" in src
    assert 'id="clerk_bus_poll"' in src
    assert 'register_expected_job("clerk_bus_poll", _clerk_bus_interval)' in src


def test_worker_uses_direct_keepalive_connection_pattern():
    src = open("orchestrator/clerk_bus_worker.py", encoding="utf-8").read()

    assert "config.postgres.host_direct" in src
    assert "config.postgres.direct_dsn_params" in src
    assert "connect_timeout=5" in src
