"""General Knowledge layer: store, retrieval priority, follow-ups, import/export, owner API. No GPU, no network."""

import io
import json

import pytest
from fastapi.testclient import TestClient

from rupsaa.rag import general_knowledge_import as gki
from rupsaa.rag.context_builder import build_turn_knowledge
from rupsaa.rag.general_knowledge import CATEGORIES, GeneralKnowledgeStore, KnowledgeError, _names_covered, _content_words
from rupsaa.rag.terminology import TerminologyStore
from tests.conftest_rupsaa_fakes import keyword_embedder

HAIR = {"title": "Hair Straightening", "category": "Beauty", "aliases": ["chul straight kora", "হেয়ার স্ট্রেইটনিং"],
        "summary": "Making curly or wavy hair straight with heat tools or chemical treatments.",
        "key_points": ["Use heat protectant", "Chemical straightening lasts months"]}


@pytest.fixture
def store(tmp_path):
    s = GeneralKnowledgeStore(tmp_path / "general", embedder=keyword_embedder)
    s.create(HAIR)
    s.create({"title": "Capsule Wardrobe", "category": "Fashion", "summary": "A small set of versatile clothes."})
    return s


def test_categories_cover_the_owner_list():
    for c in ("Relationships", "Dating", "Sexual Education", "Health & Hygiene", "Beauty", "Fashion", "Fitness",
              "Entertainment", "Creator Platforms", "Social Media", "Technology", "Indian Culture", "Food / Recipes",
              "Lifestyle", "General Education", "Custom"):
        assert c in CATEGORIES


def test_crud_validation_duplicates_and_history(store, tmp_path):
    with pytest.raises(KnowledgeError):
        store.create({"title": "No content"})
    with pytest.raises(KnowledgeError):
        store.create({"title": "X", "summary": "y", "category": "Nonsense"})
    with pytest.raises(KnowledgeError):  # alias already used by another record (any language)
        store.create({"title": "Straight hair", "summary": "x", "aliases": ["হেয়ার স্ট্রেইটনিং"]})
    with pytest.raises(KnowledgeError):
        store.get("../../etc/passwd")
    rec = store.update("gk-hair_straightening", {"summary": "Straightening hair with heat or chemicals."})
    assert rec.revision == 2 and rec.summary.startswith("Straightening")
    assert list((tmp_path / "general" / ".history").glob("gk-hair_straightening.*.json"))  # previous version kept
    store.update(rec.id, {"enabled": False})
    assert store.lookup("Hair straightening ki?") == []  # disabled records are not retrieved
    with pytest.raises(KnowledgeError):
        store.delete(rec.id, confirm=False)
    store.delete(rec.id, confirm=True)
    assert rec.id not in {r.id for r in store.list()}


def test_hot_reload_without_restart(store, tmp_path):
    other = GeneralKnowledgeStore(tmp_path / "general", embedder=keyword_embedder)  # e.g. the chat service's instance
    assert other.lookup("biryani ki?", "biryani") == []
    store.create({"title": "Biryani", "category": "Food / Recipes", "aliases": ["biriyani", "বিরিয়ানি"],
                  "summary": "Layered spiced rice dish."})
    assert [m.record.id for m in other.lookup("biryani ki?", "biryani")] == ["gk-biryani"]


@pytest.mark.parametrize("msg,cand", [("Hair straightening ki?", "Hair straightening"),
                                      ("হেয়ার স্ট্রেইটনিং কী?", "হেয়ার স্ট্রেইটনিং"),
                                      ("chul straight kora mane ki?", "chul straight kora")])
def test_exact_and_multilingual_alias_retrieval(store, msg, cand):
    m = store.lookup(msg, cand)
    assert m and m[0].record.id == "gk-hair_straightening" and m[0].method in ("exact", "phrase")


def test_semantic_retrieval_requires_topic_words():
    rec = type("R", (), {"title": "Hair Straightening", "aliases": ["chul straight kora"]})()
    assert _names_covered(_content_words("how do I make my hair straight"), rec)
    assert _names_covered(_content_words("chul straight korar upay"), rec)
    assert not _names_covered(_content_words("what is hair color"), rec)  # look-alike topic rejected
    assert not _names_covered(_content_words("curly hair care tips"), rec)


def test_semantic_weak_matches_rejected(store):
    assert store.lookup("ajke amar mood kharap") == []
    assert store.lookup("Taj Mahal kothay?") == []


def _k(msg, general, prev=None, history=0, terms=None):
    return build_turn_knowledge(msg, use_rag=False, rag_query=None, terminology=terms, general=general,
                                previous_terms=prev, history_messages=history)


def test_routing_priority_and_no_rag_for_chat(store, tmp_path):
    terms = TerminologyStore(tmp_path / "terms")
    terms.create({"term": "Foreplay", "definition": "Intimacy before sex.", "aliases": ["fore play", "ফোরপ্লে"]})
    k = _k("Hair straightening ki?", store, terms=terms)
    assert k.terms_used == ["gk-hair_straightening"] and "Topic: Hair Straightening" in k.general_context
    assert k.retrieval[0]["source"] == "general" and k.retrieval[0]["category"] == "Beauty"
    k = _k("Foreplay mane ki?", store, terms=terms)  # specialised terminology wins
    assert k.terms_used == ["term-foreplay"] and k.general_context is None
    for msg in ("Hi Rupsaa", "Ajke mon kharap", "Amar favourite color blue"):
        k = _k(msg, store, terms=terms)
        assert k.terms_used == [] and k.general_context is None, msg


def test_followups_keep_the_active_topic(store):
    k = _k("Hair straightening ki?", store)
    for follow in ("Eta Bengali te bolo.", "abar Banglish e bolo.", "aro simple kore bolo"):
        f = _k(follow, store, prev=k.terms_used, history=2)
        assert f.route == "followup" and f.terms_used == ["gk-hair_straightening"], follow
        assert "Hair Straightening" in f.general_context


def test_import_preview_commit_duplicates_and_export(store):
    csv = ("title,category,aliases,summary,key_points\r\n"
           "Retinol,Beauty,retinol cream|রেটিনল,Vitamin A skincare ingredient.,Start slow|Use sunscreen\r\n"
           "Retinol Again,Beauty,retinol,dup,\r\n"
           "Hair Straightening,Beauty,,Updated summary.,\r\n"
           "Bad,Weird Category,,x,\r\n"
           ",Beauty,,missing title,\r\n").encode()
    pv = gki.preview("k.csv", csv, store)
    status = {r["data"]["title"]: r["status"] for r in pv["rows"]}
    assert status["Retinol"] == "valid" and status["Retinol Again"] == "duplicate_in_file"
    assert status["Hair Straightening"] == "existing_match" and status["Bad"] == "warning" and status[""] == "invalid"
    res = gki.commit("k.csv", csv, store)
    assert res["counts"]["created"] == 2  # Retinol + Bad (as Custom); existing skipped unless UPDATE chosen
    assert store.get("gk-retinol").key_points == ["Start slow", "Use sunscreen"]
    assert store.get("gk-hair_straightening").summary.startswith("Making")  # skipped, not overwritten
    data = json.loads(gki.export_json(store))
    assert {r["id"] for r in data["records"]} >= {"gk-retinol", "gk-hair_straightening"}
    assert b"Retinol" in gki.export_csv(store) and gki.export_xlsx(store)[:2] == b"PK"
    rt = gki.preview("back.json", gki.export_json(store), store)  # round-trip: everything already exists
    assert all(r["status"] == "existing_match" for r in rt["rows"])


def test_import_limits(store):
    with pytest.raises(gki.ImportFileError):
        gki.preview("k.txt", b"x", store)
    with pytest.raises(gki.ImportFileError):
        gki.preview("k.csv", b"", store)
    with pytest.raises(gki.ImportFileError):
        gki.preview("k.csv", b"x" * (3 * 1024 * 1024), store)


def test_owner_api_requires_key_and_works(tmp_path, monkeypatch):
    import api.owner_routes as owner_routes
    from api.main import app
    from rupsaa.config import get_settings

    monkeypatch.setenv("OWNER_API_KEY", "k" * 40)
    get_settings.cache_clear()
    store = GeneralKnowledgeStore(tmp_path / "g", embedder=keyword_embedder)
    monkeypatch.setattr(owner_routes, "_get_general", lambda: store)
    c, h = TestClient(app), {"X-Owner-Key": "k" * 40}
    assert c.get("/owner/general").status_code == 401
    r = c.post("/owner/general", json=HAIR, headers=h)
    assert r.status_code == 200 and r.json()["id"] == "gk-hair_straightening"
    assert c.post("/owner/general", json=HAIR, headers=h).status_code == 400  # duplicate
    assert c.get("/owner/general?category=Beauty", headers=h).json()["count"] == 1
    assert c.put("/owner/general/gk-hair_straightening", json={"tags": ["hair"]}, headers=h).json()["tags"] == ["hair"]
    assert c.get("/owner/general?tag=hair", headers=h).json()["count"] == 1
    assert c.get("/owner/general/meta", headers=h).json()["counts"]["Beauty"] == 1
    up = c.post("/owner/general/import", files={"file": ("k.json", json.dumps([{"title": "Wet Look", "category": "Fashion", "summary": "Glossy."}]).encode(), "application/json")}, headers=h)
    assert up.json()["counts"]["created"] == 1
    assert c.get("/owner/general/export.csv", headers=h).status_code == 200
    assert c.delete("/owner/general/gk-wet_look", headers=h).status_code == 400
    assert c.delete("/owner/general/gk-wet_look?confirm=true", headers=h).status_code == 200
    get_settings.cache_clear()


def test_provenance_fields_validated_and_round_trip(tmp_path):
    from rupsaa.rag import general_knowledge_import as gki
    from rupsaa.rag.general_knowledge import GeneralKnowledgeStore, KnowledgeError

    store = GeneralKnowledgeStore(tmp_path / "gk", embedder=lambda t, q: None)
    with pytest.raises(KnowledgeError):
        store.create({"title": "X", "summary": "y", "source_type": "web"})  # live web is never a provenance on its own
    with pytest.raises(KnowledgeError):
        store.create({"title": "X", "summary": "y", "sources": [{"url": "http://127.0.0.1/x"}]})
    rec = store.create({"title": "Aftercare", "category": "Adult Terminology", "summary": "Care after an intense scene.",
                        "source_type": "owner_verified_web", "verified": True,
                        "sources": [{"title": "Glossary", "url": "https://www.scarleteen.com/read/glossary"}]})
    assert rec.sources[0]["domain"] == "www.scarleteen.com" and rec.approved_by == "owner" and rec.revision == 1
    csv_bytes = gki.export_csv(store)
    assert b"owner_verified_web" in csv_bytes and b"source_type" in csv_bytes
    other = GeneralKnowledgeStore(tmp_path / "gk2", embedder=lambda t, q: None)
    gki.commit("k.json", gki.export_json(store), other)
    back = other.list()[0]
    assert (back.source_type, back.verified, back.sources[0]["url"]) == ("owner_verified_web", True, rec.sources[0]["url"])
    gki.commit("k.csv", b"title,summary\nNew Thing,Something\n", other)
    assert other.get("gk-new_thing").source_type == "import"
