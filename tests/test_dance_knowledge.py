"""Dance knowledge store, import, retrieval, prompt block and owner API. No model.

Fixture records use placeholder descriptions — these tests check mechanics, not dance facts
(the owner's real records live in knowledge/dance/).
"""

import io
import json

import pytest
from fastapi.testclient import TestClient

from rupsaa.personality.system_prompt import build_system_prompt
from rupsaa.rag import dance_import
from rupsaa.rag.context_builder import build_turn_knowledge
from rupsaa.rag.dance import DanceError, DanceStore
from rupsaa.rag.router import Route, classify_message

FIXTURES = [
    {"name": "Belly Dance", "aliases": ["belly dancing", "bellydance"], "origin": "fixture-origin-A", "description": "fixture description A"},
    {"name": "Ballet", "origin": "fixture-origin-B", "description": "fixture description B"},
    {"name": "Kathak", "aliases": ["কথক"], "origin": "fixture-origin-C", "description": "fixture description C"},
    {"name": "Voguing", "aliases": ["vogue dance"], "description": "fixture description D"},
    {"name": "Breaking (Breakdance)", "aliases": ["b-boying"], "description": "fixture description E"},
    {"name": "Haka", "origin": "fixture-origin-F", "description": "fixture description F"},
    {"name": "Bhangra", "aliases": ["ভাংড়া"], "origin": "fixture-origin-G", "description": "fixture description G"},
    {"name": "Salsa", "description": "fixture description H"},
]


@pytest.fixture
def dances(tmp_path) -> DanceStore:
    store = DanceStore(tmp_path / "dance")
    for d in FIXTURES:
        store.create(d)
    return store


def ids(store, msg):
    return [m.record.id for m in store.lookup(msg, classify_message(msg).term_candidate)
            ] if classify_message(msg).use_terminology else []


@pytest.mark.parametrize("msg,want", [
    ("Belly dance ki?", "dance-belly_dance"),
    ("belly dancing mane ki?", "dance-belly_dance"),
    ("Ballet ki?", "dance-ballet"),
    ("Kathak kothakar dance?", "dance-kathak"),
    ("Voguing ki?", "dance-voguing"),
    ("Breaking ar breakdance same?", "dance-breaking_breakdance"),
    ("Haka origin kothay?", "dance-haka"),
    ("আমাকে কথক সম্পর্কে বলো", "dance-kathak"),
    ("Bhangra ta banglish e bojhao", "dance-bhangra"),
    ("where does salsa come from?", "dance-salsa"),
    ("tell me about kathak", "dance-kathak"),
    ("balet ki?", "dance-ballet"),        # typo
    ("kathk kothakar?", "dance-kathak"),   # typo
    ("bhangraa ki?", "dance-bhangra"),     # typo
])
def test_owner_queries_retrieve_the_right_dance(dances, msg, want):
    assert ids(dances, msg)[:1] == [want], msg


def test_no_false_matches(dances):
    for msg in ("tumi kemon acho?", "salad ki?", "ami ki bolechilam?", "ball ki?", "hake ki?", "kal office e chap chilo"):
        assert ids(dances, msg) == [], msg


def test_record_keys_and_context_only_show_supplied_fields(dances):
    rec = dances.get("dance-breaking_breakdance")
    assert {"breaking", "breakdance", "b boying"} <= rec.keys()
    ctx = dances.get("dance-voguing").to_context()
    assert "Description: fixture description D" in ctx and "Origin:" not in ctx
    assert "Step-by-step instructions: not in the owner's records." in ctx
    for field in ("Difficulty", "Warm-up", "Basic steps", "Common mistakes", "Practice tips"):
        assert f"{field}:" not in ctx
    rec = dances.update("dance-voguing", {"basic_steps": "owner-verified steps", "difficulty": "owner level"})
    ctx = rec.to_context()
    assert "Basic steps: owner-verified steps" in ctx and "Step-by-step instructions" not in ctx


def test_crud_validation_conflicts_and_disable(dances):
    with pytest.raises(DanceError):
        dances.create({"name": "No Description"})
    with pytest.raises(DanceError):
        dances.create({"name": "Another", "aliases": ["kathak"], "description": "x"})  # alias clash
    with pytest.raises(DanceError):
        dances.get("../../etc")
    dances.update("dance-haka", {"enabled": False})
    assert ids(dances, "Haka origin kothay?") == []
    dances.delete("dance-haka", confirm=True)
    assert "dance-haka" not in {d.id for d in dances.list()}


def test_turn_knowledge_attaches_dance_block_and_carries_it_to_followups(dances, tmp_path):
    from rupsaa.rag.terminology import TerminologyStore

    terms = TerminologyStore(tmp_path / "terms")
    k = build_turn_knowledge("Kathak kothakar dance?", use_rag=True, rag_query=lambda q, strict=False: ("DOC", [{}]),
                             terminology=terms, dance=dances)
    assert k.route == "terminology" and k.terms_used == ["dance-kathak"] and k.retrieved_context is None
    assert k.dance_context.startswith("Dance: Kathak") and k.terminology_context is None
    f = build_turn_knowledge("এটা বাংলায় বুঝিয়ে বলো", use_rag=False, rag_query=None, terminology=terms, dance=dances,
                             previous_terms=k.terms_used, history_messages=2)
    assert f.route == "followup" and f.terms_used == ["dance-kathak"] and "Kathak" in f.dance_context and f.language == "bn"
    prompt = build_system_prompt(prompt_version="v0.2", dance_context=k.dance_context)
    assert "Reference dance knowledge:\nDance: Kathak" in prompt and "instead of making them up" in prompt


def test_casual_turns_get_no_dance(dances, tmp_path):
    from rupsaa.rag.terminology import TerminologyStore

    k = build_turn_knowledge("hi, kemon acho?", use_rag=False, rag_query=None,
                             terminology=TerminologyStore(tmp_path / "t"), dance=dances)
    assert k.route == "casual" and k.dance_context is None and k.terms_used == []


def test_router_keeps_non_questions_casual():
    for msg in ("পড়াশোনা নিয়ে", "porashona niye", "tumi kothakar?", "ki niye bolo"):
        assert classify_message(msg).route in (Route.CASUAL, Route.GENERAL), msg
        assert classify_message(msg).term_candidate is None, msg
    assert classify_message("tell me about yourself").route == Route.KNOWLEDGE


# --- import ---------------------------------------------------------------------------------

CSV = ("Dance Style,Also known as,Region,Description,Key Movements\r\n"
       "Flamenco,flamenco dance,fixture-origin-X,fixture description X,fixture moves\r\n"
       "Tango,,fixture-origin-Y,fixture description Y,\r\n"
       "Samba,,,fixture description Z,\r\n"
       "NoDesc,,somewhere,,\r\n"
       "Flamenco Again,flamenco,,dup,\r\n").encode("utf-8")


def test_import_csv_with_header_synonyms(tmp_path):
    store = DanceStore(tmp_path / "d")
    pv = dance_import.preview("dances.csv", CSV, store)
    status = {r.data["name"]: r.status for r in pv.rows}
    assert status["Flamenco"] == "valid" and status["Tango"] == "valid"
    assert status["Samba"] == "warning"  # no origin -> warning, nothing filled in
    assert status["NoDesc"] == "invalid" and status["Flamenco Again"] == "duplicate_in_file"
    res = dance_import.commit("dances.csv", CSV, store)
    assert res.to_dict()["counts"]["created"] == 3
    samba = store.get("dance-samba")
    assert samba.origin == "" and samba.basic_steps == "" and samba.key_movements == ""
    assert store.get("dance-flamenco").origin == "fixture-origin-X"
    again = dance_import.commit("dances.csv", CSV, store)  # re-import: existing are skipped, not duplicated
    assert again.to_dict()["counts"]["created"] == 0 and len(store.list()) == 3


def test_import_json_and_xlsx(tmp_path):
    store = DanceStore(tmp_path / "d")
    payload = json.dumps({"dances": [{"name": "Garba", "origin": "fixture", "description": "fixture", "aliases": ["garba raas"]}]})
    assert dance_import.commit("d.json", payload.encode(), store).to_dict()["counts"]["created"] == 1
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["name", "origin", "description"])
    ws.append(["Odissi", "fixture", "fixture"])
    buf = io.BytesIO()
    wb.save(buf)
    assert dance_import.commit("d.xlsx", buf.getvalue(), store).to_dict()["counts"]["created"] == 1
    assert dance_import.template_xlsx()[:2] == b"PK" and b"name" in dance_import.template_csv()


# --- owner API ------------------------------------------------------------------------------

def test_owner_dance_api(tmp_path, monkeypatch):
    import api.owner_routes as owner_routes
    from api.main import app

    store = DanceStore(tmp_path / "api_dance")
    monkeypatch.setattr(owner_routes, "_get_dance", lambda: store)
    c = TestClient(app)
    r = c.post("/owner/dance", json={"name": "Kathak", "origin": "fixture", "description": "fixture", "aliases": ["কথক"]})
    assert r.status_code == 200 and r.json()["id"] == "dance-kathak"
    assert c.get("/owner/dance?q=kath").json()["count"] == 1
    look = c.get("/owner/dance/lookup", params={"message": "আমাকে কথক সম্পর্কে বলো"}).json()
    assert look["matches"][0]["id"] == "dance-kathak"
    assert c.put("/owner/dance/dance-kathak", json={"category": "classical"}).json()["category"] == "classical"
    assert c.get("/owner/dance/template.csv").status_code == 200  # not captured as a dance id
    up = c.post("/owner/dance/import", files={"file": ("d.csv", CSV, "text/csv")}).json()
    assert up["counts"]["created"] == 3
    assert c.delete("/owner/dance/dance-kathak").status_code == 400  # needs confirm
    assert c.delete("/owner/dance/dance-kathak?confirm=true").status_code == 200
