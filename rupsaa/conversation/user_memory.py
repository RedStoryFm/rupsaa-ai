"""Opt-in persistent user memory (owner decision: remember users across sessions only if they agree).

Identity: a random id the browser generates and keeps (no login). Only ids that look like a UUID are accepted and
the file name is the SHA-256 of the id, so ids never reach the filesystem.

What is stored: only things the user states about themselves (name, where they live, favourites, likes, work,
study, pets, birthday) or explicitly asks Rupsaa to remember ("mone rekho …", "remember that …"). Nothing is stored
until the user has opted in; turning memory off or asking Rupsaa to forget deletes everything immediately.

At chat time the stored facts are added to the conversation note (the same place as the same-session recall note the
adapter was trained with), so Rupsaa can use them naturally and answer "what do you remember about me?".
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

_BN = "ঀ-৿"
_B = rf"(?<![A-Za-z{_BN}])"
_ID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
MAX_FACT_CHARS = 200

# Explicit "remember this" requests — the rest of the message is stored.
_REMEMBER_RE = re.compile(
    rf"^\s*(?:(?:please|pls)\s+)?(?:remember(?: that)?|mone rekho|mone rakho|mone rakhbe|mone rekhe dao|"
    rf"মনে রেখো|মনে রাখো)\s*[:,\-–]?\s*(?P<fact>.+)$",
    re.IGNORECASE,
)
# Self-statements worth remembering (the whole sentence is stored as the user wrote it).
_SELF_FACT_RE = re.compile(
    rf"{_B}(?:amar|amr|my)\s+(?:naam|nam|name|favou?rite|priyo|pochonder|birthday|jonmodin|bari|basha|kaj|job|"
    rf"pet|biral|kukur|cat|dog|hobby|hobbies)(?![A-Za-z])"
    rf"|{_B}(?:ami|i)\s+(?:thaki|live|stay|kaj kori|work|pori|study|studying|pochondo kori|bhalobashi|love|like|hate|"
    rf"vegetarian|vegan)(?![A-Za-z])"
    rf"|{_B}(?:i am|i'm|im|ami)\s+(?:a |an )?(?:student|doctor|engineer|teacher|designer|developer|nurse|artist|creator)"
    rf"|{_B}(?:ami|i)\s+\S+\s+(?:e|te|in)\s+(?:thaki|kaj kori|pori|live|work|study)(?![A-Za-z])"
    rf"|{_B}ami\s+(?:\S+\s+){{0,3}}(?:pochondo kori|bhalobashi|ghrina kori|khub bhalobashi)(?![A-Za-z])"
    rf"|{_B}amar\s+(?:\S+\s+){{0,3}}(?:khub )?(?:bhalo lage|pochondo)(?![A-Za-z])"
    r"|আমার\s+(?:নাম|প্রিয়|জন্মদিন|বাড়ি|কাজ|শখ)|আমি\s+\S*\s*(?:থাকি|কাজ করি|পড়ি|ভালোবাসি|পছন্দ করি)",
    re.IGNORECASE,
)
_FORGET_RE = re.compile(
    rf"{_B}(?:forget (?:me|everything|all|what you (?:know|remember))|delete (?:my|what you) (?:memory|data|remember)|"
    rf"(?:amake|amar kotha|amar bishoye|sob|shob|sob kichu|shob kichu)\s+bhule jao|bhule jao (?:amake|sob|shob)|"
    rf"amar (?:memory|data) (?:delete|muche) (?:koro|dao))"
    r"|আমাকে ভুলে যাও|সব ভুলে যাও|আমার সম্পর্কে সব মুছে ফেলো",
    re.IGNORECASE,
)
_RECALL_RE = re.compile(
    rf"{_B}(?:what do you (?:know|remember) about me|do you remember me|what have you remembered|"
    rf"(?:amar|amake) (?:bishoye|somporke|shomporke|niye) (?:ki|ki ki) (?:jano|mone ache|mone rekhecho)|"
    rf"amar kotha (?:mone ache|ki mone ache)|tumi amar (?:bishoye|somporke|shomporke) ki jano)"
    r"|আমার সম্পর্কে (?:কী|কি) (?:জানো|মনে আছে)",
    re.IGNORECASE,
)


def valid_user_id(user_id: str | None) -> bool:
    return bool(user_id) and bool(_ID_RE.match(user_id))


def extract_facts(message: str) -> list[str]:
    text = " ".join(message.strip().split())
    if not text or len(text) > 400:
        return []
    m = _REMEMBER_RE.match(text)
    if m:
        return [m.group("fact").strip()[:MAX_FACT_CHARS]]
    if text.endswith("?") or "?" in text:
        return []
    if _SELF_FACT_RE.search(text):
        return [text[:MAX_FACT_CHARS]]
    return []


def is_forget_request(message: str) -> bool:
    return bool(_FORGET_RE.search(message))


def is_recall_request(message: str) -> bool:
    return bool(_RECALL_RE.search(message))


@dataclass
class UserMemory:
    consent: bool = False
    facts: list[dict] = field(default_factory=list)  # {"text", "at"}
    updated_at: float = 0.0


class UserMemoryStore:
    def __init__(self, directory: Path, max_facts: int = 50):
        self.directory = Path(directory)
        self.max_facts = max_facts
        self._lock = threading.Lock()

    def _path(self, user_id: str) -> Path:
        if not valid_user_id(user_id):
            raise ValueError("invalid user id")
        return self.directory / f"{hashlib.sha256(user_id.lower().encode()).hexdigest()}.json"

    def get(self, user_id: str) -> UserMemory:
        p = self._path(user_id)
        if not p.exists():
            return UserMemory()
        d = json.loads(p.read_text(encoding="utf-8"))
        return UserMemory(consent=bool(d.get("consent")), facts=list(d.get("facts", [])), updated_at=d.get("updated_at", 0))

    def _write(self, user_id: str, mem: UserMemory) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        p = self._path(user_id)
        tmp = p.with_suffix(".tmp")
        mem.updated_at = time.time()
        tmp.write_text(json.dumps({"consent": mem.consent, "facts": mem.facts, "updated_at": mem.updated_at},
                                  ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)

    def set_consent(self, user_id: str, enabled: bool) -> UserMemory:
        with self._lock:
            if not enabled:  # turning memory off deletes everything (privacy first)
                self.forget(user_id, _locked=True)
                return UserMemory()
            mem = self.get(user_id)
            mem.consent = True
            self._write(user_id, mem)
            return mem

    def remember(self, user_id: str, facts: list[str]) -> int:
        """Store new facts for a user who opted in. Returns how many were added."""
        if not facts:
            return 0
        with self._lock:
            mem = self.get(user_id)
            if not mem.consent:
                return 0
            known = {f["text"].lower() for f in mem.facts}
            added = []
            for f in facts:  # dedupe against stored facts and within this batch
                if f.lower() not in known:
                    known.add(f.lower())
                    added.append(f)
            mem.facts += [{"text": f, "at": time.time()} for f in added]
            mem.facts = mem.facts[-self.max_facts:]
            if added:
                self._write(user_id, mem)
            return len(added)

    def forget(self, user_id: str, *, _locked: bool = False) -> None:
        p = self._path(user_id)
        if p.exists():
            p.unlink()


def memory_note(mem: UserMemory, *, recall: bool = False, forgotten: bool = False) -> str | None:
    """Conversation-note text for the system prompt (None when there is nothing to say)."""
    if forgotten:
        return ("The user asked you to forget what you remembered about them from earlier conversations. It has been "
                "deleted. Confirm briefly and warmly, in the user's language.")
    if not mem.consent:
        return None
    if not mem.facts:
        return ("Long-term memory is on for this user, but nothing has been saved yet. If they ask what you "
                "remember, say so briefly.") if recall else None
    lines = ["From earlier conversations, the user chose to let you remember these things they told you (their own "
             "words, oldest first). Use them naturally when relevant; don't list them unless asked:"]
    lines += [f"- {f['text']}" for f in mem.facts]
    if recall:
        lines.append("They are asking what you remember about them: answer from this list, briefly.")
    return "\n".join(lines)
