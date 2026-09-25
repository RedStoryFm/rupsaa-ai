"""V0.2 prep: request routing, structured terminology, retrieval suppression,
conversation memory. No model weights and no embedding model are loaded —
the engine and RAG pipeline are faked, the vector store is exercised with
hand-made vectors.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from fastapi.testclient import TestClient

import api.owner_routes as owner_routes
from api.main import app
from api.services import RupsaaService
from rupsaa.conversation.manager import ConversationManager, InMemoryConversationStore
from rupsaa.personality.system_prompt import build_system_prompt
from rupsaa.rag.context_builder import build_turn_knowledge
from rupsaa.rag.document_loader import load_documents_from_dir
from rupsaa.rag.pipeline import filter_results, is_hidden_source
from rupsaa.rag.router import Route, classify_message
from rupsaa.rag.terminology import TerminologyError, TerminologyStore
from rupsaa.rag.vector_store import ChunkMetadata, SearchResult

STRIP = {
    "term": "Strip / Stripping",
    "aliases": ["strip", "stripping", "striptease", "স্ট্রিপ", "স্ট্রিপিং"],
    "category": "adult_terminology",
    "definition": "Removing clothing, sometimes gradually, including in seductive, performance or sexual contexts.",
    "answer_guidance": "Answer the definition directly; match the user's language; start concise.",
    "example_queries": ["strip mane ki", "what does stripping mean", "stripping bolte ki bojhay"],
}


@pytest.fixture
def terms(tmp_path) -> TerminologyStore:
    store = TerminologyStore(tmp_path / "terminology")
    store.create(STRIP)
    store.create({"term": "Chargeback", "definition": "A bank-initiated payment reversal.", "category": "creator_platform"})
    return store


# --- routing -----------------------------------------------------------------

@pytest.mark.parametrize("msg", ["kemon acho?", "Hi Rupsaa, kemon acho?", "ajke amar mood ta bhalo na",
                                 "কেমন আছো?", "tumi ki korcho?", "What's up?", "good night"])
def test_casual_chat_bypasses_rag(msg):
    d = classify_message(msg)
    assert d.route == Route.CASUAL
    assert not d.use_documents and not d.use_terminology


@pytest.mark.parametrize("msg,term", [
    ("Strip mane ki?", "Strip"),                       # Banglish
    ("strip ki?", "strip"),
    ("stripping bolte ki bojhay?", "stripping"),
    ("what does stripping mean?", "stripping"),        # English
    ("What is a chargeback?", "chargeback"),
    ("স্ট্রিপ মানে কী?", "স্ট্রিপ"),                     # Bengali
    ("স্ট্রিপিং বলতে কী বোঝায়?", "স্ট্রিপিং"),
    ("accha, PPV mane ki?", "PPV"),
])
def test_definition_questions_route_to_terminology(msg, term):
    d = classify_message(msg)
    assert d.route == Route.TERMINOLOGY
    assert d.term_candidate == term
    assert d.use_terminology


@pytest.mark.parametrize("msg", ["ami age ki bolechilam?", "What did I say first?", "ami ki color bolechilam?",
                                 "আমি আগে কী বলেছিলাম?", "what was my first message?"])
def test_memory_questions_route_to_history_not_rag(msg):
    d = classify_message(msg)
    assert d.route == Route.MEMORY
    assert not d.use_documents and not d.use_terminology


@pytest.mark.parametrize("msg", ["এটা বাংলায় বুঝিয়ে বলো", "eta short kore bolo", "bangla te bujhiye bolo",
                                 "explain that in English", "make it shorter"])
def test_followups_route_to_followup(msg):
    assert classify_message(msg).route == Route.FOLLOWUP


def test_knowledge_questions_still_use_documents():
    for msg in ["What is this platform's exact refund policy?", "How do payouts work for creators?", "tumi ke?"]:
        d = classify_message(msg)
        assert d.route == Route.KNOWLEDGE and d.use_documents and not d.strict_documents


# --- terminology store ----------------------------------------------------------

@pytest.mark.parametrize("msg", ["Strip mane ki?", "strip ki?", "stripping bolte ki bojhay?",
                                 "what does stripping mean?", "স্ট্রিপ মানে কী?", "স্ট্রিপিং বলতে কী বোঝায়?"])
def test_terminology_lookup_by_term_and_aliases_across_languages(terms, msg):
    d = classify_message(msg)
    matches = terms.lookup(msg, d.term_candidate)
    assert matches and matches[0].record.id == "term-strip_stripping"


def test_terminology_lookup_does_not_match_unrelated(terms):
    assert terms.lookup("what is love?", "love") == []
    assert terms.lookup("kemon acho?", None) == []


def test_terminology_fuzzy_typo(terms):
    m = terms.lookup("stripin mane ki?", "stripin")
    assert m and m[0].record.id == "term-strip_stripping" and m[0].method == "fuzzy"


def test_disabled_terms_are_not_retrieved(terms):
    terms.update("term-strip_stripping", {"enabled": False})
    assert terms.lookup("Strip mane ki?", "Strip") == []
    assert any(t.id == "term-strip_stripping" for t in terms.list())  # still listed for the owner


def test_terminology_crud_validation_and_conflicts(terms):
    with pytest.raises(TerminologyError):
        terms.create({"term": "", "definition": "x"})
    with pytest.raises(TerminologyError):
        terms.create({"term": "Other", "definition": "x", "category": "not-a-category"})
    with pytest.raises(TerminologyError, match="already used"):
        terms.create({"term": "Striptease thing", "aliases": ["strip"], "definition": "dup alias"})
    rec = terms.update("term-chargeback", {"aliases": ["charge back", "cb"]})
    assert rec.aliases == ["charge back", "cb"] and rec.updated_at >= rec.created_at
    assert terms.lookup("charge back mane ki?", "charge back")[0].record.id == "term-chargeback"
    with pytest.raises(TerminologyError):
        terms.delete("term-chargeback", confirm=False)
    terms.delete("term-chargeback", confirm=True)
    assert [t.id for t in terms.list()] == ["term-strip_stripping"]


def test_terminology_rejects_path_traversal_ids(terms):
    with pytest.raises(TerminologyError):
        terms.get("../../etc/passwd")


def test_terminology_edits_are_live_without_reindex(terms):
    assert terms.lookup("GFE mane ki?", "GFE") == []
    terms.create({"term": "GFE", "definition": "Girlfriend experience.", "category": "adult_terminology"})
    assert terms.lookup("GFE mane ki?", "GFE")[0].record.term == "GFE"


# --- knowledge assembly / response construction ----------------------------------------

class SpyRag:
    def __init__(self, result=("[Source: faq.md]\nPayouts are weekly.", [{"source_filename": "faq.md", "chunk_id": 0, "score": 0.9}])):
        self.calls = []
        self.result = result

    def __call__(self, question, strict=False):
        self.calls.append((question, strict))
        return self.result


def test_casual_turn_never_calls_rag(terms):
    rag = SpyRag()
    k = build_turn_knowledge("kemon acho?", use_rag=True, rag_query=rag, terminology=terms)
    assert rag.calls == [] and k.retrieved_context is None and k.terminology_context is None


def test_terminology_turn_uses_terms_not_documents(terms):
    rag = SpyRag()
    k = build_turn_knowledge("Strip mane ki?", use_rag=True, rag_query=rag, terminology=terms)
    assert k.route == "terminology" and k.terms_used == ["term-strip_stripping"]
    assert "Definition: Removing clothing" in k.terminology_context
    assert rag.calls == []  # the structured entry answers it


def test_terminology_works_with_rag_toggle_off(terms):
    k = build_turn_knowledge("strip ki?", use_rag=False, rag_query=SpyRag(), terminology=terms)
    assert k.terms_used == ["term-strip_stripping"]


def test_unknown_term_falls_back_to_strict_documents(terms):
    rag = SpyRag()
    build_turn_knowledge("PPV mane ki?", use_rag=True, rag_query=rag, terminology=terms)
    assert rag.calls == [("PPV mane ki?", True)]


def test_knowledge_question_still_uses_documents(terms):
    rag = SpyRag()
    k = build_turn_knowledge("How do payouts work for creators?", use_rag=True, rag_query=rag, terminology=terms)
    assert rag.calls == [("How do payouts work for creators?", False)] and k.sources


def test_followup_carries_previous_terms_without_documents(terms):
    rag = SpyRag()
    k = build_turn_knowledge("এটা বাংলায় বুঝিয়ে বলো", use_rag=True, rag_query=rag, terminology=terms,
                             previous_terms=["term-strip_stripping"], history_messages=2)
    assert k.route == "followup" and k.terms_used == ["term-strip_stripping"] and rag.calls == []


def test_posttrain_router_gaps_are_closed(terms):
    """Owner failure prompts found in the V0.2 post-training evaluation."""
    k = build_turn_knowledge("strip ta ektu simple kore bojhao", use_rag=False, rag_query=None, terminology=terms,
                             previous_terms=["term-strip_stripping"], history_messages=2)
    assert k.route == "followup" and k.terms_used == ["term-strip_stripping"]
    k = build_turn_knowledge("stirp mane ki bolo to", use_rag=False, rag_query=None, terminology=terms)
    assert k.route == "terminology" and k.terms_used == ["term-strip_stripping"]
    k = build_turn_knowledge("Tell me what strip means", use_rag=False, rag_query=None, terminology=terms)
    assert k.route == "terminology" and k.terms_used == ["term-strip_stripping"]
    k = build_turn_knowledge("strip niye ektu detail e bojhao", use_rag=False, rag_query=None, terminology=terms)
    assert k.route == "general" and k.terms_used == ["term-strip_stripping"]
    k = build_turn_knowledge("এটা বাংলায় বুঝিয়ে বলো", use_rag=False, rag_query=None, terminology=terms, history_messages=0)
    assert k.route == "followup" and not k.terms_used and "no earlier messages" in k.conversation_note
    k = build_turn_knowledge("I need to talk to my partner about something hard", use_rag=False, rag_query=None, terminology=terms)
    assert k.terms_used == []


def test_memory_turn_gets_note_and_no_knowledge(terms):
    rag = SpyRag()
    k = build_turn_knowledge("ami age ki bolechilam?", use_rag=True, rag_query=rag, terminology=terms,
                             history_messages=4)
    assert rag.calls == [] and k.retrieved_context is None and k.terminology_context is None
    assert "earlier in this conversation" in k.conversation_note
    trunc = build_turn_knowledge("What did I say first?", use_rag=True, rag_query=rag, terminology=terms,
                                 history_messages=20, history_truncated=True)
    assert "too far back" in trunc.conversation_note


def test_system_prompt_presents_terminology_as_reference_not_script(terms):
    ctx = build_turn_knowledge("Strip mane ki?", use_rag=False, rag_query=None, terminology=terms).terminology_context
    prompt = build_system_prompt(terminology_context=ctx)
    assert "Reference terminology" in prompt and "in your own words" in prompt
    assert "Term: Strip / Stripping" in prompt
    assert "Reference terminology" not in build_system_prompt()


# --- retrieval suppression ------------------------------------------------------------

def _res(name, score, text="payout schedule weekly"):
    return SearchResult(score=score, metadata=ChunkMetadata(chunk_id=0, source_filename=name, text=text))


def test_metadata_files_never_returned_as_sources():
    assert is_hidden_source(".metadata.json") and is_hidden_source("docs/.metadata.json")
    out = filter_results("payout?", [_res(".metadata.json", 0.9, "{}"), _res("faq.md", 0.85)])
    assert [r.metadata.source_filename for r in out] == ["faq.md"]


def test_document_loader_skips_hidden_files(tmp_path):
    (tmp_path / ".metadata.json").write_text("{}", encoding="utf-8")
    (tmp_path / "faq.md").write_text("Payouts are weekly.", encoding="utf-8")
    docs = load_documents_from_dir(tmp_path, [".md", ".json"])
    assert [d.source_filename for d in docs] == ["faq.md"]


def test_low_confidence_tail_is_suppressed():
    out = filter_results("payout schedule?", [_res("a.md", 0.86), _res("b.md", 0.85), _res("c.md", 0.78)])
    assert [r.metadata.source_filename for r in out] == ["a.md", "b.md"]


def test_strict_retrieval_requires_keyword_overlap():
    results = [_res("identity.md", 0.83, "Rupsaa is a warm companion who likes music.")]
    assert filter_results("How do I bring it up without starting a fight?", results, strict=True) == []
    assert filter_results("what music do you like?", results, strict=True)


# --- conversation memory through the real service (fake engine + fake RAG) --------------------

@dataclass
class FakeEngineResult:
    text: str
    blocked: bool = False


@dataclass
class RecordingEngine:
    calls: list = field(default_factory=list)

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        return FakeEngineResult(text=f"reply {len(self.calls)}")


class FakeRagPipeline:
    def __init__(self):
        self.calls = []

    def query(self, q, strict=False):
        self.calls.append(q)
        return None, []


@pytest.fixture
def service(tmp_path, terms):
    svc = RupsaaService()
    svc.conversation_manager = ConversationManager(store=InMemoryConversationStore(), max_history_messages=20)
    svc._engine = RecordingEngine()
    svc._rag_pipeline = FakeRagPipeline()
    svc._terminology = terms
    return svc


def _chat(svc, msg, cid="c1", use_rag=True):
    return svc.chat(message=msg, conversation_id=cid, use_rag=use_rag, temperature=None, top_p=None, max_new_tokens=None)


def test_memory_question_uses_conversation_history(service):
    _chat(service, "amar favourite color blue")
    out = _chat(service, "ami ki color bolechilam?")
    call = service._engine.calls[-1]
    history = [(m.role, m.content) for m in call["history"]]
    assert ("user", "amar favourite color blue") in history
    assert call["conversation_note"] and call["retrieved_context"] is None
    assert out["route"] == "memory" and out["rag_used"] is False and out["sources"] == []


def test_what_did_i_say_first_does_not_invoke_knowledge_rag(service):
    _chat(service, "amar favourite color blue")
    service._rag_pipeline.calls.clear()
    _chat(service, "What did I say first?")
    assert service._rag_pipeline.calls == []
    assert service._engine.calls[-1]["history"][0].content == "amar favourite color blue"


def test_service_terminology_turn_and_followup(service):
    out = _chat(service, "Strip mane ki?")
    assert out["route"] == "terminology" and out["terms_used"] == ["term-strip_stripping"]
    assert "Term: Strip / Stripping" in service._engine.calls[-1]["terminology_context"]
    out2 = _chat(service, "এটা বাংলায় বুঝিয়ে বলো")
    assert out2["route"] == "followup" and out2["terms_used"] == ["term-strip_stripping"]
    service.reset_conversation("c1")
    assert _chat(service, "এটা বাংলায় বুঝিয়ে বলো")["terms_used"] == []


def test_history_cap_tracks_dropped_messages():
    manager = ConversationManager(store=InMemoryConversationStore(), max_history_messages=4)
    conv = manager.get_or_create(None)
    for i in range(3):
        manager.append_turn(conv, f"u{i}", f"a{i}")
    assert conv.dropped_messages == 2 and conv.messages[0].content == "u1"


# --- owner API ----------------------------------------------------------------------------

@pytest.fixture
def owner_terms(tmp_path, monkeypatch):
    store = TerminologyStore(tmp_path / "owner_terms")
    monkeypatch.setattr(owner_routes, "_get_terminology", lambda: store)
    return store


def test_owner_terminology_crud_and_lookup(owner_terms):
    client = TestClient(app)
    r = client.post("/owner/terminology", json=STRIP)
    assert r.status_code == 200, r.text
    term_id = r.json()["id"]
    assert client.get("/owner/terminology", params={"q": "stripping"}).json()["terms"][0]["id"] == term_id
    look = client.get("/owner/terminology/lookup", params={"message": "Strip mane ki?"}).json()
    assert look["route"] == "terminology" and look["matches"][0]["id"] == term_id
    r = client.put(f"/owner/terminology/{term_id}", json={"details": "Also a performance genre."})
    assert r.status_code == 200 and r.json()["details"] == "Also a performance genre."
    assert client.post("/owner/terminology", json={"term": "x", "definition": "y", "category": "nope"}).status_code == 400
    assert client.delete(f"/owner/terminology/{term_id}").status_code == 400  # needs confirm
    assert client.delete(f"/owner/terminology/{term_id}", params={"confirm": True}).status_code == 200
    assert client.get(f"/owner/terminology/{term_id}").status_code == 404


def test_owner_terminology_requires_key_when_configured(owner_terms, monkeypatch):
    from rupsaa.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("OWNER_API_KEY", "k")
    get_settings.cache_clear()
    try:
        client = TestClient(app)
        assert client.get("/owner/terminology").status_code == 401
        assert client.get("/owner/terminology", headers={"X-Owner-Key": "k"}).status_code == 200
    finally:
        get_settings.cache_clear()


def test_chat_response_schema_backward_compatible():
    from api.schemas import ChatResponse

    old_shape = {"response": "hi", "conversation_id": "c", "language": "en", "rag_used": False}
    resp = ChatResponse(**old_shape)
    assert resp.route is None and resp.terms_used == [] and resp.sources == []
