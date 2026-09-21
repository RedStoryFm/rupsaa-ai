"""Descriptive statistics and report rendering for the production dataset."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from rupsaa.dataset.schema import ConversationRecord


def approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


@dataclass
class DatasetStats:
    total: int = 0
    by_status: Counter = field(default_factory=Counter)
    by_category: Counter = field(default_factory=Counter)
    by_subcategory: Counter = field(default_factory=Counter)
    by_language: Counter = field(default_factory=Counter)
    by_tone: Counter = field(default_factory=Counter)
    by_conversation_length: Counter = field(default_factory=Counter)
    by_source_type: Counter = field(default_factory=Counter)
    message_count: int = 0
    approx_token_total: int = 0
    char_lengths: list[int] = field(default_factory=list)


def build_stats(records: list[ConversationRecord]) -> DatasetStats:
    stats = DatasetStats(total=len(records))
    for r in records:
        stats.by_status[r.quality_status] += 1
        stats.by_category[r.category] += 1
        stats.by_subcategory[r.subcategory or "(none)"] += 1
        stats.by_language[r.language] += 1
        stats.by_tone[r.tone or "(none)"] += 1
        stats.by_conversation_length[r.conversation_length or "(none)"] += 1
        stats.by_source_type[r.source_type] += 1
        stats.message_count += len(r.messages)
        conv_text = " ".join(m["content"] for m in r.messages)
        stats.approx_token_total += approx_tokens(conv_text)
        stats.char_lengths.append(len(conv_text))
    return stats


def length_distribution(lengths: list[int]) -> dict:
    if not lengths:
        return {}
    s = sorted(lengths)
    n = len(s)
    return {
        "min": s[0],
        "max": s[-1],
        "median": s[n // 2],
        "p90": s[int(n * 0.9)] if n > 1 else s[0],
    }


def render_markdown_report(title: str, stats: DatasetStats) -> str:
    lines = [f"# {title}", ""]
    lines.append(f"- Total conversations: **{stats.total}**")
    lines.append(f"- Total messages: **{stats.message_count}**")
    lines.append(f"- Approx. token count: **{stats.approx_token_total}**")
    lines.append("")

    def _section(name: str, counter: Counter) -> None:
        lines.append(f"## {name}")
        if not counter:
            lines.append("(no data)")
        for key, count in counter.most_common():
            pct = (count / stats.total * 100) if stats.total else 0
            lines.append(f"- {key}: {count} ({pct:.1f}%)")
        lines.append("")

    _section("Quality status", stats.by_status)
    _section("Category", stats.by_category)
    _section("Language", stats.by_language)
    _section("Tone", stats.by_tone)
    _section("Conversation length", stats.by_conversation_length)
    _section("Source type", stats.by_source_type)

    lines.append("## Length distribution (chars/conversation)")
    dist = length_distribution(stats.char_lengths)
    if dist:
        for k, v in dist.items():
            lines.append(f"- {k}: {v}")
    else:
        lines.append("(no data)")
    lines.append("")

    return "\n".join(lines)
