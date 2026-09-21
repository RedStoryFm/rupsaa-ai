"""API tests. The heavy model is never loaded here — chat-generation
endpoints are exercised against a fake RupsaaService (dependency-injected
via FastAPI's app.dependency_overrides), while /health and /model/info are
also checked against the real (lazy, unloaded) service to confirm
configuration loads correctly without pulling in the model.
"""

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.services import get_service


class FakeService:
    def __init__(self):
        self.reset_calls = []
        self.reindex_calls = 0

    def is_model_loaded(self) -> bool:
        return True

    def model_info(self) -> dict:
        return {
            "base_model_id": "Qwen/Qwen2.5-7B-Instruct",
            "adapter_path": "adapters/rupsaa-v1",
            "quantized": True,
            "device": "cuda:0",
        }

    def chat(self, *, message, conversation_id, use_rag, temperature, top_p, max_new_tokens):
        return {
            "response": f"echo: {message}",
            "conversation_id": conversation_id or "generated-id",
            "language": "en",
            "rag_used": use_rag,
            "sources": [{"source_filename": "doc.txt", "chunk_id": 0, "score": 0.9}] if use_rag else [],
            "blocked": False,
        }

    def reindex(self) -> int:
        self.reindex_calls += 1
        return 3

    def reset_conversation(self, conversation_id: str) -> None:
        self.reset_calls.append(conversation_id)


@pytest.fixture
def fake_service():
    service = FakeService()
    app.dependency_overrides[get_service] = lambda: service
    yield service
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    return TestClient(app)


def test_health_without_model_loaded(client):
    # Uses the real (lazy) service — confirms the app boots and responds
    # without ever loading the base model.
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["model_loaded"] is False


def test_model_info_reads_config_without_loading_model(client):
    response = client.get("/model/info")
    assert response.status_code == 200
    body = response.json()
    assert body["base_model_id"] == "Qwen/Qwen2.5-7B-Instruct"
    assert body["device"] == "not loaded yet"


def test_chat_returns_expected_shape(client, fake_service):
    response = client.post("/chat", json={"message": "hello", "conversation_id": None, "use_rag": False})
    assert response.status_code == 200
    body = response.json()
    assert body["response"] == "echo: hello"
    assert body["conversation_id"] == "generated-id"
    assert body["rag_used"] is False
    assert body["sources"] == []


def test_chat_with_rag_returns_sources(client, fake_service):
    response = client.post("/chat", json={"message": "hi", "use_rag": True})
    assert response.status_code == 200
    body = response.json()
    assert body["rag_used"] is True
    assert len(body["sources"]) == 1


def test_chat_rejects_empty_message(client, fake_service):
    response = client.post("/chat", json={"message": ""})
    assert response.status_code == 422


def test_chat_rejects_missing_message_field(client, fake_service):
    response = client.post("/chat", json={})
    assert response.status_code == 422


def test_chat_rejects_out_of_range_temperature(client, fake_service):
    response = client.post("/chat", json={"message": "hi", "temperature": 5.0})
    assert response.status_code == 422


def test_rag_reindex(client, fake_service):
    response = client.post("/rag/reindex")
    assert response.status_code == 200
    assert response.json() == {"chunks_indexed": 3}
    assert fake_service.reindex_calls == 1


def test_conversation_reset(client, fake_service):
    response = client.post("/conversation/reset", json={"conversation_id": "abc-123"})
    assert response.status_code == 200
    assert response.json() == {"conversation_id": "abc-123", "reset": True}
    assert fake_service.reset_calls == ["abc-123"]


def test_conversation_reset_requires_id(client, fake_service):
    response = client.post("/conversation/reset", json={})
    assert response.status_code == 422
