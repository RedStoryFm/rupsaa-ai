"""Explicit response-language requests ("banglay bolo", "বাংলায় বলো", "english e bolo").

Why: the V0.2 system prompt only says "mirror the user's language … only
switch fully if asked", and V0.2's training data has 5 switch requests in
1,938 turns (1 towards Bengali script). Live, "এটা বাংলায় বুঝিয়ে বলো" after a
Banglish answer came back in Banglish: nothing in the turn told the model
*which* script the user had asked for. This module turns an explicit request
into a one-line directive for the system prompt, and carries it over to the
follow-ups that reformulate the same answer ("short kore bolo") — generic
rules, no canned replies.

Languages: "bn" = Bengali in Bengali script, "banglish" = Bengali written in
Latin letters, "en" = English.
"""

from __future__ import annotations

import re

_BN = "ঀ-৿"
_B = rf"(?<![A-Za-z{_BN}])"

# Order matters: "banglish" must be tested before "bangla".
_REQUEST_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("banglish", re.compile(
        rf"{_B}(?:banglish|benglish|romanized bengali|roman horofe|english letter(?:s)? e)\s*(?:e|a|te|y)?(?:-?i)?\s*"
        rf"(?:bolo|bol|bolen|likho|lekho|explain|bujhao|bojhao|bujhiye|bojhiye|kotha|reply|answer|koro|korbe|bolbe|please|pls)"
        rf"|(?:in|into|switch to)\s+banglish|বাংলিশে", re.I)),
    ("bn", re.compile(
        rf"{_B}(?:bangla\s?(?:y|te|e|ey|ay|hoy)(?:-?i)?|banglay(?:-?i)?|bengali\s?(?:te|e|y)(?:-?i)?|bangla\s+(?:hoorofe|horofe|script e)|"
        rf"bengali script e)\s*(?:bujhiye|bojhiye|bujhie)?\s*"
        rf"(?:bolo|bol|bolen|likho|lekho|explain|bujhao|bojhao|kotha|reply|answer|koro|korbe|bolbe|please|pls)?(?![A-Za-z])"
        rf"|(?:in|into|switch to)\s+(?:bengali|bangla)(?:\s+script)?"
        r"|বাংলায়|বাংলাতে|বাংলা ভাষায়|বাংলা হরফে", re.I)),
    ("en", re.compile(
        rf"{_B}(?:english\s?(?:e|a|y|te|ey)(?:-?i)?)\s*(?:bolo|bol|bolen|likho|lekho|explain|bujhao|bojhao|kotha|reply|answer|koro|korbe|bolbe|please|pls)?(?![A-Za-z])"
        rf"|(?:in|into|switch to)\s+english|ইংরেজিতে|ইংলিশে", re.I)),
]

# "from now on" markers make the choice stick until the user asks for another language.
_PERSIST_RE = re.compile(
    rf"{_B}(?:ekhon theke|akhon theke|ebar theke|from now on|always|sob somoy|shob shomoy|shobshomoy)|এখন থেকে|এবার থেকে|সবসময়", re.I)

_LANG_TEXT = {
    "bn": ("Bengali", "write in Bengali script (বাংলা হরফে) — not Banglish, not Latin letters; common English terms may stay in English"),
    "banglish": ("Banglish", "write Bengali in Latin letters (Banglish, e.g. \"eta mane …\") — no Bengali script"),
    "en": ("English", "write in English"),
}

# The directive quotes the request, so it is true for every turn of the conversation — including the
# earlier ones — which keeps serving and training identical (LLaMA-Factory 0.7.1 trains every
# assistant turn under the one system prompt of a record).
DIRECTIVE_TEMPLATE = ("Response language: in the message \"{request}\" the user explicitly asked for {name}. "
                      "From that message on, {how}.")
STICKY_SUFFIX = " Keep this until the user asks for a different language."
TURN_SUFFIX = " This covers that answer and follow-ups about it; after that, mirror the user's language again."


def requested_language(message: str) -> str | None:
    """The language the user explicitly asks the reply to be in, if any."""
    for lang, pat in _REQUEST_PATTERNS:
        if pat.search(message):
            return lang
    return None


def is_persistent_request(message: str) -> bool:
    return bool(_PERSIST_RE.search(message))


def resolve_turn_language(message: str, route: str, state: dict | None) -> tuple[str | None, dict | None]:
    """Language to enforce for this turn + the per-conversation state to keep.

    state = {"lang": "bn"|"banglish"|"en", "sticky": bool, "request": str} or None.
    - an explicit request sets the language for this turn (sticky if "from now on")
    - a non-sticky choice carries over to follow-ups/memory turns that rework the
      previous answer, and ends at the next ordinary message (mirroring resumes)
    - a sticky choice lasts until the user asks for another language
    """
    lang = requested_language(message)
    if lang:
        new_state = {"lang": lang, "sticky": is_persistent_request(message), "request": message.strip()[:200]}
        return lang, new_state
    if state:
        if state.get("sticky") or route in ("followup", "memory"):
            return state["lang"], state
    return None, None


def directive_for(state: dict | None) -> str | None:
    """System-prompt line for an active explicit language choice (the state from resolve_turn_language)."""
    if not state or state.get("lang") not in _LANG_TEXT:
        return None
    name, how = _LANG_TEXT[state["lang"]]
    text = DIRECTIVE_TEMPLATE.format(request=state.get("request", ""), name=name, how=how)
    return text + (STICKY_SUFFIX if state.get("sticky") else TURN_SUFFIX)
