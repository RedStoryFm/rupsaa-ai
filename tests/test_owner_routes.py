"""Tests for the owner-only Teach Rupsaa / Rupsaa Knowledge API routes.

All tests monkeypatch api.owner_routes._get_store / _get_doc_manager to
point at tmp_path fixtures, so they never touch the real production
dataset or the real knowledge/documents directory.
"""

import api.owner_routes as owner_routes
import pytest
from fastapi.testclient import TestClient

from api.main import app
from rupsaa.dataset.store import DatasetStore
from rupsaa.rag.document_manager import DocumentManager


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def isolated_store(tmp_path, monkeypatch):
    store = DatasetStore(tmp_path / "production")
    monkeypatch.setattr(owner_routes, "_get_store", lambda: store)
    return store


@pytest.fixture
def isolated_docs(tmp_path, monkeypatch):
    dm = DocumentManager(tmp_path / "knowledge_docs")
    monkeypatch.setattr(owner_routes, "_get_doc_manager", lambda: dm)
    return dm


@pytest.fixture
def owner_key(monkeypatch):
    """Configure OWNER_API_KEY so auth enforcement is actually exercised."""
    from rupsaa.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("OWNER_API_KEY", "test-secret-key")
    get_settings.cache_clear()
    yield "test-secret-key"
    get_settings.cache_clear()


# --- Teach Rupsaa ---

def test_teach_taxonomy_is_public(client):
    response = client.get("/owner/teach/taxonomy")
    assert response.status_code == 200
    body = response.json()
    assert "Banglish" in body["languages"]
    assert any(c["slug"] == "casual_friendly" for c in body["categories"])


def test_create_teach_example_single_turn(client, isolated_store):
    payload = {
        "turns": [{"user": "kemon acho?", "rupsaa": "bhalo achi, tumi kemon acho?"}],
        "language": "Banglish",
        "category": "casual_friendly",
    }
    response = client.post("/owner/teach/examples", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["conversation_id"] is not None
    assert body["errors"] == []

    saved = isolated_store.list_all(None)
    assert len(saved) == 1
    assert saved[0].record.source_type == "human_authored"
    assert saved[0].record.quality_status == "draft"


def test_create_teach_example_multi_turn(client, isolated_store):
    payload = {
        "turns": [
            {"user": "hi", "rupsaa": "hey, kemon acho?"},
            {"user": "bhalo, tumi?", "rupsaa": "ami o bhalo achi :)"},
        ],
        "language": "Bengali + English",
        "category": "casual_friendly",
    }
    response = client.post("/owner/teach/examples", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True

    saved = isolated_store.list_all(None)[0].record
    # system + 2 user + 2 assistant = 5 messages
    assert len(saved.messages) == 5
    assert saved.language == "mixed"
    assert saved.language_mix == "bn_en"


def test_create_teach_example_rejects_empty_turn(client, isolated_store):
    payload = {
        "turns": [{"user": "  ", "rupsaa": "hi"}],
        "language": "English",
        "category": "casual_friendly",
    }
    response = client.post("/owner/teach/examples", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert any("USER message is empty" in e for e in body["errors"])
    assert isolated_store.list_all(None) == []


def test_create_teach_example_rejects_unknown_category(client, isolated_store):
    payload = {
        "turns": [{"user": "hi", "rupsaa": "hello"}],
        "language": "English",
        "category": "not_a_real_category",
    }
    response = client.post("/owner/teach/examples", json=payload)
    body = response.json()
    assert body["success"] is False
    assert any("category" in e for e in body["errors"])


def test_create_teach_example_blocks_exact_duplicate(client, isolated_store):
    payload = {
        "turns": [{"user": "kemon acho?", "rupsaa": "bhalo achi, tumi kemon acho?"}],
        "language": "Banglish",
        "category": "casual_friendly",
    }
    first = client.post("/owner/teach/examples", json=payload)
    assert first.json()["success"] is True

    second = client.post("/owner/teach/examples", json=payload)
    body = second.json()
    assert body["success"] is False
    assert any("already exists" in e for e in body["errors"])
    assert len(isolated_store.list_all(None)) == 1


def test_teach_example_ignores_client_supplied_source_type(client, isolated_store):
    # TeachExampleRequest has no source_type field at all — confirm the
    # server never lets a client claim e.g. "synthetic_reviewed" here.
    payload = {
        "turns": [{"user": "hi", "rupsaa": "hello there"}],
        "language": "English",
        "category": "casual_friendly",
        "source_type": "synthetic_reviewed",
    }
    response = client.post("/owner/teach/examples", json=payload)
    assert response.json()["success"] is True
    assert isolated_store.list_all(None)[0].record.source_type == "human_authored"


# --- Rupsaa Knowledge ---

def test_knowledge_categories_is_public(client):
    response = client.get("/owner/knowledge/categories")
    assert response.status_code == 200
    assert "rupsaa_identity" in response.json()["categories"]


def test_knowledge_document_crud_flow(client, isolated_docs):
    create_resp = client.post(
        "/owner/knowledge/documents",
        json={
            "title": "Test Doc",
            "category": "faq",
            "content": "# Test Doc\n\nSome FAQ content.",
            "source_notes": "unit test",
        },
    )
    assert create_resp.status_code == 200
    created = create_resp.json()
    assert created["owner_created"] is True
    filename = created["filename"]

    list_resp = client.get("/owner/knowledge/documents")
    assert any(d["filename"] == filename for d in list_resp.json()["documents"])

    get_resp = client.get(f"/owner/knowledge/documents/{filename}")
    assert get_resp.status_code == 200
    assert "Some FAQ content" in get_resp.json()["content"]

    update_resp = client.put(
        f"/owner/knowledge/documents/{filename}",
        json={"content": "# Test Doc\n\nUpdated content."},
    )
    assert update_resp.status_code == 200
    assert client.get(f"/owner/knowledge/documents/{filename}").json()["content"].endswith("Updated content.")

    delete_no_confirm = client.delete(f"/owner/knowledge/documents/{filename}")
    assert delete_no_confirm.status_code == 400

    delete_resp = client.delete(f"/owner/knowledge/documents/{filename}?confirm=true")
    assert delete_resp.status_code == 200
    assert all(d["filename"] != filename for d in client.get("/owner/knowledge/documents").json()["documents"])


def test_knowledge_reindex_uses_existing_rag_pipeline(client, isolated_docs, monkeypatch):
    calls = []

    class FakePipeline:
        def ingest(self):
            calls.append(1)
            return 7

    import rupsaa.rag.pipeline as pipeline_module

    monkeypatch.setattr(pipeline_module, "RagPipeline", FakePipeline)
    response = client.post("/owner/knowledge/reindex")
    assert response.status_code == 200
    assert response.json()["chunks_indexed"] == 7
    assert calls == [1]


# --- Owner auth enforcement ---

def test_owner_route_rejects_missing_key_when_configured(client, isolated_store, owner_key):
    response = client.post(
        "/owner/teach/examples",
        json={
            "turns": [{"user": "hi", "rupsaa": "hello"}],
            "language": "English",
            "category": "casual_friendly",
        },
    )
    assert response.status_code == 401


def test_owner_route_accepts_correct_key_when_configured(client, isolated_store, owner_key):
    response = client.post(
        "/owner/teach/examples",
        json={
            "turns": [{"user": "hi", "rupsaa": "hello"}],
            "language": "English",
            "category": "casual_friendly",
        },
        headers={"X-Owner-Key": owner_key},
    )
    assert response.status_code == 200
    assert response.json()["success"] is True


def test_owner_route_rejects_wrong_key_when_configured(client, isolated_store, owner_key):
    response = client.post(
        "/owner/teach/examples",
        json={
            "turns": [{"user": "hi", "rupsaa": "hello"}],
            "language": "English",
            "category": "casual_friendly",
        },
        headers={"X-Owner-Key": "wrong-key"},
    )
    assert response.status_code == 401


def test_public_taxonomy_route_unaffected_by_owner_key(client, owner_key):
    # /owner/teach/taxonomy and /owner/knowledge/categories are static-data
    # routes that never call require_owner — confirm they still work even
    # once OWNER_API_KEY is configured and no key is sent.
    response = client.get("/owner/teach/taxonomy")
    assert response.status_code == 200
