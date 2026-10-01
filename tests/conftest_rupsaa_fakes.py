"""Shared fakes for the knowledge / memory / internet / teaching suites (no GPU, no network)."""

import uuid

from rupsaa.rag import web_search as ws


class FakeEngine:
    """Records every call; `complete` returns a canned JSON draft or raises."""

    def __init__(self, draft_json: str | None = None):
        self.calls, self.completions, self.draft_json = [], [], draft_json

    def chat(self, **kw):
        from rupsaa.model.inference import ChatResult
        self.calls.append(kw)
        return ChatResult(text="ok", blocked=False)

    def complete(self, system, user, **kw):
        self.completions.append((system, user))
        if self.draft_json is None:
            raise RuntimeError("no structurer")
        return self.draft_json


class FakeProvider(ws.WebSearchProvider):
    name, fresh_capable = "fake", True

    def __init__(self, results=None):
        super().__init__()
        self.queries, self.results = [], results

    def search(self, query, fresh=False):
        self.queries.append((query, fresh))
        if self.results is not None:
            return self.results
        return [ws.WebResult(title=f"{query} result", url="https://example.org/a", extract=f"Facts about {query}.",
                             provider="fake")]


def new_uid() -> str:
    return str(uuid.uuid4())


def make_service(tmp_path, monkeypatch, *, secret="", draft_json=None, provider=None):
    from api.services import RupsaaService
    from rupsaa.config import get_settings

    monkeypatch.setenv("RUPSAA_USER_MEMORY_DIR", str(tmp_path / "mem"))
    monkeypatch.setenv("RUPSAA_USER_PREFS_DIR", str(tmp_path / "prefs"))
    monkeypatch.setenv("RUPSAA_TEACH_SECRET", secret)
    get_settings.cache_clear()
    svc = RupsaaService()
    svc._engine = FakeEngine(draft_json)
    svc._rag_pipeline = type("NoDocs", (), {"query": lambda self, q, strict=False: (None, [])})()
    svc._web_provider = provider if provider is not None else FakeProvider()
    svc._web_provider_loaded = True
    from rupsaa.rag.general_knowledge import GeneralKnowledgeStore
    svc._general = GeneralKnowledgeStore(tmp_path / "general", embedder=keyword_embedder)
    return svc


def keyword_embedder(texts, is_query):
    """Deterministic bag-of-words 'embedding' for tests (cosine of word overlap)."""
    import re

    import numpy as np
    vocab = {}
    vecs = []
    for t in texts:
        words = re.findall(r"\w+", t.lower())
        vecs.append(words)
    dim = 512
    out = np.zeros((len(texts), dim), dtype="float32")
    for i, words in enumerate(vecs):
        for w in words:
            out[i, hash(w) % dim] += 1.0
        n = np.linalg.norm(out[i]) or 1.0
        out[i] /= n
    return out


def chat(svc, msg, cid=None, **kw):
    return svc.chat(message=msg, conversation_id=cid, use_rag=False, temperature=None, top_p=None,
                    max_new_tokens=None, **kw)
