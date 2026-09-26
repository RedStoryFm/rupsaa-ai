"""Structured DANCE knowledge: owner-editable dance-style records + chat-time lookup.

Same contract as the terminology store (rupsaa/rag/terminology.py): one JSON
file per dance in knowledge/dance/ (Settings.knowledge_dance_dir), edited through
the owner UI (web/knowledge.html → Dance) or imported from CSV/XLSX/JSON
(rupsaa/rag/dance_import.py, scripts/import_dance_knowledge.py). Reads go to
disk (mtime-cached), so an added or edited dance is live on the next chat
message — no reindex, no retraining.

Dance facts live HERE, not in the LoRA: the model is only taught how to explain
retrieved dance knowledge naturally. The prompt block contains only the fields
the owner filled in; empty step/technique fields are omitted, and the model is
told not to invent what isn't listed.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path

from rupsaa.rag.terminology import (
    TERM_LANGUAGES,
    TermMatch,
    _all_known_words,
    _clean_list,
    _now,
    match_records,
    normalize,
)

DANCE_LANGUAGES = list(TERM_LANGUAGES)  # en, bn, banglish
# Dance names that are also everyday words outside the Qwen vocabulary list ("polka dots", "hula hoop").
EVERYDAY_WORD_NAMES = {"polka", "hula", "salsa", "tango", "samba", "rumba", "mambo", "waltz", "popping", "locking",
                       "breaking", "krump", "house dance", "zouk", "garba"}
# Words that show a message is about dancing (normalized, whole words).
DANCE_CUES = ("dance", "dances", "dancing", "dancer", "dancers", "dance form", "nach", "nache", "nacher", "nritto",
              "nritya", "moves", "choreography", "নাচ", "নাচের", "নৃত্য", "ডান্স")
_ID_RE = re.compile(r"^dance-[a-z0-9_]{1,60}$")

# Optional, future fields: kept empty unless the owner supplies them — never generated.
FUTURE_FIELDS = ("difficulty", "prerequisites", "warmup", "basic_steps", "step_sequence", "common_mistakes", "practice_tips")
_FIELD_LABELS = {
    "origin": "Origin",
    "category": "Category",
    "description": "Description",
    "key_movements": "Key movements",
    "difficulty": "Difficulty",
    "prerequisites": "Prerequisites",
    "warmup": "Warm-up",
    "basic_steps": "Basic steps",
    "step_sequence": "Step sequence",
    "common_mistakes": "Common mistakes",
    "practice_tips": "Practice tips",
}
_TEXT_LIMITS = {"name": 120, "origin": 1000, "category": 120, "description": 4000, "key_movements": 4000,
                "answer_guidance": 2000, "difficulty": 200, "prerequisites": 2000, "warmup": 4000,
                "basic_steps": 6000, "step_sequence": 6000, "common_mistakes": 4000, "practice_tips": 4000}


class DanceError(ValueError):
    pass


@dataclass
class DanceRecord:
    id: str
    name: str
    description: str
    origin: str = ""
    category: str = ""
    aliases: list[str] = field(default_factory=list)
    key_movements: str = ""
    answer_guidance: str = ""
    languages: list[str] = field(default_factory=lambda: list(DANCE_LANGUAGES))
    tags: list[str] = field(default_factory=list)
    enabled: bool = True
    # optional future fields (owner-supplied only)
    difficulty: str = ""
    prerequisites: str = ""
    warmup: str = ""
    basic_steps: str = ""
    step_sequence: str = ""
    common_mistakes: str = ""
    practice_tips: str = ""
    source: str = ""  # where the record came from (e.g. "owner list 2026-09")
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def keys(self) -> set[str]:
        """Normalized names: the name, its "/"-separated and parenthesised parts, and aliases
        ("Breaking (Breakdance)" -> breaking, breakdance)."""
        parts = [self.name, *re.split(r"\s*/\s*", self.name), *self.aliases]
        paren = re.findall(r"\(([^)]*)\)", self.name)
        parts += paren + [re.sub(r"\s*\([^)]*\)", "", self.name)]
        return {normalize(p) for p in parts if normalize(p)}

    def to_context(self) -> str:
        """Plain-text block for the prompt: only the fields the owner filled in."""
        lines = [f"Dance: {self.name}"]
        if self.aliases:
            lines.append(f"Also called / asked as: {', '.join(self.aliases[:8])}")
        for key in ("origin", "category", "description", "key_movements", *FUTURE_FIELDS):
            value = (getattr(self, key) or "").strip()
            if value:
                lines.append(f"{_FIELD_LABELS[key]}: {value}")
        missing_steps = not any((getattr(self, k) or "").strip() for k in ("basic_steps", "step_sequence"))
        if missing_steps:
            lines.append("Step-by-step instructions: not in the owner's records.")
        if self.answer_guidance:
            lines.append(f"Owner's guidance for answering: {self.answer_guidance}")
        return "\n".join(lines)


def validate(data: dict) -> list[str]:
    errors = []
    if not str(data.get("name", "")).strip():
        errors.append("name is required")
    if not str(data.get("description", "")).strip():
        errors.append("description is required")
    bad = [lang for lang in data.get("languages") or [] if lang not in DANCE_LANGUAGES]
    if bad:
        errors.append(f"unknown language(s) {bad} (allowed: {DANCE_LANGUAGES})")
    for key, limit in _TEXT_LIMITS.items():
        if len(str(data.get(key) or "")) > limit:
            errors.append(f"{key} longer than {limit} characters")
    return errors


def _slug(name: str) -> str:
    ascii_only = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "_", ascii_only.lower()).strip("_")[:50] or "dance"


_TEXT_FIELDS = ("name", "description", "origin", "category", "key_movements", "answer_guidance", "source", *FUTURE_FIELDS)
_LIST_FIELDS = ("aliases", "languages", "tags")


def _clean(data: dict) -> dict:
    out = {k: (str(data.get(k) or "")).strip() for k in _TEXT_FIELDS}
    out["aliases"] = _clean_list(data.get("aliases"))
    out["tags"] = _clean_list(data.get("tags"))
    out["languages"] = _clean_list(data.get("languages")) or list(DANCE_LANGUAGES)
    out["enabled"] = bool(data.get("enabled", True))
    return out


class DanceStore:
    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self._cache: dict[str, tuple[float, DanceRecord]] = {}

    def _path(self, dance_id: str) -> Path:
        if not _ID_RE.match(dance_id):
            raise DanceError(f"invalid dance id: {dance_id!r}")
        return self.directory / f"{dance_id}.json"

    @staticmethod
    def _from_json(data: dict) -> DanceRecord:
        return DanceRecord(**{k: v for k, v in data.items() if k in DanceRecord.__dataclass_fields__})

    def list(self, *, include_disabled: bool = True) -> list[DanceRecord]:
        if not self.directory.exists():
            return []
        out, live = [], set()
        for path in sorted(self.directory.glob("dance-*.json")):
            live.add(path.name)
            mtime = path.stat().st_mtime
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
        return sorted(out, key=lambda r: normalize(r.name))

    def get(self, dance_id: str) -> DanceRecord:
        path = self._path(dance_id)
        if not path.exists():
            raise DanceError(f"no such dance: {dance_id}")
        return self._from_json(json.loads(path.read_text(encoding="utf-8")))

    def _write(self, rec: DanceRecord) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self._path(rec.id)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(asdict(rec), ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    def _check_conflicts(self, rec: DanceRecord) -> None:
        mine = rec.keys()
        for other in self.list():
            if other.id != rec.id and mine & other.keys():
                raise DanceError(f"name/alias {sorted(mine & other.keys())[0]!r} already used by {other.id} ({other.name})")

    def create(self, data: dict) -> DanceRecord:
        errors = validate(data)
        if errors:
            raise DanceError("; ".join(errors))
        clean = _clean(data)
        base = f"dance-{_slug(clean['name'])}"
        dance_id, n = base, 2
        while self._path(dance_id).exists():
            dance_id, n = f"{base}_{n}", n + 1
        rec = DanceRecord(id=dance_id, **clean)
        self._check_conflicts(rec)
        self._write(rec)
        return rec

    def update(self, dance_id: str, changes: dict) -> DanceRecord:
        rec = self.get(dance_id)
        merged = {**asdict(rec), **{k: v for k, v in changes.items() if v is not None}}
        errors = validate(merged)
        if errors:
            raise DanceError("; ".join(errors))
        new = DanceRecord(id=rec.id, created_at=rec.created_at, updated_at=_now(), **_clean(merged))
        self._check_conflicts(new)
        self._write(new)
        return new

    def delete(self, dance_id: str, *, confirm: bool) -> None:
        if not confirm:
            raise DanceError("deletion requires confirm=true")
        path = self._path(dance_id)
        if not path.exists():
            raise DanceError(f"no such dance: {dance_id}")
        path.unlink()

    def search(self, query: str) -> list[DanceRecord]:
        q = normalize(query)
        if not q:
            return self.list()
        return [r for r in self.list()
                if q in normalize(" ".join([r.name, *r.aliases, *r.tags, r.origin, r.category, r.description]))]

    def lookup(self, message: str, candidate: str | None = None, *, limit: int = 2) -> list[TermMatch]:
        """Dances a chat message is about — same matcher as terminology (exact name/alias,
        whole-phrase mention, conservative typos that are never real English words).

        A passing mention of a name that is also a common English word ("breaking point",
        "popping up", "salsa sauce") only counts when the message also talks about dancing;
        a direct question about it ("Locking ki?") is an exact match and always counts."""
        matches = match_records(self.list(include_disabled=False), message, candidate, limit=limit + 2)

        def guarded(m) -> bool:
            return m.method == "phrase" and (_all_known_words(m.matched) or m.matched in EVERYDAY_WORD_NAMES)

        # Dancing is the topic if the message says so, or if it also names an unambiguous dance
        # ("difference between rumba and cha-cha").
        has_cue = self.mentions_dancing(message) or any(not guarded(m) for m in matches)
        return [m for m in matches if has_cue or not guarded(m)][:limit]

    @staticmethod
    def mentions_dancing(message: str) -> bool:
        msg = f" {normalize(message)} "
        return any(f" {c} " in msg for c in DANCE_CUES)


def format_dance_context(matches: list[TermMatch]) -> str | None:
    if not matches:
        return None
    return "\n\n".join(m.record.to_context() for m in matches)
