from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone
from threading import RLock

from fastapi.testclient import TestClient


def _set_api_key(monkeypatch, key="test-key-clerk"):
    monkeypatch.setenv("BAKER_API_KEY", key)
    monkeypatch.delenv("CLERK_SAVE_APPROVAL_SECRET", raising=False)
    import outputs.dashboard as dash

    dash._BAKER_API_KEY = key
    dash.app.dependency_overrides.pop(dash.verify_api_key, None)
    return dash


def _manual_save_token(secret, session_id, target_path):
    payload = f"clerk-save-v1:{session_id}:{target_path}"
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _unwrap_json_param(value):
    if hasattr(value, "adapted"):
        return value.adapted
    return value


class _FakeCursor:
    def __init__(self, store):
        self.store = store
        self._row = None
        self._rows = []

    def execute(self, sql, params=()):
        compact = " ".join(sql.split()).lower()
        with self.store.lock:
            if compact.startswith("insert into clerk_sessions"):
                session_id, task, status, source_meta = params
                now = datetime.now(timezone.utc)
                self.store.rows[session_id] = {
                    "session_id": session_id,
                    "task": task,
                    "status": status,
                    "result_json": {},
                    "draft_content": None,
                    "draft_path": None,
                    "source_meta": _unwrap_json_param(source_meta),
                    "error": None,
                    "created_at": now,
                    "updated_at": now,
                }
                return

            if compact.startswith("select session_id") and "order by created_at desc" in compact:
                limit = params[0]
                rows = sorted(
                    self.store.rows.values(),
                    key=lambda row: row["created_at"],
                    reverse=True,
                )[:limit]
                self._rows = [dict(row) for row in rows]
                self._row = None
                return

            if compact.startswith("select session_id"):
                session_id = params[0]
                row = self.store.rows.get(session_id)
                self._row = dict(row) if row else None
                self._rows = []
                return

            if compact.startswith("update clerk_sessions set"):
                session_id = params[-1]
                row = self.store.rows.get(session_id)
                if not row:
                    return
                assignments = sql.split("SET", 1)[1].split("WHERE", 1)[0].split(",")
                values = iter(params[:-1])
                for assignment in assignments:
                    assignment = assignment.strip()
                    if assignment.lower().startswith("updated_at"):
                        row["updated_at"] = datetime.now(timezone.utc)
                        continue
                    key = assignment.split("=", 1)[0].strip()
                    row[key] = _unwrap_json_param(next(values))
                return

            raise AssertionError(f"unexpected SQL: {sql}")

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._rows

    def close(self):
        pass


class _FakeConn:
    def __init__(self, store):
        self.store = store

    def cursor(self, *args, **kwargs):
        return _FakeCursor(self.store)

    def commit(self):
        pass

    def rollback(self):
        pass


class _FakeStore:
    def __init__(self):
        self.rows = {}
        self.lock = RLock()

    def _get_conn(self):
        return _FakeConn(self)

    def _put_conn(self, conn):
        pass


def _install_fake_store(monkeypatch):
    dash = _set_api_key(monkeypatch)
    store = _FakeStore()
    monkeypatch.setattr(dash, "_get_store", lambda: store)
    return dash, store


def test_clerk_run_auth_required(monkeypatch):
    _set_api_key(monkeypatch)
    from outputs.dashboard import app

    client = TestClient(app)
    resp = client.post("/api/clerk/run", json={"task": "prepare a harmless note"})

    assert resp.status_code == 401


def test_clerk_run_creates_session_and_background_persists_result(monkeypatch):
    dash, store = _install_fake_store(monkeypatch)

    import orchestrator.clerk_runtime as clerk_runtime

    monkeypatch.setattr(
        clerk_runtime,
        "run_clerk_task",
        lambda task: {
            "status": "ready",
            "answer": "Ready: /Baker-Feed/Clerk-Workbench/out.md",
            "usage": {
                "prompt_tokens": 12000,
                "completion_tokens": 345,
                "total_tokens": 12345,
                "context_window_used": 12000,
                "context_window_max": 1000000,
                "session_cost_usd": 0.0042,
            },
            "tool_calls": [
                {
                    "name": "file_save",
                    "input": {"content": "draft body", "filename": "out.md"},
                    "duration_ms": 1,
                }
            ],
        },
    )

    client = TestClient(dash.app)
    resp = client.post(
        "/api/clerk/run",
        json={"task": "prepare a harmless note"},
        headers={"X-Baker-Key": "test-key-clerk"},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["session_id"]
    assert body["status"] == "running"
    assert store.rows[body["session_id"]]["status"] == "ready"
    assert store.rows[body["session_id"]]["draft_content"] == "draft body"

    poll = client.get(
        f"/api/clerk/session/{body['session_id']}",
        headers={"X-Baker-Key": "test-key-clerk"},
    )
    assert poll.status_code == 200
    assert poll.json()["status"] == "ready"
    assert poll.json()["result"]["answer"] == "Ready: /Baker-Feed/Clerk-Workbench/out.md"
    assert poll.json()["draft_content"] == "draft body"
    assert poll.json()["draft_path"] == "/Baker-Feed/Clerk-Workbench/out.md"
    assert poll.json()["prompt_tokens"] == 12000
    assert poll.json()["completion_tokens"] == 345
    assert poll.json()["total_tokens"] == 12345
    assert poll.json()["context_window_used"] == 12000
    assert poll.json()["context_window_max"] == 1000000
    assert poll.json()["session_cost_usd"] == 0.0042


def test_clerk_edit_shell_no_header_and_fetches_auth_gated_content(monkeypatch):
    dash, store = _install_fake_store(monkeypatch)
    now = datetime.now(timezone.utc)
    store.rows["sess-1"] = {
        "session_id": "sess-1",
        "task": "render",
        "status": "ready",
        "result_json": {"status": "ready"},
        "draft_content": "<script>alert(1)</script>",
        "draft_path": "/Baker-Feed/Clerk-Workbench/out.md",
        "source_meta": {},
        "error": None,
        "created_at": now,
        "updated_at": now,
    }

    client = TestClient(dash.app)
    missing = client.get("/clerk/edit/missing")
    assert missing.status_code == 200
    assert "Session not found" in missing.text

    resp = client.get("/clerk/edit/sess-1")
    assert resp.status_code == 200, resp.text
    assert "<script>alert(1)</script>" not in resp.text
    assert "innerHTML" not in resp.text
    assert "/api/clerk/session/${sessionId}" in resp.text
    assert 'fetch("/api/client-config")' in resp.text
    assert "loadClientConfig().then(loadSession)" in resp.text

    unauthenticated_api = client.get("/api/clerk/session/sess-1")
    assert unauthenticated_api.status_code == 401

    authenticated_api = client.get(
        "/api/clerk/session/sess-1",
        headers={"X-Baker-Key": "test-key-clerk"},
    )
    assert authenticated_api.status_code == 200
    assert authenticated_api.json()["draft_content"] == "<script>alert(1)</script>"


def test_clerk_launcher_shell_and_sessions_endpoint(monkeypatch):
    dash, store = _install_fake_store(monkeypatch)
    older = datetime(2026, 1, 1, tzinfo=timezone.utc)
    newer = datetime(2026, 1, 2, tzinfo=timezone.utc)
    store.rows["older"] = {
        "session_id": "older",
        "task": "old task",
        "status": "ready",
        "result_json": {},
        "draft_content": "old",
        "draft_path": "/Baker-Feed/Clerk-Workbench/old.md",
        "source_meta": {},
        "error": None,
        "created_at": older,
        "updated_at": older,
    }
    store.rows["newer"] = {
        "session_id": "newer",
        "task": "x" * 140,
        "status": "running",
        "result_json": {},
        "draft_content": None,
        "draft_path": None,
        "source_meta": {},
        "error": None,
        "created_at": newer,
        "updated_at": newer,
    }

    client = TestClient(dash.app)
    launcher = client.get("/clerk")
    assert launcher.status_code == 200
    assert "test-key-clerk" not in launcher.text
    assert "/api/clerk/run" in launcher.text
    assert 'fetch("/api/client-config")' in launcher.text
    assert "loadClientConfig().then(loadSessions)" in launcher.text

    no_key = client.get("/api/clerk/sessions")
    assert no_key.status_code == 401

    resp = client.get("/api/clerk/sessions?limit=1", headers={"X-Baker-Key": "test-key-clerk"})
    assert resp.status_code == 200, resp.text
    sessions = resp.json()["sessions"]
    assert len(sessions) == 1
    assert sessions[0]["session_id"] == "newer"
    assert sessions[0]["status"] == "running"
    assert len(sessions[0]["task"]) == 120
    assert sessions[0]["task"].endswith("...")


def test_clerk_save_working_folder_uses_save_helper(monkeypatch):
    dash, store = _install_fake_store(monkeypatch)
    now = datetime.now(timezone.utc)
    store.rows["sess-save"] = {
        "session_id": "sess-save",
        "task": "save",
        "status": "ready",
        "result_json": {},
        "draft_content": "old",
        "draft_path": "/Baker-Feed/Clerk-Workbench/out.md",
        "source_meta": {},
        "error": None,
        "created_at": now,
        "updated_at": now,
    }
    calls = []

    def fake_save(session_id, content, target_path, approved_save_paths):
        calls.append((session_id, content, target_path, approved_save_paths))
        dash._clerk_update_session(
            session_id,
            status="saved",
            draft_content=content,
            draft_path=target_path,
            result_json={"status": "saved", "path": target_path},
        )
        return {"session_id": session_id, "status": "saved", "path": target_path}

    monkeypatch.setattr(dash, "_clerk_save_content_sync", fake_save)

    client = TestClient(dash.app)
    resp = client.post(
        "/api/clerk/save/sess-save",
        json={"content": "new content", "target_path": "/Baker-Feed/Clerk-Workbench/out.md"},
        headers={"X-Baker-Key": "test-key-clerk"},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "saved"
    assert calls == [("sess-save", "new content", "/Baker-Feed/Clerk-Workbench/out.md", set())]
    assert store.rows["sess-save"]["draft_content"] == "new content"


def test_clerk_save_non_working_target_requires_approval(monkeypatch):
    dash, store = _install_fake_store(monkeypatch)
    now = datetime.now(timezone.utc)
    store.rows["sess-reject"] = {
        "session_id": "sess-reject",
        "task": "save",
        "status": "ready",
        "result_json": {},
        "draft_content": "old",
        "draft_path": "/Baker-Feed/Clerk-Workbench/out.md",
        "source_meta": {},
        "error": None,
        "created_at": now,
        "updated_at": now,
    }

    client = TestClient(dash.app)
    resp = client.post(
        "/api/clerk/save/sess-reject",
        json={"content": "new", "target_path": "/Baker-Feed/Approved/out.md"},
        headers={"X-Baker-Key": "test-key-clerk"},
    )

    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]["status"] == "pending_approval"
    assert store.rows["sess-reject"]["status"] == "pending_approval"


def test_clerk_save_rejects_api_key_derived_token_when_secret_unset(monkeypatch):
    dash, store = _install_fake_store(monkeypatch)
    now = datetime.now(timezone.utc)
    target = "/Baker-Feed/Approved/out.md"
    store.rows["sess-api-key-token"] = {
        "session_id": "sess-api-key-token",
        "task": "save",
        "status": "ready",
        "result_json": {},
        "draft_content": "old",
        "draft_path": "/Baker-Feed/Clerk-Workbench/out.md",
        "source_meta": {},
        "error": None,
        "created_at": now,
        "updated_at": now,
    }
    token = _manual_save_token("test-key-clerk", "sess-api-key-token", target)

    client = TestClient(dash.app)
    resp = client.post(
        "/api/clerk/save/sess-api-key-token",
        json={"content": "new", "target_path": target, "approval_token": token},
        headers={"X-Baker-Key": "test-key-clerk"},
    )

    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]["status"] == "pending_approval"
    assert store.rows["sess-api-key-token"]["status"] == "pending_approval"


def test_clerk_save_secret_unset_rejects_approved_root_but_allows_working_folder(monkeypatch):
    dash, store = _install_fake_store(monkeypatch)
    now = datetime.now(timezone.utc)
    store.rows["sess-no-secret"] = {
        "session_id": "sess-no-secret",
        "task": "save",
        "status": "ready",
        "result_json": {},
        "draft_content": "old",
        "draft_path": "/Baker-Feed/Clerk-Workbench/out.md",
        "source_meta": {},
        "error": None,
        "created_at": now,
        "updated_at": now,
    }
    calls = []

    def fake_save(session_id, content, target_path, approved_save_paths):
        calls.append((session_id, content, target_path, approved_save_paths))
        return {"session_id": session_id, "status": "saved", "path": target_path}

    monkeypatch.setattr(dash, "_clerk_save_content_sync", fake_save)
    client = TestClient(dash.app)

    approved = client.post(
        "/api/clerk/save/sess-no-secret",
        json={
            "content": "approved",
            "target_path": "/Baker-Feed/Approved/out.md",
            "approval_token": "not-enough",
        },
        headers={"X-Baker-Key": "test-key-clerk"},
    )
    working = client.post(
        "/api/clerk/save/sess-no-secret",
        json={"content": "working", "target_path": "/Baker-Feed/Clerk-Workbench/out.md"},
        headers={"X-Baker-Key": "test-key-clerk"},
    )

    assert approved.status_code == 403, approved.text
    assert working.status_code == 200, working.text
    assert calls == [("sess-no-secret", "working", "/Baker-Feed/Clerk-Workbench/out.md", set())]


def test_clerk_save_exact_approved_target_passes_approved_path_set(monkeypatch):
    dash, store = _install_fake_store(monkeypatch)
    monkeypatch.setenv("CLERK_SAVE_APPROVAL_SECRET", "distinct-server-only-secret")
    now = datetime.now(timezone.utc)
    target = "/Baker-Feed/Approved/out.md"
    store.rows["sess-approved"] = {
        "session_id": "sess-approved",
        "task": "save",
        "status": "ready",
        "result_json": {},
        "draft_content": "old",
        "draft_path": "/Baker-Feed/Clerk-Workbench/out.md",
        "source_meta": {},
        "error": None,
        "created_at": now,
        "updated_at": now,
    }
    token = dash._clerk_save_approval_token("sess-approved", target)
    calls = []

    def fake_save(session_id, content, target_path, approved_save_paths):
        calls.append((session_id, content, target_path, approved_save_paths))
        return {"session_id": session_id, "status": "saved", "path": target_path}

    monkeypatch.setattr(dash, "_clerk_save_content_sync", fake_save)

    client = TestClient(dash.app)
    resp = client.post(
        "/api/clerk/save/sess-approved",
        json={"content": "new", "target_path": target, "approval_token": token},
        headers={"X-Baker-Key": "test-key-clerk"},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["path"] == target
    assert calls == [("sess-approved", "new", target, {target})]


def test_clerk_routes_use_asyncio_to_thread():
    src = open("outputs/dashboard.py", encoding="utf-8").read()

    assert "await asyncio.to_thread(_clerk_run_session_sync" in src
    assert "await asyncio.to_thread(\n        _clerk_save_content_sync" in src
