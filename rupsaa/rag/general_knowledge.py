"""General Knowledge — owner-curated records for any topic (beauty, fashion, relationships, technology, …).

Same contract as the terminology and dance stores: one human-readable JSON file per record in
knowledge/general/ (Settings.knowledge_general_dir), validated, atomic writes, path-traversal-safe ids, duplicate
title/alias protection, mtime-cached reads — an added or edited record is live on the next chat message without
restarting the model. Before an update or delete the previous version is copied to knowledge/general/.history/.

One concept = one record for every language: English, Banglish and Bengali names are aliases of the same record
("foreplay", "fore play", "ফোরপ্লে"). Knowledge is WHAT Rupsaa knows; the model decides HOW she says it.

Retrieval (lookup): exact title/alias (router candidate) → whole-phrase alias mention → semantic similarity with
multilingual-e5-small, accepted only above a strict score AND with a shared content word, so weak or unrelated
matches are rejected. Web results never enter this store; only the owner (Knowledge Manager, Teach page or
authenticated in-chat teaching) writes here.
"""

from __future__ import annotations

import json
import re
import shutil
import threading
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path

from rupsaa.rag.terminology import TermMatch, _clean_list, _now, match_records, normalize

CATEGORIES = ["Relationships", "Dating", "Sexual Education", "Adult Terminology", "Health & Hygiene", "Beauty", "Fashion", "Fitness",
              "Entertainment", "Creator Platforms", "Social Media", "Technology", "Indian Culture", "Food / Recipes",
              "Lifestyle", "General Education", "Custom"]
LANGUAGES = ["en", "bn", "banglish"]
# Provenance: how a record entered the curated store. Live web results are never a source type on their own —
# "owner_verified_web" means the owner reviewed web evidence and explicitly approved the record.
SOURCE_TYPES = ["owner", "owner_teaching", "owner_verified_web", "import", "test"]
MAX_SOURCES = 10
LIST_FIELDS = ("aliases", "key_points", "steps", "do", "dont", "languages", "tags")
TEXT_FIELDS = ("title", "category", "subcategory", "summary", "description", "answer_guidance", "source")
_TEXT_LIMITS = {"title": 120, "subcategory": 120, "summary": 1000, "description": 6000, "answer_guidance": 2000,
                "source": 300}
_LIST_LIMITS = {"aliases": (30, 120), "key_points": (20, 400), "steps": (30, 400), "do": (15, 300), "dont": (15, 300),
                "tags": (20, 60), "languages": (3, 10)}
_ID_RE = re.compile(r"^gk-[a-z0-9_]{1,60}$")
_BN = "ঀ-৿"
# Semantic retrieval acceptance (multilingual-e5-small cosine; e5 scores are compressed, unrelated ≈ 0.75–0.80).
SEMANTIC_MIN_SCORE = 0.85
_STOPWORDS = {"ki", "kii", "mane", "what", "is", "the", "a", "an", "of", "how", "to", "kivabe", "keno", "why", "er",
              "ta", "ti", "e", "te", "bolo", "kore", "koro", "and", "ar", "o", "about", "somporke", "কী", "কি", "মানে"}


class KnowledgeError(ValueError):
    pass


@dataclass
class KnowledgeRecord:
    id: str
    title: str
    category: str = "Custom"
    subcategory: str = ""
    aliases: list[str] = field(default_factory=list)
    summary: str = ""
    description: str = ""
    key_points: list[str] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    do: list[str] = field(default_factory=list)
    dont: list[str] = field(default_factory=list)
    answer_guidance: str = ""
    languages: list[str] = field(default_factory=lambda: list(LANGUAGES))
    tags: list[str] = field(default_factory=list)
    enabled: bool = True
    source: str = ""  # free-text note on who/what supplied it ("owner via chat teaching", import file name)
    source_type: str = "owner"  # one of SOURCE_TYPES
    sources: list[dict] = field(default_factory=list)  # [{title, url, domain, retrieved_at}] for web-assisted records
    verified: bool = False  # owner checked it against sources
    approved_by: str = "owner"
    revision: int = 1
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def keys(self) -> set[str]:
        return {normalize(x) for x in [self.title, *self.aliases] if normalize(x)}

    def search_text(self) -> str:
        return " | ".join(x for x in [self.title, ", ".join(self.aliases), self.summary, " ".join(self.key_points),
                                      self.description[:400]] if x)

    def to_context(self) -> str:
        """Prompt block: only filled fields."""
        lines = [f"Topic: {self.title}" + (f" ({self.category}{' / ' + self.subcategory if self.subcategory else ''})")]
        if self.aliases:
            lines.append(f"Also called / asked as: {', '.join(self.aliases[:8])}")
        if self.summary:
            lines.append(f"Summary: {self.summary}")
        if self.description:
            lines.append(f"Details: {self.description}")
        for label, items in (("Key points", self.key_points), ("Steps", self.steps), ("Do", self.do),
                             ("Don't", self.dont)):
            if items:
                lines.append(f"{label}:\n" + "\n".join(f"- {x}" for x in items))
        if self.answer_guidance:
            lines.append(f"Owner's guidance for answering: {self.answer_guidance}")
        return "\n".join(lines)


def validate(data: dict) -> list[str]:
    errors = []
    if not str(data.get("title", "")).strip():
        errors.append("title is required")
    if not any(str(data.get(k) or "").strip() for k in ("summary", "description")) and not data.get("key_points"):
        errors.append("give at least a summary, a description or key points")
    if data.get("category") and data["category"] not in CATEGORIES:
        errors.append(f"unknown category {data['category']!r} (allowed: {', '.join(CATEGORIES)})")
    if data.get("source_type") and data["source_type"] not in SOURCE_TYPES:
        errors.append(f"unknown source_type {data['source_type']!r} (allowed: {SOURCE_TYPES})")
    errors += _source_errors(data.get("sources") or [])
    bad = [x for x in data.get("languages") or [] if x not in LANGUAGES]
    if bad:
        errors.append(f"unknown language(s) {bad} (allowed: {LANGUAGES})")
    for key, limit in _TEXT_LIMITS.items():
        if len(str(data.get(key) or "")) > limit:
            errors.append(f"{key} longer than {limit} characters")
    for key, (n, each) in _LIST_LIMITS.items():
        items = data.get(key) or []
        if len(items) > n:
            errors.append(f"too many {key} (max {n})")
        if any(len(str(x)) > each for x in items):
            errors.append(f"an item in {key} is longer than {each} characters")
    return errors


def _source_errors(sources) -> list[str]:
    if not isinstance(sources, list) or len(sources) > MAX_SOURCES:
        return [f"sources must be a list of at most {MAX_SOURCES} items"]
    from rupsaa.rag.web_search import safe_url

    for src in sources:
        if not isinstance(src, dict) or not safe_url(str(src.get("url") or "")):
            return ["each source needs a public http(s) url"]
    return []


def _clean_sources(sources) -> list[dict]:
    out = []
    for src in sources or []:
        url = str(src.get("url") or "").strip()[:500]
        out.append({"title": str(src.get("title") or "").strip()[:200], "url": url,
                    "domain": str(src.get("domain") or "").strip()[:120] or url.split("/")[2].lower(),
                    "retrieved_at": str(src.get("retrieved_at") or "").strip()[:40]})
    return out


def _slug(text: str) -> str:
    ascii_only = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "_", ascii_only.lower()).strip("_")[:50] or "topic"


def clean(data: dict) -> dict:
    out = {k: str(data.get(k) or "").strip() for k in TEXT_FIELDS}
    out["category"] = out["category"] or "Custom"
    for k in LIST_FIELDS:
        vals = data.get(k)
        if isinstance(vals, str) and k != "aliases" and k != "tags" and k != "languages":
            vals = [v.strip() for v in vals.split("\n")]
        out[k] = _clean_list(vals)
    out["languages"] = out["languages"] or list(LANGUAGES)
    out["enabled"] = bool(data.get("enabled", True))
    out["source_type"] = str(data.get("source_type") or "owner")
    out["sources"] = _clean_sources(data.get("sources"))
    out["verified"] = bool(data.get("verified", False))
    out["approved_by"] = str(data.get("approved_by") or "owner").strip()[:60]
    return out


class GeneralKnowledgeStore:
    def __init__(self, directory: Path, embedder=None):
        self.directory = Path(directory)
        self._cache: dict[str, tuple[float, KnowledgeRecord]] = {}
        self._lock = threading.RLock()
        self._embedder = embedder  # (texts, is_query) -> np.ndarray; default: multilingual-e5-small
        self._index_sig = None
        self._index = None

    # --- storage ---------------------------------------------------------------------------------------------
    def _path(self, rid: str) -> Path:
        if not _ID_RE.match(rid or ""):
            raise KnowledgeError(f"invalid knowledge id: {rid!r}")
        return self.directory / f"{rid}.json"

    @staticmethod
    def _from_json(data: dict) -> KnowledgeRecord:
        return KnowledgeRecord(**{k: v for k, v in data.items() if k in KnowledgeRecord.__dataclass_fields__})

    def list(self, *, include_disabled: bool = True) -> list[KnowledgeRecord]:
        if not self.directory.exists():
            return []
        out, live = [], set()
        for path in sorted(self.directory.glob("gk-*.json")):
            live.add(path.name)
            mtime = path.stat().st_mtime_ns
            cached = self._cache.get(path.name)
            if cached and cached[0] == mtime:
                rec = cached[1]
            else:
                rec = self._from_json(json.loads(path.read_text(encoding="utf-8")))
                self._cache[path.name] = (mtime, rec)
            if include_disabled or rec.enabled:
                out.append(rec)
        for stale in set(self._cache) - live:
            del self._cache[stale]
        return sorted(out, key=lambda r: normalize(r.title))

    def get(self, rid: str) -> KnowledgeRecord:
        p = self._path(rid)
        if not p.exists():
            raise KnowledgeError(f"no such knowledge record: {rid}")
        return self._from_json(json.loads(p.read_text(encoding="utf-8")))

    def _write(self, rec: KnowledgeRecord) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        p = self._path(rec.id)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(asdict(rec), ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(p)

    def _backup(self, rid: str) -> None:
        p = self._path(rid)
        if p.exists():
            hist = self.directory / ".history"
            hist.mkdir(parents=True, exist_ok=True)
            stamp = _now().replace(":", "").replace("-", "").split(".")[0]
            shutil.copy2(p, hist / f"{rid}.{stamp}.json")

    def _conflicts(self, rec: KnowledgeRecord) -> None:
        mine = rec.keys()
        for other in self.list():
            if other.id != rec.id and mine & other.keys():
                raise KnowledgeError(f"title/alias {sorted(mine & other.keys())[0]!r} already used by {other.id} ({other.title})")

    def create(self, data: dict) -> KnowledgeRecord:
        errors = validate(data)
        if errors:
            raise KnowledgeError("; ".join(errors))
        with self._lock:
            c = clean(data)
            base = f"gk-{_slug(c['title'])}"
            rid, n = base, 2
            while self._path(rid).exists():
                rid, n = f"{base}_{n}", n + 1
            rec = KnowledgeRecord(id=rid, **c)
            self._conflicts(rec)
            self._write(rec)
            return rec

    def update(self, rid: str, changes: dict) -> KnowledgeRecord:
        with self._lock:
            rec = self.get(rid)
            merged = {**asdict(rec), **{k: v for k, v in changes.items() if v is not None}}
            errors = validate(merged)
            if errors:
                raise KnowledgeError("; ".join(errors))
            new = KnowledgeRecord(id=rec.id, created_at=rec.created_at, updated_at=_now(), revision=rec.revision + 1,
                                  **clean(merged))
            self._conflicts(new)
            self._backup(rid)
            self._write(new)
            return new

    def delete(self, rid: str, *, confirm: bool) -> None:
        if not confirm:
            raise KnowledgeError("deletion requires confirm=true")
        with self._lock:
            p = self._path(rid)
            if not p.exists():
                raise KnowledgeError(f"no such knowledge record: {rid}")
            self._backup(rid)
            p.unlink()

    def search(self, query: str = "", category: str | None = None, tag: str | None = None) -> list[KnowledgeRecord]:
        q = normalize(query or "")
        out = []
        for r in self.list():
            if category and r.category != category:
                continue
            if tag and normalize(tag) not in {normalize(t) for t in r.tags}:
                continue
            if q and q not in normalize(" ".join([r.title, *r.aliases, *r.tags, r.summary, r.description])):
                continue
            out.append(r)
        return out

    # --- retrieval -------------------------------------------------------------------------------------------
    def _embed(self, texts: list[str], is_query: bool):
        if self._embedder is not None:
            return self._embedder(texts, is_query)
        from rupsaa.rag.embeddings import embed_passages, embed_query
        import numpy as np
        return np.stack([embed_query(t) for t in texts]) if is_query else embed_passages(texts)

    def _semantic_index(self, records: list[KnowledgeRecord]):
        sig = tuple((r.id, r.updated_at) for r in records)
        if sig != self._index_sig:
            self._index = self._embed([r.search_text() for r in records], False) if records else None
            self._index_sig = sig
        return self._index

    def lookup(self, message: str, candidate: str | None = None, *, limit: int = 2, semantic: bool = True) -> list[TermMatch]:
        records = self.list(include_disabled=False)
        if not records:
            return []
        matches = match_records(records, message, candidate, limit=limit)
        if matches or not semantic:
            return matches
        # Semantic fallback: the question must share a content word with the record (rejects look-alike topics).
        with self._lock:
            index = self._semantic_index(records)
        q = self._embed([candidate or message], True)[0]
        scores = index @ q
        words = _content_words(message)
        out = []
        for i in scores.argsort()[::-1][:limit]:
            rec, score = records[i], float(scores[i])
            if score >= SEMANTIC_MIN_SCORE and _names_covered(words, rec):
                out.append(TermMatch(rec, round(score, 3), rec.title, "semantic"))
        return out


def _content_words(text: str) -> set[str]:
    return {w for w in re.findall(rf"[a-z0-9{_BN}]+", normalize(text)) if len(w) > 2 and w not in _STOPWORDS}


def _same_word(a: str, b: str) -> bool:
    return a == b or (min(len(a), len(b)) >= 5 and a[:5] == b[:5])  # straight ~ straightening


def _names_covered(words: set[str], rec: KnowledgeRecord) -> bool:
    """At least 60% of the title's (or one alias's) content words appear in the question — 'hair color' is not
    'Hair Straightening' even though both mention hair."""
    for name in [rec.title, *rec.aliases]:
        need = _content_words(name)
        if need and sum(any(_same_word(n, w) for w in words) for n in need) / len(need) >= 0.6:
            return True
    return False


def format_general_context(matches: list) -> str | None:
    if not matches:
        return None
    return "\n\n".join(m.record.to_context() for m in matches)
