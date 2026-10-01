"""User memory V1 — opt-in, per browser/device id, separate from global knowledge.

Three layers (see docs/KNOWLEDGE_MEMORY_INTERNET.md):
  A. Conversation context — the chat history + same-session recall note (rupsaa/conversation/manager.py)
  B. Relevant user facts / preferences — THIS module (durable, opt-in)
  C. Active topic context — the knowledge records of the previous turn (api/services.py `_last_terms`)

Identity: a random id the browser generates and keeps (no login, so memory is per browser, not cross-device).
Only UUID-shaped ids are accepted and files are named by SHA-256(id): ids never reach the filesystem.

What is stored (conservatively, only after the user opted in):
  - durable self-statements, each under a slot key so a correction REPLACES the old value:
      name, location, favourite_<thing>, reply_language, job, study, diet, pet, birthday, likes:<thing>, dislikes:<thing>
  - explicit requests ("mone rekho …", "remember that …") as note:<n>
Never stored: temporary states and plans ("ajke mon kharap", "ekhon khide peyeche", "ajke movie dekhbo"), questions,
and nothing at all without consent. Turning memory off or "forget" deletes everything.

Recall injects only the facts relevant to the current message (plus name / reply-language preference), never the
whole store; "what do you remember about me?" lists them all.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

_BN = "ঀ-৿"
_B = rf"(?<![A-Za-z{_BN}])"
_E = rf"(?![A-Za-z{_BN}])"
_ID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
MAX_FACT_CHARS = 200
MAX_VALUE_CHARS = 80

_FILLER = re.compile(rf"{_B}(actually|asole|ashole|now|ekhon|to be honest|btw|by the way|haha|holo|hocche)"
                     rf"{_E}|এখন", re.I)
# Temporary states / plans — conversation-only, never durable.
_TEMPORARY = re.compile(
    rf"{_B}(ajke|aj|ajk|aaj|today|tonight|right now|ei muhurte|kal|kalke|tomorrow|yesterday|this (?:week|morning|evening)|"
    rf"mood|mon kharap|mon bhalo|khide|khida|hungry|tired|klanto|bored|sleepy|ghum pacche|dekhbo|jabo|korbo|khabo)"
    rf"{_E}|আজ|আজকে|কাল|মন খারাপ|খিদে",
    re.I,
)
_REMEMBER_RE = re.compile(
    r"^\s*(?:(?:please|pls)\s+)?(?:remember(?: that)?|mone rekho|mone rakho|mone rakhbe|mone rekhe dao|মনে রেখো|মনে রাখো)"
    r"\s*[:,\-–]?\s*(?P<fact>.+)$", re.I)
_FORGET_RE = re.compile(
    rf"{_B}(?:forget (?:me|everything|all|what you (?:know|remember))|delete (?:my|what you) (?:memory|data|remember)|"
    rf"(?:amake|amar kotha|amar bishoye|sob|shob|sob kichu|shob kichu)\s+bhule jao|bhule jao (?:amake|sob|shob)|"
    rf"amar (?:memory|data) (?:delete|muche) (?:koro|dao))"
    r"|আমাকে ভুলে যাও|সব ভুলে যাও|আমার সম্পর্কে সব মুছে ফেলো", re.I)
_RECALL_ALL_RE = re.compile(
    rf"{_B}(?:what do you (?:know|remember) about me|do you remember me|what have you remembered|"
    rf"(?:amar|amake) (?:bishoye|somporke|shomporke|niye) (?:ki|ki ki) (?:jano|mone ache|mone rekhecho)|"
    rf"amar kotha (?:mone ache|ki mone ache)|tumi amar (?:bishoye|somporke|shomporke) ki jano)"
    r"|আমার সম্পর্কে (?:কী|কি) (?:জানো|মনে আছে)", re.I)

_THING_NORMAL = {"color": "color", "colour": "color", "rong": "color", "রং": "color", "রঙ": "color",
                 "khabar": "food", "food": "food", "gaan": "song", "song": "song", "movie": "movie", "cinema": "movie",
                 "phool": "flower", "flower": "flower", "phul": "flower", "boi": "book", "book": "book",
                 "season": "season", "ritu": "season", "khela": "sport", "sport": "sport", "drink": "drink",
                 "singer": "singer", "actor": "actor", "place": "place", "jayga": "place", "prani": "animal",
                 "animal": "animal", "খাবার": "food", "গান": "song", "ফুল": "flower", "বই": "book", "সিনেমা": "movie"}
_LANG_PREF = re.compile(
    rf"{_B}(?:ami|i)\s+(?:(?:shob shomoy|always)\s+)?(?P<lang>banglish|bangla|bengali|english|ingreji)\s*(?:e|te)?\s+"
    rf"(?:reply|uttor|answer|kotha|message)?\s*(?:pochondo kori|prefer|like|chai|bhalobashi){_E}", re.I)
_SLOTS: list[tuple[str, re.Pattern]] = [
    ("name", re.compile(rf"{_B}(?:amar|amr|my)\s+(?:naam|nam|name)\s+(?:is\s+|holo\s+)?(?P<v>[^\s,.!?]+(?:\s+[^\s,.!?]+)?)", re.I)),
    ("name", re.compile(r"আমার নাম\s+(?P<v>\S+)")),
    ("location", re.compile(rf"{_B}(?:ami|i)\s+(?P<v>[^\s,.!?]+(?:\s+[^\s,.!?]+)??)(?:\s+|-)(?:e|te)\s+thaki{_E}", re.I)),
    ("location", re.compile(rf"{_B}(?:ami|i)\s+(?P<v>[^\s,.!?]+?)(?:y|e)?\s+thaki{_E}", re.I)),
    ("location", re.compile(rf"{_B}i\s+(?:live|stay)\s+in\s+(?P<v>[^,.!?]+)", re.I)),
    ("location", re.compile(r"আমি\s+(?P<v>\S+?)(?:য়|ে|তে)?\s+থাকি")),
    ("job", re.compile(rf"{_B}(?:ami|i)\s+(?P<v>[^,.!?]+?)\s+(?:hisebe\s+|hishebe\s+)?(?:kaj kori|chakri kori){_E}", re.I)),
    ("job", re.compile(rf"{_B}i\s+work\s+(?:as|at|in)\s+(?P<v>[^,.!?]+)", re.I)),
    ("study", re.compile(rf"{_B}(?:ami|i)\s+(?P<v>[^,.!?]+?)\s+(?:pori|porchi|study){_E}", re.I)),
    ("diet", re.compile(rf"{_B}(?:ami|i am|i'm)\s+(?P<v>vegetarian|vegan|non-?veg(?:etarian)?){_E}", re.I)),
    ("birthday", re.compile(rf"{_B}(?:amar|my)\s+(?:birthday|jonmodin)\s+(?:is\s+|holo\s+)?(?P<v>[^,.!?]+)", re.I)),
]
_FAV = [
    re.compile(rf"{_B}(?:amar|amr|my)\s+(?:favou?rite|priyo|pochonder)\s+(?P<thing>\S+)\s+(?:is\s+|holo\s+)?(?P<v>[^,.!?]+)", re.I),
    re.compile(r"আমার প্রিয়\s+(?P<thing>\S+)\s+(?P<v>[^,।!?]+)"),
]
_LIKE = [
    re.compile(rf"(?:(?P<over>[^\s,.!?]+?)(?:-?r|-?er)\s+theke\s+)?(?P<v>[^,.!?]+?)\s+(?:beshi\s+)?(?:pochondo kori|bhalobashi)"
               rf"{_E}", re.I),
    re.compile(rf"{_B}i\s+(?:really\s+)?(?:like|love|prefer)\s+(?P<v>[^,.!?]+)", re.I),
]
_DISLIKE = [re.compile(rf"(?P<v>[^,.!?]+?)\s+(?:pochondo kori na|ghrina kori|bhalobashi na){_E}", re.I),
            re.compile(rf"{_B}i\s+(?:hate|dislike|don't like)\s+(?P<v>[^,.!?]+)", re.I)]

# Which slots a message is about (relevance-filtered recall).
_TOPIC_HINTS = [
    (re.compile(rf"{_B}(color|colour|rong){_E}|রং|রঙ", re.I), ("favourite_color",)),
    (re.compile(rf"{_B}(naam|nam|name){_E}|নাম", re.I), ("name",)),
    (re.compile(rf"{_B}(thaki|thako|live|kothay|kothakar|city|shohor){_E}|থাকি|কোথায়", re.I), ("location",)),
    (re.compile(rf"{_B}(kaj|job|chakri|work|office){_E}", re.I), ("job",)),
    (re.compile(rf"{_B}(pori|study|college|school|university){_E}", re.I), ("study",)),
    (re.compile(rf"{_B}(khabar|food|khai|recipe|veg|dinner|lunch|biryani){_E}|খাবার", re.I), ("diet", "favourite_food")),
    (re.compile(rf"{_B}(birthday|jonmodin){_E}|জন্মদিন", re.I), ("birthday",)),
    (re.compile(rf"{_B}(pochondo|like|love|favou?rite|priyo|bhalobashi|prefer){_E}|প্রিয়|পছন্দ", re.I), ("*likes",)),
]
_ALWAYS = ("name", "reply_language")


def valid_user_id(user_id: str | None) -> bool:
    return bool(user_id) and bool(_ID_RE.match(user_id))


def _clean_value(v: str) -> str:
    v = _FILLER.sub(" ", v or "")
    v = re.sub(r"\s+", " ", v).strip(" .,!?-–—'\"।")
    return v[:MAX_VALUE_CHARS]


def _key_word(text: str) -> str:
    w = re.sub(rf"[^a-z0-9{_BN} ]", "", text.lower()).split()
    return (w[-1] if w else "x")[:30]


def _strip_subject(v: str) -> str:
    return re.sub(r"^(?:ami|i)\s+", "", v, flags=re.I).strip()


def extract_facts(message: str) -> list[dict]:
    """Durable facts in a message as [{"key", "value", "text"}] — [] for questions, temporary states and chat."""
    text = " ".join(message.strip().split())
    if not text or len(text) > 400:
        return []
    m = _REMEMBER_RE.match(text)
    if m:
        fact = m.group("fact").strip()[:MAX_FACT_CHARS]
        return [{"key": f"note:{hashlib.sha1(fact.lower().encode()).hexdigest()[:8]}", "value": fact, "text": fact}]
    if "?" in text or "？" in text:
        return []
    snippet = text[:MAX_FACT_CHARS]
    facts: list[dict] = []
    for pat in _FAV:
        for mm in pat.finditer(text):
            thing = _THING_NORMAL.get(mm.group("thing").lower(), _key_word(mm.group("thing")))
            v = _clean_value(mm.group("v"))
            if v:
                facts.append({"key": f"favourite_{thing}", "value": v, "text": snippet})
    lp = _LANG_PREF.search(text)
    if lp:
        lang = {"bangla": "bn", "bengali": "bn", "english": "en", "ingreji": "en"}.get(lp.group("lang").lower(), "banglish")
        facts.append({"key": "reply_language", "value": lang, "text": snippet})
    temporary = bool(_TEMPORARY.search(text))
    if temporary and not facts:
        return []  # "ajke mon kharap", "ajke movie dekhbo": conversation-only
    for key, pat in _SLOTS:
        mm = pat.search(text)
        if mm and not any(f["key"] == key for f in facts):
            v = _clean_value(mm.group("v"))
            if v:
                facts.append({"key": key, "value": v, "text": snippet})
    if not lp and not any(f["key"].startswith("favourite_") for f in facts):
        mm = next((p.search(text) for p in _DISLIKE if p.search(text)), None)
        if mm:
            v = _strip_subject(_clean_value(mm.group("v")))
            if v:
                facts.append({"key": f"dislikes:{_key_word(v)}", "value": v, "text": snippet})
        else:
            mm = next((p.search(text) for p in _LIKE if p.search(text)), None)
            if mm:
                v = _strip_subject(_clean_value(mm.group("v")))
                over = _clean_value(mm.groupdict().get("over") or "")
                if v:
                    facts.append({"key": f"likes:{_key_word(v)}", "value": v + (f" (more than {over})" if over else ""),
                                  "text": snippet})
    return facts


def is_forget_request(message: str) -> bool:
    return bool(_FORGET_RE.search(message))


def is_recall_request(message: str) -> bool:
    return bool(_RECALL_ALL_RE.search(message))


@dataclass
class UserMemory:
    consent: bool = False
    facts: list[dict] = field(default_factory=list)  # {"id","key","value","text","created_at","updated_at"}
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
        facts = []
        for f in d.get("facts", []):  # earlier records had only {"text","at"}
            facts.append({"id": f.get("id") or uuid.uuid4().hex[:10],
                          "key": f.get("key") or f"note:{hashlib.sha1(f.get('text', '').encode()).hexdigest()[:8]}",
                          "value": f.get("value") or f.get("text", ""), "text": f.get("text", ""),
                          "created_at": f.get("created_at", f.get("at", 0)), "updated_at": f.get("updated_at", f.get("at", 0))})
        return UserMemory(consent=bool(d.get("consent")), facts=facts, updated_at=d.get("updated_at", 0))

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
                self.forget(user_id)
                return UserMemory()
            mem = self.get(user_id)
            mem.consent = True
            self._write(user_id, mem)
            return mem

    def remember(self, user_id: str, facts: list[dict]) -> list[dict]:
        """Add or UPDATE (same slot key → value replaced) facts for a user who opted in. Returns changed facts."""
        if not facts:
            return []
        with self._lock:
            mem = self.get(user_id)
            if not mem.consent:
                return []
            now, changed = time.time(), []
            by_key = {f["key"]: f for f in mem.facts}
            for new in facts:
                old = by_key.get(new["key"])
                if old and old["value"].lower() == new["value"].lower():
                    continue
                if old:  # correction: one active value per slot
                    old.update(value=new["value"], text=new["text"], updated_at=now)
                    changed.append(old)
                else:
                    rec = {"id": uuid.uuid4().hex[:10], **new, "created_at": now, "updated_at": now}
                    mem.facts.append(rec)
                    by_key[new["key"]] = rec
                    changed.append(rec)
            mem.facts = mem.facts[-self.max_facts:]
            if changed:
                self._write(user_id, mem)
            return changed

    def delete_fact(self, user_id: str, fact_id: str) -> bool:
        with self._lock:
            mem = self.get(user_id)
            keep = [f for f in mem.facts if f["id"] != fact_id]
            if len(keep) == len(mem.facts):
                return False
            mem.facts = keep
            self._write(user_id, mem)
            return True

    def forget(self, user_id: str) -> None:
        p = self._path(user_id)
        if p.exists():
            p.unlink()


def relevant_facts(mem: UserMemory, message: str, *, recall_all: bool = False, limit: int = 6) -> list[dict]:
    if recall_all:
        return mem.facts[-20:]
    wanted: set[str] = set(_ALWAYS)
    likes = False
    for pat, keys in _TOPIC_HINTS:
        if pat.search(message):
            for k in keys:
                if k == "*likes":
                    likes = True
                else:
                    wanted.add(k)
    out = [f for f in mem.facts if f["key"] in wanted
           or (likes and f["key"].startswith(("likes:", "dislikes:", "favourite_")))]
    words = set(re.findall(r"\w{4,}", message.lower()))
    notes = [f for f in mem.facts if f["key"].startswith("note:") and set(re.findall(r"\w{4,}", f["value"].lower())) & words]
    return (out + [n for n in notes if n not in out])[:limit]


def memory_note(mem: UserMemory, message: str = "", *, recall: bool = False, forgotten: bool = False) -> str | None:
    """Conversation-note text (None when nothing is relevant)."""
    if forgotten:
        return ("The user asked you to forget what you remembered about them from earlier conversations. It has been "
                "deleted. Confirm briefly and warmly, in the user's language.")
    if not mem.consent:
        return None
    facts = relevant_facts(mem, message, recall_all=recall)
    if not facts:
        return ("Long-term memory is on for this user, but nothing is saved yet. If they ask what you remember, say "
                "so briefly.") if recall else None
    lines = ["Things this user chose to let you remember from earlier conversations (latest values; use them naturally "
             "when relevant, don't list them unless asked):"]
    for f in facts:
        label = f["key"].split(":")[0].replace("_", " ")
        lines.append(f"- {f['value']}" if f["key"].startswith("note:") else f"- {label}: {f['value']}")
    if recall:
        lines.append("They are asking what you remember about them: answer from this list, briefly.")
    return "\n".join(lines)
