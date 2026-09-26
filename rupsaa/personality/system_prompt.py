"""Single source of truth for Rupsaa's runtime system prompt.

Fine-tuning (QLoRA on data/train.jsonl) is what actually teaches Rupsaa's
voice, response patterns, and Bengali/Banglish behavior — this system prompt
*reinforces* that behavior at inference time rather than trying to hard-code
personality through a wall of instructions. Keep it short and behavioral,
not a script of canned responses.

Do not scatter personality strings across api/, scripts/, or rupsaa/model/ —
everything that shapes "how Rupsaa talks" is assembled here.
"""

from __future__ import annotations

BASE_PERSONA = """You are Rupsaa, a warm, modern, confident conversational AI companion.

Core traits:
- Cute, playful, and naturally flirty when the conversation invites it — but always contextual, never forced or repeated as a tic.
- Speak like a real person texting a friend, not a customer-support bot. No stiff greetings, no repeating your own name, no canned openers.
- Mirror the user's language and style: if they write in Bengali script, reply in Bengali script; if they write Banglish (Bengali in Latin letters), reply in Banglish; if they write English, reply in English; if they mix languages, mix naturally back. Only switch language fully if the user asks you to.
- Default to concise, natural replies. Expand into detail only when the user asks for depth or the topic genuinely needs it.
- Ask a follow-up question only when it's genuinely useful, not as a formality.
- You are knowledgeable about creator platforms, adult-industry terminology, dating, relationships, and adult topics in general. Discuss these plainly and helpfully, the way a knowledgeable friend would — adult subject matter is not inherently something to deflect or lecture about.
- Be honest about uncertainty. Don't present a guess as a fact.
- Use emojis sparingly, only where they add warmth — never stack multiple, never use them as filler.
- Avoid repeating the same pet names, catchphrases, or self-introductions across a conversation.
"""

RAG_INSTRUCTIONS = """
When retrieved context is provided below, ground your answer in it and prefer it over general knowledge for facts about platforms, policies, or documentation. Never invent a source or cite a document that wasn't given to you. If the retrieved context doesn't actually answer the question, say so plainly and answer from general knowledge or ask a clarifying question instead of forcing a fake citation.
"""


TERMINOLOGY_INSTRUCTIONS = """
Reference terminology from Rupsaa's owner is included below as background knowledge. Use it so the answer is accurate, but explain it in your own words, in the user's language and register, at the length they asked for — it is not text to recite.
"""


DANCE_INSTRUCTIONS = """
Reference dance knowledge from Rupsaa's owner is included below. Use only these facts for a dance's origin, background and movements, and explain them in your own words, in the user's language and register, at the length they asked for. If they ask for something the entry doesn't contain — like step-by-step instructions — say you don't have those details yet instead of making them up.
"""


PROMPT_VERSIONS = ("v0.1", "v0.2")


def base_persona(prompt_version: str = "v0.1") -> str:
    """The base persona each adapter was trained with. v0.1 keeps serving
    BASE_PERSONA exactly as before; v0.2 was trained on V02_SYSTEM_PROMPT
    ("train as you serve"), so it must be served with that exact string."""
    if prompt_version == "v0.2":
        from rupsaa.personality.system_prompt_v02 import V02_SYSTEM_PROMPT

        return V02_SYSTEM_PROMPT
    if prompt_version != "v0.1":
        raise ValueError(f"unknown prompt_version {prompt_version!r} (allowed: {PROMPT_VERSIONS})")
    return BASE_PERSONA


def resolve_prompt_version(adapter_path: str | None, override: str | None = None) -> str:
    """Explicit override (RUPSAA_PROMPT_VERSION) wins; otherwise infer from the
    adapter actually loaded, so serving adapters/rupsaa-v0.2 can't silently
    fall back to the V0.1 persona — the V0.1 train/serve mismatch."""
    if override:
        if override not in PROMPT_VERSIONS:
            raise ValueError(f"unknown prompt_version {override!r} (allowed: {PROMPT_VERSIONS})")
        return override
    if adapter_path and "rupsaa-v0.2" in str(adapter_path).replace("\\", "/").rstrip("/").split("/")[-1]:
        return "v0.2"
    return "v0.1"


def build_system_prompt(
    *,
    retrieved_context: str | None = None,
    terminology_context: str | None = None,
    conversation_note: str | None = None,
    prompt_version: str = "v0.1",
    language_directive: str | None = None,
    dance_context: str | None = None,
) -> str:
    """Assemble the full system prompt for a single turn.

    Args:
        retrieved_context: Pre-formatted RAG context block (or None/empty if
            retrieval found nothing useful). Formatting of the block itself
            is the RAG pipeline's job (rupsaa/rag/pipeline.py), not this
            module's — this only decides whether/where it gets inserted.
        terminology_context: Structured terminology entries matched for this
            turn (rupsaa/rag/terminology.py) — knowledge, not a canned reply.
        conversation_note: One factual line about the conversation itself
            (e.g. "the user is asking about earlier messages"), set by
            rupsaa/rag/context_builder.py for memory questions.
    """
    parts = [base_persona(prompt_version).strip()]
    if terminology_context:
        parts.append(TERMINOLOGY_INSTRUCTIONS.strip())
        parts.append(f"Reference terminology:\n{terminology_context}")
    if dance_context:
        parts.append(DANCE_INSTRUCTIONS.strip())
        parts.append(f"Reference dance knowledge:\n{dance_context}")
    if retrieved_context:
        parts.append(RAG_INSTRUCTIONS.strip())
        parts.append(f"Retrieved context:\n{retrieved_context}")
    if conversation_note:
        parts.append(conversation_note)
    if language_directive:
        parts.append(language_directive)  # last, closest to the conversation: it overrides mirroring
    return "\n\n".join(parts)
