"""Adult / sexual-education trusted source routing and source-type labelling. Fake providers only (no network)."""

import pytest

from rupsaa.conversation import internet_policy as ip
from rupsaa.rag import source_policy as sp
from rupsaa.rag import web_search as ws
from tests.conftest_rupsaa_fakes import FakeProvider, chat, make_service, new_uid


def _r(domain, title="t"):
    return ws.WebResult(title=title, url=f"https://{domain}/page", extract=f"{title} from {domain}", provider="fake")


MIXED = [_r("www.reddit.com", "community thread"), _r("archiveofourown.org", "a story"), _r("en.wikipedia.org", "wiki"),
         _r("www.plannedparenthood.org", "pp"), _r("goaskalice.columbia.edu", "alice"), _r("www.scarleteen.com", "st")]


@pytest.mark.parametrize("domain,cls", [("www.scarleteen.com", sp.HEALTH_EDU), ("plannedparenthood.org", sp.HEALTH_EDU),
                                        ("goaskalice.columbia.edu", sp.EDU_QA), ("bn.wikipedia.org", sp.REFERENCE),
                                        ("old.reddit.com", sp.COMMUNITY), ("www.literotica.com", sp.FICTION),
                                        ("archiveofourown.org", sp.FICTION), ("notreddit.com", sp.OTHER),
                                        ("evilscarleteen.com", sp.OTHER)])
def test_domain_classes(domain, cls):
    assert sp.classify_domain(domain) == cls


@pytest.mark.parametrize("msg,topic", [("Condom kivabe use korte hoy?", "health"), ("STI test kokhon korbo?", "health"),
                                       ("What is a safe word?", "consent_safety"), ("Aftercare mane ki?", "consent_safety"),
                                       ("Shibari ki?", "bdsm"), ("What does DTF stand for?", "slang"),
                                       ("Foreplay mane ki?", "education"), ("Taj Mahal kothay?", None),
                                       ("Latest iPhone price koto?", None), ("Python er latest version ki?", None)])
def test_adult_topic_purpose(msg, topic):
    assert sp.adult_topic(msg) == topic


def test_health_and_education_prefer_educational_sources_and_drop_fiction():
    for topic in ("health", "education", "consent_safety"):
        ranked = sp.rank(list(MIXED), topic)
        classes = [r.source_class for r in ranked]
        assert sp.FICTION not in classes  # erotic fiction is never a factual source
        assert classes[0] == sp.HEALTH_EDU and classes[-1] == sp.COMMUNITY  # Reddit never outranks health sources


def test_community_supplements_slang_and_bdsm_uses_reference():
    slang = [r.source_class for r in sp.rank(list(MIXED) + [_r("example.org")], "slang")]
    assert slang.index(sp.REFERENCE) < slang.index(sp.COMMUNITY) < slang.index(sp.OTHER)  # usable, after reference
    bdsm = [r.source_class for r in sp.rank(list(MIXED), "bdsm")]
    assert bdsm.index(sp.REFERENCE) < bdsm.index(sp.EDU_QA) < bdsm.index(sp.COMMUNITY)


def test_non_adult_order_untouched_and_community_labelled_in_context():
    ranked = sp.rank([_r("www.reddit.com"), _r("example.org")], None)
    assert [r.domain for r in ranked] == ["www.reddit.com", "example.org"]
    ctx = ws.format_web_context(ranked)
    assert "community discussion" in ctx and "never as medical or factual authority" in ctx


class SiteAwareProvider(FakeProvider):
    supports_site_filter = True


def test_site_restricted_query_first_on_capable_providers():
    p = SiteAwareProvider(results=[_r("www.scarleteen.com")])
    ws.search_with_policy(p, "condom use", topic="health")
    assert "site:plannedparenthood.org" in p.queries[0][0] and p.queries[1][0] == "condom use"
    q = FakeProvider(results=[_r("www.reddit.com")])
    ws.search_with_policy(q, "condom use", topic="health")
    assert q.queries == [("condom use", False)]  # no site: syntax for providers that don't support it


def test_local_curated_knowledge_comes_first(tmp_path, monkeypatch):
    svc, uid = make_service(tmp_path, monkeypatch), new_uid()
    svc.general.create({"title": "Foreplay", "category": "Sexual Education", "aliases": ["fore play", "ফোরপ্লে"],
                        "summary": "Intimate touching and closeness before sex."})
    svc.set_internet_mode(uid, None, ip.ALLOW)
    r = chat(svc, "Foreplay mane ki?", user_id=uid)
    assert svc._web_provider.queries == [] and r["terms_used"]  # Terminology/GK answer it: no web
    assert r["source_types"] == ["CURATED_RAG"]
    svc.general.create({"title": "Love Language", "category": "Relationships", "aliases": ["love languages"],
                        "summary": "How a person prefers to give and receive affection."})
    r = chat(svc, "Love language ki?", user_id=uid)
    assert r["terms_used"] == ["gk-love_language"] and svc._web_provider.queries == []


def test_web_answers_carry_source_class_and_type(tmp_path, monkeypatch):
    svc = make_service(tmp_path, monkeypatch, provider=FakeProvider(results=list(MIXED)))
    uid = new_uid()
    svc.set_internet_mode(uid, None, ip.ALLOW)
    r = chat(svc, "STI test kokhon korbo?", user_id=uid)
    assert r["source_types"] == ["WEB"]
    assert [s["source_class"] for s in r["web_sources"]][0] == sp.HEALTH_EDU
    assert all("archiveofourown" not in s["url"] for s in r["web_sources"])
    assert svc.general.list() == []  # web evidence is never stored as curated knowledge


def test_ask_mode_asks_before_adult_health_lookup(tmp_path, monkeypatch):
    svc, uid = make_service(tmp_path, monkeypatch), new_uid()
    r = chat(svc, "Ami ki STI test korbo? kokhon korte hoy?", user_id=uid)
    assert r["internet_permission_requested"] and svc._web_provider.queries == []


def test_casual_chat_is_model_knowledge_only(tmp_path, monkeypatch):
    svc = make_service(tmp_path, monkeypatch)
    r = chat(svc, "Hi Rupsaa")
    assert r["source_types"] == ["MODEL_GENERAL_KNOWLEDGE"] and svc._web_provider.queries == []
