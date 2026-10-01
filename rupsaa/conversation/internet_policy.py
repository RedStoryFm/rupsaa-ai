"""Internet permission policy: ASK / ALLOW / DENY, one-time vs persistent consent, pending look-ups, freshness.

Rules (owner spec):
  - Internet is a FALLBACK: conversation/user memory and curated knowledge come first.
  - A look-up is *needed* only for factual questions that ask for current information ("latest", "today", price,
    news, weather, scores, versions …) or that explicitly ask to search. Other general questions are answered from
    local knowledge or the model's own general knowledge — no web.
  - ASK (default): never contact a provider before permission; the ORIGINAL question is kept as the pending query.
      "ha, eta search koro" → search the pending query once, stay in ASK
      "na, search korona"   → drop it, stay in ASK
  - ALLOW: search when needed without asking.       DENY: never search until the preference changes.
  - Persistent commands ("ekhon theke internet use korte paro", "ar internet use korbe na", "search korar age
    jiggesh korbe") change the mode; the newest explicit preference wins.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from pathlib import Path

ASK, ALLOW, DENY = "ASK", "ALLOW", "DENY"
MODES = (ASK, ALLOW, DENY)
DEFAULT_MODE = ASK
PENDING_TTL_SECONDS = 15 * 60

_BN = "ঀ-৿"
_B = rf"(?<![A-Za-z{_BN}])"
_E = rf"(?![A-Za-z{_BN}])"
_NET = r"(?:internet|net|online|web|google|search|সার্চ|ইন্টারনেট)"

_SET_ASK = re.compile(
    rf"{_B}(?:search|internet|net)\s*(?:korar|use korar|e jawar)\s+age\s+(?:jiggesh|jigges|jiggasha|ask)|"
    rf"{_B}ask (?:me )?(?:first|before (?:searching|you search|using the internet))|"
    rf"{_B}(?:always )?ask before search|আগে জিজ্ঞেস", re.I)
_SET_DENY = re.compile(
    rf"{_B}(?:ar|aar|kokhono|kokhonoi|never|don'?t|do not|no more)\s+(?:\w+\s+){{0,2}}{_NET}\w*\s*(?:use\s+)?"
    rf"(?:korbe na|koro na|korona|korbena|use|search|ever)?|"
    rf"{_NET}\s+(?:\w+\s+){{0,2}}(?:use\s+)?(?:korbe na|korbena|koro na|korona|bondho|off)(?:\s+ekhon theke)?{_E}|"
    rf"{_B}stop (?:using|searching) (?:the )?(?:internet|web)|never use (?:the )?internet|ইন্টারনেট ব্যবহার করবে না", re.I)
_SET_ALLOW = re.compile(
    rf"{_B}(?:future\s*-?\s*e|ekhon theke|ebar theke|from now on|whenever|jokhon)\b[^?.!]{{0,40}}{_NET}[^?.!]{{0,30}}"
    rf"(?:korte paro|use korte paro|koro|search korte paro|allowed|you can|can)|"
    rf"{_B}(?:proyojon|dorkar)\s+hole\s+(?:\w+\s+){{0,2}}{_NET}|"
    rf"{_B}you (?:can|may) (?:always )?(?:search|use the internet)(?: whenever| when)?|"
    rf"{_B}internet allow|always search|search whenever (?:needed|you need)", re.I)
_PERSIST = re.compile(
    rf"{_B}(?:ar|aar|kokhono|kokhonoi|never|ever|ekhon theke|ebar theke|from now on|no more|any ?more|future|always|"
    rf"shob shomoy|sob somoy|jokhon|whenever|proyojon hole|dorkar hole)(?![A-Za-z{_BN}])|আর|কখনো|এখন থেকে", re.I)
_APPROVE = re.compile(
    rf"^\s*(?:ha+|haa+n?|hya+|hyan|han|ho|yes|yeah|yep|ok(?:ay)?|sure|thik ache|koro|kor|go ahead|please do|হ্যাঁ|হ্যা|ঠিক আছে)"
    rf"(?:[\s,!.]+(?:eta|ota|ekta|please|pls|kore)?\s*(?:search|dekho|check|google)?\s*(?:koro|kor|do|dao|it|now)?)*"
    rf"[\s!.]*$|^\s*(?:search|google|check)\s*(?:koro|kor|it|do it)[\s!.]*$", re.I)
_REJECT = re.compile(
    rf"^\s*(?:na+|nah|no|nope|thak|lagbe na|dorkar nei|dorkar nai|don'?t|না|থাক)"
    rf"(?:[\s,!.]+(?:eta|ota|ekhon)?\s*(?:search|google)?\s*(?:korona|koro na|korbe na|korte hobe na|lagbe na|do it)?)*"
    rf"[\s!.]*$|^\s*(?:search|google)\s*(?:korona|koro na|korte hobe na)[\s!.]*$", re.I)
_EXPLICIT_LOOKUP = re.compile(
    rf"{_B}(?:search|google|look (?:it )?up|check online|search online|internet\s*-?e\s*(?:dekho|khojo|search|verify|check)|"
    rf"online\s*-?e\s*(?:dekho|check)|net\s*-?e\s*dekho|verify koro)\b|ইন্টারনেটে দেখো|সার্চ করো", re.I)
# Words that by themselves ask for live data.
_FRESH = re.compile(
    rf"{_B}(?:latest|newest|current(?:ly)?|live|recent(?:ly)?|"
    rf"news|headlines?|weather|forecast|temperature|price|prices|rate|rates|stock|stocks|share price|exchange rate|"
    rf"score|scores|result|results|standings|election|trending|release date|version|sensex|nifty|bitcoin|crypto|"
    rf"who won|jitlo|jiteche|dam|koto taka|khobor|abohawa|briskti|brishti|live score|202[4-9])"
    rf"{_E}|সর্বশেষ|দাম|খবর|আবহাওয়া|ফলাফল", re.I)
# Time words ("ajke", "today", "এখন") only make a question current together with a value question ("ajker Sensex
# koto?") — "ajke ki korle bhalo lagbe?" is advice, not a live-data request.
_TIME = re.compile(rf"{_B}(?:today'?s?|todays|right now|now|this (?:week|month|year)|ajker|ajke|aj|ekhon|ekhonkar|akhon)"
                   rf"{_E}|আজ|আজকের|এখন", re.I)
_VALUE_Q = re.compile(rf"{_B}(?:koto|how much|how many|what'?s the|ki ache){_E}|কত", re.I)


def detect_command(message: str, *, has_pending: bool) -> str | None:
    """'ask' | 'deny' | 'allow' (persistent) | 'approve_once' | 'reject_once' (only with a pending query) | None."""
    text = message.strip()
    if _SET_ASK.search(text):
        return "ask"
    persistent = bool(_PERSIST.search(text))
    if has_pending and not persistent and _REJECT.search(text):
        return "reject_once"  # "na, eta search korona" answers THIS question only
    if _SET_DENY.search(text) and (persistent or not has_pending):
        return "deny"
    if _SET_ALLOW.search(text):
        return "allow"
    if has_pending and _APPROVE.search(text):
        return "approve_once"
    if has_pending and _REJECT.search(text):
        return "reject_once"
    return None


def is_fresh(message: str) -> bool:
    return bool(_FRESH.search(message) or (_TIME.search(message) and _VALUE_Q.search(message)))


def explicit_lookup(message: str) -> bool:
    return bool(_EXPLICIT_LOOKUP.search(message))


_PERMISSION_QUESTIONS = {
    "banglish": ["Eta amar local knowledge-e enough nei. Internet-e search kore dekhi?",
                 "Eta jante hole online check korte hobe — internet-e search korbo?",
                 "Amar kache eta-r thik, updated info nei. Internet-e ekbar search kori?"],
    "bn": ["এটা আমার লোকাল জ্ঞানে যথেষ্ট নেই। ইন্টারনেটে সার্চ করে দেখি?",
           "এটা জানতে অনলাইনে দেখতে হবে — ইন্টারনেটে সার্চ করব?"],
    "en": ["My local knowledge isn't enough for this one. Shall I search the internet for it?",
           "I'd need to check online for that — okay if I search the internet?"],
}


def permission_question(message: str, requested_language: str | None = None) -> str:
    """The ASK-mode reply — fixed text in the user's language, so no model guess can slip in before permission."""
    from rupsaa.personality.language import fixed_reply_language

    lang = requested_language if requested_language in _PERMISSION_QUESTIONS else fixed_reply_language(message)
    options = _PERMISSION_QUESTIONS[lang]
    return options[sum(map(ord, message)) % len(options)]


def needs_web(*, message: str, route: str, smalltalk: bool, personal: bool, local_found: bool, question: bool,
              authoritative_topic: bool = False) -> bool:
    """Internet is needed only for factual questions asking for CURRENT information or explicitly asking to search —
    or for sexual-health / slang / kink-terminology questions the curated knowledge doesn't cover, where an
    authoritative educational source beats a model guess (rupsaa/rag/source_policy.py). Local knowledge that
    answers a non-current question makes the web unnecessary."""
    if smalltalk or route in ("memory", "followup"):
        return False
    if authoritative_topic and question and not local_found:
        return True  # "ami ki STI test korbo?" is personal wording, but still a health-fact question
    if personal:
        return False
    wants_search = explicit_lookup(message)
    if not (question or wants_search):
        return False
    if wants_search:
        return True
    return is_fresh(message) and not (local_found and not is_fresh(message))


class PreferenceStore:
    """Durable per-browser internet preference (data/user_prefs/<sha256(id)>.json); in-memory for anonymous chats."""

    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self._lock = threading.Lock()
        self._anon: dict[str, str] = {}

    def _path(self, user_id: str) -> Path:
        return self.directory / f"{hashlib.sha256(user_id.lower().encode()).hexdigest()}.json"

    def get(self, user_id: str | None, conversation_id: str | None = None) -> str:
        if user_id:
            p = self._path(user_id)
            if p.exists():
                mode = json.loads(p.read_text(encoding="utf-8")).get("internet_mode")
                return mode if mode in MODES else DEFAULT_MODE
            return DEFAULT_MODE
        return self._anon.get(conversation_id or "", DEFAULT_MODE)

    def set(self, user_id: str | None, conversation_id: str | None, mode: str) -> str:
        if mode not in MODES:
            raise ValueError(f"internet mode must be one of {MODES}")
        with self._lock:
            if user_id:
                self.directory.mkdir(parents=True, exist_ok=True)
                p = self._path(user_id)
                tmp = p.with_suffix(".tmp")
                tmp.write_text(json.dumps({"internet_mode": mode, "updated_at": time.time()}), encoding="utf-8")
                tmp.replace(p)
            else:
                self._anon[conversation_id or ""] = mode
        return mode
