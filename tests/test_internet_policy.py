"""Internet permission system: ASK / ALLOW / DENY, one-time vs persistent, pending query, freshness, sources,
provider safety. The provider is a fake that records every request (zero real network)."""

import pytest

from rupsaa.conversation import internet_policy as ip
from rupsaa.rag import web_search as ws
from tests.conftest_rupsaa_fakes import FakeProvider, chat, make_service, new_uid


@pytest.mark.parametrize("msg,pending,cmd", [
    ("Ha, eta search koro.", True, "approve_once"), ("ha", True, "approve_once"), ("yes", True, "approve_once"),
    ("Na, eta search korona.", True, "reject_once"), ("na", True, "reject_once"),
    ("Future-e proyojon hole internet search korte paro.", False, "allow"),
    ("Ekhon theke internet use korte paro.", True, "allow"),
    ("Ar internet use korbe na.", False, "deny"), ("Ar internet use korbe na.", True, "deny"),
    ("Search korar age jiggesh korbe.", True, "ask"),
    ("ha", False, None), ("na, ami bhalo achi", True, None), ("Latest iPhone price koto?", False, None),
])
def test_command_detection(msg, pending, cmd):
    assert ip.detect_command(msg, has_pending=pending) == cmd


@pytest.mark.parametrize("msg,fresh", [("Latest iPhone price koto?", True), ("ajker weather kemon?", True),
                                       ("India vs Pakistan match er result ki?", True), ("Python er latest version ki?", True),
                                       ("Taj Mahal kothay?", False), ("Hair straightening ki?", False),
                                       ("ajke ki korle bhalo lagbe bolo to?", False), ("aj ki khabo?", False),
                                       ("PAN card update korbo kivabe?", False), ("What should I do today?", False),
                                       ("Ajker Sensex koto?", True), ("আজ পেট্রলের দাম কত?", True),
                                       ("Who won the match yesterday?", True)])
def test_freshness(msg, fresh):
    assert ip.is_fresh(msg) is fresh


def _svc(tmp_path, monkeypatch, **kw):
    svc = make_service(tmp_path, monkeypatch, **kw)
    svc.general.create({"title": "Hair Straightening", "category": "Beauty", "summary": "Straightening hair."})
    return svc


def test_no_web_for_local_knowledge_memory_or_chat(tmp_path, monkeypatch):
    svc, uid = _svc(tmp_path, monkeypatch), new_uid()
    svc.set_internet_mode(uid, None, ip.ALLOW)
    for msg in ("Hi Rupsaa", "Ajke amar mood kharap", "Hair straightening ki?", "Taj Mahal kothay?",
                "Ami kon color pochondo kori bolechilam?", "tumi ke?"):
        chat(svc, msg, user_id=uid)
    assert svc._web_provider.queries == []


def test_ask_mode_asks_first_then_one_time_yes_searches_the_original_query(tmp_path, monkeypatch):
    svc, uid = _svc(tmp_path, monkeypatch), new_uid()
    r = chat(svc, "Latest iPhone price koto?", user_id=uid)
    assert r["internet_mode"] == "ASK" and r["pending_search"] and r["internet_permission_requested"]
    assert svc._web_provider.queries == []  # nothing left the server before permission
    assert svc._engine.calls == [] and r["response"] in sum(ip._PERMISSION_QUESTIONS.values(), [])  # fixed wording
    r = chat(svc, "ha eta search koro", r["conversation_id"], user_id=uid)
    assert svc._web_provider.queries == [("Latest iPhone price", True)]  # the ORIGINAL question, once
    assert r["web_sources"][0]["domain"] == "example.org" and r["web_sources"][0]["retrieved_at"]
    assert r["internet_mode"] == "ASK" and not r["pending_search"]  # one-time approval: mode unchanged
    assert "Latest iPhone price koto?" in svc._engine.calls[-1]["conversation_note"]


def test_rejection_and_reset_clear_the_pending_query(tmp_path, monkeypatch):
    svc, uid = _svc(tmp_path, monkeypatch), new_uid()
    r = chat(svc, "Latest iPhone price koto?", user_id=uid)
    r = chat(svc, "Na, eta search korona.", r["conversation_id"], user_id=uid)
    assert not r["pending_search"] and r["internet_mode"] == "ASK" and svc._web_provider.queries == []
    r = chat(svc, "ajker weather kemon?", user_id=uid)
    svc.reset_conversation(r["conversation_id"])  # New chat
    r = chat(svc, "ha", r["conversation_id"], user_id=uid)
    assert svc._web_provider.queries == [] and not r["pending_search"]


def test_topic_change_abandons_the_pending_query(tmp_path, monkeypatch):
    svc, uid = _svc(tmp_path, monkeypatch), new_uid()
    r = chat(svc, "Latest iPhone price koto?", user_id=uid)
    r = chat(svc, "accha thak, Hair straightening ki?", r["conversation_id"], user_id=uid)
    assert not r["pending_search"] and svc._web_provider.queries == []


def test_persistent_modes_allow_deny_ask(tmp_path, monkeypatch):
    svc, uid = _svc(tmp_path, monkeypatch), new_uid()
    r = chat(svc, "Latest iPhone price koto?", user_id=uid)
    r = chat(svc, "future-e proyojon hole internet search korte paro", r["conversation_id"], user_id=uid)
    assert r["internet_mode"] == "ALLOW" and len(svc._web_provider.queries) == 1  # pending searched on ALLOW
    chat(svc, "Python er latest version ki?", user_id=uid)  # ALLOW: searched without asking
    assert len(svc._web_provider.queries) == 2
    chat(svc, "Hair straightening ki?", user_id=uid)  # ALLOW + local knowledge: no unnecessary web
    assert len(svc._web_provider.queries) == 2
    r = chat(svc, "ar internet use korbe na", user_id=uid)
    assert r["internet_mode"] == "DENY"
    chat(svc, "ajker weather kemon?", user_id=uid)
    assert len(svc._web_provider.queries) == 2  # DENY: zero requests
    assert "switched off by the user" in svc._engine.calls[-1]["conversation_note"]
    r = chat(svc, "Ekhon theke internet use korte paro.", user_id=uid)
    assert r["internet_mode"] == "ALLOW"
    r = chat(svc, "search korar age jiggesh korbe", user_id=uid)
    assert r["internet_mode"] == "ASK" and svc.internet_mode(uid, None) == "ASK"  # durable per browser


def test_permissions_are_isolated_between_users(tmp_path, monkeypatch):
    svc = _svc(tmp_path, monkeypatch)
    a, b = new_uid(), new_uid()
    svc.set_internet_mode(a, None, ip.ALLOW)
    assert svc.internet_mode(b, None) == "ASK"
    chat(svc, "Latest iPhone price koto?", user_id=b)
    assert svc._web_provider.queries == []


def test_web_results_never_enter_curated_knowledge(tmp_path, monkeypatch):
    svc, uid = _svc(tmp_path, monkeypatch), new_uid()
    before = [r.id for r in svc.general.list()]
    svc.set_internet_mode(uid, None, ip.ALLOW)
    chat(svc, "Latest iPhone price koto?", user_id=uid)
    assert [r.id for r in svc.general.list()] == before


def test_provider_failure_does_not_fabricate(tmp_path, monkeypatch):
    svc, uid = _svc(tmp_path, monkeypatch, provider=FakeProvider(results=[])), new_uid()
    svc.set_internet_mode(uid, None, ip.ALLOW)
    r = chat(svc, "Latest iPhone price koto?", user_id=uid)
    assert r["web_sources"] == [] and svc._engine.calls[-1]["web_context"] is None
    assert "found nothing usable" in svc._engine.calls[-1]["conversation_note"]


@pytest.mark.parametrize("msg,query", [("Python er latest version ki?", "Python latest version"),
                                       ("ajker Kolkata weather kemon?", "Kolkata weather")])
def test_search_query_drops_banglish_fillers(msg, query):
    from rupsaa.rag.router import classify_message

    assert ws.clean_query(msg, classify_message(msg).term_candidate) == query


@pytest.mark.parametrize("msg,lang", [("ajker Kolkata weather kemon?", "banglish"), ("আজকের কলকাতার আবহাওয়া কেমন?", "bn"),
                                      ("What is the latest iPhone price today?", "en")])
def test_ask_reply_is_fixed_text_in_users_language_no_model_guess(tmp_path, monkeypatch, msg, lang):
    svc = _svc(tmp_path, monkeypatch)
    r = chat(svc, msg, user_id=new_uid())
    assert r["response"] in ip._PERMISSION_QUESTIONS[lang] and svc._engine.calls == []  # Gemma never ran
    assert r["pending_search"]


def test_provider_security():
    assert ws.safe_url("https://en.wikipedia.org/wiki/X")
    for bad in ("http://127.0.0.1/admin", "file:///etc/passwd", "https://user:pw@evil.com", "http://localhost:8000",
                "javascript:alert(1)", "http://10.0.0.5/", "https://intranet.local/x"):
        assert not ws.safe_url(bad), bad
    p = ws.WikipediaProvider()
    with pytest.raises(ValueError):
        p._get("https://evil.example.com/x")  # host allow-list
    with pytest.raises(ValueError):
        p._get("http://en.wikipedia.org/w/api.php")  # https only
    with pytest.raises(ValueError):
        ws.BraveSearchProvider(api_key="")


def test_internet_mode_endpoint(tmp_path, monkeypatch):
    import api.main as main
    from fastapi.testclient import TestClient

    svc = _svc(tmp_path, monkeypatch)
    main.app.dependency_overrides[main.get_service] = lambda: svc
    try:
        c, uid = TestClient(main.app), new_uid()
        assert c.post("/internet/mode", json={"user_id": uid}).json() == {"mode": "ASK"}
        assert c.post("/internet/mode", json={"user_id": uid, "mode": "DENY"}).json() == {"mode": "DENY"}
        assert c.post("/internet/mode", json={"user_id": uid, "mode": "SOMETIMES"}).status_code == 422
    finally:
        main.app.dependency_overrides.clear()
