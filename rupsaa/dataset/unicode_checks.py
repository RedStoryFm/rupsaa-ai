"""Unicode integrity checks for Bengali/Banglish/English/mixed text.

Deliberately narrow: this catches genuine encoding corruption (replacement
characters, unpaired surrogates, stray control characters, encode/decode
round-trip failures) — it does not try to validate "correct" Bengali
grammar or spelling, which is a human review judgment, not a mechanical
check.
"""

from __future__ import annotations

import unicodedata

_REPLACEMENT_CHAR = "�"

# Control characters that should never appear in normal conversational text.
# \n and \t are allowed.
_DISALLOWED_CONTROL_CHARS = {
    chr(c) for c in range(0x00, 0x20) if chr(c) not in ("\n", "\t")
} | {chr(0x7F)}


def check_text_unicode(text: str) -> list[str]:
    """Returns a list of issue descriptions; empty list means clean."""
    issues: list[str] = []
    if not text:
        return issues

    if _REPLACEMENT_CHAR in text:
        issues.append("contains U+FFFD replacement character (likely corrupted encoding)")

    for ch in text:
        if ch in _DISALLOWED_CONTROL_CHARS:
            issues.append(f"contains disallowed control character U+{ord(ch):04X}")
            break  # one mention is enough, don't spam per-character

    try:
        text.encode("utf-8").decode("utf-8")
    except UnicodeError:
        issues.append("failed UTF-8 encode/decode round-trip")

    for ch in text:
        if unicodedata.category(ch) == "Cs":  # surrogate
            issues.append("contains an unpaired UTF-16 surrogate code point")
            break

    return issues


def check_messages_unicode(messages: list[dict]) -> list[str]:
    issues: list[str] = []
    for i, m in enumerate(messages):
        for issue in check_text_unicode(m.get("content", "")):
            issues.append(f"message {i} ({m.get('role')}): {issue}")
    return issues
