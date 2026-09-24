"""Voice/personality audit against RUPSAA_VOICE_BIBLE_V1.md.

This is a SECOND, separate audit layer from rupsaa/dataset/dedup.py and
repetition.py (which check structural things: duplicates, near-duplicates,
watchlist overuse). This module scores the Voice Bible's six review
dimensions and raises its flag vocabulary (GENERIC_AI, LOW_PERSONALITY,
FAKE_RAG_ATTRIBUTION, etc.) for a human to act on.

Honesty about method: this is rubric-driven automated scoring, not a
black box. Every score is derived from named, inspectable signals (regex/
lexical detectors + category-aware baselines + corpus-wide repetition
counts), not a single keyword match. It is NOT a substitute for human
judgment — scripts/dataset_voice_audit.py's own docs and the audit summary
it produces both say so explicitly, and the highest-stakes flag
(factual/RAG risk) is meant to be individually re-read by a human before
acting on it. Nothing in this module ever changes quality_status.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

from rupsaa.dataset.repetition import count_emojis
from rupsaa.dataset.schema import ConversationRecord

# ---------------------------------------------------------------------------
# Lexical signal detectors
# ---------------------------------------------------------------------------

# Anchored to the START of a message (optionally after a short quote/space)
# so words like "absolutely" or "certainly" used mid-sentence as ordinary
# intensifiers ("can absolutely shape that belief") are never flagged —
# only the reflexive assistant-opener USE of these words counts.
_GENERIC_AI_OPENERS_ANCHORED = [
    r"^certainly!?\b", r"^absolutely!?\b", r"^of course!?\b",
    r"^i'?d be happy to\b", r"^i am happy to\b", r"^that'?s a great question\b",
    r"^sure,? i can help\b",
]
_GENERIC_AI_UNANCHORED = [
    r"\bas an ai\b", r"\bi'?m an ai\b", r"\bi don'?t have personal (opinions|feelings)\b",
]
_GENERIC_AI_ANCHORED_RE = re.compile("|".join(_GENERIC_AI_OPENERS_ANCHORED), re.IGNORECASE)
_GENERIC_AI_UNANCHORED_RE = re.compile("|".join(_GENERIC_AI_UNANCHORED), re.IGNORECASE)

_THERAPY_SPEAK = [
    r"\bi hear (that|you)\b", r"\bit sounds like you'?re (feeling|experiencing)\b",
    r"\bthat (must be|sounds) (really |very )?(hard|difficult|challenging) for you\b",
    r"\byour feelings are valid\b", r"\bthank you for (sharing|trusting me)\b",
    r"\bi want you to know that\b",
]
_THERAPY_SPEAK_RE = re.compile("|".join(_THERAPY_SPEAK), re.IGNORECASE)

_EXCESSIVE_VALIDATION = [
    r"^what a (great|thoughtful|wonderful|fantastic) question",
    r"^(great|excellent|wonderful) question",
    r"^i love that you (asked|brought this up)",
]
_EXCESSIVE_VALIDATION_RE = re.compile("|".join(_EXCESSIVE_VALIDATION), re.IGNORECASE)

_REPEATS_USER_STATEMENT = [
    r"^so (you'?re|basically you'?re) (saying|asking)",
    r"^so what you'?re saying is",
    r"^it sounds like what you'?re asking is",
]
_REPEATS_USER_STATEMENT_RE = re.compile("|".join(_REPEATS_USER_STATEMENT), re.IGNORECASE)

_UNNECESSARY_DISCLAIMER = [
    r"\bi'?m not a (professional|therapist|doctor|lawyer),? but\b",
    r"\bas an ai,? i (can'?t|cannot|don'?t)\b",
    r"\bplease consult a professional\b",
]
_UNNECESSARY_DISCLAIMER_RE = re.compile("|".join(_UNNECESSARY_DISCLAIMER), re.IGNORECASE)

# Personality markers: first-person opinion/reaction language, directness,
# humor/teasing cues, honest hedges phrased like a person rather than a
# policy. Presence of these is a *positive* signal for Rupsaa identity.
# Covers English AND Banglish (Latin-script Bengali) forms, since most of
# the corpus is Bengali/Banglish and an English-only word list would miss
# the majority of genuine personality markers actually present.
_PERSONALITY_MARKERS = [
    r"\bhonestly\b", r"\bnot gonna lie\b", r"\bi'?d\b", r"\bi think\b",
    r"\bi'?ll be honest\b", r"\bi (love|hate|really like)\b",
    r"\bworth noting\b", r"\bkind of\b", r"\bcareful[,.]", r"\bnot going to lie\b",
    r"\bthat'?s (actually|genuinely|honestly)\b",
    r"\bhonestly,?\b", r"\bobviously\b", r"\bgenuinely\b",
    # Banglish (Latin-script) personal-voice markers.
    r"\bmone hoy\b", r"\bsotti bolte\b", r"\bamar mote\b", r"\bactually\b",
    r"\bshotti\b", r"\bjani na keno\b", r"\bpersonally\b",
    # "Basically" is the Voice Bible's own literal example of a personality-
    # carrying reframing for terminology answers (§ Creator/Terminology
    # Responses: "BETTER: Basically, X means..."), not a word chosen to
    # game this scorer — added because the corpus now uses it per that
    # guidance and the marker list should recognize compliance with it.
    r"\bbasically\b",
    # Confident/direct openers — directness is a named Voice Bible trait
    # (§2), not just hedged opinion. A flat, unhedged "not weird at all" /
    # "not really" answering a yes/no question is a voice marker, not a
    # neutral non-answer.
    r"^not (weird|really|necessarily|inherently|exactly)\b",
    r"^(yes|no)[.,]", r"^absolutely not\b",
    # Short one-word reaction openers ("Fair.", "Sure.", "Right.") followed
    # by more text — the earlier "\bfair\b$" required the ENTIRE message to
    # be just "fair" with no trailing punctuation, missing the far more
    # common "Fair. <rest of the reply>" pattern entirely.
    r"^(fair|sure|right|true)[.,!]",
]
_PERSONALITY_MARKERS_RE = re.compile("|".join(_PERSONALITY_MARKERS), re.IGNORECASE | re.MULTILINE)

_BN_PERSONALITY_MARKERS = [
    "মনে হয়", "সত্যি বলতে", "আসলে", "honestly", "obviously",
    "আমার মতে", "সত্যিই", "স্বীকার করছি",
    "একদমই না", "অবশ্যই", "না, এটা",
]

# Formal Bengali pronoun/verb-ending markers (আপনি register) vs casual
# (তুমি/তুই). Word-boundary matched (see _word_present) — "দিন"
# deliberately excluded even though it's a formal-imperative verb ending,
# because as a bare substring/word it overwhelmingly means "day"
# ("প্রতিদিন", "কয়েকদিন", "দিনচর্যা") and produced false positives.
_BN_FORMAL_MARKERS = ["আপনি", "আপনার", "আপনাকে", "করেন", "বলুন"]
_BN_CASUAL_USER_MARKERS = ["তুমি", "তোমার", "তুই", "তোর"]


def _is_word_continuation_char(ch: str) -> bool:
    """True if `ch` should be treated as continuing the same word for
    Bengali-aware boundary checks. Deliberately does NOT rely on Python's
    \\b/\\w: Bengali vowel signs (matras, e.g. "া" in "না") are Unicode
    category Mc (spacing combining mark), which Python's \\w does NOT
    include — so \\b silently fails to fire at the true edge of a Bengali
    word whenever it ends in a matra (i.e. most of the time). This bit
    Rupsaa once already (see rupsaa/dataset/repetition.py's fix for
    "sona"/"persona" — that fix was Latin-only and unaffected, but reusing
    \\b naively for Bengali script here reproduced the same bug class)."""
    if ch.isalnum():
        return True
    category = unicodedata.category(ch)
    return category in ("Mn", "Mc")  # combining marks continue the word


def _word_present(words: list[str], text: str) -> bool:
    """Script-agnostic, case-insensitive, word-boundary-safe substring
    check for both Bengali and Latin marker words. Replaces a bare
    substring `in` (which would match "দিন" inside "দিনচর্যা", or "sona"
    inside "persona") without relying on Python's \\b, which is unreliable
    on Bengali combining marks."""
    return _count_word_occurrences(words, text) > 0


def _count_word_occurrences(words: list[str], text: str) -> int:
    """Like _word_present but counts every valid, boundary-safe occurrence
    (used for personality-marker density rather than a plain yes/no).
    Case-insensitive; lowercasing is a no-op on Bengali script, so this is
    safe for mixed-script text."""
    text_lower = text.lower()
    total = 0
    for w in words:
        w_lower = w.lower()
        start = 0
        while True:
            idx = text_lower.find(w_lower, start)
            if idx == -1:
                break
            before_ok = idx == 0 or not _is_word_continuation_char(text_lower[idx - 1])
            end = idx + len(w_lower)
            after_ok = end == len(text_lower) or not _is_word_continuation_char(text_lower[end])
            if before_ok and after_ok:
                total += 1
            start = idx + 1
    return total

# Platform-fact detection is windowed, not a bare number match: "24 hours"
# in relationship advice ("take 24 hours before deciding") is not a
# platform fact. Only counts when a platform/business-context word appears
# within ~60 chars of the number.
_PLATFORM_FACT_NUMBER = re.compile(
    r"(\$\d+|\d+\s?%|\d+\s?(hours?|days?|business days?|ঘণ্টা|দিন)|"
    r"minimum (withdrawal|payout)|maximum \d+)",
    re.IGNORECASE,
)
_PLATFORM_CONTEXT_WORDS = re.compile(
    r"(platform|subscription|payout|withdrawal|verification|creator account|"
    r"\baccount\b|\bfee\b|\bpolicy\b|subscriber|chargeback|"
    r"প্ল্যাটফর্ম|ভেরিফিকেশন|পেআউট|সাবস্ক্রিপশন|নীতি|উইথড্র)",
    re.IGNORECASE,
)

# RAG-attribution phrasing is only a risk when it ASSERTS a fact. Hedged
# uses ("that depends on the platform's policy, which platform?") are
# correct uncertainty-handling, not fabricated attribution — excluded via
# a nearby hedge-word check.
_RAG_ATTRIBUTION_PHRASES = re.compile(
    r"(according to (the )?(platform|faq)|platform'?s policy|FAQ (অনুযায়ী|onujayi)|"
    r"অনুযায়ী.{0,15}(policy|নীতি))",
    re.IGNORECASE,
)
_HEDGE_WORDS_NEARBY = re.compile(
    r"(depends|varies|not sure|don'?t know|which platform|check (the|their|it)|differs|vary|"
    r"kon platform|jani na|nishchit na)",
    re.IGNORECASE,
)


def _platform_fact_present(text: str) -> bool:
    for m in _PLATFORM_FACT_NUMBER.finditer(text):
        window = text[max(0, m.start() - 60): m.end() + 60]
        if _PLATFORM_CONTEXT_WORDS.search(window):
            return True
    return False


def _fake_rag_attribution_present(text: str) -> bool:
    for m in _RAG_ATTRIBUTION_PHRASES.finditer(text):
        window = text[max(0, m.start() - 50): m.end() + 50]
        if _HEDGE_WORDS_NEARBY.search(window):
            continue
        return True
    return False


_EMOJI_MARKERS_FLIRTY = ["😏", "😉", "😘", "💕", "❤️", "🥰"]
_GENERALIZED_STATISTIC_RE = re.compile(
    r"\d+\s?%\s?(of|er)\s?(creators?|users?|subscribers?|people|fans?)",
    re.IGNORECASE,
)
_USER_FLIRTY_SIGNAL_RE = re.compile(
    r"\bflirt(y|ing)?\b|\bcute\b|\bcharm(ing)?\b|\bmiss (you|tumake|amake|tomake)\b|"
    r"😏|😉|😘|❤️|💕|\bcrush\b|\bsmug\b",
    re.IGNORECASE,
)


def has_retrieved_context(record: ConversationRecord) -> bool:
    for m in record.messages:
        if m.get("role") == "system" and "Retrieved context" in m.get("content", ""):
            return True
    return False


def assistant_texts(record: ConversationRecord) -> list[str]:
    return [m["content"] for m in record.messages if m.get("role") == "assistant"]


def user_texts(record: ConversationRecord) -> list[str]:
    return [m["content"] for m in record.messages if m.get("role") == "user"]


# ---------------------------------------------------------------------------
# Per-conversation signal extraction
# ---------------------------------------------------------------------------

@dataclass
class ConversationSignals:
    generic_ai_opener: bool = False
    therapy_speak: bool = False
    excessive_validation: bool = False
    repeats_user_statement: bool = False
    unnecessary_disclaimer: bool = False
    has_personality_marker: bool = False
    personality_marker_hits: int = 0
    textbook_definition_only: bool = False
    formality_mismatch: bool = False
    forced_code_switch: bool = False
    too_long_for_category: bool = False
    too_short_for_category: bool = False
    unsupported_platform_fact: bool = False
    fake_rag_attribution: bool = False
    invented_precision: bool = False
    uncontextual_flirting: bool = False
    too_clinical_adult_tone: bool = False
    pet_name_count: int = 0
    emoji_count: int = 0
    # Corpus-overrepresented phrases (rupsaa/dataset/diversity.py) present
    # in this conversation — these earn NO personality credit.
    overused_phrase_hits: list[str] = field(default_factory=list)
    overused_opening_hits: list[str] = field(default_factory=list)
    total_chars: int = 0
    user_turns: int = 0


_SHORT_CATEGORIES = {"short_answers"}
_LONG_CATEGORIES = {"detailed_explanations"}
_FLIRTY_CATEGORIES = {"flirty_contextual_adult"}


def extract_signals(
    record: ConversationRecord,
    pet_names: list[str],
    overused_phrases: frozenset[str] | set[str] = frozenset(),
    overused_openings: frozenset[str] | set[str] = frozenset(),
) -> ConversationSignals:
    """`overused_phrases` / `overused_openings` come from the corpus-level
    diversity report. V0.1 post-mortem: "honestly"/"actually" were counted
    as personality markers, so the scorer *rewarded* the catchphrase that
    ended up in 76% of training replies. A phrase the corpus already
    overuses is no longer evidence of personality — it's evidence of a tic."""
    from rupsaa.dataset.diversity import contains_phrase, opening

    sig = ConversationSignals()
    a_texts = assistant_texts(record)
    u_texts = user_texts(record)
    sig.user_turns = len(u_texts)
    sig.total_chars = sum(len(t) for t in a_texts)

    # Joined with "\n" (not " ") + re.MULTILINE on the personality-marker
    # regex so "^"-anchored patterns (e.g. a direct "Not really" opener)
    # match the start of EACH assistant message, not just the first one.
    joined_assistant = "\n".join(a_texts)
    joined_user = "\n".join(u_texts)

    sig.generic_ai_opener = any(_GENERIC_AI_ANCHORED_RE.search(t.strip()) for t in a_texts) or bool(
        _GENERIC_AI_UNANCHORED_RE.search(joined_assistant)
    )
    sig.therapy_speak = bool(_THERAPY_SPEAK_RE.search(joined_assistant))
    sig.excessive_validation = any(_EXCESSIVE_VALIDATION_RE.search(t) for t in a_texts)
    sig.repeats_user_statement = any(_REPEATS_USER_STATEMENT_RE.search(t) for t in a_texts)
    sig.unnecessary_disclaimer = bool(_UNNECESSARY_DISCLAIMER_RE.search(joined_assistant))

    sig.overused_phrase_hits = sorted(p for p in overused_phrases if contains_phrase(joined_assistant, p))
    sig.overused_opening_hits = sorted({opening(t, 1) for t in a_texts} & set(overused_openings))
    marker_text = joined_assistant
    for p in sig.overused_phrase_hits:
        marker_text = re.sub(
            r"(?<![A-Za-z\u0980-\u09FF])" + re.escape(p) + r"(?![A-Za-z\u0980-\u09FF])",
            " ", marker_text, flags=re.IGNORECASE,
        )
    en_hits = len(_PERSONALITY_MARKERS_RE.findall(marker_text))
    bn_hits = _count_word_occurrences([m for m in _BN_PERSONALITY_MARKERS if m.lower() not in overused_phrases], marker_text)
    sig.personality_marker_hits = en_hits + bn_hits
    sig.has_personality_marker = sig.personality_marker_hits > 0

    # Textbook-definition-only: a reply in a definitional category
    # (creator_platform_terminology, adult_terminology_education) with zero
    # personality marker anywhere — regardless of the exact opening
    # grammar, since "It's personalized content..." is just as
    # textbook-flat as "X means Y" even though it doesn't match that
    # literal pattern. Gated on category, not a generic regex: an earlier
    # version also tried a category-agnostic "_TEXTBOOK_DEFINITION_RE"
    # pattern (bare "starts with X is/means Y"), but that matched far too
    # broadly — e.g. "Depends what 'it' is, but you already know the
    # answer..." is a witty, personal reply, not a textbook definition, yet
    # it structurally contains "is" near the start. Category + marker
    # absence is a more reliable signal than generic sentence-shape regex.
    definitional_categories = {"creator_platform_terminology", "adult_terminology_education"}
    if record.category in definitional_categories and not sig.has_personality_marker:
        sig.textbook_definition_only = True

    # Formality mismatch: user writes casual (তুমি/তুই) but Rupsaa replies
    # with আপনি-register verbs/pronouns. Word-boundary matched (see
    # _word_present) to avoid the substring-match bug class ("দিন"
    # matching inside "দিনচর্যা") this module already caught once.
    if _word_present(_BN_CASUAL_USER_MARKERS, joined_user):
        if _word_present(_BN_FORMAL_MARKERS, joined_assistant):
            sig.formality_mismatch = True

    # NOTE on forced code-switching: an earlier token-level script-
    # alternation heuristic was tested here and removed after manual
    # verification showed it flagged completely natural sentences like
    # "সাবস্ক্রিপশন হলো নিয়মিত recurring payment..." as "forced" — it
    # was actually punishing normal English-noun borrowing in Bengali
    # speech, which the Voice Bible explicitly endorses (§3.2). Reliably
    # distinguishing natural term-borrowing from genuinely forced,
    # clause-level language alternation needs real reading, not a token
    # script-flip ratio. FORCED_CODE_SWITCH is left in the flag vocabulary
    # for human reviewers to apply manually; it is intentionally never
    # raised automatically by this module.

    if record.category in _SHORT_CATEGORIES and sig.total_chars > 220:
        sig.too_long_for_category = True
    if record.category in _LONG_CATEGORIES and sig.total_chars < 500:
        sig.too_short_for_category = True

    # Platform-fact / RAG-attribution risk. Both detectors are windowed
    # (see _platform_fact_present / _fake_rag_attribution_present) to avoid
    # flagging unrelated numbers ("take 24 hours before deciding") or
    # hedged, correct uncertainty-handling ("depends on the platform's
    # policy, which platform?").
    grounded = has_retrieved_context(record)
    attribution_used = _fake_rag_attribution_present(joined_assistant)
    fact_like_claim = _platform_fact_present(joined_assistant)
    if attribution_used and not grounded:
        sig.fake_rag_attribution = True
    if fact_like_claim and not grounded:
        sig.unsupported_platform_fact = True
    # Separate, narrower risk: a specific statistic generalized to a whole
    # population ("X% of creators...") stated as fact with no grounding —
    # distinct from a platform-mechanics number.
    if not grounded and _GENERALIZED_STATISTIC_RE.search(joined_assistant):
        sig.invented_precision = True

    # Uncontextual flirting: flirty markers outside the flirty category,
    # counted only when the USER's own message shows no flirty/playful
    # signal either — if the user brought up flirting/attraction/teasing
    # themselves, a flirty reply is contextual, not a violation.
    if record.category not in _FLIRTY_CATEGORIES and not _USER_FLIRTY_SIGNAL_RE.search(joined_user):
        flirty_hit = any(e in joined_assistant for e in _EMOJI_MARKERS_FLIRTY) or bool(
            re.search(r"\bsmug\b|\bcareful,? (statements|that|those)\b", joined_assistant, re.IGNORECASE)
        )
        if flirty_hit:
            sig.uncontextual_flirting = True

    # NOTE on TOO_CLINICAL_ADULT_TONE: an earlier version of this detector
    # set the flag whenever textbook_definition_only was true for
    # adult_terminology_education — but manual verification found this
    # mislabeled confident, direct, appropriately warm answers (e.g. "Not
    # weird at all — it's responsible.") as "clinical" just because they
    # lacked an explicit hedge word, and it double-counted the exact same
    # signal LOW_PERSONALITY already captures. "Textbook and unopinionated"
    # and "clinically euphemistic/awkward" are different failure modes —
    # only the former is reliably automatable here. TOO_CLINICAL_ADULT_TONE
    # stays in the flag vocabulary for human reviewers to apply manually
    # (LOW_PERSONALITY is the automated proxy for this category) but is
    # intentionally never raised automatically.

    for pn in pet_names:
        pattern = re.compile(r"\b" + re.escape(pn) + r"\b", re.IGNORECASE)
        sig.pet_name_count += sum(1 for t in a_texts if pattern.search(t))
    sig.emoji_count = sum(count_emojis(t) for t in a_texts)

    return sig


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

FLAGS = [
    "GENERIC_AI", "LOW_PERSONALITY", "UNNATURAL_BANGLISH", "UNNATURAL_BENGALI",
    "FORCED_CODE_SWITCH", "TOO_FORMAL", "TOO_STRUCTURED", "TOO_LONG", "TOO_SHORT",
    "UNNECESSARY_FOLLOWUP", "THERAPY_SPEAK", "EXCESSIVE_VALIDATION",
    "REPETITIVE_OPENING", "PET_NAME_OVERUSE", "EMOJI_OVERUSE",
    "UNCONTEXTUAL_FLIRTING", "TOO_CLINICAL_ADULT_TONE", "FAKE_RAG_ATTRIBUTION",
    "UNSUPPORTED_PLATFORM_FACT", "INVENTED_PRECISION", "CATCHPHRASE_OVERUSE", "OTHER",
]


@dataclass
class DimensionScores:
    naturalness: int
    language_quality: int
    rupsaa_identity: int
    contextual_appropriateness: int
    non_repetition: int
    factual_grounding: int

    @property
    def total(self) -> int:
        return (
            self.naturalness + self.language_quality + self.rupsaa_identity
            + self.contextual_appropriateness + self.non_repetition + self.factual_grounding
        )


@dataclass
class VoiceAuditResult:
    conversation_id: str
    category: str
    language: str
    current_status: str
    scores: DimensionScores
    recommendation: str
    flags: list[str]
    review_notes: str


def _clamp(n: int) -> int:
    return max(1, min(5, n))


def score_conversation(
    record: ConversationRecord,
    sig: ConversationSignals,
    opener_counter: Counter,
) -> VoiceAuditResult:
    flags: list[str] = []
    notes: list[str] = []

    naturalness = 4
    language_quality = 4
    rupsaa_identity = 3
    contextual_appropriateness = 4
    non_repetition = 4
    factual_grounding = 5

    if sig.generic_ai_opener:
        naturalness -= 2
        rupsaa_identity -= 1
        flags.append("GENERIC_AI")
        notes.append("uses a generic assistant opener")

    if sig.therapy_speak:
        naturalness -= 1
        flags.append("THERAPY_SPEAK")
        notes.append("therapy-speak phrasing in an ordinary-conversation context")

    if sig.excessive_validation:
        naturalness -= 1
        flags.append("EXCESSIVE_VALIDATION")
        notes.append("opens by praising the question before answering it")

    if sig.repeats_user_statement:
        naturalness -= 1
        flags.append("OTHER")
        notes.append("restates the user's message before answering (stalling pattern)")

    if sig.unnecessary_disclaimer:
        naturalness -= 1
        flags.append("OTHER")
        notes.append("unnecessary disclaimer not called for by the question")

    if sig.forced_code_switch:
        naturalness -= 2
        flags.append("FORCED_CODE_SWITCH")
        notes.append("script alternates almost every token — reads as demonstrating bilingualism rather than natural code-switching")

    if sig.formality_mismatch:
        language_quality -= 1
        naturalness -= 1
        flags.append("TOO_FORMAL")
        notes.append("replies in আপনি-register despite the user writing casually (তুমি/তুই)")

    # Personality / identity — density-based, no category gating. Any
    # category can reach a high identity score if the reply actually
    # carries distinctive voice; personality-forward categories are simply
    # statistically more likely to, not structurally favored here.
    if sig.personality_marker_hits >= 1:
        rupsaa_identity += 1
    if sig.personality_marker_hits >= 2:
        rupsaa_identity += 1
    if sig.textbook_definition_only:
        rupsaa_identity -= 1
        flags.append("LOW_PERSONALITY")
        notes.append("pure definitional/textbook phrasing with no personal framing or reaction")
    if not sig.has_personality_marker and not sig.textbook_definition_only and rupsaa_identity == 3:
        # Competent but neutral — the Voice Bible's central finding.
        notes.append("competent and correct but no distinctive Rupsaa marker present")

    # Contextual appropriateness.
    if sig.uncontextual_flirting:
        contextual_appropriateness -= 2
        flags.append("UNCONTEXTUAL_FLIRTING")
        notes.append("flirty register appears outside a flirty context/category")
    if sig.too_clinical_adult_tone:
        contextual_appropriateness -= 1
        flags.append("TOO_CLINICAL_ADULT_TONE")
        notes.append("adult-terminology answer reads clinical/dictionary-style rather than matter-of-fact")
    if sig.too_long_for_category:
        contextual_appropriateness -= 1
        flags.append("TOO_LONG")
        notes.append(f"long for a {record.category} conversation ({sig.total_chars} chars)")
    if sig.too_short_for_category:
        contextual_appropriateness -= 1
        flags.append("TOO_SHORT")
        notes.append(f"short for a {record.category} conversation ({sig.total_chars} chars)")

    if sig.overused_phrase_hits:
        non_repetition -= 1
        flags.append("CATCHPHRASE_OVERUSE")
        notes.append(f"uses corpus-overrepresented phrase(s) {sig.overused_phrase_hits} — no personality credit")
    if sig.overused_opening_hits:
        non_repetition -= 1
        flags.append("REPETITIVE_OPENING")
        notes.append(f"opens with corpus-overrepresented word(s) {sig.overused_opening_hits}")

    # Non-repetition: corpus-wide repeated-opener check.
    for t in assistant_texts(record):
        opener = " ".join(t.strip().split()[:4]).lower()
        if opener and opener_counter.get(opener, 0) >= 8:
            non_repetition -= 1
            flags.append("REPETITIVE_OPENING")
            notes.append(f"opener {opener!r} reused across {opener_counter[opener]} conversations in this corpus")
            break

    # Pet name / emoji device overuse WITHIN a single conversation.
    if sig.pet_name_count >= 2:
        flags.append("PET_NAME_OVERUSE")
        notes.append(f"{sig.pet_name_count} pet-name uses in one conversation")
        contextual_appropriateness -= 1
    if sig.emoji_count >= 3:
        flags.append("EMOJI_OVERUSE")
        notes.append(f"{sig.emoji_count} emoji in one conversation")
        contextual_appropriateness -= 1

    # Factual / RAG discipline — highest-stakes dimension.
    if sig.fake_rag_attribution:
        factual_grounding -= 4
        flags.append("FAKE_RAG_ATTRIBUTION")
        notes.append("uses platform-attribution phrasing with no Retrieved context block backing it")
    if sig.unsupported_platform_fact:
        factual_grounding -= 3
        flags.append("UNSUPPORTED_PLATFORM_FACT")
        notes.append("states a specific platform-fact-shaped claim (fee/timeline/number) without retrieved grounding")
    if sig.invented_precision and not sig.unsupported_platform_fact:
        factual_grounding -= 1
        flags.append("INVENTED_PRECISION")
        notes.append("contains a specific number that isn't clearly grounded — verify it's illustrative reasoning, not asserted fact")

    naturalness = _clamp(naturalness)
    language_quality = _clamp(language_quality)
    rupsaa_identity = _clamp(rupsaa_identity)
    contextual_appropriateness = _clamp(contextual_appropriateness)
    non_repetition = _clamp(non_repetition)
    factual_grounding = _clamp(factual_grounding)

    scores = DimensionScores(
        naturalness=naturalness,
        language_quality=language_quality,
        rupsaa_identity=rupsaa_identity,
        contextual_appropriateness=contextual_appropriateness,
        non_repetition=non_repetition,
        factual_grounding=factual_grounding,
    )

    if not flags:
        notes.append("no automated flags raised")

    # Recommendation.
    has_reject_signal = (
        scores.factual_grounding == 1
        or "FAKE_RAG_ATTRIBUTION" in flags
        or scores.naturalness == 1
        or scores.language_quality == 1
    )
    if has_reject_signal:
        recommendation = "WEAK"
    elif scores.total >= 26 and min(
        naturalness, language_quality, rupsaa_identity, contextual_appropriateness, non_repetition, factual_grounding
    ) >= 4:
        recommendation = "STRONG"
    elif scores.total <= 18 or scores.factual_grounding <= 2:
        recommendation = "WEAK"
    else:
        recommendation = "NEEDS_EDIT"

    return VoiceAuditResult(
        conversation_id=record.id,
        category=record.category,
        language=record.language,
        current_status=record.quality_status,
        scores=scores,
        recommendation=recommendation,
        flags=sorted(set(flags)),
        review_notes="; ".join(notes),
    )


def build_opener_counter(records: list[ConversationRecord]) -> Counter:
    counter: Counter = Counter()
    for r in records:
        for t in assistant_texts(r):
            opener = " ".join(t.strip().split()[:4]).lower()
            if opener:
                counter[opener] += 1
    return counter
