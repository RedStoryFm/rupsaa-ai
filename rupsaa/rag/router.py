"""Lightweight request routing: decide which knowledge (if any) a message needs.

Why: before V0.2 prep, every message with the web UI's RAG toggle on got
document retrieval — "kemon acho?" came back with rupsaa_identity.md chunks
(and the .metadata.json sidecar) attached, and "What did I say first?" got
knowledge documents plus the RAG instruction "if the retrieved context
doesn't answer, say so", so V0.1 answered "I don't remember" even though the
answer was in the conversation history.

This is a deterministic, rule-based classifier (regexes over English,
Banglish and Bengali phrasings) — microseconds per message, no extra model
call, fully unit-testable. It does not need to be perfect: it only decides
*eligibility*. Retrieval itself still applies score thresholds, and the
default route for anything unrecognised is GENERAL (documents allowed but
filtered strictly), so an unmatched knowledge question still works.

Routes:
  MEMORY       questions about this conversation → history only, never RAG
  FOLLOWUP     "explain that in Bengali", "make it short", "more detail" → reformulate
               the previous answer from history; the previous turn's terminology is
               carried over (by the caller), documents are not searched
  TERMINOLOGY  "X mane ki?", "what does X mean?" → structured terminology
               (+ documents as a fallback when no term matches)
  KNOWLEDGE    platform/creator/policy/factual/identity questions → documents
  CASUAL       greetings, small talk, feelings → no retrieval
  GENERAL      everything else → documents only if strongly relevant
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

_BN = r"ঀ-৿"
_B = rf"(?<![A-Za-z{_BN}])"  # word boundary that works next to Bengali combining marks
_E = rf"(?![A-Za-z{_BN}])"


class Route(str, Enum):
    MEMORY = "memory"
    FOLLOWUP = "followup"
    TERMINOLOGY = "terminology"
    KNOWLEDGE = "knowledge"
    CASUAL = "casual"
    GENERAL = "general"


@dataclass(frozen=True)
class RouteDecision:
    route: Route
    reason: str
    term_candidate: str | None = None
    use_documents: bool = False
    use_terminology: bool = False
    strict_documents: bool = False  # GENERAL: only strongly relevant chunks


def _rx(*patterns: str) -> re.Pattern:
    return re.compile("|".join(f"(?:{p})" for p in patterns), re.IGNORECASE)


_MEMORY_RE = _rx(
    # English
    rf"{_B}what (did|have) i (just )?(say|said|tell|told|ask|asked|mention|mentioned|write|wrote){_E}",
    rf"{_B}what was (my|the) (first|last|previous|earlier) (message|question|thing)",
    rf"{_B}(do|did) you remember (what|when) i",
    rf"{_B}remember what i (said|told|asked|wrote)",
    rf"{_B}what (color|colour|name|number|city|food|thing) did i ",
    rf"{_B}(earlier|before|previously),? i (said|told|mentioned|asked)",
    rf"{_B}what did we (talk|discuss) about",
    # Banglish
    rf"{_B}ami (age|agey|prothome|prothom e|first e|shurute|shuru te)?\s*ki\s+(\w+\s+)?(bolechilam|bollam|boleci|bolchilam|likhechilam|jiggesh korechilam|jigges korechilam|jiggasha korechilam)",
    rf"{_B}(amar|amr) (ager|agey|prothom|first|shesh|last) (kotha|message|msg|question|proshno)",
    rf"{_B}mone (ache|ase|ache ki)[, ]+ami ki",
    rf"{_B}(ki|kon) (color|colour|nam|naam|jinis|kotha) (bolechilam|bollam)",
    # Bengali
    rf"আমি (আগে|প্রথমে|শুরুতে)?\s*(কী|কি)\s+(\S+\s+)?(বলেছিলাম|বললাম|লিখেছিলাম|জিজ্ঞেস করেছিলাম)",
    rf"আমার (আগের|প্রথম|শেষ) (কথা|মেসেজ|প্রশ্ন)",
    rf"মনে আছে[, ]*আমি",
)

_FOLLOWUP_RE = _rx(
    # English
    rf"^\s*(can you |could you |please )?(explain|say|tell|put|write) (it|that|this)( again)? (in|into) (bangla|bengali|banglish|english)",
    rf"^\s*(in|into) (bangla|bengali|banglish|english)( please)?\s*[?.!]*\s*$",
    rf"^\s*(make it|keep it|say it|explain it) (short|shorter|simple|simpler|brief)",
    rf"^\s*(explain|tell me) (more|in (more )?detail)|^\s*(more detail|elaborate|go deeper)\s*[?.!]*\s*$",
    rf"^\s*(what do you mean|i don'?t get it|didn'?t understand)",
    # Banglish
    rf"{_B}(eta|sheta|seta|oita)?\s*(bangla\s?(y|te|e)?|english\s?e|banglish\s?e|ingreji\s?te)\s*(bujhiye|bujhie|bujhaye)?\s*(bolo|bolen|bol|likho)",
    rf"{_B}(eta|sheta|seta)?\s*(short|choto|sohoj|shohoj|easy) kore (bolo|bol|bujhao|likho)",
    rf"{_B}(aro|ektu) (detail|bistarito|bistarito bhabe|bujhiye) (bolo|bol|bujhao)",
    rf"{_B}(bujhlam|bujhini|bujhi ni|bujhte parini|bujhte pari ni)",
    # Bengali
    r"(এটা|সেটা|ওটা)?\s*(বাংলায়|ইংরেজিতে)\s*(বুঝিয়ে)?\s*(বলো|বলুন|বল|লেখো)",
    r"(ছোট|সহজ) করে (বলো|বল|বোঝাও)",
    r"(আরও|আরো|একটু) (বিস্তারিত|বুঝিয়ে) (বলো|বল|বোঝাও)",
    r"(বুঝলাম না|বুঝিনি|বুঝতে পারিনি)",
)

# Definition questions. Group "term" captures the thing being asked about.
_TERM_PATTERNS = [
    # English
    re.compile(r"^\s*what(?:'s| is| are| does)\s+(?:a |an |the )?[\"'“]?(?P<term>[^\"'”?]{1,40}?)[\"'”]?\s*(?:mean|means|stand for)?\s*\??\s*$", re.I),
    re.compile(r"^\s*(?:what(?:'s| is) the )?meaning of\s+[\"'“]?(?P<term>[^\"'”?]{1,40}?)[\"'”]?\s*\??\s*$", re.I),
    re.compile(r"^\s*(?:define|explain the term|explain)\s+[\"'“]?(?P<term>[^\"'”?]{1,40}?)[\"'”]?\s*\??\s*$", re.I),
    re.compile(r"^\s*[\"'“]?(?P<term>[^\"'”?]{1,40}?)[\"'”]?\s+(?:means|meaning)\s*\?\s*$", re.I),
    # Banglish: "strip mane ki", "strip ki", "strip bolte ki bojhay", "strip ki jinis", "strip er mane ki"
    re.compile(r"^\s*[\"'“]?(?P<term>[^\"'”?]{1,40}?)[\"'”]?\s+(?:er\s+)?(?:mane|mani|meaning)\s+(?:ki|kii|ki\s+jinis|kii\s+jinis)\s*\??\s*$", re.I),
    re.compile(r"^\s*[\"'“]?(?P<term>[^\"'”?]{1,40}?)[\"'”]?\s+(?:bolte|bolle)\s+ki\s+(?:bojhay|bujhay|bojhai|bujhai|bojhano hoy|bujhano hoy)\s*\??\s*$", re.I),
    re.compile(r"^\s*[\"'“]?(?P<term>[^\"'”?]{1,30}?)[\"'”]?\s+(?:ki|kii)(?:\s+jinis)?\s*\??\s*$", re.I),
    re.compile(r"^\s*(?:ki|kii)\s+(?:mane|bojhay)\s+[\"'“]?(?P<term>[^\"'”?]{1,40}?)[\"'”]?\s*\??\s*$", re.I),
    # Bengali: "স্ট্রিপ মানে কী", "X কী", "X বলতে কী বোঝায়", "X কাকে বলে", "X এর মানে কি"
    re.compile(r"^\s*[\"'“]?(?P<term>[^\"'”?]{1,40}?)[\"'”]?\s+(?:এর\s+)?(?:মানে|অর্থ)\s+(?:কী|কি)\s*[?？।]?\s*$"),
    re.compile(r"^\s*[\"'“]?(?P<term>[^\"'”?]{1,40}?)[\"'”]?\s+বলতে\s+(?:কী|কি)\s+(?:বোঝায়|বোঝানো হয়)\s*[?？।]?\s*$"),
    re.compile(r"^\s*[\"'“]?(?P<term>[^\"'”?]{1,40}?)[\"'”]?\s+কাকে\s+বলে\s*[?？।]?\s*$"),
    re.compile(r"^\s*[\"'“]?(?P<term>[^\"'”?]{1,30}?)[\"'”]?\s+(?:কী|কি)(?:\s+জিনিস)?\s*[?？।]?\s*$"),
]
# Leading filler that isn't part of the term ("accha, strip mane ki?").
_TERM_PREFIX_RE = re.compile(
    rf"^(?:ok(?:ay)?|accha|acha|achha|hmm+|so|tell me|bolo(?: to)?|amake bolo|আচ্ছা|বলো তো)[,\s]+", re.I
)
# Things that look like "X ki?" but are casual questions, not term lookups.
_NOT_A_TERM = re.compile(
    rf"^(?:tumi|tui|apni|ami|amar|tomar|tor|ajke|aj|kal|ekhon|keno|kemon|kivabe|kothay|kokhon|ke|eta|sheta|seta|oita|"
    rf"you|i|it|this|that|he|she|they|we|up|going on|new|wrong|happening|the time|your name|"
    rf"তুমি|তুই|আপনি|আমি|আমার|তোমার|আজ|আজকে|এখন|কেন|কেমন|এটা|সেটা)(?:\s|$)",
    re.I,
)

_KNOWLEDGE_RE = _rx(
    rf"{_B}(payout|pay ?out|withdraw(al)?|fee|fees|commission|refund|chargeback|subscription|subscriber|verification|verify|kyc|"
    rf"policy|policies|terms of service|tos|guideline|rule|rules|limit|limits|payment|earnings?|tax|dmca|copyright|"
    rf"account|ban|banned|suspend(ed)?|platform|pricing|price|ppv|tier|tiers|tip|tips|dm pricing|niyom|shorto|"
    rf"নিয়ম|পেআউট|পেমেন্ট|ফি|রিফান্ড|সাবস্ক্রিপশন|ভেরিফিকেশন|প্ল্যাটফর্ম|অ্যাকাউন্ট|উইথড্র){_E}",
    rf"{_B}how (does|do|can|should) (a |the |my )?(creator|platform|account|payout|subscription)",
    rf"{_B}(kivabe|kibhabe) (kaj kore|pay kore|withdraw|payout)",
)
_IDENTITY_RE = _rx(
    rf"{_B}(who are you|what are you|tell me about yourself|about you|who (made|created|built) you|your name){_E}",
    rf"{_B}(tumi ke|tui ke|tomar (naam|nam) ki|tomake ke (banieche|baniyeche)|nijer (bishoye|shomporke) bolo){_E}",
    r"(তুমি কে|তোমার নাম কী|তোমার নাম কি|নিজের সম্পর্কে বলো)",
)
_CASUAL_RE = _rx(
    rf"^\s*(hi+|hey+|hello+|hlw|helo|yo|sup|hii+|good (morning|night|evening|afternoon)|gm|gn|bye|ok(ay)?|thanks?|thank you|ty|lol|haha+|hehe+)\b",
    rf"{_B}(kemon|kmn|kamon) (acho|aso|achis|achen|asen|asho)",
    rf"{_B}(ki|ki re|ki go) (korcho|koro|korchis|korchen|khobor)",
    rf"{_B}(how are you|how('s| is) (it going|your day|life)|what'?s up|wyd|what are you doing)",
    rf"{_B}(mood|mon) (ta )?(bhalo|valo|kharap|off)",
    rf"{_B}(bored|lonely|sad|tired|happy|excited|miss (you|u)|love (you|u)|good night|shubho ratri){_E}",
    r"(কেমন আছো|কেমন আছ|কি করছো|কী করছো|মন খারাপ|মন ভালো|শুভ রাত্রি|শুভ সকাল)",
)


def _term_candidate(message: str) -> str | None:
    text = _TERM_PREFIX_RE.sub("", message.strip())
    for pat in _TERM_PATTERNS:
        m = pat.match(text)
        if not m:
            continue
        term = m.group("term").strip(" \"'“”‘’.,")
        if not term or _NOT_A_TERM.match(term) or len(term.split()) > 5:
            continue
        return term
    return None


def classify_message(message: str) -> RouteDecision:
    text = message.strip()
    if _MEMORY_RE.search(text):
        return RouteDecision(Route.MEMORY, "asks about earlier messages in this conversation")
    if _FOLLOWUP_RE.search(text):
        return RouteDecision(Route.FOLLOWUP, "follow-up about the previous answer (language/length/clarity)")
    term = _term_candidate(text)
    if term:
        # Documents are a strict fallback: used only if no terminology entry matches.
        return RouteDecision(Route.TERMINOLOGY, f"definition question about {term!r}", term_candidate=term,
                             use_terminology=True, use_documents=True, strict_documents=True)
    if _KNOWLEDGE_RE.search(text) or _IDENTITY_RE.search(text):
        return RouteDecision(Route.KNOWLEDGE, "platform/creator/policy/identity knowledge question",
                             use_documents=True, use_terminology=True)
    if _CASUAL_RE.search(text) or len(re.findall(rf"[A-Za-z{_BN}]+", text)) <= 3:
        return RouteDecision(Route.CASUAL, "greeting / small talk / short casual message")
    return RouteDecision(Route.GENERAL, "no strong knowledge signal", use_documents=True, strict_documents=True)
