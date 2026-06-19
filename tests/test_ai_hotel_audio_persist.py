"""AI_HOTEL_FIELD_NOTES_AND_AUDIO_1 (WP-A) — raw audio persistence + audio shelf.

AC6  audio submit creates capture row + ai_hotel_capture_audio row BEFORE transcription.
AC7  transcription failure still leaves the capture row AND the audio row.
AC8  successful transcription writes transcript to BOTH note_text and audio.transcript_text.
AC9  card detail can surface the associated audio (the per-capture audio fetch endpoint).
AC10 list view returns audio METADATA only — never the large audio_b64.

The LLM is mocked at the `_llm_call` seam only. TestClient runs skip cleanly when
outputs.dashboard cannot import.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

import pytest


# ─── Source / migration checks (always run) ─────────────────────────────────


def test_migration_shape():
    mig = Path("migrations/20260619b_ai_hotel_capture_audio.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS ai_hotel_capture_audio" in mig
    assert "REFERENCES ai_hotel_captures(id) ON DELETE CASCADE" in mig
    assert "audio_b64        TEXT NOT NULL" in mig
    assert "transcript_text" in mig and "duration_seconds" in mig
    up = mig.split("== migrate:down ==")[0]
    assert "DROP TABLE" not in up
    assert "-- DROP TABLE IF EXISTS ai_hotel_capture_audio" in mig


def test_list_endpoint_audio_metadata_only_in_source():
    """AC10 guard: the list query must NOT select audio_b64; the detail endpoint
    is the only one that returns the bytes."""
    src = Path("outputs/dashboard.py").read_text()
    listseg = src[src.index("async def ai_hotel_captures("):src.index("async def ai_hotel_capture_audio_detail(")]
    aq = listseg[listseg.index("FROM ai_hotel_capture_audio"):]
    # the list audio query selects metadata columns, never the base64 blob
    assert "audio_b64" not in aq.split("ORDER BY")[0]
    assert "has_transcript" in listseg
    # the detail endpoint does return audio_b64
    detseg = src[src.index("async def ai_hotel_capture_audio_detail("):src.index("# ── AI_HOTEL_VOICE_FORM_SUPPLIER_1")]
    assert "audio_b64" in detseg


# ─── TestClient harness ─────────────────────────────────────────────────────


def _dashboard_importable() -> bool:
    try:
        import outputs.dashboard  # noqa: F401
        return True
    except Exception:
        return False


_skip = pytest.mark.skipif(
    not _dashboard_importable(),
    reason="outputs.dashboard unimportable (Python 3.9 PEP-604 chain — clears on 3.10+)",
)


class _FakeUsage:
    input_tokens = 10
    output_tokens = 5


class _FakeResp:
    def __init__(self, text):
        self.text = text
        self.usage = _FakeUsage()


def _has_audio_part(messages):
    for m in (messages or []):
        c = m.get("content")
        if isinstance(c, list):
            for p in c:
                if isinstance(p, dict) and p.get("type") == "audio":
                    return True
    return False


class _Cur:
    def __init__(self, store):
        self.s = store
        self._res = []
        self.rowcount = 0

    def execute(self, sql, params=None):
        self.rowcount = 0
        if "INSERT INTO ai_hotel_captures" in sql:
            source, note, b64, media, section, related, summary = params
            nid = self.s.nextcap; self.s.nextcap += 1
            self.s.captures.append({"id": nid, "source": source, "note_text": note, "summary": summary,
                                    "status": "new", "image_b64": b64, "image_media": media,
                                    "section_guess": section, "related_area": related,
                                    "created_at": _dt.datetime(2026, 6, 19, 9, nid % 60, 0)})
            self._res = [(nid,)]; self.rowcount = 1
        elif "INSERT INTO ai_hotel_capture_images" in sql:
            cid, ordi, b64, media = params
            self.s.images.append({"capture_id": cid, "ordinal": ordi, "image_b64": b64, "image_media": media})
            self.rowcount = 1
        elif "INSERT INTO ai_hotel_capture_audio" in sql:
            cid, ab64, amedia, dur = params           # ordinal is the literal 0 in the SQL
            aid = self.s.nextaud; self.s.nextaud += 1
            self.s.audio.append({"id": aid, "capture_id": cid, "ordinal": 0, "audio_b64": ab64,
                                 "audio_media": amedia, "duration_seconds": dur, "transcript_text": None})
            self._res = [(aid,)]; self.rowcount = 1
        elif "UPDATE ai_hotel_captures" in sql and "note_text" in sql:
            note, summary, cid = params
            for r in self.s.captures:
                if r["id"] == cid:
                    r["note_text"] = note; r["summary"] = summary
            self.rowcount = 1
        elif "UPDATE ai_hotel_capture_audio" in sql and "transcript_text" in sql:
            tx, aid = params
            for a in self.s.audio:
                if a["id"] == aid:
                    a["transcript_text"] = tx
            self.rowcount = 1
        elif "INSERT INTO ai_hotel_form_records" in sql:
            cid = params[0]; ft = params[1]
            fid = self.s.nextform; self.s.nextform += 1
            self.s.forms.append({"id": fid, "capture_id": cid, "form_type": ft, "status": "draft"})
            self._res = [(fid,)]; self.rowcount = 1
        elif "FROM ai_hotel_capture_images" in sql:
            ids = params[0] if params else []
            kids = [dict(i) for i in self.s.images if i["capture_id"] in ids]
            self._res = sorted(kids, key=lambda i: (i["capture_id"], i["ordinal"]))
        elif "FROM ai_hotel_form_records" in sql:
            ids = params[0] if params else []
            frs = [f for f in self.s.forms if f["capture_id"] in ids and f.get("status") != "discarded"]
            latest = {}
            for f in sorted(frs, key=lambda f: (f["capture_id"], f["id"])):
                latest[f["capture_id"]] = f
            self._res = [{"capture_id": f["capture_id"], "id": f["id"], "form_type": f["form_type"],
                          "schema_version": "v", "status": f["status"], "extracted_json": {},
                          "corrected_json": None, "field_meta_json": {}} for f in latest.values()]
        elif "FROM ai_hotel_capture_audio" in sql and "audio_b64" in sql:
            cid = params[0] if params else None      # detail endpoint
            self._res = [dict(a) for a in self.s.audio if a["capture_id"] == cid]
        elif "FROM ai_hotel_capture_audio" in sql:    # list metadata (no audio_b64)
            ids = params[0] if params else []
            self._res = [{"capture_id": a["capture_id"], "ordinal": a["ordinal"],
                          "audio_media": a["audio_media"], "duration_seconds": a["duration_seconds"],
                          "has_transcript": bool(a["transcript_text"])}
                         for a in self.s.audio if a["capture_id"] in ids]
        elif "FROM ai_hotel_captures" in sql:
            rows = [r for r in self.s.captures if r.get("status") != "dismissed"]
            self._res = [dict(r) for r in sorted(rows, key=lambda r: r["created_at"], reverse=True)]
        else:
            self._res = []

    def fetchone(self):
        return self._res[0] if self._res else None

    def fetchall(self):
        return self._res

    def close(self):
        pass


class _Conn:
    def __init__(self, store):
        self.s = store

    def cursor(self, cursor_factory=None):
        return _Cur(self.s)

    def commit(self):
        pass

    def rollback(self):
        pass


class _Store:
    def __init__(self):
        self.captures = []
        self.images = []
        self.audio = []
        self.forms = []
        self.nextcap = 1
        self.nextaud = 1
        self.nextform = 1

    def _get_conn(self):
        return _Conn(self)

    def _put_conn(self, conn):
        pass


def _client(monkeypatch, store, llm=None):
    from fastapi.testclient import TestClient
    import outputs.dashboard as dash
    import orchestrator.cost_monitor as cm
    monkeypatch.setenv("BAKER_API_KEY", "test-key")
    monkeypatch.setattr(dash, "_BAKER_API_KEY", "test-key")
    dash.app.dependency_overrides.pop(dash.verify_api_key, None)
    monkeypatch.setattr(dash, "_get_store", lambda: store)
    monkeypatch.setattr(cm, "log_api_cost", lambda *a, **k: None)
    if llm is not None:
        monkeypatch.setattr(dash, "_llm_call", llm)
    return TestClient(dash.app)


_HDR = {"X-Baker-Key": "test-key"}
_AUDIO = {"audio": ("d.webm", b"\x1aE\xdf\xa3fakeaudiobytes", "audio/webm")}


# ─── AC6: audio row exists BEFORE transcription ─────────────────────────────


@_skip
def test_ac6_audio_row_before_transcription(monkeypatch):
    store = _Store()
    seen = {"audio_rows_at_transcribe": None}

    def _llm(model, messages=None, **k):
        if _has_audio_part(messages):
            seen["audio_rows_at_transcribe"] = len(store.audio)   # snapshot at transcription time
            return _FakeResp("the transcript")
        return _FakeResp("{}")

    client = _client(monkeypatch, store, llm=_llm)
    resp = client.post("/api/ai-hotel/form-drafts", headers=_HDR,
                       data={"form_type": "site_visit", "duration_seconds": "34"}, files=_AUDIO)
    assert resp.status_code == 200, resp.text
    assert seen["audio_rows_at_transcribe"] == 1          # row already existed when transcription ran
    assert len(store.audio) == 1
    assert store.audio[0]["duration_seconds"] == 34
    assert store.audio[0]["audio_media"] == "audio/webm"
    assert store.audio[0]["audio_b64"]                    # bytes persisted


# ─── AC7: transcription failure leaves BOTH rows ────────────────────────────


@_skip
def test_ac7_transcription_failure_keeps_capture_and_audio(monkeypatch):
    store = _Store()

    def _boom(model, messages=None, **k):
        raise RuntimeError("gemini exploded")

    client = _client(monkeypatch, store, llm=_boom)
    resp = client.post("/api/ai-hotel/form-drafts", headers=_HDR,
                       data={"form_type": "site_visit"}, files=_AUDIO)
    assert resp.status_code == 200, resp.text          # not a 400-with-zero-rows
    assert len(store.captures) == 1                     # capture kept
    assert len(store.audio) == 1                        # audio kept (no loss)
    assert store.audio[0]["transcript_text"] is None    # transcription failed → no transcript


# ─── AC8: transcript mirrored to note_text AND audio.transcript_text ────────


@_skip
def test_ac8_transcript_written_to_both(monkeypatch):
    store = _Store()

    def _llm(model, messages=None, **k):
        if _has_audio_part(messages):
            return _FakeResp("Vacant lot near the NVIDIA campus.")
        return _FakeResp("{}")

    client = _client(monkeypatch, store, llm=_llm)
    resp = client.post("/api/ai-hotel/form-drafts", headers=_HDR,
                       data={"form_type": "site_visit"}, files=_AUDIO)
    assert resp.status_code == 200, resp.text
    assert "NVIDIA campus" in (store.captures[0]["note_text"] or "")     # note_text
    assert "NVIDIA campus" in (store.audio[0]["transcript_text"] or "")  # audio.transcript_text


# ─── AC10: list metadata only; AC9: detail returns the bytes ────────────────


@_skip
def test_ac10_list_metadata_only_and_ac9_detail_has_bytes(monkeypatch):
    store = _Store()
    store.captures = [{"id": 17, "source": "audio", "note_text": "Palo Alto site", "summary": "Palo Alto",
                       "status": "new", "image_b64": None, "image_media": None, "section_guess": "general",
                       "related_area": None, "created_at": _dt.datetime(2026, 6, 19, 9, 0, 0)}]
    store.audio = [{"id": 1, "capture_id": 17, "ordinal": 0, "audio_b64": "QUJDQUJD",
                    "audio_media": "audio/webm", "duration_seconds": 34, "transcript_text": "Palo Alto site"}]
    client = _client(monkeypatch, store)

    # list: metadata only, NO base64
    item = client.get("/api/ai-hotel/captures", headers=_HDR).json()["captures"][0]
    assert isinstance(item["audio"], list) and len(item["audio"]) == 1
    meta = item["audio"][0]
    assert meta["duration_seconds"] == 34 and meta["has_transcript"] is True
    assert "audio_b64" not in meta and "audio" not in meta     # no bytes in the list (AC10)

    # detail: full bytes as a data URL (AC9)
    det = client.get("/api/ai-hotel/captures/17/audio", headers=_HDR).json()["audio"]
    assert len(det) == 1
    assert det[0]["audio"].startswith("data:audio/webm;base64,QUJDQUJD")
    assert det[0]["transcript_text"] == "Palo Alto site"


@_skip
def test_detail_audio_unknown_capture_fail_soft(monkeypatch):
    store = _Store()
    client = _client(monkeypatch, store)
    resp = client.get("/api/ai-hotel/captures/9999/audio", headers=_HDR)
    assert resp.status_code == 200
    assert resp.json()["audio"] == []


@_skip
def test_detail_audio_requires_auth(monkeypatch):
    store = _Store()
    client = _client(monkeypatch, store)
    assert client.get("/api/ai-hotel/captures/1/audio").status_code == 401
