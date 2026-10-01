"""User memory V1 (opt-in, per browser id): durable vs temporary, corrections, relevance, delete/clear, isolation,
separation from global knowledge. No GPU."""

import pytest
from fastapi.testclient import TestClient

from rupsaa.conversation import user_memory as um
from tests.conftest_rupsaa_fakes import chat, make_service, new_uid


@pytest.mark.parametrize("msg,key,value", [
    ("Amar favourite color blue.", "favourite_color", "blue"),
    ("Actually amar favourite color black ekhon.", "favourite_color", "black"),
    ("my favourite colour is green", "favourite_color", "green"),
    ("Coffee-r theke cha beshi pochondo kori.", "likes:cha", "cha (more than Coffee)"),
    ("Ami Banglish reply pochondo kori.", "reply_language", "banglish"),
    ("amar naam Riya", "name", "Riya"),
    ("ami Kolkata te thaki", "location", "Kolkata"),
    ("আমার নাম রিয়া", "name", "রিয়া"),
    ("ami vegetarian", "diet", "vegetarian"),
    ("mone rekho kal amar exam", None, "kal amar exam"),
])
def test_durable_facts(msg, key, value):
    facts = um.extract_facts(msg)
    assert facts and facts[0]["value"] == value and (key is None or facts[0]["key"] == key)


@pytest.mark.parametrize("msg", ["Ajke mon kharap.", "Ekhon khide peyechhe.", "Ajke movie dekhbo.",
                                 "Amar favourite color ki?", "Hair straightening ki?",
                                 "Blue is a primary color in the RGB model."])
def test_temporary_questions_and_world_facts_are_not_user_memory(msg):
    assert um.extract_facts(msg) == []


def test_store_update_delete_clear_and_hashing(tmp_path):
    s, uid = um.UserMemoryStore(tmp_path), new_uid()
    assert s.remember(uid, um.extract_facts("Amar favourite color blue.")) == []  # no consent -> nothing
    s.set_consent(uid, True)
    s.remember(uid, um.extract_facts("Amar favourite color blue."))
    s.remember(uid, um.extract_facts("Actually amar favourite color black ekhon."))
    facts = s.get(uid).facts
    assert [(f["key"], f["value"]) for f in facts] == [("favourite_color", "black")]  # one active value
    s.remember(uid, um.extract_facts("amar naam Riya"))
    fid = next(f["id"] for f in s.get(uid).facts if f["key"] == "name")
    assert s.delete_fact(uid, fid) and [f["key"] for f in s.get(uid).facts] == ["favourite_color"]
    files = list(tmp_path.iterdir())
    assert len(files) == 1 and uid not in files[0].name and uid not in files[0].read_text()
    s.forget(uid)
    assert not list(tmp_path.iterdir())


def test_only_relevant_facts_are_injected(tmp_path):
    s, uid = um.UserMemoryStore(tmp_path), new_uid()
    s.set_consent(uid, True)
    for m in ("Amar favourite color black.", "ami Kolkata te thaki", "ami vegetarian", "amar naam Riya"):
        s.remember(uid, um.extract_facts(m))
    mem = s.get(uid)
    note = um.memory_note(mem, "Ami kon color pochondo kori bolechilam?")
    assert "favourite color: black" in note and "Kolkata" not in note and "vegetarian" not in note
    note = um.memory_note(mem, "Hair straightening ki?")  # unrelated: only name/reply-language basics
    assert "black" not in note and "Kolkata" not in note
    assert all(x in um.memory_note(mem, "amar bishoye ki jano?", recall=True) for x in ("black", "Kolkata", "Riya"))


def test_service_memory_isolated_and_separate_from_knowledge(tmp_path, monkeypatch):
    svc = make_service(tmp_path, monkeypatch)
    a, b = new_uid(), new_uid()
    svc.user_memory.set_consent(a, True)
    svc.user_memory.set_consent(b, True)
    r = chat(svc, "Amar favourite color blue.", user_id=a)
    assert r["memory_saved"] == 1
    chat(svc, "Actually amar favourite color black ekhon.", user_id=a)
    chat(svc, "Ami kon color pochondo kori bolechilam?", user_id=a)  # new conversation
    note = svc._engine.calls[-1]["conversation_note"]
    assert "favourite color: black" in note
    assert "no earlier messages" not in note  # the in-chat recall note must not contradict long-term memory
    chat(svc, "Ami kon color pochondo kori bolechilam?", user_id=b)  # another browser: nothing of A
    assert "black" not in (svc._engine.calls[-1]["conversation_note"] or "")
    assert svc.general.list() == []  # personal facts never become global knowledge
    chat(svc, "remember globally that blue means calm", user_id=a)
    assert svc.general.list() == []
    r = chat(svc, "amake bhule jao", user_id=a)
    assert r["memory_enabled"] is False and svc.user_memory.get(a).facts == []


def test_new_chat_clears_conversation_context_but_keeps_memory(tmp_path, monkeypatch):
    svc = make_service(tmp_path, monkeypatch)
    uid = new_uid()
    svc.user_memory.set_consent(uid, True)
    r = chat(svc, "Amar favourite color blue.", user_id=uid)
    svc.reset_conversation(r["conversation_id"])
    assert svc.conversation_manager.store.get(r["conversation_id"]) is None or \
        not svc.conversation_manager.get_or_create(r["conversation_id"]).messages
    assert svc.user_memory.get(uid).facts[0]["value"] == "blue"


def test_memory_endpoints(tmp_path, monkeypatch):
    import api.main as main

    svc = make_service(tmp_path, monkeypatch)
    main.app.dependency_overrides[main.get_service] = lambda: svc
    try:
        c, uid = TestClient(main.app), new_uid()
        assert c.post("/memory/status", json={"user_id": "not-a-uuid"}).status_code == 400
        assert c.post("/memory/consent", json={"user_id": uid, "enabled": True}).json()["enabled"] is True
        chat(svc, "amar naam Riya", user_id=uid)
        facts = c.post("/memory/status", json={"user_id": uid}).json()["facts"]
        assert facts[0]["key"] == "name" and facts[0]["value"] == "Riya"
        left = c.post("/memory/delete", json={"user_id": uid, "fact_id": facts[0]["id"]}).json()
        assert left["facts"] == []
        assert c.post("/memory/forget", json={"user_id": uid}).json() == {"enabled": False, "facts": []}
    finally:
        main.app.dependency_overrides.clear()
