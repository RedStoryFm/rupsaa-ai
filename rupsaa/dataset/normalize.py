"""Text normalization for imported conversations.

Applies Unicode NFC normalization (important for Bengali, where the same
visual glyph can be represented by different combining-character sequences)
and strips genuinely invisible junk characters, while deliberately
preserving ZWJ/ZWNJ (U+200D / U+200C) — these are typographically meaningful
in Bengali conjunct formation and must never be stripped.
"""

from __future__ import annotations

import re
import unicodedata

# Characters that are pure noise and safe to strip: BOM and zero-width space.
# ZWJ (U+200D) and ZWNJ (U+200C) are intentionally NOT in this set.
_STRIP_CHARS = "﻿​"
_STRIP_TABLE = str.maketrans("", "", _STRIP_CHARS)

_MULTI_SPACE = re.compile(r"[ \t]+")
_MULTI_BLANK_LINE = re.compile(r"\n{3,}")


def normalize_text(text: str) -> str:
    if text is None:
        return text
    text = unicodedata.normalize("NFC", text)
    text = text.translate(_STRIP_TABLE)
    text = _MULTI_SPACE.sub(" ", text)
    text = _MULTI_BLANK_LINE.sub("\n\n", text)
    return text.strip()


def normalize_messages(messages: list[dict]) -> list[dict]:
    return [
        {**m, "content": normalize_text(m.get("content", ""))}
        for m in messages
    ]
