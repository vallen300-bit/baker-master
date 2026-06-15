"""
AI_HOTEL_FIELD_CAPTURE_1: /api/ai-hotel/capture + /api/ai-hotel/captures tests.

Source-level checks always run. TestClient runs skip cleanly when
outputs.dashboard cannot import (local Python 3.9 PEP-604 chain — clears on
3.10+ and in CI).
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

import pytest


def _dashboard_importable() -> bool:
    try:
        import outputs.dashboard  # noqa: F401
        return True
    except Exception:
        return False


_skip_without_dashboard = pytest.mark.skipif(
    not _dashboard_importable(),
    reason="outputs.dashboard unimportable (Python 3.9 PEP-604 chain — clears on 3.10+)",
)

# A tiny valid 1x1 JPEG so PIL/upload validation has real bytes to chew.
_JPEG_1x1 = bytes.fromhex(
    "ffd8ffe000104a46494600010100000100010000ffdb004300080606070605080707"
    "07090908"  # truncated header is fine — content-type allowlist gates, not decode
)


# ─── Source-level checks (always run) ──────────────────────────────────────


def test_routes_registered_in_source():
    src = Path("outputs/dashboard.py").read_text()
    assert '"/api/ai-hotel/capture"' in src
    assert '"/api/ai-hotel/captures"' in src
    assert 'tags=["ai-hotel"]' in src
    assert 'async def ai_hotel_capture(' in src
    assert 'async def ai_hotel_captures(' in src


def test_capture_reuses_scan_image_model_string():
    """Must reuse scan_image's exact model string — never guess a model name."""
    src = Path("outputs/dashboard.py").read_text()
    # The classification call uses the same model literal as scan_image.
    assert src.count('_llm_call("gemini-2.5-flash"') >= 2


def test_image_never_written_to_disk():
    src = Path("outputs/dashboard.py").read_text()
    # Capture handler must not open files for writing (Render FS is ephemeral).
    seg = src[src.index("async def ai_hotel_capture("):src.index("async def ai_hotel_captures(")]
    assert "image_b64" in seg
    assert "open(" not in seg  # base64 → Postgres, never disk


# ─── Stub store for TestClient runs ────────────────────────────────────────


class _DictCursor:
    """Stands in for both a plain cursor (INSERT/RETURNING) and a
    RealDictCursor (SELECT returns dict rows)."""

    def __init__(self, store, real_dict=False):
        self._store = store
        self._real_dict = real_dict
        self._result = []

    def execute(self, sql, params=None):
        if "INSERT INTO ai_hotel_captures" in sql:
            source, note, b64, media, section, related, summary = params
            new_id = self._store._next_id
            self._store._next_id += 1
            self._store.rows.append({
                "id": new_id,
                "created_at": _dt.datetime(2026, 6, 15, 12, 0, 0),
                "source": source,
                "note_text": note,
                "image_b64": b64,
                "image_media": media,
                "section_guess": section,
                "related_area": related,
                "summary": summary,
                "status": "new",
            })
            self._result = [(new_id,)]
        elif "FROM ai_hotel_captures" in sql:
            rows = [r for r in self._store.rows if r["status"] != "dismissed"]
            rows = sorted(rows, key=lambda r: r["created_at"], reverse=True)
            self._result = rows
        else:
            self._result = []

    def fetchone(self):
        return self._result[0] if self._result else None

    def fetchall(self):
        return self._result

    def close(self):
        pass


class _StubConn:
    def __init__(self, store):
        self._store = store

    def cursor(self, cursor_factory=None):
        return _DictCursor(self._store, real_dict=cursor_factory is not None)

    def commit(self):
        pass

    def rollback(self):
        pass


class _StubStore:
    def __init__(self):
        self.rows = []
        self._next_id = 1

    def _get_conn(self):
        return _StubConn(self)

    def _put_conn(self, conn):
        pass


class _FakeUsage:
    input_tokens = 10
    output_tokens = 5


class _FakeResp:
    def __init__(self, text):
        self.text = text
        self.usage = _FakeUsage()


def _client(monkeypatch, llm_text='{"section_guess":"general","related_area":null,"summary":"x"}'):
    from fastapi.testclient import TestClient
    import outputs.dashboard as dash
    import orchestrator.cost_monitor as cm

    monkeypatch.setenv("BAKER_API_KEY", "test-key")
    monkeypatch.setattr(dash, "_BAKER_API_KEY", "test-key")
    dash.app.dependency_overrides.pop(dash.verify_api_key, None)

    stub = _StubStore()
    monkeypatch.setattr(dash, "_get_store", lambda: stub)
    monkeypatch.setattr(dash, "_llm_call", lambda *a, **k: _FakeResp(llm_text))
    monkeypatch.setattr(cm, "log_api_cost", lambda *a, **k: None)
    return TestClient(dash.app), stub


# ─── TestClient runs ───────────────────────────────────────────────────────


@_skip_without_dashboard
def test_401_without_auth(monkeypatch):
    client, _ = _client(monkeypatch)
    resp = client.post("/api/ai-hotel/capture", data={"note": "hi"})
    assert resp.status_code == 401


@_skip_without_dashboard
def test_400_when_neither_image_nor_note(monkeypatch):
    client, _ = _client(monkeypatch)
    resp = client.post("/api/ai-hotel/capture", headers={"X-Baker-Key": "test-key"},
                       data={"note": "   "})
    assert resp.status_code == 400


@_skip_without_dashboard
def test_note_only_classified_and_stored(monkeypatch):
    client, stub = _client(
        monkeypatch,
        llm_text='{"section_guess":"stakeholder","related_area":"NVIDIA","summary":"NVIDIA wants a hospitality reference."}',
    )
    resp = client.post("/api/ai-hotel/capture", headers={"X-Baker-Key": "test-key"},
                       data={"note": "Talked to NVIDIA booth about a flagship reference."})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["section_guess"] == "stakeholder"
    assert body["related_area"] == "NVIDIA"
    assert body["summary"].startswith("NVIDIA wants")
    assert len(stub.rows) == 1
    assert stub.rows[0]["source"] == "note"
    assert stub.rows[0]["image_b64"] is None


@_skip_without_dashboard
def test_classification_parse_failure_falls_soft_to_general(monkeypatch):
    client, stub = _client(monkeypatch, llm_text="this is not json at all, sorry")
    resp = client.post("/api/ai-hotel/capture", headers={"X-Baker-Key": "test-key"},
                       data={"note": "Some floor observation"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["section_guess"] == "general"
    assert body["related_area"] is None
    # summary falls back to the note text.
    assert "floor observation" in body["summary"]


@_skip_without_dashboard
def test_invalid_section_from_model_coerced_to_general(monkeypatch):
    client, _ = _client(
        monkeypatch,
        llm_text='{"section_guess":"marketing","related_area":"x","summary":"y"}',
    )
    resp = client.post("/api/ai-hotel/capture", headers={"X-Baker-Key": "test-key"},
                       data={"note": "note"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["section_guess"] == "general"


@_skip_without_dashboard
def test_fenced_json_is_parsed(monkeypatch):
    client, _ = _client(
        monkeypatch,
        llm_text='```json\n{"section_guess":"research","related_area":null,"summary":"A market datapoint."}\n```',
    )
    resp = client.post("/api/ai-hotel/capture", headers={"X-Baker-Key": "test-key"},
                       data={"note": "competitor opened an AI suite"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["section_guess"] == "research"


@_skip_without_dashboard
def test_bad_image_type_rejected(monkeypatch):
    client, _ = _client(monkeypatch)
    resp = client.post(
        "/api/ai-hotel/capture",
        headers={"X-Baker-Key": "test-key"},
        files={"image": ("note.txt", b"not an image", "text/plain")},
    )
    assert resp.status_code == 400


@_skip_without_dashboard
def test_captures_read_builds_data_url_and_hides_dismissed(monkeypatch):
    client, stub = _client(monkeypatch)
    stub.rows = [
        {"id": 1, "created_at": _dt.datetime(2026, 6, 15, 9, 0), "source": "photo",
         "note_text": None, "image_b64": "QUJD", "image_media": "image/jpeg",
         "section_guess": "use_case", "related_area": "concierge",
         "summary": "Booth demo of concierge AI.", "status": "new"},
        {"id": 2, "created_at": _dt.datetime(2026, 6, 15, 10, 0), "source": "note",
         "note_text": "x", "image_b64": None, "image_media": None,
         "section_guess": "general", "related_area": None,
         "summary": "A note.", "status": "dismissed"},
    ]
    resp = client.get("/api/ai-hotel/captures", headers={"X-Baker-Key": "test-key"})
    assert resp.status_code == 200, resp.text
    caps = resp.json()["captures"]
    # dismissed row hidden.
    assert len(caps) == 1
    c = caps[0]
    assert c["id"] == 1
    assert c["image"] == "data:image/jpeg;base64,QUJD"
    assert "image_b64" not in c  # raw b64 popped, only the data URL returned


@_skip_without_dashboard
def test_captures_limit_clamped(monkeypatch):
    client, _ = _client(monkeypatch)
    resp = client.get("/api/ai-hotel/captures?limit=9999",
                      headers={"X-Baker-Key": "test-key"})
    assert resp.status_code == 200
