"""Knowledge V1 retrieval-layer fixes (synthetic records only — never the private evaluation queries):
lookup gating, short exact-only messages, specificity, Bengali suffixes, elliptical follow-ups, ranking among
name hits, kitchen-context protection."""

import pytest

from rupsaa.rag.context_builder import build_turn_knowledge
from rupsaa.rag.dance import DanceStore
from rupsaa.rag.general_knowledge import GeneralKnowledgeStore
from rupsaa.rag.terminology import TerminologyStore
from tests.conftest_rupsaa_fakes import keyword_embedder


@pytest.fixture
def stores(tmp_path):
    t = TerminologyStore(tmp_path / "t")
    t.create({"term": "Consent", "definition": "Agreement.", "category": "adult_terminology", "aliases": ["consent"]})
    t.create({"term": "Grinding", "definition": "Rubbing bodies.", "category": "adult_terminology", "aliases": ["grind"]})
    d = DanceStore(tmp_path / "d")
    d.create({"name": "Breaking", "origin": "New York", "description": "Breakdance.", "aliases": ["breaking"]})
    g = GeneralKnowledgeStore(tmp_path / "g", embedder=keyword_embedder)
    for title, cat, aliases, summary in [
        ("Enthusiastic Consent", "Sexual Education", ["enthusiastic consent"], "A clear, eager yes."),
        ("Ejaculation", "Sexual Education", ["বীর্যপাত"], "Release of semen."),
        ("Premature Ejaculation", "Sexual Education", ["অকাল বীর্যপাত"], "Ejaculating sooner than wanted."),
        ("Menstruation", "Health & Hygiene", ["মাসিক", "period"], "The monthly period."),
        ("Libido", "Sexual Education", ["sex drive"], "Sexual desire."),
        ("Condom", "Sexual Education", ["condom"], "A barrier method."),
    ]:
        g.create({"title": title, "category": cat, "aliases": aliases, "summary": summary})
    return t, d, g


def _ask(stores, message, previous=None):
    t, d, g = stores
    return build_turn_knowledge(message, use_rag=False, rag_query=None, terminology=t, dance=d, general=g,
                                previous_terms=previous, history_messages=2 if previous else 0)


def test_short_message_naming_a_concept_is_looked_up(stores):
    assert _ask(stores, "sex drive").terms_used == ["gk-libido"]
    assert _ask(stores, "consent?").terms_used == ["term-consent"]


@pytest.mark.parametrize("msg", ["breaking news", "Hi Rupsaa", "Ajke amar mood kharap", "ami vegetarian"])
def test_short_casual_messages_never_phrase_match(stores, msg):
    assert _ask(stores, msg).terms_used == []  # "breaking news" must not reach the dance "Breaking"


def test_personal_wording_still_reaches_general_knowledge(stores):
    assert _ask(stores, "amar sex drive onek kom, ki korbo").terms_used == ["gk-libido"]


def test_most_specific_name_wins_within_and_across_stores(stores):
    assert _ask(stores, "অকাল বীর্যপাত কেন হয়").terms_used[0] == "gk-premature_ejaculation"
    k = _ask(stores, "tell me about enthusiastic consent please")
    assert k.terms_used == ["gk-enthusiastic_consent"]  # not the broader Terminology "consent" inside it


def test_bengali_inflected_words_match_their_alias(stores):
    assert _ask(stores, "মাসিকের সময় পেটে ব্যথা কেন হয়?").terms_used == ["gk-menstruation"]


def test_elliptical_followup_carries_topic_but_fresh_or_smalltalk_does_not(stores):
    assert _ask(stores, "kono risk ache ki?", previous=["gk-condom"]).terms_used == ["gk-condom"]
    assert _ask(stores, "আর প্রথমবার হলে?", previous=["term-consent"]).terms_used == ["term-consent"]
    assert _ask(stores, "ajker weather kemon?", previous=["gk-condom"]).terms_used == []
    assert _ask(stores, "Hi Rupsaa", previous=["gk-condom"]).terms_used == []
    assert _ask(stores, "sex drive ki?", previous=["gk-condom"]).terms_used == ["gk-libido"]  # topic shift
    # a new, unknown named topic never inherits the previous one
    assert _ask(stores, "Kintsugi ki?", previous=["term-consent"]).terms_used == []
    assert _ask(stores, "Kintsugi mane ki jano?", previous=["term-consent"]).terms_used == []


def _two_topic_embedder(texts, is_query):
    """Controlled e5-like scores: queries are close to PrEP/PEP (0.99) and far from HIV (0.5)."""
    import numpy as np

    return np.array([[0.5, 0.866] if is_query else ([0.6, 0.8] if "prep" in t.lower() else [1.0, 0.0])
                     for t in texts], dtype="float32")


def test_semantic_match_outranks_a_weaker_name_hit_only_when_guarded(tmp_path):
    g = GeneralKnowledgeStore(tmp_path / "g", embedder=_two_topic_embedder)
    g.create({"title": "HIV", "category": "Sexual Education", "aliases": ["hiv"], "summary": "A virus."})
    g.create({"id": "gk-prep_pep", "title": "PrEP and PEP", "category": "Sexual Education", "aliases": ["hiv prep", "prep for hiv"],
              "summary": "Medicines that prevent hiv infection: prep before, pep after exposure."})
    found = g.lookup("is prep medicine good for hiv prevention before exposure")  # name hit: only "hiv"
    assert [m.record.id for m in found][:2] == ["gk-prep_pep", "gk-hiv"] and found[0].method == "semantic"
    assert g.lookup("hiv ki?", "hiv")[0].record.id == "gk-hiv"  # an exact name is never overridden


@pytest.mark.parametrize("msg", ["coffee grind kivabe kori", "masala grind korte hobe"])
def test_kitchen_context_blocks_adult_phrase_hits(stores, msg):
    assert _ask(stores, msg).terms_used == []
    assert _ask(stores, "grinding mane ki?").terms_used == ["term-grinding"]  # a direct question still works
