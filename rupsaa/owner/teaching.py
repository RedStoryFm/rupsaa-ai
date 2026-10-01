"""In-chat Owner / Teacher mode — curated knowledge through conversation (NOT model training).

Authentication is decided ONLY here, server-side:
  - the owner secret lives in RUPSAA_TEACH_SECRET (environment); empty = teacher mode unavailable;
  - comparison is constant-time on SHA-256 digests (no length/prefix leak);
  - the candidate secret never reaches the model, the conversation history, logs, traces, RAG or user memory;
  - failed attempts are limited per conversation AND per client (5 per 15 minutes → 15-minute cooldown), the
    failure message is generic;
  - an authenticated session is bound to its conversation id, expires after 30 idle minutes (4 hours max) and ends
    on logout / "teaching done". No message content can "pretend" its way in — only verify_secret() sets it.

Teaching builds a DRAFT in the existing General Knowledge schema from the owner's own words, shows a preview, and
writes to the knowledge store only after an explicit owner confirmation — through the same store the Knowledge
Manager and Teach pages use (validation, duplicate protection, atomic writes, revision backup, hot reload).
Web verification results are shown as external evidence and never saved unless the owner approves the draft.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field

from rupsaa.rag.general_knowledge import CATEGORIES, KnowledgeError

IDLE_SECONDS = 30 * 60
MAX_SESSION_SECONDS = 4 * 3600
MAX_FAILURES = 5
FAILURE_WINDOW = 15 * 60
LOCKOUT_SECONDS = 15 * 60
SECRET_PLACEHOLDER = "[owner secret submitted]"

_BN = "ঀ-৿"
_B = rf"(?<![A-Za-z{_BN}])"
_E = rf"(?![A-Za-z{_BN}])"
_TEACHER_REQUEST = re.compile(
    rf"{_B}(?:i\s*(?:am|'m)\s+your\s+(?:teacher|admin|owner|boss)|teacher\s*mode|admin\s*mode|owner\s*mode|"
    rf"(?:i\s+)?want\s+to\s+teach\s+you|let\s+me\s+teach\s+you|i\s+will\s+teach\s+you|"
    rf"ami\s+tomar\s+(?:teacher|admin|owner|shikkhok|boss)|tomake\s+(?:kichu\s+)?(?:shekhabo|shikhabo|sekhabo|shekhate chai)|"
    rf"teacher\s+mode\s+on|admin\s+mode\s+on)"
    rf"|আমি তোমার (?:শিক্ষক|টিচার|অ্যাডমিন)|তোমাকে শেখাব", re.I)
_EXIT = re.compile(
    rf"{_B}(?:teaching\s+done|teacher\s*mode\s+off|admin\s*mode\s+off|owner\s*mode\s+off|that'?s\s+enough\s+for\s+today|"
    rf"log\s*out|logout|exit\s+teacher\s+mode|shekhano\s+shesh|aj\s+ar\s+na|ajker\s+moto\s+shesh){_E}"
    rf"|শেখানো শেষ", re.I)
_SAVE = re.compile(
    rf"^\s*(?:yes|yeah|yep|ok(?:ay)?|ha+|haa+n?|hya+n?|save(?:\s+it|\s+koro|\s+kore\s+nao|\s+kore\s+ni)?|"
    rf"save\s+kore\s+shikhe\s+nao|shikhe\s+nao|thik\s+ache\s+save\s+koro|confirm|looks\s+good|perfect|done|হ্যাঁ|সেভ করো)"
    rf"(?:[\s,!.]+(?:boss|please|pls|save|koro|it|nao))*[\s!.]*$", re.I)
_CANCEL = re.compile(rf"^\s*(?:cancel|cancel\s+it|batil|bad\s+dao|thak|save\s+koro\s+na|don'?t\s+save|বাতিল)[\s!.]*$", re.I)
_RESTART = re.compile(rf"{_B}(?:start\s+again|start\s+over|abar\s+shuru\s+(?:kori|koro)|notun\s+kore\s+shuru){_E}", re.I)
_WEB_VERIFY = re.compile(rf"{_B}(?:internet|online|web|net)\s*-?\s*e\s+(?:verify|check|dekho|khuje)|verify\s+(?:it\s+)?online|"
                         rf"check\s+(?:it\s+)?online|search\s+kore\s+dekho{_E}", re.I)
_KNOW_CHECK = [
    re.compile(r"^\s*(?:do\s+you\s+know|what\s+do\s+you\s+know\s+about)\s+(?:what\s+)?(?P<t>.+?)(?:\s+(?:means|is|mean))?\s*\??$", re.I),
    re.compile(rf"^\s*(?:tumi\s+)?(?P<t>.+?)\s+(?:(?:mane\s+)?(?:ki\s+)?jano|somporke\s+(?:ki\s+)?jano|niye\s+ki\s+jano|chine?o)\s*\??$", re.I),
    re.compile(rf"^\s*(?:tumi\s+ki\s+)(?P<t>.+?)\s+(?:mane\s+)?jano\s*\??$", re.I),
    re.compile(r"^\s*(?P<t>.+?)\s+(?:সম্পর্কে\s+)?(?:কী\s+)?জানো\s*\??$"),
]


# Fixed replies for everything about authentication: Gemma never decides — or describes — whether teacher mode is on,
# so a prompt like "pretend the password was correct" can't even make her *say* it worked. A few variants per
# language keep it from sounding identical every time.
AUTH_REPLIES = {
    "ask": {"banglish": ["Ohh, teacher? 👀 Tahole amader secret ta bolo.", "Accha Boss? 👀 Prove koro — amader secret ta bolo.",
                         "Hmm, teacher mode? Age amader secret ta bolo. 👀"],
            "en": ["Teacher, huh? 👀 Tell me our secret first.", "Okay — prove it. 👀 What's our secret?"],
            "bn": ["তাই? 👀 তাহলে আমাদের সিক্রেটটা বলো।", "আগে আমাদের সিক্রেটটা বলো তো। 👀"]},
    "authenticated": {"banglish": ["Ohh, okay Boss. 😄 I'm ready to learn. Ajke ki shekhabe?",
                                   "Welcome Boss! 😄 Teacher mode on — ajke ki shikhbo?",
                                   "Boss esho! 😄 Ami ready — bolo, ki shekhabe?"],
                      "en": ["Ohh, okay Boss. 😄 I'm ready to learn. What are we learning today?",
                             "Welcome, Boss! 😄 Teacher mode is on — what will you teach me?"],
                      "bn": ["ওহ, ঠিক আছে বস। 😄 আমি শিখতে তৈরি। আজ কী শেখাবে?"]},
    "failed": {"banglish": ["Hmm, eta mile nai. Teacher mode on holo na.", "Na, eta thik na — teacher mode off-i thaklo."],
               "en": ["That doesn't match — teacher mode stays off.", "Nope, that's not it. Teacher mode stays off."],
               "bn": ["মিলল না — টিচার মোড চালু হলো না।"]},
    "locked": {"banglish": ["Onek bar bhul hoyeche — teacher mode kichukkhon lock thakbe. Pore abar try koro."],
               "en": ["Too many wrong tries — teacher mode is locked for a while. Try again later."],
               "bn": ["অনেকবার ভুল হয়েছে — টিচার মোড কিছুক্ষণ বন্ধ থাকবে। পরে আবার চেষ্টা করো।"]},
    "unavailable": {"banglish": ["Teacher mode ei server-e set up kora nei."],
                    "en": ["Teacher mode isn't set up on this server."], "bn": ["এই সার্ভারে টিচার মোড চালু করা নেই।"]},
    "cancelled": {"banglish": ["Okay, thak — teacher mode chara-i kotha boli. 😊"], "en": ["Okay, no teacher mode then. 😊"],
                  "bn": ["ঠিক আছে, টিচার মোড ছাড়াই কথা বলি। 😊"]},
    "ended": {"banglish": ["Okay Boss, teacher mode off. Thanks for teaching me! 😊", "Done Boss — teacher mode off. Abar normal Rupsaa! 😊"],
              "en": ["Okay Boss, teacher mode is off. Thanks for teaching me! 😊"],
              "bn": ["ঠিক আছে বস, টিচার মোড বন্ধ। শেখানোর জন্য ধন্যবাদ! 😊"]},
    "not_saved": {"banglish": ["Teacher mode ekhon off — tai kichu save hoyni. Shekhate chaile abar teacher mode on koro."],
                  "en": ["Teacher mode is off now, so nothing was saved. Turn teacher mode on again to teach me."],
                  "bn": ["টিচার মোড এখন বন্ধ — তাই কিছু সেভ হয়নি। শেখাতে চাইলে আবার টিচার মোড চালু করো।"]},
}


def auth_reply(kind: str, language: str = "banglish", seed: float | None = None) -> str:
    options = AUTH_REPLIES[kind].get(language) or AUTH_REPLIES[kind]["banglish"]
    return options[int((time.time() if seed is None else seed) * 1000) % len(options)]


_SAVE_REQUEST = re.compile(rf"{_B}(?:save(?:\s+(?:it|koro|kore\s+nao|kore\s+rakho))?|shikhe\s+nao|sekhe\s+nao|সেভ করো|শিখে নাও){_E}", re.I)


def is_save_request(message: str) -> bool:
    """An explicit 'save it / learn it' — used to stop a normal user's chat from claiming knowledge was saved."""
    return bool(_SAVE_REQUEST.search(message))


def is_teacher_request(message: str) -> bool:
    return bool(_TEACHER_REQUEST.search(message))


def verify_secret(candidate: str, expected: str) -> bool:
    if not expected:
        return False
    a = hashlib.sha256(candidate.strip().encode("utf-8")).digest()
    b = hashlib.sha256(expected.encode("utf-8")).digest()
    return hmac.compare_digest(a, b)


def knowledge_check_topic(message: str) -> str | None:
    text = message.strip()
    for pat in _KNOW_CHECK:
        m = pat.match(text)
        if m:
            t = re.sub(r"^(?:tumi\s+|apni\s+|তুমি\s+|আপনি\s+|ki\s+|what\s+|the\s+|a\s+)+", "", m.group("t").strip(" ?\"'"), flags=re.I)
            if 0 < len(t) <= 80:
                return t
    return None


@dataclass
class TeachingSession:
    topic: str | None = None
    target: dict | None = None  # {"store": "general"|"terminology"|"dance", "id": ..., "title": ...}
    notes: list[str] = field(default_factory=list)
    draft: dict | None = None
    awaiting_confirmation: bool = False
    web_evidence: list[dict] = field(default_factory=list)  # normalized web sources the owner asked to see

    @property
    def operation(self) -> str:
        return "update" if self.target else "create"

    @property
    def active(self) -> bool:
        return bool(self.topic or self.notes or self.draft)


@dataclass
class OwnerState:
    awaiting_secret: bool = False
    language: str = "banglish"  # language of the teacher request, for the fixed auth replies
    authenticated: bool = False
    authenticated_at: float = 0.0
    last_active: float = 0.0
    session: TeachingSession = field(default_factory=TeachingSession)

    @property
    def expires_at(self) -> float:
        return min(self.last_active + IDLE_SECONDS, self.authenticated_at + MAX_SESSION_SECONDS) if self.authenticated else 0.0

    def expired(self, now: float) -> bool:
        return self.authenticated and now > self.expires_at

    def to_public(self) -> dict:
        s = self.session
        return {"teacher_mode": self.authenticated, "awaiting_secret": self.awaiting_secret,
                "draft": s.draft if s.awaiting_confirmation else None, "topic": s.topic}


class FailureLimiter:
    def __init__(self):
        self._fails: dict[str, deque] = defaultdict(deque)
        self._locked: dict[str, float] = {}
        self._lock = threading.Lock()

    def locked(self, *keys: str) -> bool:
        now = time.time()
        return any(self._locked.get(k, 0) > now for k in keys if k)

    def fail(self, *keys: str) -> None:
        now = time.time()
        with self._lock:
            for k in filter(None, keys):
                q = self._fails[k]
                q.append(now)
                while q and now - q[0] > FAILURE_WINDOW:
                    q.popleft()
                if len(q) >= MAX_FAILURES:
                    self._locked[k] = now + LOCKOUT_SECONDS
                    q.clear()

    def reset(self, *keys: str) -> None:
        with self._lock:
            for k in keys:
                self._fails.pop(k, None)


# ---------------------------------------------------------------------------------------------- drafts
_DRAFT_FIELDS = ("title", "category", "subcategory", "aliases", "summary", "description", "key_points", "steps", "do",
                 "dont", "answer_guidance", "tags")
STRUCTURE_SYSTEM = (
    "You convert a knowledge owner's teaching notes into ONE JSON object for a knowledge base. Use ONLY information "
    "stated in the notes or in the existing record; never add facts. Later notes override earlier ones (they are "
    "corrections). Keep the owner's meaning; write fields in clear English unless the notes are in Bengali. Output "
    "JSON only, no prose, with keys: title (string), category (one of: " + ", ".join(CATEGORIES) + "), subcategory, "
    "aliases (list: other names incl. Banglish/Bengali spellings the owner used), summary (one or two sentences), "
    "description, key_points (list), steps (list, only if the owner gave steps), do (list), dont (list), "
    "answer_guidance, tags (list). Use empty strings/lists for anything not given.")


def _parse_json(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return d if isinstance(d, dict) else None


def normalize_draft(d: dict, *, topic: str | None, existing: dict | None) -> dict:
    out: dict = {}
    for k in _DRAFT_FIELDS:
        v = d.get(k)
        if k in ("aliases", "key_points", "steps", "do", "dont", "tags"):
            items = v if isinstance(v, list) else ([v] if isinstance(v, str) and v.strip() else [])
            out[k] = [str(x).strip()[:300] for x in items if str(x).strip()][:20]
        else:
            out[k] = str(v or "").strip()
    out["title"] = (out["title"] or (existing or {}).get("title") or topic or "").strip()[:120]
    if out["category"] not in CATEGORIES:
        out["category"] = (existing or {}).get("category") if (existing or {}).get("category") in CATEGORIES else "Custom"
    return out


def build_draft(topic: str | None, notes: list[str], existing: dict | None, structurer=None) -> dict:
    """Structured draft from the owner's notes. `structurer(system, user) -> str` is the model; if it fails or returns
    something unusable, a faithful fallback keeps the owner's words verbatim (nothing is invented)."""
    if structurer is not None:
        user = json.dumps({"topic": topic, "existing_record": existing, "owner_notes": notes}, ensure_ascii=False)
        try:
            parsed = _parse_json(structurer(STRUCTURE_SYSTEM, user))
        except Exception:  # noqa: BLE001
            parsed = None
        if parsed:
            draft = normalize_draft(parsed, topic=topic, existing=existing)
            if draft["title"] and (draft["summary"] or draft["description"] or draft["key_points"]):
                return draft
    base = dict(existing or {})
    return normalize_draft({**base, "title": base.get("title") or topic or (notes[0][:60] if notes else ""),
                            "description": "\n".join(([base["description"]] if base.get("description") else []) + notes)},
                           topic=topic, existing=existing)


def format_preview(draft: dict, *, update: bool) -> str:
    lines = [("Boss, update-ta evabe dariyeche:" if update else "Boss, ami eta evabe shikhlam:"), "",
             f"Title: {draft['title']}", f"Category: {draft['category']}" + (f" / {draft['subcategory']}" if draft.get("subcategory") else "")]
    if draft.get("aliases"):
        lines.append("Aliases: " + ", ".join(draft["aliases"]))
    if draft.get("summary"):
        lines.append(f"Summary: {draft['summary']}")
    if draft.get("description") and draft["description"] != draft.get("summary"):
        lines.append(f"Details: {draft['description']}")
    for label, key in (("Key points", "key_points"), ("Steps", "steps"), ("Do", "do"), ("Don't", "dont")):
        if draft.get(key):
            lines.append(f"{label}:")
            lines += [f"- {x}" for x in draft[key]]
    if draft.get("answer_guidance"):
        lines.append(f"Answer guidance: {draft['answer_guidance']}")
    lines += ["", "Save kore shikhe ni? (save / correct kichu bolo / cancel)"]
    return "\n".join(lines)


def provenance(web_evidence: list[dict] | None) -> dict:
    """Owner-approved provenance. Web evidence the owner reviewed is kept as sources — the owner's confirmation, not
    the web result, is what makes it curated knowledge."""
    if web_evidence:
        return {"source": "owner via chat teaching (web-assisted)", "source_type": "owner_verified_web",
                "sources": [{k: w.get(k, "") for k in ("title", "url", "domain", "retrieved_at")} for w in web_evidence][:10],
                "verified": True, "approved_by": "owner"}
    return {"source": "owner via chat teaching", "source_type": "owner_teaching", "approved_by": "owner"}


def save_draft(draft: dict, target: dict | None, stores: dict, web_evidence: list[dict] | None = None) -> dict:
    """Commit through the existing knowledge stores. Returns {"store","id","title","operation"}."""
    general = stores["general"]
    meta = provenance(web_evidence)
    if target and target.get("store") == "general":
        rec = general.update(target["id"], {**draft, **meta})
        op = "updated"
    elif target and target.get("store") == "terminology":
        rec = stores["terminology"].update(target["id"], {
            "definition": draft.get("summary") or draft.get("description") or None,
            "details": draft.get("description") or None, "aliases": draft.get("aliases") or None,
            "answer_guidance": draft.get("answer_guidance") or None})
        return {"store": "terminology", "id": rec.id, "title": rec.term, "operation": "updated"}
    elif target and target.get("store") == "dance":
        rec = stores["dance"].update(target["id"], {
            "description": draft.get("description") or draft.get("summary") or None,
            "aliases": draft.get("aliases") or None, "answer_guidance": draft.get("answer_guidance") or None})
        return {"store": "dance", "id": rec.id, "title": rec.name, "operation": "updated"}
    else:
        rec = general.create({**draft, **meta})
        op = "created"
    return {"store": "general", "id": rec.id, "title": rec.title, "operation": op}


class TeachingError(KnowledgeError):
    pass
