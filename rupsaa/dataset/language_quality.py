"""Bengali / Banglish / code-switching quality signals + V0.2 triage.

V0.1 post-mortem: Bengali/Banglish replies in the corpus frequently had
English discourse fillers glued onto Bengali sentences ("Honestly না মূলত না
actually…"), words spelled half in Latin and half in Bengali script
("korার", "nেয়া"), romanized Bengali inside Bengali-script replies and vice
versa, and replies that answer a question with only a counter-question. None
of the existing checks looked at any of this.

Every signal here is a named, inspectable heuristic. They catch mechanical
defects well; they do NOT judge semantic coherence, contradictions or
whether a follow-up makes sense — those need a fluent human reader, which
is why the triage sends anything beyond a mechanical tic to HUMAN_REVIEW
instead of auto-repairing it.

Nothing here changes a record or its quality_status.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from rupsaa.dataset.schema import ConversationRecord

_BN_CHAR = r"ঀ-৿"
_INTRAWORD_MIX_RE = re.compile(rf"[A-Za-z][{_BN_CHAR}]|[{_BN_CHAR}][A-Za-z]")
_LATIN_WORD_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")
_BN_WORD_RE = re.compile(rf"[{_BN_CHAR}]+")
_SENTENCE_RE = re.compile(r"[^.!?।]+[.!?।]*")

FILLERS = ("honestly", "actually", "genuinely", "basically", "obviously", "literally")
_FILLER_RE = re.compile(r"(?<![A-Za-z])(" + "|".join(FILLERS) + r")(?![A-Za-z])", re.IGNORECASE)

# Romanized-Bengali function words — their presence in a Bengali-script
# reply means the writer switched *script* mid-reply (not a loanword).
BANGLISH_LEXICON = frozenset(
    """
    ami tumi tui amar tomar tor amake tomake eta sheta seta oita ekta kintu tahole jodi
    kora korle korte koro korbo kore korchi korcho hoy hobe hoye hote hoyeche ache achi acho nai
    theke jonno niye diye sathe moto mone bhalo khub shob sob dekho bolo bole bujhte bujhi lage lagche
    ekhon ajke keno kivabe kothay kokhon naki chai lagbe hoyto shudhu sudhu aro onek ektu
    """.split()
)
_BANGLISH_QWORDS = re.compile(r"(?<![A-Za-z])(ki|keno|kivabe|kothay|kokhon|kemon|koto|kon)(?![A-Za-z])", re.IGNORECASE)
_BN_QWORDS = re.compile(rf"(?<![{_BN_CHAR}])(কী|কি|কেন|কিভাবে|কীভাবে|কোথায়|কখন|কেমন|কত|কোন)(?![{_BN_CHAR}])")
_EN_QWORDS = re.compile(r"(?<![A-Za-z])(what|why|how|when|where|which|who|can|should|do|does|is|are)(?![A-Za-z])", re.IGNORECASE)

# Letters from scripts that never belong in Bengali/Banglish/English text
# (Cyrillic/Greek/Devanagari lookalikes, e.g. "kичhu") — generation artifacts.
_FOREIGN_SCRIPT_RE = re.compile(r"[\u0370-\u03FF\u0400-\u04FF\u0900-\u0963\u0966-\u097F]")  # excludes ।॥ (U+0964/5), used in Bengali
SEVERE = {"FOREIGN_SCRIPT", "INTRAWORD_SCRIPT_MIX", "LANGUAGE_MISMATCH", "SCRIPT_INCONSISTENT", "QUESTION_UNANSWERED"}
# Soft signals: surfaced to reviewers, never decide a classification on their own.
STYLE = {"ENGLISH_CALQUE"}
# English "worth <verb>-ing" / "make sense" syntax carried over with Bengali words.
_CALQUE_RE = re.compile(
    r"(?<![A-Za-z])(worth\s+[a-z]+\s+(kora|korা|korar|korte)|(sheta|eta|seta)\s+worth|make(s)?\s+sense\s+(kore|hoy))(?![A-Za-z])",
    re.IGNORECASE,
)
TIC = {"FILLER_STACK", "ENGLISH_FILLER_IN_BENGALI", "ENGLISH_DISCOURSE_OPENER", "TRAILING_FILLER", "CATCHPHRASE"}


def script_profile(text: str) -> tuple[int, int]:
    """(latin_word_count, bengali_word_count)."""
    return len(_LATIN_WORD_RE.findall(text)), len(_BN_WORD_RE.findall(text))


def dominant_script(text: str) -> str:
    latin, bn = script_profile(text)
    if latin + bn == 0:
        return "none"
    if bn / (latin + bn) >= 0.6:
        return "bengali"
    if latin / (latin + bn) >= 0.7:
        return "latin"
    return "mixed"


def is_question(text: str) -> bool:
    t = text.strip()
    return t.endswith("?") or bool(_BANGLISH_QWORDS.search(t)) or bool(_BN_QWORDS.search(t)) or (
        bool(_EN_QWORDS.match(t))
    )


def filler_count(text: str) -> int:
    return len(_FILLER_RE.findall(text))


@dataclass
class TurnIssue:
    code: str
    turn_index: int  # index into record.messages
    detail: str


@dataclass
class LanguageQualityResult:
    record_id: str
    language: str
    source_type: str
    issues: list[TurnIssue] = field(default_factory=list)

    @property
    def codes(self) -> set[str]:
        return {i.code for i in self.issues}

    @property
    def severe(self) -> set[str]:
        return self.codes & SEVERE

    @property
    def tics(self) -> set[str]:
        return self.codes & TIC


def analyze_record(record: ConversationRecord, overused_phrases: set[str] | frozenset[str] = frozenset()) -> LanguageQualityResult:
    res = LanguageQualityResult(record.id, record.language, record.source_type)
    last_user = ""
    for idx, m in enumerate(record.messages):
        role, text = m.get("role"), m.get("content", "")
        if role == "user":
            last_user = text
            continue
        if role != "assistant":
            continue
        add = lambda code, detail: res.issues.append(TurnIssue(code, idx, detail))  # noqa: E731

        foreign = _FOREIGN_SCRIPT_RE.findall(text)
        if foreign:
            add("FOREIGN_SCRIPT", f"non-Bengali/Latin letters: {sorted(set(foreign))[:6]}")

        mixed_tokens = [w for w in re.findall(rf"[A-Za-z{_BN_CHAR}]+", text) if _INTRAWORD_MIX_RE.search(w)]
        if mixed_tokens:
            add("INTRAWORD_SCRIPT_MIX", f"{len(mixed_tokens)} token(s): {mixed_tokens[:5]}")

        clean_text = " ".join(w for w in text.split() if not _INTRAWORD_MIX_RE.search(w))
        reply_script = dominant_script(text)
        user_script = dominant_script(last_user)
        latin_words = [w.lower() for w in _LATIN_WORD_RE.findall(text)]
        # Mirror check: a Bengali-script user answered in Latin (or vice versa).
        if user_script == "bengali" and reply_script == "latin":
            add("LANGUAGE_MISMATCH", "user wrote Bengali script, reply is Latin-script")
        elif user_script == "latin" and reply_script == "bengali" and record.language != "bn":
            add("LANGUAGE_MISMATCH", "user wrote Latin script, reply is Bengali script")

        if reply_script == "bengali":
            romanized = [w for w in latin_words if w in BANGLISH_LEXICON]
            if len(romanized) >= 2:
                add("SCRIPT_INCONSISTENT", f"romanized Bengali inside a Bengali-script reply: {romanized[:6]}")
            en_fillers = _FILLER_RE.findall(text)
            if en_fillers:
                add("ENGLISH_FILLER_IN_BENGALI", f"English filler(s) in Bengali-script reply: {en_fillers}")
        elif reply_script == "latin" and record.language == "banglish":
            bn_words = _BN_WORD_RE.findall(clean_text)
            if bn_words:
                add("SCRIPT_INCONSISTENT", f"Bengali-script words inside a Banglish reply: {bn_words[:6]}")

        if record.language in ("bn", "banglish", "mixed"):
            first = (_LATIN_WORD_RE.findall(text) or [""])[0].lower()
            if first in FILLERS:
                add("ENGLISH_DISCOURSE_OPENER", f"opens with English filler {first!r}")

        if record.language in ("banglish", "mixed") and _CALQUE_RE.search(text):
            add("ENGLISH_CALQUE", f"English syntax with Bengali words: {_CALQUE_RE.search(text).group(0)!r}")

        n_fill = filler_count(text)
        if n_fill >= 2:
            add("FILLER_STACK", f"{n_fill} filler words in one reply")
        if re.search(r"(?<![A-Za-z])(actually|honestly)[\s,]*[.!?।]?\s*$", text.strip(), re.IGNORECASE):
            add("TRAILING_FILLER", "reply ends on a filler word")
        hits = sorted(p for p in overused_phrases if re.search(
            rf"(?<![A-Za-z{_BN_CHAR}]){re.escape(p)}(?![A-Za-z{_BN_CHAR}])", text, re.IGNORECASE))
        if hits:
            add("CATCHPHRASE", f"corpus-overused phrase(s): {hits}")

        if last_user and is_question(last_user):
            # Only a bare counter-question counts: no answer clause before it
            # ("Khaisi, tui ki…?" answers first, then asks — that's fine).
            sentences = [s.strip() for s in _SENTENCE_RE.findall(text) if s.strip()]
            if (sentences and len(sentences) <= 2 and all(s.endswith("?") for s in sentences)
                    and not re.search(r"[,;:]|\s[-–—]\s", sentences[0])):
                add("QUESTION_UNANSWERED", "user asked a question; reply is only a counter-question")
    return res


# ---------------------------------------------------------------------------
# Mechanical repair (proposal only — never applied automatically)
# ---------------------------------------------------------------------------

_ALWAYS_REMOVE = ("honestly",)
_CONDITIONAL = ("actually", "genuinely", "obviously", "basically", "literally")


def _remove_word(text: str, word: str, *, anywhere: bool) -> str:
    w = re.escape(word)
    b = rf"(?<![A-Za-z{_BN_CHAR}])"
    e = rf"(?![A-Za-z{_BN_CHAR}])"
    # sentence-initial: "Honestly, X" / "Honestly - X" / "Honestly X"
    text = re.sub(rf"(^|(?<=[.!?।]\s)){b}{w}{e}\s*[,;:]?\s*(?:[-–—]\s*)?", r"\1", text, flags=re.IGNORECASE)
    # clause-final: "X actually." / "X, honestly।" / "X actually -"
    text = re.sub(rf"[,\s]*{b}{w}{e}\s*(?=[.!?।,;:]|\s[-–—]|$)", "", text, flags=re.IGNORECASE)
    # comma-bracketed: ", honestly," / "- honestly -"
    text = re.sub(rf"\s*[,–—-]\s*{b}{w}{e}\s*(?=[,–—-])", "", text, flags=re.IGNORECASE)
    if anywhere:
        text = re.sub(rf"\s*{b}{w}{e}\s*", " ", text, flags=re.IGNORECASE)
    return text


def _tidy(original: str, text: str) -> str:
    text = re.sub(r"\s+([,.!?।;:])", r"\1", text)
    text = re.sub(r"([,;:])\s*([,.!?।;:])", r"\2", text)
    text = re.sub(r"^\s*[,;:–—-]\s*", "", text)
    text = re.sub(r"(?<=[.!?।])\s*[,;:–—-]\s*", " ", text)
    text = re.sub(r"\s*[-–—]\s*([.!?।])", r"\1", text)
    text = re.sub(r"[ \t]{2,}", " ", text).strip()
    # re-capitalize the first Latin letter of each sentence if the original started capitalized
    if original[:1].isupper():
        text = re.sub(r"^([a-z])", lambda m: m.group(1).upper(), text)
    text = re.sub(r"([.!?]\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), text)
    return text


_BN_TO_LATIN = {
    "া": "a", "ি": "i", "ী": "i", "ু": "u", "ূ": "u", "ে": "e", "ৈ": "oi", "ো": "o", "ৌ": "ou",
    "্": "", "ং": "ng", "ঃ": "h", "ঁ": "n", "ক": "k", "খ": "kh", "গ": "g", "ঘ": "gh", "ঙ": "ng",
    "চ": "ch", "ছ": "chh", "জ": "j", "ঝ": "jh", "ঞ": "n", "ট": "t", "ঠ": "th", "ড": "d", "ঢ": "dh",
    "ণ": "n", "ত": "t", "থ": "th", "দ": "d", "ধ": "dh", "ন": "n", "প": "p", "ফ": "f", "ব": "b",
    "ভ": "bh", "ম": "m", "য": "j", "র": "r", "ল": "l", "শ": "sh", "ষ": "sh", "স": "s", "হ": "h",
    "ড়": "r", "ঢ়": "rh", "য়": "y", "ৎ": "t", "অ": "o", "আ": "a", "ই": "i", "ঈ": "i", "উ": "u",
    "ঊ": "u", "এ": "e", "ঐ": "oi", "ও": "o", "ঔ": "ou",
}
_LATIN_TO_BN_SINGLE = {"e": "এ", "o": "ও", "i": "ই", "h": "হ", "k": "ক", "g": "গ", "j": "জ", "t": "ত", "d": "দ", "n": "ন",
                       "p": "প", "b": "ব", "m": "ম", "r": "র", "l": "ল", "s": "স"}


def repair_script_mix(text: str) -> str:
    """Mechanically fix words spelled half in Latin, half in Bengali script
    ("korার" → "korar" in a Latin-script reply; "hঠাৎ" → "হঠাৎ" in a
    Bengali-script reply). Only simple, unambiguous cases; anything else is
    left for a human (and stays flagged)."""
    reply_is_latin = dominant_script(text) == "latin"

    def fix(m: re.Match) -> str:
        word = m.group(0)
        if not _INTRAWORD_MIX_RE.search(word):
            return word
        latin = len(re.findall(r"[A-Za-z]", word))
        bengali = len(word) - latin
        # Only unambiguous cases: a short Bengali suffix on a Latin stem
        # ("korার") or a single Latin letter on a Bengali word ("hঠাৎ").
        # Anything longer ("shobসময়") is left alone and stays flagged.
        if latin >= bengali and bengali <= 3:
            return "".join(_BN_TO_LATIN.get(ch, ch) for ch in word)
        if latin == 1 and bengali > latin and not reply_is_latin:
            return re.sub(r"[A-Za-z]", lambda c: _LATIN_TO_BN_SINGLE.get(c.group(0).lower(), c.group(0)), word)
        return word

    return re.sub(rf"[A-Za-z{_BN_CHAR}]+", fix, text)


def propose_filler_repair(text: str, language: str) -> str:
    """Remove catchphrase fillers mechanically. "honestly" is removed
    everywhere; "actually"/"genuinely"/… are removed everywhere in
    Bengali/Banglish/mixed replies (where they're English fillers glued onto
    Bengali syntax) and, in English replies, only where they're pure
    discourse filler (sentence-initial/final, comma-bracketed) or stacked
    with another filler — mid-sentence "what you actually want" is meaning,
    not a tic."""
    out = text
    for w in _ALWAYS_REMOVE:
        out = _remove_word(out, w, anywhere=True)
    stacked = filler_count(text) >= 2
    for w in _CONDITIONAL:
        out = _remove_word(out, w, anywhere=(language != "en") or stacked)
    return _tidy(text, out)


# ---------------------------------------------------------------------------
# V0.2 triage
# ---------------------------------------------------------------------------

@dataclass
class TriageDecision:
    record_id: str
    classification: str  # KEEP | REPAIR | REJECT | HUMAN_REVIEW
    reasons: list[str]
    language: str
    category: str
    source_type: str
    quality_status: str
    issues: list[dict]
    proposed_messages: list[dict] | None = None  # REPAIR (and advisory for human_authored)
    residual_issues: list[str] = field(default_factory=list)


def propose_repair(record: ConversationRecord) -> list[dict]:
    """Mechanical proposal for every assistant turn: filler removal +
    intra-word script-mix transliteration. A proposal, never applied."""
    return [
        {**m, "content": propose_filler_repair(repair_script_mix(m["content"]), record.language)}
        if m.get("role") == "assistant" else dict(m)
        for m in record.messages
    ]


def triage_record(
    record: ConversationRecord,
    overused_phrases: set[str] | frozenset[str],
    prior_audit_flags: set[str] | frozenset[str] = frozenset(),
) -> TriageDecision:
    """KEEP / REPAIR / REJECT / HUMAN_REVIEW for V0.2 (a recommendation only).

    The mechanical proposal is applied hypothetically first; the decision is
    based on what's LEFT after it:
      * human_authored → never auto-repaired: KEEP if clean, else HUMAN_REVIEW
      * ≥2 distinct severe defects remain → REJECT (needs regeneration, not an edit)
      * 1 severe defect or a prior factual-risk flag → HUMAN_REVIEW (fluent rewrite)
      * proposal changes the text and leaves no tic/severe issue → REPAIR
      * otherwise KEEP (a remaining mid-sentence "actually" in English is meaning,
        and the corpus gate — not this per-record rule — polices its rate)
    """
    lq = analyze_record(record, overused_phrases)
    base = dict(record_id=record.id, language=record.language, category=record.category,
                source_type=record.source_type, quality_status=record.quality_status,
                issues=[vars(i) for i in lq.issues])
    factual = set(prior_audit_flags) & {"FAKE_RAG_ATTRIBUTION", "UNSUPPORTED_PLATFORM_FACT", "INVENTED_PRECISION"}

    proposed = propose_repair(record)
    changed = proposed != [dict(m) for m in record.messages]
    after = analyze_record(ConversationRecord(**{**vars(record), "messages": proposed}), overused_phrases)
    residual = sorted(after.codes)
    residual_actionable = (after.codes - {"CATCHPHRASE"})

    if record.quality_status == "rejected":
        return TriageDecision(classification="REJECT", reasons=["already rejected"], **base)
    if record.source_type == "human_authored":
        if lq.codes - {"CATCHPHRASE"} or factual or changed:
            return TriageDecision(
                classification="HUMAN_REVIEW",
                reasons=[f"human_authored with issues {sorted(lq.codes | factual)} — never auto-repaired"],
                proposed_messages=proposed if changed else None, residual_issues=residual, **base)
        return TriageDecision(classification="KEEP", reasons=["human_authored, no actionable issues"], **base)

    if len(after.severe) >= 2:
        return TriageDecision(classification="REJECT",
                              reasons=[f"severe defects remain after mechanical repair: {sorted(after.severe)}"], **base)
    if after.severe or factual:
        return TriageDecision(classification="HUMAN_REVIEW",
                              reasons=[f"needs a fluent rewrite, not a mechanical fix: {sorted(after.severe | factual)}"],
                              proposed_messages=proposed if changed else None, residual_issues=residual, **base)
    if changed:
        if residual_actionable or any(not m["content"].strip() for m in proposed if m.get("role") == "assistant"):
            return TriageDecision(classification="HUMAN_REVIEW",
                                  reasons=[f"mechanical repair left issues {sorted(residual_actionable)}"],
                                  proposed_messages=proposed, residual_issues=residual, **base)
        return TriageDecision(classification="REPAIR",
                              reasons=[f"mechanical fix for {sorted(lq.codes - after.codes) or sorted(lq.codes)}"],
                              proposed_messages=proposed, residual_issues=residual, **base)
    return TriageDecision(classification="KEEP", reasons=["no actionable language-quality or catchphrase issues"], **base)
