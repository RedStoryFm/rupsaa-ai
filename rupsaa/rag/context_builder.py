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

from collections.abc import Callable
from dataclasses import dataclass, field

from rupsaa.conversation.language_control import resolve_turn_language
from rupsaa.rag.router import Route, RouteDecision, classify_message
from rupsaa.rag.terminology import TerminologyStore, format_terminology_context


@dataclass
class TurnKnowledge:
    decision: RouteDecision
    retrieved_context: str | None = None
    sources: list[dict] = field(default_factory=list)
    terminology_context: str | None = None
    terms_used: list[str] = field(default_factory=list)
    conversation_note: str | None = None
    language: str | None = None  # explicitly requested reply language ("bn"/"banglish"/"en")
    language_state: dict | None = None  # per-conversation language choice to keep for the next turn

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

    matches = []
    if terminology is not None:
        if decision.route == Route.FOLLOWUP:
            by_id = {r.id: r for r in terminology.list(include_disabled=False)}
            matches = [_Carried(by_id[t]) for t in previous_terms or [] if t in by_id]
            # "strip ta simple kore bojhao" names the term itself; a newly named term joins the carried one.
            carried = set(previous_terms or [])
            matches += [m for m in terminology.lookup(message) if m.record.id not in carried]
            matches = matches[:2]
        elif decision.use_terminology:
            matches = terminology.lookup(message, decision.term_candidate)
    if decision.route == Route.FOLLOWUP and history_messages == 0:
        out.conversation_note = ("The user refers to an earlier answer, but this conversation has no earlier messages yet — "
                                 "ask what they would like explained instead of guessing a topic.")
    if matches:
        out.terminology_context = format_terminology_context(matches)
        out.terms_used = [m.record.id for m in matches]

    wants_documents = use_rag and rag_query is not None and decision.use_documents
    if decision.route == Route.TERMINOLOGY and matches:
        wants_documents = False  # the structured entry answers it; don't dilute with chunks
    if wants_documents:
        out.retrieved_context, out.sources = rag_query(message, strict=decision.strict_documents)
    return out


MAX_RECALL_MESSAGES = 12
MAX_RECALL_CHARS = 300


def memory_note(history: list | None, history_messages: int, history_truncated: bool, question: str = "") -> str:
    """Conversation-recall note: the user's own messages before the recall question as a
    numbered, oldest-first list (the chat history itself also follows the system prompt).
    Facts are only *listed* — which one answers the question is the model's job. The note
    quotes the question, so it stays true for every turn of a conversation (serving == training)."""
    user_msgs = [m.content for m in (history or []) if getattr(m, "role", None) == "user"]
    q = question.strip()[:200]
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
