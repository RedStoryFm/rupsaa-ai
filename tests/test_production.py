"""Production hardening: fail-closed config, owner auth, limits, redaction, readiness, isolation,
and the production smoke-test script — all with a fake engine (never loads a model or CUDA)."""

import importlib
import types

import pytest
from fastapi.testclient import TestClient

KEY = "k" * 32


class FakeLoaded:
    base_model_id = "Qwen/Qwen2.5-7B-Instruct"
    quantized = True

    def __init__(self, adapter_path):
        self.adapter_path = adapter_path
        self.model = types.SimpleNamespace(parameters=lambda: iter([types.SimpleNamespace(device="cuda:0")]))


class FakeEngine:
    prompt_version = "v0.2"

    def __init__(self, adapter_path):
        self.loaded = FakeLoaded(adapter_path)
        self.calls = []

    def chat(self, **kw):
        from rupsaa.model.inference import ChatResult
        self.calls.append(kw)
        msg = kw["user_message"]
        if "bolechilam" in msg:
            text = "shiuli bolechile."
        elif any("ঀ" <= ch <= "৿" for ch in msg):
            text = "ভালো কাটছে।"
        else:
            text = "Bhalo, tumi bolo."
        return ChatResult(text=text, blocked=False, completion_tokens=5)


@pytest.fixture
def prod(monkeypatch):
    """A production-mode app with a fake, already-loaded engine. Yields (client, service, main module)."""
    from rupsaa.config import PROJECT_ROOT, get_settings

    adapter = PROJECT_ROOT / "adapters/rupsaa-v0.2"

    def make(**env):
        base = {"RUPSAA_ENV": "production", "OWNER_API_KEY": KEY, "RUPSAA_ADAPTER_PATH": str(adapter),
                "RUPSAA_PRELOAD_MODEL": "0", "CORS_ORIGINS": "https://rupsaa.example.com",
                "RUPSAA_RATE_LIMIT_PER_MINUTE": "0", "RUPSAA_RATE_LIMIT_GLOBAL_PER_MINUTE": "0"}
        for k, v in {**base, **env}.items():
            monkeypatch.setenv(k, v)
        get_settings.cache_clear()
        import api.main
        import api.services
        main = importlib.reload(api.main)
        svc = api.services.RupsaaService()
        svc._engine = FakeEngine(str(adapter))
        main.app.dependency_overrides[api.services.get_service] = lambda: svc
        monkeypatch.setattr(api.services, "get_service", lambda: svc)
        return main, svc

    yield make
    get_settings.cache_clear()
    monkeypatch.undo()
    get_settings.cache_clear()
    import api.main
    importlib.reload(api.main)


def test_production_refuses_to_start_without_owner_key(prod):
    main, _ = prod(OWNER_API_KEY="")
    with pytest.raises(RuntimeError, match="OWNER_API_KEY"):
        with TestClient(main.app):
            pass


def test_production_refuses_missing_adapter(prod):
    main, _ = prod(RUPSAA_ADAPTER_PATH="adapters/does-not-exist")
    with pytest.raises(RuntimeError, match="RUPSAA_ADAPTER_PATH"):
        with TestClient(main.app):
            pass


def test_owner_routes_fail_closed_and_require_key(prod):
    main, _ = prod()
    with TestClient(main.app) as c:
        for method, path in (("GET", "/owner/terminology"), ("GET", "/owner/dance"), ("POST", "/rag/reindex"),
                             ("POST", "/owner/knowledge/reindex"), ("POST", "/owner/teach/examples")):
            assert c.request(method, path).status_code in (401, 422), path
            assert c.request(method, path, headers={"X-Owner-Key": "wrong"}).status_code in (401, 422), path
        assert c.get("/owner/dance", headers={"X-Owner-Key": KEY}).status_code == 200
    from api.owner_routes import require_owner
    from rupsaa.config import get_settings
    get_settings().owner_api_key = ""
    with pytest.raises(Exception) as e:
        require_owner(None)
    assert getattr(e.value, "status_code", None) == 503  # production never runs owner tools unprotected


def test_model_info_redacts_paths_and_names_the_adapter(prod):
    main, _ = prod()
    with TestClient(main.app) as c:
        info = c.get("/model/info").json()
    assert info["adapter_name"] == "rupsaa-v0.2" and info["environment"] == "production"
    assert not str(info["adapter_path"]).startswith("/") and not str(info["configured_adapter_path"]).startswith("/")


def test_health_and_ready(prod):
    main, svc = prod()
    with TestClient(main.app) as c:
        h = c.get("/health").json()
        assert h["status"] == "ok" and h["ready"] and h["dance_entries"] == 60 and h["terminology_entries"] >= 1
        assert c.get("/ready").status_code == 200
        svc._engine = None
        assert c.get("/ready").status_code == 503


def test_request_size_limit_and_token_cap(prod):
    main, svc = prod(RUPSAA_MAX_REQUEST_BYTES="2000", RUPSAA_MAX_NEW_TOKENS_CAP="256")
    with TestClient(main.app) as c:
        assert c.post("/chat", json={"message": "x" * 5000}).status_code == 413
        assert c.post("/chat", content=b"{not json", headers={"Content-Type": "application/json"}).status_code == 422
        assert c.post("/chat", json={"message": "hi", "max_new_tokens": 2000}).status_code == 200
        assert svc._engine.calls[-1]["generation_overrides"]["max_new_tokens"] == 256


def test_chat_rate_limit_per_client(prod):
    main, _ = prod(RUPSAA_RATE_LIMIT_PER_MINUTE="3")
    with TestClient(main.app) as c:
        codes = [c.post("/chat", json={"message": f"hello {i}"}).status_code for i in range(5)]
        assert codes[:3] == [200, 200, 200] and codes[3] == 429
        r = c.post("/chat", json={"message": "again"})
        assert r.status_code == 429 and "Retry-After" in r.headers


def test_client_key_trusts_forwarded_for_only_from_the_local_proxy():
    from api.security import client_key

    def req(peer, xff=None):
        headers = {"x-forwarded-for": xff} if xff else {}
        return types.SimpleNamespace(client=types.SimpleNamespace(host=peer), headers=headers)
    assert client_key(req("127.0.0.1", "203.0.113.9, 10.0.0.1")) == "203.0.113.9"
    assert client_key(req("198.51.100.7", "203.0.113.9")) == "198.51.100.7"  # spoofed header from outside ignored


def test_conversations_are_isolated_via_the_api(prod):
    main, _ = prod()
    with TestClient(main.app) as c:
        a = c.post("/chat", json={"message": "amar priyo phool shiuli", "conversation_id": "1"}).json()
        b = c.post("/chat", json={"message": "ami kon phool er kotha bolechilam?", "conversation_id": "1"}).json()
        assert a["conversation_id"] != "1" and b["conversation_id"] not in ("1", a["conversation_id"])


def test_production_smoke_script_passes_against_a_healthy_instance(prod):
    main, _ = prod()
    from scripts.production_smoke import run

    with TestClient(main.app) as c:
        class Client:
            def call(self, method, path, body=None, headers=None, timeout=0):
                r = c.request(method, path, json=body, headers=headers or {})
                return r.status_code, (r.json() if r.content else {})
        report = run(Client(), KEY, "rupsaa-v0.2", "v0.2", strict=True)
    assert report["pass"], [x for x in report["checks"] + report["quality_checks"] if not x["pass"]]


def test_check_production_config(monkeypatch):
    from rupsaa.config import get_settings
    from scripts.check_production_config import check

    monkeypatch.setenv("RUPSAA_ENV", "production")
    monkeypatch.setenv("OWNER_API_KEY", KEY)
    monkeypatch.setenv("RUPSAA_ADAPTER_PATH", "adapters/rupsaa-v0.2")
    monkeypatch.setenv("CORS_ORIGINS", "https://rupsaa.example.com")
    get_settings.cache_clear()
    try:
        assert check(skip_runtime=True)["ok"]
        monkeypatch.setenv("RUPSAA_ADAPTER_SHA256", "0" * 64)
        get_settings.cache_clear()
        assert not check(skip_runtime=True)["ok"]
        monkeypatch.setenv("CORS_ORIGINS", "*")
        monkeypatch.delenv("RUPSAA_ADAPTER_SHA256")
        get_settings.cache_clear()
        assert any("CORS" in p for p in check(skip_runtime=True)["problems"])
    finally:
        get_settings.cache_clear()
