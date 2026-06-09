from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient


class _FakeRetriever:
    def __init__(self):
        self.qdrant_collections = []
        self.email_calls = []

    def _embed_query(self, query):
        self.query = query
        return [0.1, 0.2, 0.3]

    def search_collection(self, *, query_vector, collection, limit, score_threshold, project=None, role=None):
        self.qdrant_collections.append(collection)
        if collection == "sentinel-interactions":
            return [
                SimpleNamespace(
                    source="interactions",
                    content="Spanyi 6 Jun email from the M365 ingestion collection",
                    score=0.91,
                    metadata={"collection": collection, "subject": "Spanyi"},
                    token_estimate=12,
                )
            ]
        if collection == "baker-documents":
            return [
                SimpleNamespace(
                    source="documents",
                    content="Document semantic hit",
                    score=0.7,
                    metadata={"collection": collection, "title": "doc"},
                    token_estimate=5,
                )
            ]
        return []

    def get_email_messages(self, query, limit):
        self.email_calls.append((query, limit))
        return [
            SimpleNamespace(
                source="email",
                content="Postgres email arm still runs",
                score=0.8,
                metadata={"message_id": "m1"},
                token_estimate=6,
            )
        ]

    def get_meeting_transcripts(self, query, limit):
        return []

    def get_whatsapp_messages(self, query, limit):
        return []


@pytest.fixture
def unified_client(monkeypatch):
    import outputs.dashboard as dash

    fake = _FakeRetriever()
    monkeypatch.setattr(dash.config.qdrant, "collections", [
        "baker-documents",
        "baker-conversations",
        "sentinel-interactions",
    ])
    monkeypatch.setattr(dash, "_retriever", fake)
    dash.app.dependency_overrides[dash.verify_api_key] = lambda: None
    try:
        yield TestClient(dash.app), fake
    finally:
        dash.app.dependency_overrides.pop(dash.verify_api_key, None)


def test_unified_search_uses_configured_qdrant_collections(unified_client):
    client, fake = unified_client

    resp = client.get("/api/search/unified", params={"q": "Spanyi", "limit": 10})

    assert resp.status_code == 200
    payload = resp.json()
    assert fake.qdrant_collections == [
        "baker-documents",
        "baker-conversations",
        "sentinel-interactions",
    ]
    assert payload["qdrant_collections_searched"] == fake.qdrant_collections
    assert any(
        r["metadata"].get("collection") == "sentinel-interactions"
        and "Spanyi 6 Jun email" in r["content"]
        for r in payload["results"]
    )


def test_unified_search_preserves_legacy_document_source_filter(unified_client):
    client, fake = unified_client

    resp = client.get(
        "/api/search/unified",
        params={"q": "Spanyi", "limit": 10, "sources": "documents"},
    )

    assert resp.status_code == 200
    assert fake.qdrant_collections == ["baker-documents"]
    payload = resp.json()
    assert payload["qdrant_collections_searched"] == ["baker-documents"]
    assert all(r["metadata"].get("collection") != "sentinel-interactions" for r in payload["results"])


def test_unified_search_preserves_postgres_email_arm_filter(unified_client):
    client, fake = unified_client

    resp = client.get(
        "/api/search/unified",
        params={"q": "Spanyi", "limit": 10, "sources": "emails"},
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert fake.email_calls == [("Spanyi", 3)]
    assert fake.qdrant_collections == []
    assert payload["qdrant_collections_searched"] == []
    assert payload["results"][0]["source"] == "email"
