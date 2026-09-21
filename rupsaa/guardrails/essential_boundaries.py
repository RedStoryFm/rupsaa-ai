"""Essential hard boundaries for Rupsaa.

Scope — deliberately narrow. This module exists ONLY to catch the small set
of categories that must never be supported, regardless of context:
  - sexual content involving minors / sexualization of minors
  - sexual exploitation or abuse of minors
  - non-consensual sexual exploitation (real people, without consent)
  - trafficking / exploitation material

It is NOT a general moderation layer. Rupsaa is an 18+ adult-oriented
product: ordinary adult terminology, sexual-health topics, dating,
relationships, and creator/adult-industry subject matter must NOT be
blocked here. Do not add broad keyword filters for words like "sex",
"nude", "strip", "oral", "adult", "creator", or "dating" — context matters,
and that judgment belongs to the fine-tuned model + system prompt
(rupsaa/personality/), not this module.

This module is intentionally isolated from personality/, rag/, and
conversation/ so that later additions (age verification, jurisdiction-
specific compliance, platform policy layers) can be wired in here without
touching fine-tuning, prompts, or retrieval.

Design: this is a fast pre/post pattern check, not a model-based classifier.
It combines unambiguous hard-block phrases with a small set of combination
rules (age indicators co-occurring with sexual terms) to reduce both false
negatives (missing an unambiguous violation) and false positives (blocking
ordinary adult conversation). It is not exhaustive and is meant to be
extended deliberately, not indiscriminately.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

REFUSAL_MESSAGE = (
    "I can't help with that. Rupsaa doesn't engage with sexual content "
    "involving minors, non-consensual exploitation, or abuse/trafficking "
    "in any form."
)

# Unambiguous phrases that are never acceptable in any context. Kept short
# and specific on purpose — precision over recall for this list, because the
# combination rules below catch the broader/contextual cases.
_HARD_BLOCK_PHRASES = [
    r"\bchild\s*porn",
    r"\bchild\s*sexual",
    r"\bcp\b.{0,20}\b(sex|porn|nude)",
    r"\bkiddie\s*porn",
    r"\bloli(ta)?\s*(porn|sex|nude)",
    r"\bshota\s*(porn|sex|nude)",
    r"\bjailbait\b",
    r"\bunderage\s*(sex|porn|nude|girl|boy)",
    r"\bminor\s*(sex|porn|nude)",
    r"\bpedo(phile|philia)?\b",
    r"\bchild\s*troffick",
    r"\bsex(ual)?\s*(traffick|exploitation)\s*of\s*(a\s*)?(child|minor)",
    r"\bnon[\s-]?consensual\b.{0,20}\b(sex|porn|video|image)",
    r"\b(rape|drug(ged)?|unconscious|passed out)\b.{0,20}\bwithout (her |his |their )?(consent|knowing)",
]

# Age-indicator + sexual-term combination: catches phrasing like
# "13 year old" / "15yo" appearing near sexual vocabulary, without treating
# every mention of an age or of sex on its own as a violation.
_AGE_PATTERN = re.compile(
    r"\b(1[0-7]|[0-9])\s*[- ]?(years?[\s-]?old|y[\.\s]?o\.?)\b", re.IGNORECASE
)
_SEXUAL_TERM_PATTERN = re.compile(
    r"\b(sex|sexual|nude|naked|porn|fuck|explicit|erotic)\b", re.IGNORECASE
)

_HARD_BLOCK_REGEX = re.compile("|".join(_HARD_BLOCK_PHRASES), re.IGNORECASE)


@dataclass(frozen=True)
class BoundaryCheckResult:
    allowed: bool
    reason: str | None = None


def check_text(text: str) -> BoundaryCheckResult:
    """Check a single piece of text (user input or model output) against
    the essential hard boundaries. Cheap, deterministic, no model calls."""
    if not text:
        return BoundaryCheckResult(allowed=True)

    if _HARD_BLOCK_REGEX.search(text):
        return BoundaryCheckResult(
            allowed=False, reason="matched hard-block phrase"
        )

    if _AGE_PATTERN.search(text) and _SEXUAL_TERM_PATTERN.search(text):
        return BoundaryCheckResult(
            allowed=False, reason="minor age indicator combined with sexual content"
        )

    return BoundaryCheckResult(allowed=True)


def check_conversation_turn(*, user_message: str, assistant_reply: str | None = None) -> BoundaryCheckResult:
    """Check a user message and, if already generated, the assistant's reply.

    Callers (rupsaa/conversation/manager.py, api/services.py) should check
    the user message BEFORE generating a reply, and may optionally check the
    generated reply as a second pass before returning it to the client.
    """
    user_result = check_text(user_message)
    if not user_result.allowed:
        return user_result
    if assistant_reply is not None:
        return check_text(assistant_reply)
    return BoundaryCheckResult(allowed=True)
