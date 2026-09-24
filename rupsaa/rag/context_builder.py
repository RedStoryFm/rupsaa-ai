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
) -> TurnKnowledge:
    """`use_rag` is the user's document-RAG toggle; it gates *documents* only.
    Owner-curated terminology is small, deterministic and always consulted
    for definition questions (a "Strip mane ki?" answer shouldn't depend on a
    UI checkbox). `rag_query(question, strict=...)` is RagPipeline.query."""
    decision = classify_message(message)
    out = TurnKnowledge(decision=decision)

    if decision.route == Route.MEMORY:
        note = (
            "The user is asking about something said earlier in this conversation. "
            "The conversation so far is above — answer from it directly."
        )
        if history_messages == 0:
            note = "The user is asking about earlier messages, but this conversation has no earlier messages yet."
        elif history_truncated:
            note += " Only the most recent messages are kept; if what they ask about isn't there, say it's too far back."
        out.conversation_note = note
        return out

    matches = []
    if terminology is not None:
        if decision.route == Route.FOLLOWUP and previous_terms:
            by_id = {r.id: r for r in terminology.list(include_disabled=False)}
            matches = [_Carried(by_id[t]) for t in previous_terms if t in by_id]
        elif decision.use_terminology:
            matches = terminology.lookup(message, decision.term_candidate)
    if matches:
        out.terminology_context = format_terminology_context(matches)
        out.terms_used = [m.record.id for m in matches]

    wants_documents = use_rag and rag_query is not None and decision.use_documents
    if decision.route == Route.TERMINOLOGY and matches:
        wants_documents = False  # the structured entry answers it; don't dilute with chunks
    if wants_documents:
        out.retrieved_context, out.sources = rag_query(message, strict=decision.strict_documents)
    return out


@dataclass
class _Carried:
    """Adapter so carried-over TermRecords format like fresh TermMatches."""
    record: object
