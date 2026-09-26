"""V0.2.1 runtime fixes found in the owner's live V0.2 test: explicit language
control, structured conversation recall, conservative typo matching. No model."""

from dataclasses import dataclass

import pytest

from rupsaa.conversation.language_control import directive_for, requested_language, resolve_turn_language
from rupsaa.personality.system_prompt import build_system_prompt
from rupsaa.rag.context_builder import build_turn_knowledge, memory_note
from rupsaa.rag.router import Route, classify_message
from rupsaa.rag.terminology import TerminologyStore


@dataclass
class Msg:
    role: str
    content: str


@pytest.fixture
def terms(tmp_path) -> TerminologyStore:
    store = TerminologyStore(tmp_path / "terminology")
    store.create({"term": "Foreplay", "definition": "Intimacy before sex.", "category": "adult_terminology"})
    store.create({"term": "Consent", "definition": "Agreement.", "category": "adult_terminology"})
    store.create({"term": "Tease", "definition": "Playful build-up.", "category": "adult_terminology"})
    return store


@pytest.mark.parametrize("msg,lang", [
    ("এটা বাংলায় বুঝিয়ে বলো", "bn"), ("banglay bolo", "bn"), ("bangla te bolo", "bn"), ("bengali te bolo", "bn"),
    ("explain in Bengali", "bn"), ("এবার বাংলায়", "bn"),
    ("banglish e bolo", "banglish"), ("Banglish e explain koro", "banglish"), ("in Banglish please", "banglish"),
    ("english e bolo", "en"), ("say it in English", "en"), ("ইংরেজিতে বলো", "en"),
])
def test_explicit_language_requests(msg, lang):
    assert requested_language(msg) == lang


@pytest.mark.parametrize("msg", ["ami bangla bhalo bujhi na", "amar bangla movie bhalo lage", "English teacher ta kharap",
                                 "বাংলা গান শুনছি", "Strip mane ki?", "tumi kemon acho?"])
def test_mentions_of_a_language_are_not_requests(msg):
    assert requested_language(msg) is None


def test_language_choice_carries_to_followups_then_mirroring_resumes():
    lang, state = resolve_turn_language("এটা বাংলায় বুঝিয়ে বলো", "followup", None)
    assert lang == "bn" and not state["sticky"]
    assert resolve_turn_language("short kore bolo", "followup", state)[0] == "bn"
    assert resolve_turn_language("amar favourite color blue", "general", state) == (None, None)


def test_sticky_language_choice_lasts_until_changed():
    _, state = resolve_turn_language("ekhon theke banglay kotha bolo", "general", None)
    assert state["sticky"]
    assert resolve_turn_language("tumi kemon acho?", "casual", state)[0] == "bn"
    assert resolve_turn_language("english e bolo", "followup", state)[0] == "en"


def test_directive_quotes_the_request_and_is_last_in_the_prompt():
    _, state = resolve_turn_language("এটা বাংলায় বুঝিয়ে বলো", "followup", None)
    d = directive_for(state)
    assert '"এটা বাংলায় বুঝিয়ে বলো"' in d and "Bengali script" in d
    prompt = build_system_prompt(prompt_version="v0.2", terminology_context="Term: X\nDefinition: y", language_directive=d)
    assert prompt.endswith(d)
    assert directive_for(None) is None


def test_memory_routes(terms):
    for msg in ("ami age ki bolechilam?", "ami prothome ki bolechilam?", "what did I say earlier?", "what did I say first?",
                "ami age ki bolechi?", "ager message e ki bolechilam?", "আমি আগে কী বলেছিলাম?",
                "ami kar biyer kotha bolechilam?", "ami keno mon kharap bolechilam?", "আমার কুকুরের নাম কী বলেছিলাম?"):
        assert classify_message(msg).route == Route.MEMORY, msg


def test_non_recall_questions_are_not_memory():
    for msg in ("tumi ki bolechile?", "ajke ki korbo?", "keno emon hoy?", "Strip mane ki?"):
        assert classify_message(msg).route != Route.MEMORY, msg


def test_memory_note_lists_earlier_user_messages_without_answering(terms):
    history = [Msg("user", "amar favourite color blue"), Msg("assistant", "Blue sundor."),
               Msg("user", "ajke office e chap chilo"), Msg("assistant", "Ki hoyechilo?")]
    k = build_turn_knowledge("ami age ki bolechilam?", use_rag=True, rag_query=lambda q, strict=False: ("DOC", [{}]),
                             terminology=terms, history=history, history_messages=4)
    assert k.route == "memory" and k.retrieved_context is None and k.terminology_context is None
    note = k.conversation_note
    assert '"ami age ki bolechilam?"' in note
    assert "1. amar favourite color blue" in note and "2. ajke office e chap chilo" in note
    assert "Blue sundor" not in note  # only the user's own messages are listed
    empty = memory_note([], 0, False, question="what did I say first?")
    assert "no earlier messages" in empty


def test_memory_note_caps_long_histories():
    history = [Msg("user", f"message {i}") for i in range(30)]
    note = memory_note(history, 30, True, question="what did I say first?")
    assert "19. message 18" in note and "30. message 29" in note and "1. message 0" not in note
    assert "too far back" in note


def test_typo_matching_is_conservative(terms):
    def match(msg):
        return [m.record.id for m in terms.lookup(msg, classify_message(msg).term_candidate)]
    assert match("Forplay ki?") == ["term-foreplay"]
    assert match("consnet ki?") == ["term-consent"]
    assert match("content ki?") == []  # a real word is never a typo
    assert match("testing ki?") == []
    assert match("peace ki?") == []  # different first letter


def test_service_keeps_language_state_per_conversation():
    from api.services import RupsaaService

    class FakeEngine:
        prompt_version = "v0.2"

        def __init__(self):
            self.calls = []

        def chat(self, **kw):
            from rupsaa.model.inference import ChatResult
            self.calls.append(kw)
            return ChatResult(text="ok", blocked=False)

    svc = RupsaaService()
    svc._engine = FakeEngine()
    r1 = svc.chat(message="foreplay ki?", conversation_id=None, use_rag=False, temperature=None, top_p=None, max_new_tokens=None)
    cid = r1["conversation_id"]
    r2 = svc.chat(message="এটা বাংলায় বুঝিয়ে বলো", conversation_id=cid, use_rag=False, temperature=None, top_p=None, max_new_tokens=None)
    assert r2["response_language"] == "bn" and "Bengali script" in svc._engine.calls[-1]["language_directive"]
    svc.chat(message="amar favourite color blue", conversation_id=cid, use_rag=False, temperature=None, top_p=None, max_new_tokens=None)
    assert svc._engine.calls[-1]["language_directive"] is None
    r4 = svc.chat(message="ami age ki bolechilam?", conversation_id=cid, use_rag=False, temperature=None, top_p=None, max_new_tokens=None)
    assert r4["route"] == "memory" and "amar favourite color blue" in svc._engine.calls[-1]["conversation_note"]
    svc.reset_conversation(cid)
    assert cid not in svc._language


def test_followup_phrasings_found_while_building_corrective_data():
    for msg in ("শর্ট করে বলো, বাংলায়", "বাংলায় বুঝিয়ে দাও", "banglish e likhe dao", "bujhlam na"):
        assert classify_message(msg).route == Route.FOLLOWUP, msg
    assert classify_message("bujhlam").route != Route.FOLLOWUP  # "got it" is an acknowledgement, not a re-ask


def test_exact_term_match_drops_sub_phrase_matches_of_other_terms(tmp_path):
    store = TerminologyStore(tmp_path / "t")
    store.create({"term": "Lip Biting", "definition": "x", "category": "adult_terminology", "aliases": ["lip biting"]})
    store.create({"term": "Bite (Gentle)", "definition": "y", "category": "adult_terminology", "aliases": ["biting"]})
    got = [m.record.id for m in store.lookup("lip biting ki?", classify_message("lip biting ki?").term_candidate)]
    assert got == ["term-lip_biting"]
    got = [m.record.id for m in store.lookup("biting ki?", classify_message("biting ki?").term_candidate)]
    assert got == ["term-bite_gentle"]


def test_corrective_records_are_built_by_the_runtime():
    """Every V0.2.1 corrective record's system prompt is what the app would send on its final turn."""
    import json

    from rupsaa.config import PROJECT_ROOT
    from scripts.v021_build_corrective import build, load_source

    src = PROJECT_ROOT / "data/production/corrective/rupsaa_v0.2.1/corrective_records.jsonl"
    if not src.exists():
        pytest.skip("corrective records not built")
    store = TerminologyStore(PROJECT_ROOT / "knowledge/terminology")
    rebuilt, errors = build(load_source(), store)
    assert not errors
    on_disk = [json.loads(line) for line in open(src, encoding="utf-8")]
    assert [r["messages"] for r in rebuilt] == [r["messages"] for r in on_disk]
