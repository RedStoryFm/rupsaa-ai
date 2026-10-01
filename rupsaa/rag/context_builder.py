"""Per-turn knowledge assembly: route → terminology / documents / history note.

Single place that turns a user message into the knowledge blocks for the
system prompt, used by api/services.py and scripts/chat.py so both entry
points behave identically:

    message ──> router.classify_message ──┬─ MEMORY    → conversation note only (history answers it)
                                          ├─ FOLLOWUP  → previous turn's terminology carried over
                                          ├─ TERMINOLOGY → terminology store (+ strict document fallback)
                                          ├─ KNOWLEDGE → documents (+ any terms the message mentions)
                                          ├─ CASUAL    → nothing
                                          └─ GENERAL   → documents, strict relevance only

The model always receives knowledge as *reference material* (see
rupsaa/personality/system_prompt.py), never as a canned reply.
"""

from __future__ import annotations

import re

from collections.abc import Callable
from dataclasses import dataclass, field

from rupsaa.conversation.language_control import resolve_turn_language
from rupsaa.rag.dance import DanceStore, format_dance_context
from rupsaa.rag.general_knowledge import GeneralKnowledgeStore, format_general_context
from rupsaa.rag.router import Route, RouteDecision, classify_message
from rupsaa.rag.terminology import TerminologyStore, contains_phrase, format_terminology_context


@dataclass
class TurnKnowledge:
    decision: RouteDecision
    retrieved_context: str | None = None
    sources: list[dict] = field(default_factory=list)
    terminology_context: str | None = None
    terms_used: list[str] = field(default_factory=list)  # terminology AND dance record ids
    dance_context: str | None = None
    conversation_note: str | None = None
    language: str | None = None  # explicitly requested reply language ("bn"/"banglish"/"en")
    language_state: dict | None = None  # per-conversation language choice to keep for the next turn
    general_context: str | None = None  # owner General Knowledge records (knowledge/general)
    # Internal retrieval metadata (logs/trace only, never shown in chat): source, record_id, category, match, score.
    retrieval: list[dict] = field(default_factory=list)

    @property
    def route(self) -> str:
        return self.decision.route.value


def build_turn_knowledge(
    message: str,
    *,
    use_rag: bool,
    rag_query: Callable[..., tuple[str | None, list[dict]]] | None,
    terminology: TerminologyStore | None,
    previous_terms: list[str] | None = None,
    history_messages: int = 0,
    history_truncated: bool = False,
    history: list | None = None,
    language_state: dict | None = None,
    dance: DanceStore | None = None,
    general: GeneralKnowledgeStore | None = None,
) -> TurnKnowledge:
    """`use_rag` is the user's document-RAG toggle; it gates *documents* only.
    Owner-curated terminology is small, deterministic and always consulted
    for definition questions (a "Strip mane ki?" answer shouldn't depend on a
    UI checkbox). `rag_query(question, strict=...)` is RagPipeline.query.
    `history` (ChatMessage-like objects with .role/.content) feeds the
    structured recall block for memory questions; `language_state` is the
    conversation's explicit language choice (rupsaa.conversation.language_control)."""
    decision = classify_message(message)
    out = TurnKnowledge(decision=decision)
    out.language, out.language_state = resolve_turn_language(message, decision.route.value, language_state)

    if decision.route == Route.MEMORY:
        out.conversation_note = memory_note(history, history_messages, history_truncated, question=message)
        return out

    mode = _lookup_mode(decision, message)
    matches = _reference_matches(terminology, decision, message, previous_terms, mode)
    dance_matches = _reference_matches(dance, decision, message, previous_terms, mode)
    if dance is not None and not dance_matches and decision.route == Route.CASUAL and dance.mentions_dancing(message):
        # Short messages are routed CASUAL ("chacha dance kemon?"); an explicit dance mention still counts.
        dance_matches = dance.lookup(message)
    if decision.route == Route.FOLLOWUP and history_messages == 0:
        out.conversation_note = ("The user refers to an earlier answer, but this conversation has no earlier messages yet — "
                                 "ask what they would like explained instead of guessing a topic.")
    # General Knowledge: carried on follow-ups; otherwise only when the specialised stores found nothing
    # (priority: exact/specialised terminology & dance first, then General Knowledge exact → strong semantic).
    general_matches = []
    if general is not None:
        if decision.route == Route.FOLLOWUP:  # carry the active topic; no semantic search on "eta Bengali te bolo"
            by_id = {r.id: r for r in general.list(include_disabled=False)}
            general_matches = [_Carried(by_id[t]) for t in previous_terms or [] if t in by_id][:2]
        elif mode == "exact":
            if not (matches or dance_matches):
                general_matches = _exact_only(general.lookup(message, _short_candidate(message), semantic=False))
        elif mode == "full":
            if not (matches or dance_matches):
                general_matches = general.lookup(message, decision.term_candidate)
            elif not any(m.method == "exact" for m in matches + dance_matches):
                # A more specific General Knowledge name beats a looser specialised phrase hit:
                # "enthusiastic consent" (GK) over the Terminology entry "consent" found inside it.
                specific = [g for g in general.lookup(message, decision.term_candidate, semantic=False)
                            if g.method == "exact" or any(contains_phrase(g.matched, m.matched)
                                                          for m in matches + dance_matches)]
                if specific:
                    general_matches = specific
                    matches = [m for m in matches if not any(contains_phrase(g.matched, m.matched) for g in specific)]
                    dance_matches = [m for m in dance_matches
                                     if not any(contains_phrase(g.matched, m.matched) for g in specific)]
    if (previous_terms and not (matches or dance_matches or general_matches)
            and decision.route not in (Route.MEMORY, Route.FOLLOWUP) and _elliptical_followup(message)
            and not _names_new_topic(decision, message)):
        # "kono risk ache ki?", "আর প্রথমবার হলে?": a short question naming no topic of its own continues
        # the active topic (fresh/current-info questions, small talk and identity questions never do).
        matches = _carry(terminology, previous_terms)
        dance_matches = _carry(dance, previous_terms)
        general_matches = _carry(general, previous_terms)
    if matches:
        out.terminology_context = format_terminology_context(matches)
    if dance_matches:
        out.dance_context = format_dance_context(dance_matches)
    if general_matches:
        out.general_context = format_general_context(general_matches)
    out.terms_used = ([m.record.id for m in matches] + [m.record.id for m in dance_matches]
                      + [m.record.id for m in general_matches])
    out.retrieval = [
        {"source": src, "record_id": m.record.id, "category": getattr(m.record, "category", "") or src,
         "match": getattr(m, "method", "carried"), "score": getattr(m, "score", 1.0)}
        for src, ms in (("terminology", matches), ("dance", dance_matches), ("general", general_matches)) for m in ms]

    wants_documents = use_rag and rag_query is not None and decision.use_documents
    if decision.route == Route.TERMINOLOGY and (matches or dance_matches or general_matches):
        wants_documents = False  # the structured entry answers it; don't dilute with chunks
    if wants_documents:
        out.retrieved_context, out.sources = rag_query(message, strict=decision.strict_documents)
    return out


def _lookup_mode(decision, message: str) -> str | None:
    """How hard to look for curated knowledge in this message:
    None    — greetings / mood / small talk, memory questions, follow-ups (those carry the active topic);
    "exact" — a short (<= 3 words) non-question casual message: only if the whole message IS a title or alias
              (or a typo of one): "vagina", "condom?" — but never "breaking news" or "popping a balloon"
              via a common word inside them;
    "full"  — everything else (questions, longer messages, personal wording like "amar … ki korbo"):
              exact → whole-phrase name → strict semantic (score + name-coverage guards)."""
    from rupsaa.rag.router import is_smalltalk
    from rupsaa.rag.web_search import is_question

    if decision.route in (Route.MEMORY, Route.FOLLOWUP) or is_smalltalk(message):
        return None
    if decision.route == Route.CASUAL and not is_question(message):
        return "exact"
    return "full"


def _gk_candidate(decision, message: str) -> bool:
    """Kept for callers that only need a yes/no: is curated knowledge looked up for this message at all?"""
    return _lookup_mode(decision, message) is not None


def _short_candidate(message: str) -> str:
    return re.sub(r"[?？!.।,]+", " ", message).strip()


def _exact_only(found: list) -> list:
    return [m for m in found if m.method in ("exact", "fuzzy")]


_ELLIPTICAL_START = re.compile(r"^\s*(?:ar|r|aar|and|আর|এবং)\s", re.I)


def _elliptical_followup(message: str) -> bool:
    from rupsaa.conversation.internet_policy import is_fresh
    from rupsaa.rag.router import _IDENTITY_RE, is_smalltalk
    from rupsaa.rag.web_search import is_question

    words = re.findall(r"\w+", message)
    if not words or len(words) > 6 or is_smalltalk(message) or is_fresh(message) or _IDENTITY_RE.search(message):
        return False
    return is_question(message) or bool(_ELLIPTICAL_START.match(message))


def _names_new_topic(decision, message: str) -> bool:
    """"Kintsugi ki?" / "Kintsugi mane ki jano?" name a topic of their own (unknown here) — don't attach the previous
    one. "kono risk ache ki?" names only common words, so it still continues the active topic."""
    from rupsaa.owner.teaching import knowledge_check_topic
    from rupsaa.rag.terminology import _all_known_words, normalize

    topic = decision.term_candidate or knowledge_check_topic(message)
    return bool(topic) and not _all_known_words(normalize(topic))


def _carry(store, previous_ids: list[str] | None) -> list:
    if store is None:
        return []
    by_id = {r.id: r for r in store.list(include_disabled=False)}
    return [_Carried(by_id[t]) for t in previous_ids or [] if t in by_id][:2]


def _reference_matches(store, decision, message: str, previous_ids: list[str] | None, mode: str | None = None) -> list:
    """Owner reference entries (terminology or dance) for this turn. Follow-ups carry the
    previous turn's entries of this store; a newly named entry joins them."""
    if store is None:
        return []
    if decision.route == Route.FOLLOWUP:
        by_id = {r.id: r for r in store.list(include_disabled=False)}
        carried = [_Carried(by_id[t]) for t in previous_ids or [] if t in by_id]
        ids = {c.record.id for c in carried}
        # "strip ta simple kore bojhao" names the term itself; a newly named term joins the carried one.
        return (carried + [m for m in store.lookup(message) if m.record.id not in ids])[:2]
    if decision.use_terminology:
        return store.lookup(message, decision.term_candidate)
    if mode == "exact" or (mode == "full" and decision.route == Route.CASUAL):
        # Short casual message: "condom?" / "vagina" — the whole message must name the entry (or be a typo of it).
        found = store.lookup(message, _short_candidate(message))
        return found if mode == "full" else _exact_only(found)
    return []


MAX_RECALL_MESSAGES = 12
MAX_RECALL_CHARS = 300


def memory_note(history: list | None, history_messages: int, history_truncated: bool, question: str = "",
                long_term: bool = False) -> str:
    """Conversation-recall note: the user's own messages before the recall question as a
    numbered, oldest-first list (the chat history itself also follows the system prompt).
    Facts are only *listed* — which one answers the question is the model's job. The note
    quotes the question, so it stays true for every turn of a conversation (serving == training)."""
    user_msgs = [m.content for m in (history or []) if getattr(m, "role", None) == "user"]
    q = question.strip()[:200]
    if long_term:  # opted-in long-term memory (listed in another note) may hold the answer from an earlier chat
        lines = [f"In the message \"{q}\" the user asks about something they told you before. Answer from the "
                 "long-term memory list or from this conversation, whichever has it (the latest value wins), directly "
                 "and briefly, in the user's language. If neither has it, say so."]
        if user_msgs:
            lines.append("The user's messages in this conversation, oldest first:")
            lines += [f"{i + 1}. {m[:MAX_RECALL_CHARS]}" for i, m in enumerate(user_msgs[-MAX_RECALL_MESSAGES:])]
        return "\n".join(lines)
    if not user_msgs and history_messages == 0:
        return (f"In the message \"{q}\" the user asks about earlier messages, but there were no earlier "
                "messages in this conversation — say so.")
    lines = [f"In the message \"{q}\" the user asks about something they said earlier in this conversation. "
             "Answer it from the conversation itself (never from documents), directly and briefly, in the user's language."]
    if user_msgs:
        shown = user_msgs[-MAX_RECALL_MESSAGES:]
        first_no = len(user_msgs) - len(shown) + 1
        lines.append("The user's messages before that question, oldest first:")
        lines += [f"{first_no + i}. {m[:MAX_RECALL_CHARS]}" for i, m in enumerate(shown)]
    if history_truncated or (user_msgs and len(user_msgs) > MAX_RECALL_MESSAGES):
        lines.append("Older messages are no longer kept; if what they ask about isn't listed, say it's too far back.")
    return "\n".join(lines)


@dataclass
class _Carried:
    """Adapter so carried-over TermRecords format like fresh TermMatches."""
    record: object
