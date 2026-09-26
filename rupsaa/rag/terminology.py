"""Structured TERMINOLOGY knowledge: owner-editable term records + lookup.

Part of the existing Rupsaa Knowledge system (same owner tool, same
"retrieved at chat time, never needs retraining" contract as
knowledge/documents/), but structured instead of free text, because a
definition question ("Strip mane ki?") needs the *right entry*, not the
nearest 800-character chunk of some document.

Storage: one JSON file per term in knowledge/terminology/ (Settings
.knowledge_terminology_dir) — human-readable, diffable, editable through the
owner UI (web/knowledge.html → Terminology) or by hand. Reads always go to
disk (cheap: small files, cached by mtime), so an added/edited term is live
on the next chat message with no reindex and no restart.

Lookup is deterministic and fast (no embedding model): normalized exact
match of the router's extracted term against term/aliases, then whole-phrase
alias/example-query containment, then a conservative fuzzy match for typos.
"""

from __future__ import annotations

import difflib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

TERM_CATEGORIES = [
    "adult_terminology",
    "creator_platform",
    "dating_relationships",
    "slang",
    "general",
]
TERM_LANGUAGES = ["en", "bn", "banglish"]
_ID_RE = re.compile(r"^term-[a-z0-9_]{1,60}$")
_BN = "ঀ-৿"


class TerminologyError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize(text: str) -> str:
    """Case/punctuation/whitespace-insensitive key (Bengali-safe)."""
    text = unicodedata.normalize("NFC", text).lower()
    text = re.sub(rf"[^a-z0-9{_BN}\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _clean_list(values) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        values = re.split(r"[\n,]", values)
    out, seen = [], set()
    for v in values:
        v = str(v).strip()
        if v and normalize(v) not in seen:
            seen.add(normalize(v))
            out.append(v)
    return out


@dataclass
class TermRecord:
    id: str
    term: str
    definition: str
    category: str = "general"
    aliases: list[str] = field(default_factory=list)
    details: str = ""
    answer_guidance: str = ""
    languages: list[str] = field(default_factory=lambda: list(TERM_LANGUAGES))
    example_queries: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    enabled: bool = True
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def keys(self) -> set[str]:
        """Normalized strings that identify this term (term, aliases, and the
        slash-separated parts of the term, e.g. "Strip / Stripping")."""
        parts = [self.term, *re.split(r"\s*/\s*", self.term), *self.aliases]
        return {normalize(p) for p in parts if normalize(p)}

    def to_context(self) -> str:
        """Plain-text block for the prompt: knowledge to explain, not a script."""
        lines = [f"Term: {self.term}"]
        if self.aliases:
            lines.append(f"Also called / asked as: {', '.join(self.aliases[:8])}")
        lines.append(f"Category: {self.category}")
        lines.append(f"Definition: {self.definition}")
        if self.details:
            lines.append(f"Details: {self.details}")
        if self.answer_guidance:
            lines.append(f"Owner's guidance for answering: {self.answer_guidance}")
        return "\n".join(lines)


def validate(data: dict) -> list[str]:
    errors = []
    if not str(data.get("term", "")).strip():
        errors.append("term is required")
    if not str(data.get("definition", "")).strip():
        errors.append("definition is required")
    if data.get("category", "general") not in TERM_CATEGORIES:
        errors.append(f"unknown category {data.get('category')!r} (allowed: {TERM_CATEGORIES})")
    bad_langs = [lang for lang in data.get("languages") or [] if lang not in TERM_LANGUAGES]
    if bad_langs:
        errors.append(f"unknown language(s) {bad_langs} (allowed: {TERM_LANGUAGES})")
    for key, limit in (("term", 120), ("definition", 2000), ("details", 6000), ("answer_guidance", 2000)):
        if len(str(data.get(key) or "")) > limit:
            errors.append(f"{key} longer than {limit} characters")
    return errors


def _slug(term: str) -> str:
    ascii_only = unicodedata.normalize("NFKD", term).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "_", ascii_only.lower()).strip("_")[:50] or "term"


@dataclass
class TermMatch:
    record: object  # TermRecord, DanceRecord, ...
    score: float
    matched: str  # which key/phrase matched
    method: str  # exact | phrase | fuzzy


class TerminologyStore:
    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self._cache: dict[str, tuple[float, TermRecord]] = {}

    # --- storage ---------------------------------------------------------

    def _path(self, term_id: str) -> Path:
        if not _ID_RE.match(term_id):
            raise TerminologyError(f"invalid term id: {term_id!r}")
        return self.directory / f"{term_id}.json"

    def list(self, *, include_disabled: bool = True) -> list[TermRecord]:
        if not self.directory.exists():
            return []
        out = []
        live = set()
        for path in sorted(self.directory.glob("term-*.json")):
            live.add(path.name)
            mtime = path.stat().st_mtime
            cached = self._cache.get(path.name)
            if cached and cached[0] == mtime:
                rec = cached[1]
            else:
                data = json.loads(path.read_text(encoding="utf-8"))
                rec = TermRecord(**{k: v for k, v in data.items() if k in TermRecord.__dataclass_fields__})
                self._cache[path.name] = (mtime, rec)
            if include_disabled or rec.enabled:
                out.append(rec)
        for stale in set(self._cache) - live:
            del self._cache[stale]
        return sorted(out, key=lambda r: normalize(r.term))

    def get(self, term_id: str) -> TermRecord:
        path = self._path(term_id)
        if not path.exists():
            raise TerminologyError(f"no such term: {term_id}")
        data = json.loads(path.read_text(encoding="utf-8"))
        return TermRecord(**{k: v for k, v in data.items() if k in TermRecord.__dataclass_fields__})

    def _write(self, rec: TermRecord) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self._path(rec.id)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(asdict(rec), ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    def _check_conflicts(self, rec: TermRecord) -> None:
        mine = rec.keys()
        for other in self.list():
            if other.id == rec.id:
                continue
            clash = mine & other.keys()
            if clash:
                raise TerminologyError(f"term/alias {sorted(clash)[0]!r} already used by {other.id} ({other.term})")

    def create(self, data: dict) -> TermRecord:
        errors = validate(data)
        if errors:
            raise TerminologyError("; ".join(errors))
        base = f"term-{_slug(data['term'])}"
        term_id, n = base, 2
        while self._path(term_id).exists():
            term_id, n = f"{base}_{n}", n + 1
        rec = TermRecord(
            id=term_id,
            term=data["term"].strip(),
            definition=data["definition"].strip(),
            category=data.get("category") or "general",
            aliases=_clean_list(data.get("aliases")),
            details=(data.get("details") or "").strip(),
            answer_guidance=(data.get("answer_guidance") or "").strip(),
            languages=_clean_list(data.get("languages")) or list(TERM_LANGUAGES),
            example_queries=_clean_list(data.get("example_queries")),
            tags=_clean_list(data.get("tags")),
            enabled=bool(data.get("enabled", True)),
        )
        self._check_conflicts(rec)
        self._write(rec)
        return rec

    def update(self, term_id: str, changes: dict) -> TermRecord:
        rec = self.get(term_id)
        merged = {**asdict(rec), **{k: v for k, v in changes.items() if v is not None}}
        errors = validate(merged)
        if errors:
            raise TerminologyError("; ".join(errors))
        for key in ("aliases", "example_queries", "tags", "languages"):
            merged[key] = _clean_list(merged[key])
        for key in ("term", "definition", "details", "answer_guidance"):
            merged[key] = (merged[key] or "").strip()
        merged["id"], merged["created_at"], merged["updated_at"] = rec.id, rec.created_at, _now()
        new = TermRecord(**merged)
        self._check_conflicts(new)
        self._write(new)
        return new

    def delete(self, term_id: str, *, confirm: bool) -> None:
        if not confirm:
            raise TerminologyError("deletion requires confirm=true")
        path = self._path(term_id)
        if not path.exists():
            raise TerminologyError(f"no such term: {term_id}")
        path.unlink()

    def search(self, query: str) -> list[TermRecord]:
        """Owner-UI search over term, aliases, tags, definition."""
        q = normalize(query)
        if not q:
            return self.list()
        return [
            r for r in self.list()
            if q in normalize(" ".join([r.term, *r.aliases, *r.tags, r.definition, r.category]))
        ]

    # --- chat-time lookup ------------------------------------------------

    def lookup(self, message: str, term_candidate: str | None = None, *, limit: int = 2) -> list[TermMatch]:
        """Terms a chat message is asking about. `term_candidate` is the
        phrase the router extracted from a definition question ("Strip" from
        "Strip mane ki?"); without it, whole-phrase alias containment is used
        (e.g. a knowledge question that mentions a defined term)."""
        return match_records(self.list(include_disabled=False), message, term_candidate, limit=limit)


def match_records(records: list, message: str, candidate: str | None = None, *, limit: int = 2) -> list[TermMatch]:
    """Shared chat-time matcher for owner knowledge records (terminology, dance, ...).

    A record needs `.id`, `.keys()` (normalized names/aliases) and optionally
    `.example_queries`. Order of evidence: exact key == router candidate,
    whole-phrase key containment, then conservative typo matching (never on real
    English words, same first letter, ratio >= 0.85 or one edit)."""
    if not records:
        return []
    matches: dict[str, TermMatch] = {}

    def add(rec, score: float, matched: str, method: str) -> None:
        if rec.id not in matches or matches[rec.id].score < score:
            matches[rec.id] = TermMatch(rec, score, matched, method)

    cand = normalize(candidate) if candidate else ""
    msg = f" {normalize(message)} "
    for rec in records:
        keys = rec.keys()
        if cand and cand in keys:
            add(rec, 1.0, cand, "exact")
            continue
        if cand and any(normalize(q) == normalize(message) for q in getattr(rec, "example_queries", []) or []):
            add(rec, 0.98, message, "exact")
            continue
        phrase_hits = [k for k in keys if len(k) >= 3 and f" {k} " in msg]
        if phrase_hits:
            best = max(phrase_hits, key=len)
            # A term mentioned inside a definition question for something else scores lower.
            add(rec, 0.9 if not cand else 0.75, best, "phrase")
            continue
        if cand and len(cand) >= 4 and not _all_known_words(cand):
            # Typos rarely change the first letter ("tripping" is not "stripping").
            same_start = [k for k in keys if k[:1] == cand[:1]]
            ratio = max((difflib.SequenceMatcher(None, cand, k).ratio() for k in same_start), default=0.0)
            if ratio >= 0.85:
                add(rec, round(ratio * 0.9, 3), cand, "fuzzy")
            # One edit on a 4-letter word is too loose ("hake" is not "haka"); needs >= 5 letters.
            elif " " not in cand and len(cand) >= 5 and any(len(k) >= 5 and _one_edit_apart(cand, k) for k in same_start):
                add(rec, 0.75, cand, "fuzzy")
    if cand and any(m.method == "exact" for m in matches.values()):
        # "lip biting ki?" is about Lip Biting — not also about the term whose alias is "biting".
        matches = {i: m for i, m in matches.items()
                   if not (m.method == "phrase" and m.matched in cand and m.matched != cand)}
    return sorted(matches.values(), key=lambda m: -m.score)[:limit]


_KNOWN_WORDS: frozenset[str] | None = None


def _all_known_words(phrase: str) -> bool:
    """True if every word of `phrase` is a common real English word (rupsaa/rag/known_words.txt):
    such a phrase is not a typo, so it never fuzzy-matches a term ("content" !~ "consent")."""
    global _KNOWN_WORDS
    if _KNOWN_WORDS is None:
        path = Path(__file__).with_name("known_words.txt")
        _KNOWN_WORDS = frozenset(
            line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line and not line.startswith("#")
        ) if path.exists() else frozenset()
    words = phrase.split()
    return bool(words) and all(w in _KNOWN_WORDS for w in words)


def _one_edit_apart(a: str, b: str) -> bool:
    """Damerau distance <= 1 (one substitution, insertion, deletion or adjacent swap: "stirp" ~ "strip")."""
    if a == b or abs(len(a) - len(b)) > 1:
        return a == b
    i = 0
    while i < min(len(a), len(b)) and a[i] == b[i]:
        i += 1
    if len(a) == len(b):
        return a[i + 1:] == b[i + 1:] or (a[i:i + 2] == b[i:i + 2][::-1] and a[i + 2:] == b[i + 2:])
    return (a[i + 1:] == b[i:]) if len(a) > len(b) else (a[i:] == b[i + 1:])


def format_terminology_context(matches: list[TermMatch]) -> str | None:
    if not matches:
        return None
    return "\n\n".join(m.record.to_context() for m in matches)
