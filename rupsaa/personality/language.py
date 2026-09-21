"""Lightweight language/script detection for mirroring the user's language.

This is a heuristic, not a classifier model — good enough to (a) tag API
responses with an approximate language code and (b) tell the system prompt
which register to lean into. It intentionally does not try to be a precise
language identifier; fine-tuning is what actually teaches Rupsaa to mirror
the user, not this module.
"""

from __future__ import annotations

import re

_BENGALI_RANGE = re.compile(r"[ঀ-৿]")

# Common Banglish (Bengali written in Latin script) function words / markers.
# Not exhaustive — a signal, not a dictionary.
_BANGLISH_MARKERS = {
    "ami", "tumi", "tui", "amar", "tomar", "ke", "kemon", "acho", "achi",
    "bhalo", "kotha", "bolo", "bolbo", "korbo", "koro", "kore", "korchi",
    "kirokom", "ekhon", "ajke", "kal", "keno", "naki", "hobe", "hoyeche",
    "bujhte", "bujhi", "chai", "lagbe", "dada", "didi", "sona", "jaan",
}

_ENGLISH_STOPWORDS = {
    "the", "is", "are", "you", "what", "how", "why", "hello", "hi", "hey",
    "can", "could", "would", "please", "thanks", "thank",
}


def detect_language(text: str) -> str:
    """Returns one of: 'bn' (Bengali script), 'banglish', 'en', 'mixed'.

    'mixed' means both Bengali script and English words/Banglish markers
    were detected in the same message (code-switching).
    """
    if not text or not text.strip():
        return "en"

    has_bengali_script = bool(_BENGALI_RANGE.search(text))

    words = re.findall(r"[a-zA-Z']+", text.lower())
    word_set = set(words)
    has_banglish = bool(word_set & _BANGLISH_MARKERS)
    has_english = bool(word_set & _ENGLISH_STOPWORDS) or (
        bool(words) and not has_banglish and not has_bengali_script
    )

    if has_bengali_script and (has_banglish or has_english):
        return "mixed"
    if has_bengali_script:
        return "bn"
    if has_banglish and has_english:
        return "mixed"
    if has_banglish:
        return "banglish"
    return "en"
