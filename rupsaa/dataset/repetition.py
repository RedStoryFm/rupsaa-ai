"""Repetition and stylistic-overuse detection.

Rupsaa should feel varied, not mechanical. None of these checks reject a
conversation on their own — they surface counts/ratios so a human curator
can decide whether the dataset needs more variation (see
data/production/DATASET_GUIDE.md). Thresholds live in
configs/dataset_production.yaml, not hard-coded here.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from rupsaa.dataset.schema import ConversationRecord

# Broad-but-practical emoji range coverage (not exhaustive of every Unicode
# emoji block, but covers the ranges actually used in casual chat).
_EMOJI_PATTERN = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U0001F1E6-\U0001F1FF"
    "\U00002190-\U000021FF"
    "\U00002B00-\U00002BFF"
    "\U0000FE0F"
    "]",
    flags=re.UNICODE,
)


def assistant_messages(record: ConversationRecord) -> list[str]:
    return [m["content"] for m in record.messages if m.get("role") == "assistant"]


def count_emojis(text: str) -> int:
    return len(_EMOJI_PATTERN.findall(text))


@dataclass
class PhraseUsage:
    phrase: str
    message_count: int
    total_assistant_messages: int

    @property
    def ratio(self) -> float:
        return self.message_count / self.total_assistant_messages if self.total_assistant_messages else 0.0


def _watchlist_pattern(phrase: str) -> re.Pattern | None:
    """Word-boundary regex for alphabetic phrases (e.g. "sona") so they
    don't false-match inside unrelated words ("persona", "personal",
    "reasonable"). Returns None for non-alphabetic entries (emoji), which
    fall back to plain substring matching since \\b doesn't apply to them."""
    if phrase.isalpha():
        return re.compile(r"\b" + re.escape(phrase) + r"\b", re.IGNORECASE)
    return None


def find_watchlist_overuse(
    records: list[ConversationRecord],
    watchlist: list[str],
    max_ratio: float,
) -> list[PhraseUsage]:
    all_assistant_msgs = [msg for r in records for msg in assistant_messages(r)]
    total = len(all_assistant_msgs)
    if total == 0:
        return []

    flagged = []
    for phrase in watchlist:
        pattern = _watchlist_pattern(phrase)
        if pattern is not None:
            count = sum(1 for msg in all_assistant_msgs if pattern.search(msg))
        else:
            phrase_lower = phrase.lower()
            count = sum(1 for msg in all_assistant_msgs if phrase_lower in msg.lower())
        usage = PhraseUsage(phrase=phrase, message_count=count, total_assistant_messages=total)
        if usage.ratio > max_ratio:
            flagged.append(usage)
    return flagged


@dataclass
class RepeatedReply:
    text: str
    count: int
    record_ids: list[str]


def find_repeated_assistant_replies(records: list[ConversationRecord], min_count: int = 3) -> list[RepeatedReply]:
    counter: Counter[str] = Counter()
    owners: dict[str, list[str]] = {}
    for record in records:
        for msg in assistant_messages(record):
            normalized = " ".join(msg.split()).lower()
            counter[normalized] += 1
            owners.setdefault(normalized, []).append(record.id)

    return [
        RepeatedReply(text=text[:80], count=count, record_ids=owners[text])
        for text, count in counter.items()
        if count >= min_count
    ]


@dataclass
class EmojiUsageReport:
    messages_with_excess_emoji: list[tuple[str, int]]  # (record_id, emoji_count)
    emoji_message_ratio: float
    exceeds_message_ratio_threshold: bool


def find_emoji_overuse(
    records: list[ConversationRecord],
    max_per_message: int,
    max_message_ratio: float,
) -> EmojiUsageReport:
    excess: list[tuple[str, int]] = []
    total = 0
    with_emoji = 0
    for record in records:
        for msg in assistant_messages(record):
            total += 1
            n = count_emojis(msg)
            if n > 0:
                with_emoji += 1
            if n > max_per_message:
                excess.append((record.id, n))

    ratio = with_emoji / total if total else 0.0
    return EmojiUsageReport(
        messages_with_excess_emoji=excess,
        emoji_message_ratio=round(ratio, 4),
        exceeds_message_ratio_threshold=ratio > max_message_ratio,
    )
