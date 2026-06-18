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

def _make_jpeg(px: int = 2400) -> bytes:
    """A real, high-entropy JPEG large enough to exercise the DB size cap."""
    from io import BytesIO
    from PIL import Image as PILImage
    # effect_noise → incompressible grayscale; convert to RGB for a fat JPEG.
    img = PILImage.effect_noise((px, px), 120).convert("RGB")
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return buf.getvalue()


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
        if "INSERT INTO ai_hotel_capture_images" in sql:
            # AI_HOTEL_CAPTURE_UPGRADES_1 child-table insert.
            capture_id, ordinal, b64, media = params
            self._store.image_rows.append({
                "id": self._store._next_img_id,
                "capture_id": capture_id,
                "ordinal": ordinal,
                "image_b64": b64,
                "image_media": media,
            })
            self._store._next_img_id += 1
            self._result = []
        elif "INSERT INTO ai_hotel_captures" in sql:
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
        elif "FROM ai_hotel_capture_images" in sql:
            # GET child-image fetch: WHERE capture_id = ANY(%s) ORDER BY capture_id, ordinal.
            cap_ids = params[0] if params else []
            kids = [dict(i) for i in self._store.image_rows if i["capture_id"] in cap_ids]
            kids = sorted(kids, key=lambda i: (i["capture_id"], i["ordinal"]))
            self._result = kids
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
        self.image_rows = []      # AI_HOTEL_CAPTURE_UPGRADES_1 child photos
        self._next_id = 1
        self._next_img_id = 1

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


class _FakeIngestResult:
    """Mimics kbl.ingest_endpoint.IngestResult. qdrant_point_id=None models the
    'wiki written but not vectorized' path (Qdrant down / empty embedding)."""
    def __init__(self, qdrant_point_id=987654):
        self.wiki_page_id = 1
        self.slug = "ai-hotel-capture-1"
        self.qdrant_point_id = qdrant_point_id
        self.gold_mirrored = False
        self.mirror_path = None


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
    # AI_HOTEL_CAPTURE_EMBED_1: capture flow now routes the note through the
    # kbl ingest chokepoint (which uses the global SentinelStoreBack singleton,
    # NOT the stub store). No-op it by default so TestClient runs stay hermetic
    # and never touch real PG/Qdrant; embed-specific tests re-patch it.
    import kbl.ingest_endpoint as _kie
    monkeypatch.setattr(_kie, "ingest", lambda *a, **k: _FakeIngestResult())
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
        files={"images": ("note.txt", b"not an image", "text/plain")},
    )
    assert resp.status_code == 400


@_skip_without_dashboard
def test_undecodable_image_rejected_not_stored(monkeypatch):
    """codex G3 S2: malformed bytes labelled image/jpeg must 400, never persist
    raw bytes that bypass the size cap."""
    client, stub = _client(monkeypatch)
    junk = b"\xff" * 1_000_000  # 1MB of non-image bytes, claims to be a JPEG
    resp = client.post(
        "/api/ai-hotel/capture",
        headers={"X-Baker-Key": "test-key"},
        files={"images": ("booth.jpg", junk, "image/jpeg")},
    )
    assert resp.status_code == 400, resp.text
    assert len(stub.rows) == 0  # nothing persisted


@_skip_without_dashboard
def test_valid_large_image_capped_under_500kb(monkeypatch):
    """codex G3 S2: a real oversize photo is stored, but only after being
    compressed under the ~500KB base64 DB cap."""
    client, stub = _client(monkeypatch)
    big = _make_jpeg(2400)
    assert len(big) > 600_000, "test fixture should start well over the cap"
    resp = client.post(
        "/api/ai-hotel/capture",
        headers={"X-Baker-Key": "test-key"},
        files={"images": ("booth.jpg", big, "image/jpeg")},
        data={"note": "booth shot"},
    )
    assert resp.status_code == 200, resp.text
    assert len(stub.rows) == 1
    row = stub.rows[0]
    assert row["source"] == "photo"
    assert row["image_media"] == "image/jpeg"
    # base64 length stays under ~500KB (370KB raw * 4/3 ≈ 493K chars; allow slack).
    assert row["image_b64"] is not None
    assert len(row["image_b64"]) <= 520_000


@_skip_without_dashboard
def test_oversize_note_rejected(monkeypatch):
    """codex G3 S3: note length is enforced server-side, not just by the HTML
    maxlength attribute. AI_HOTEL_CAPTURE_UPGRADES_1 raised the cap to 50000 so
    long audio transcripts fit; > 50000 is still rejected."""
    client, stub = _client(monkeypatch)
    resp = client.post(
        "/api/ai-hotel/capture",
        headers={"X-Baker-Key": "test-key"},
        data={"note": "x" * 50001},
    )
    assert resp.status_code == 400, resp.text
    assert len(stub.rows) == 0


@_skip_without_dashboard
def test_long_note_under_new_cap_succeeds(monkeypatch):
    """A note that exceeds the OLD 4000 cap but is within the new 50000 cap must
    now succeed (long transcripts must fit)."""
    client, stub = _client(monkeypatch)
    resp = client.post(
        "/api/ai-hotel/capture",
        headers={"X-Baker-Key": "test-key"},
        data={"note": "x" * 5000},
    )
    assert resp.status_code == 200, resp.text
    assert len(stub.rows) == 1


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


# ─── AI_HOTEL_CAPTURE_CLASSIFY_1: defect-1 regression (classification) ──────


def test_classify_call_disables_thinking_and_uses_json():
    """Source-level guard for the root cause: the capture classifier MUST
    disable gemini-2.5-flash thinking (thinking_budget=0) and request JSON.
    Without these the 600-token call truncates mid-JSON (thinking ate the
    budget, finish_reason=MAX_TOKENS) and EVERY capture silently defaulted to
    section=general + raw-truncation summary."""
    src = Path("outputs/dashboard.py").read_text()
    seg = src[src.index("async def ai_hotel_capture("):src.index("async def ai_hotel_captures(")]
    assert "thinking_budget=0" in seg
    assert 'response_format="json"' in seg


@_skip_without_dashboard
def test_known_note_routes_off_general_with_ai_summary(monkeypatch):
    """Behavioral regression: a real classified note must route OFF general and
    carry an AI summary, never the raw note[:200] truncation default."""
    note = ("Housekeeper, front desk and security teams want hands-free "
            "multilingual comms while on the floor.")
    client, stub = _client(
        monkeypatch,
        llm_text='{"section_guess":"use_case","related_area":"staff training",'
                 '"summary":"AI comms for hotel staff: multilingual, hands-free"}',
    )
    resp = client.post("/api/ai-hotel/capture", headers={"X-Baker-Key": "test-key"},
                       data={"note": note})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["section_guess"] == "use_case"          # routed off general
    assert body["section_guess"] != "general"
    assert body["related_area"] == "staff training"
    assert body["summary"] != note[:200]                # AI summary, not raw trunc
    assert body["summary"].startswith("AI comms")


@_skip_without_dashboard
def test_classify_exception_falls_soft_but_returns_200(monkeypatch):
    """FAIL-LOUD-but-fault-tolerant: if the LLM call raises, the capture still
    persists + returns 200 general (the error is logged loud server-side)."""
    client, stub = _client(monkeypatch)
    import outputs.dashboard as dash

    def _boom(*a, **k):
        raise RuntimeError("gemini exploded")

    monkeypatch.setattr(dash, "_llm_call", _boom)
    resp = client.post("/api/ai-hotel/capture", headers={"X-Baker-Key": "test-key"},
                       data={"note": "Some floor observation"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["section_guess"] == "general"
    assert len(stub.rows) == 1  # persisted despite classify failure


# ─── AI_HOTEL_CAPTURE_EMBED_1: defect-2 regression (vector memory) ──────────


def test_capture_embeds_via_kbl_ingest_source():
    """Source-level: capture flow routes the note through the canonical kbl
    ingest chokepoint, attributed (ai-hotel) and via the documented trigger."""
    src = Path("outputs/dashboard.py").read_text()
    seg = src[src.index("async def ai_hotel_capture("):src.index("async def ai_hotel_captures(")]
    assert "from kbl.ingest_endpoint import ingest" in seg
    assert 'trigger_source="ai_hotel_capture"' in seg
    assert '"ai-hotel"' in seg


@_skip_without_dashboard
def test_embed_invoked_with_attribution(monkeypatch):
    """The note is handed to kbl ingest tagged ai-hotel, authored by agent,
    via trigger_source=ai_hotel_capture."""
    client, stub = _client(
        monkeypatch,
        llm_text='{"section_guess":"comms","related_area":null,"summary":"Reach out to NVIDIA."}',
    )
    calls = []
    import kbl.ingest_endpoint as kie

    def _record(**k):
        calls.append(k)
        return _FakeIngestResult()

    monkeypatch.setattr(kie, "ingest", _record)
    resp = client.post("/api/ai-hotel/capture", headers={"X-Baker-Key": "test-key"},
                       data={"note": "Email NVIDIA about a flagship reference."})
    assert resp.status_code == 200, resp.text
    assert len(calls) == 1
    fm = calls[0]["frontmatter"]
    assert fm["type"] == "entity"
    assert fm["author"] == "agent"
    assert fm["tags"] == ["ai-hotel"]
    assert fm["slug"].startswith("ai-hotel-capture-")
    assert calls[0]["trigger_source"] == "ai_hotel_capture"


@_skip_without_dashboard
def test_embed_failure_does_not_block_capture(monkeypatch):
    """Best-effort embed: an ingest exception must NOT block the DB insert or
    the 200 response (the capture row already committed)."""
    client, stub = _client(
        monkeypatch,
        llm_text='{"section_guess":"research","related_area":null,"summary":"A datapoint."}',
    )
    import kbl.ingest_endpoint as kie

    def _boom(*a, **k):
        raise RuntimeError("qdrant down")

    monkeypatch.setattr(kie, "ingest", _boom)
    resp = client.post("/api/ai-hotel/capture", headers={"X-Baker-Key": "test-key"},
                       data={"note": "competitor opened an AI suite"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["section_guess"] == "research"
    assert len(stub.rows) == 1  # persisted despite embed failure


@_skip_without_dashboard
def test_photo_only_no_note_skips_embed(monkeypatch):
    """A pure photo with no dictation has no note_text to embed — the ingest
    chokepoint must not be called (nothing to make searchable)."""
    client, stub = _client(monkeypatch)
    calls = []
    import kbl.ingest_endpoint as kie
    monkeypatch.setattr(kie, "ingest", lambda **k: calls.append(k))
    big = _make_jpeg(2400)
    resp = client.post(
        "/api/ai-hotel/capture",
        headers={"X-Baker-Key": "test-key"},
        files={"images": ("booth.jpg", big, "image/jpeg")},
    )
    assert resp.status_code == 200, resp.text
    assert len(stub.rows) == 1
    assert len(calls) == 0  # no note → no embed


# ─── G3 re-gate: S2-1 (dependency floor) + S2-2 (embed-None path) ──────────


def test_genai_dependency_floor_supports_thinking_budget():
    """G3 S2-1: thinking_budget=0 (the Defect-1 fix) requires google-genai
    >=1.10.0 — older versions REJECT ThinkingConfig(thinking_budget=...) with a
    pydantic ValidationError, which crashes the classify call into the very
    silent-general fallback we are fixing. Guard the floor in requirements.txt."""
    import re
    req = Path("requirements.txt").read_text()
    m = re.search(r"^google-genai>=(\d+)\.(\d+)", req, re.MULTILINE)
    assert m, "google-genai floor not pinned in requirements.txt"
    major, minor = int(m.group(1)), int(m.group(2))
    assert (major, minor) >= (1, 10), (
        f"google-genai floor {major}.{minor} < 1.10 — "
        "ThinkingConfig.thinking_budget unsupported below 1.10.0"
    )


def test_thinking_config_accepts_budget_in_installed_sdk():
    """G3 S2-1 runtime proof: the installed google-genai must accept the field
    we depend on. Skips cleanly where the SDK isn't installed (e.g. local 3.9/
    homebrew without google-genai); runs green in CI / prod-parity envs."""
    try:
        from google.genai import types
    except Exception:
        pytest.skip("google-genai not importable in this env")
    # Must construct without raising — proves >=1.10.0 behavior.
    cfg = types.ThinkingConfig(thinking_budget=0)
    assert cfg.thinking_budget == 0


@_skip_without_dashboard
def test_embed_qdrant_none_does_not_claim_embedded(monkeypatch, caplog):
    """G3 S2-2: when ingest returns qdrant_point_id=None (Qdrant down / empty
    embedding), the capture must NOT log a success 'embedded' claim — it logs a
    WARNING instead, still persists the row, and still returns 200."""
    import logging
    client, stub = _client(
        monkeypatch,
        llm_text='{"section_guess":"research","related_area":null,"summary":"A datapoint."}',
    )
    import kbl.ingest_endpoint as kie
    monkeypatch.setattr(kie, "ingest", lambda **k: _FakeIngestResult(qdrant_point_id=None))
    with caplog.at_level(logging.WARNING, logger="sentinel.dashboard"):
        resp = client.post("/api/ai-hotel/capture", headers={"X-Baker-Key": "test-key"},
                           data={"note": "competitor opened an AI suite"})
    assert resp.status_code == 200, resp.text
    assert len(stub.rows) == 1  # row persisted
    text = caplog.text
    assert "NOT vector-embedded" in text          # warned about the gap
    assert "embedded to vector memory" not in text  # never falsely claimed success


# ─── AI_HOTEL_CAPTURE_UPGRADES_1: multi-photo (child table) ─────────────────


def _img_files(n):
    """n small valid JPEGs posted under the repeated `images` multipart key."""
    return [("images", (f"p{i}.jpg", _make_jpeg(64), "image/jpeg")) for i in range(n)]


@_skip_without_dashboard
def test_three_images_one_parent_three_ordered_children_classified_once(monkeypatch):
    """AC2: 3 photos + a note → 1 parent row + 3 ordered child rows; the vision
    classifier is invoked exactly once (on the first image), never per-photo."""
    import outputs.dashboard as dash
    client, stub = _client(monkeypatch)

    calls = {"n": 0}
    real_fake = _FakeResp('{"section_guess":"stakeholder","related_area":"NVIDIA","summary":"NVIDIA booth."}')

    def _counting(*a, **k):
        calls["n"] += 1
        return real_fake

    monkeypatch.setattr(dash, "_llm_call", _counting)

    resp = client.post(
        "/api/ai-hotel/capture",
        headers={"X-Baker-Key": "test-key"},
        files=_img_files(3),
        data={"note": "three booth shots"},
    )
    assert resp.status_code == 200, resp.text
    assert len(stub.rows) == 1
    assert stub.rows[0]["source"] == "photo"
    kids = sorted([i for i in stub.image_rows if i["capture_id"] == stub.rows[0]["id"]],
                  key=lambda i: i["ordinal"])
    assert [k["ordinal"] for k in kids] == [0, 1, 2]
    assert all(k["image_b64"] for k in kids)
    assert calls["n"] == 1   # classified once, not 3×


@_skip_without_dashboard
def test_ninth_image_rejected(monkeypatch):
    """AC2: more than 8 photos → 400, nothing persisted."""
    client, stub = _client(monkeypatch)
    resp = client.post(
        "/api/ai-hotel/capture",
        headers={"X-Baker-Key": "test-key"},
        files=_img_files(9),
    )
    assert resp.status_code == 400, resp.text
    assert len(stub.rows) == 0
    assert len(stub.image_rows) == 0


@_skip_without_dashboard
def test_audio_transcribed_into_note_text_source_audio(monkeypatch):
    """AC2: an audio dictation is transcribed server-side, the transcript lands
    in note_text, and provenance is source='audio'."""
    import outputs.dashboard as dash
    client, stub = _client(monkeypatch)

    def _smart(model, messages=None, **k):
        # Audio call → transcript; otherwise → classify JSON.
        msgs = messages or []
        for m in msgs:
            c = m.get("content")
            if isinstance(c, list) and any(isinstance(p, dict) and p.get("type") == "audio" for p in c):
                return _FakeResp("This is the dictated transcript about the NVIDIA booth.")
        return _FakeResp('{"section_guess":"stakeholder","related_area":"NVIDIA","summary":"Booth chat."}')

    monkeypatch.setattr(dash, "_llm_call", _smart)

    resp = client.post(
        "/api/ai-hotel/capture",
        headers={"X-Baker-Key": "test-key"},
        files={"audio": ("dictation.webm", b"\x1aE\xdf\xa3fakewebmbytes", "audio/webm")},
    )
    assert resp.status_code == 200, resp.text
    assert len(stub.rows) == 1
    row = stub.rows[0]
    assert row["source"] == "audio"
    assert "dictated transcript" in (row["note_text"] or "")
    assert len(stub.image_rows) == 0


def _has_audio_part(messages):
    for m in (messages or []):
        c = m.get("content")
        if isinstance(c, list):
            for p in c:
                if isinstance(p, dict) and p.get("type") == "audio":
                    return True
    return False


@_skip_without_dashboard
def test_audio_transcription_disables_thinking(monkeypatch):
    """AUDIO_THINKING_BUDGET_GUARD_1: the audio transcription _llm_call MUST pass
    thinking_budget=0 — the same load-bearing guard the classify call documents.
    Without it 2.5-flash's default dynamic thinking eats the output budget and
    truncates/empties the transcript (the #372 MAX_TOKENS root cause)."""
    import outputs.dashboard as dash
    client, stub = _client(monkeypatch)

    calls = []

    def _record(model, messages=None, **k):
        calls.append({"messages": messages, "kwargs": k})
        if _has_audio_part(messages):
            return _FakeResp("the transcript")
        return _FakeResp('{"section_guess":"general","related_area":null,"summary":"x"}')

    monkeypatch.setattr(dash, "_llm_call", _record)
    resp = client.post(
        "/api/ai-hotel/capture",
        headers={"X-Baker-Key": "test-key"},
        files={"audio": ("d.webm", b"\x1aE\xdf\xa3bytes", "audio/webm")},
    )
    assert resp.status_code == 200, resp.text
    audio_calls = [c for c in calls if _has_audio_part(c["messages"])]
    assert len(audio_calls) == 1
    assert audio_calls[0]["kwargs"].get("thinking_budget") == 0


@_skip_without_dashboard
def test_audio_unsupported_type_rejected(monkeypatch):
    """Audio type allowlist is enforced server-side."""
    client, stub = _client(monkeypatch)
    resp = client.post(
        "/api/ai-hotel/capture",
        headers={"X-Baker-Key": "test-key"},
        files={"audio": ("clip.txt", b"not audio", "text/plain")},
    )
    assert resp.status_code == 400, resp.text
    assert len(stub.rows) == 0


@_skip_without_dashboard
def test_get_returns_images_array_ordered_and_legacy_first(monkeypatch):
    """AC3: GET returns images:[...] ordered by ordinal; legacy `image` = first."""
    client, stub = _client(monkeypatch)
    stub.rows = [
        {"id": 7, "created_at": _dt.datetime(2026, 6, 18, 9, 0), "source": "photo",
         "note_text": "multi", "image_b64": "QUFB", "image_media": "image/jpeg",
         "section_guess": "stakeholder", "related_area": "NVIDIA",
         "summary": "Three shots.", "status": "new"},
    ]
    stub.image_rows = [
        {"id": 3, "capture_id": 7, "ordinal": 2, "image_b64": "Q0ND", "image_media": "image/jpeg"},
        {"id": 1, "capture_id": 7, "ordinal": 0, "image_b64": "QUFB", "image_media": "image/jpeg"},
        {"id": 2, "capture_id": 7, "ordinal": 1, "image_b64": "QkJC", "image_media": "image/jpeg"},
    ]
    resp = client.get("/api/ai-hotel/captures", headers={"X-Baker-Key": "test-key"})
    assert resp.status_code == 200, resp.text
    c = resp.json()["captures"][0]
    assert c["images"] == [
        "data:image/jpeg;base64,QUFB",
        "data:image/jpeg;base64,QkJC",
        "data:image/jpeg;base64,Q0ND",
    ]
    assert c["image"] == "data:image/jpeg;base64,QUFB"   # legacy = first
    assert "image_b64" not in c


@_skip_without_dashboard
def test_get_legacy_single_image_row_backward_compatible(monkeypatch):
    """AC3: a pre-upgrade row with only the parent image_b64 (no child rows) still
    renders — images=[that one], image=that one."""
    client, stub = _client(monkeypatch)
    stub.rows = [
        {"id": 5, "created_at": _dt.datetime(2026, 6, 14, 9, 0), "source": "photo",
         "note_text": None, "image_b64": "WllY", "image_media": "image/jpeg",
         "section_guess": "use_case", "related_area": None,
         "summary": "Legacy single.", "status": "new"},
    ]
    stub.image_rows = []   # no children — pre-migration capture
    resp = client.get("/api/ai-hotel/captures", headers={"X-Baker-Key": "test-key"})
    assert resp.status_code == 200, resp.text
    c = resp.json()["captures"][0]
    assert c["images"] == ["data:image/jpeg;base64,WllY"]
    assert c["image"] == "data:image/jpeg;base64,WllY"


# ─── Migration shape (source-level) ────────────────────────────────────────


def test_migration_creates_child_table_and_adds_audio_source():
    """AC1 source-level: the migration creates the child table, backfills
    existing images as ordinal=0, and adds 'audio' to the source CHECK. The
    destructive down-section stays commented (runner executes the file raw)."""
    from pathlib import Path as _P
    mig = _P("migrations/20260618_ai_hotel_capture_images.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS ai_hotel_capture_images" in mig
    assert "ON DELETE CASCADE" in mig
    assert "ordinal" in mig
    assert "INSERT INTO ai_hotel_capture_images" in mig      # backfill
    assert "WHERE c.image_b64 IS NOT NULL" in mig
    assert "'audio'" in mig                                   # source CHECK widened
    # down-section is present but commented out (never auto-run).
    assert "-- DROP TABLE IF EXISTS ai_hotel_capture_images" in mig
    up = mig.split("== migrate:down ==")[0]
    assert "DROP TABLE" not in up                             # no live drop in up
