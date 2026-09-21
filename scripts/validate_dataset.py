#!/usr/bin/env python3
"""Validate a Rupsaa conversational dataset (JSONL).

Usage:
    python scripts/validate_dataset.py --input data/examples/starter_conversations.jsonl
    python scripts/validate_dataset.py --input data/train.jsonl data/validation.jsonl data/test.jsonl

Checks: invalid JSON, missing/malformed "messages", missing/unsupported
roles, empty content, exact-duplicate conversations, unusually long
samples, broken Unicode, and near-duplicate ("suspiciously repetitive")
assistant replies. Prints conversation/message/token-approx counts, a rough
language distribution, and a length distribution.

Exits non-zero if any record has a hard validation error.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rupsaa.personality.language import detect_language  # noqa: E402

VALID_ROLES = {"system", "user", "assistant"}
LONG_SAMPLE_CHAR_THRESHOLD = 6000  # flagged as a warning, not a hard error


@dataclass
class ValidationReport:
    path: str
    total_lines: int = 0
    valid_conversations: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    message_count: int = 0
    approx_token_count: int = 0
    language_counts: Counter = field(default_factory=Counter)
    conversation_char_lengths: list[int] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0


def _approx_tokens(text: str) -> int:
    # Rough heuristic (chars / 4), language-agnostic and dependency-free.
    # Good enough for dataset sizing sanity checks, not for exact budgeting.
    return max(1, len(text) // 4)


def validate_record(record: dict, line_no: int) -> list[str]:
    errors = []
    if "messages" not in record:
        return [f"line {line_no}: missing 'messages' field"]

    messages = record["messages"]
    if not isinstance(messages, list) or len(messages) == 0:
        return [f"line {line_no}: 'messages' must be a non-empty list"]

    has_user = False
    has_assistant = False
    for i, msg in enumerate(messages):
        if not isinstance(msg, dict):
            errors.append(f"line {line_no}, message {i}: not an object")
            continue
        role = msg.get("role")
        content = msg.get("content")
        if role not in VALID_ROLES:
            errors.append(f"line {line_no}, message {i}: unsupported role '{role}'")
        if role == "user":
            has_user = True
        if role == "assistant":
            has_assistant = True
        if not isinstance(content, str) or not content.strip():
            errors.append(f"line {line_no}, message {i}: empty or non-string content")
        else:
            try:
                content.encode("utf-8").decode("utf-8")
            except UnicodeError:
                errors.append(f"line {line_no}, message {i}: broken Unicode")

    if not has_user:
        errors.append(f"line {line_no}: conversation has no 'user' message")
    if not has_assistant:
        errors.append(f"line {line_no}: conversation has no 'assistant' message")

    return errors


def _conversation_fingerprint(record: dict) -> str:
    messages = record.get("messages", [])
    return json.dumps(
        [(m.get("role"), m.get("content")) for m in messages if isinstance(m, dict)],
        ensure_ascii=False,
    )


def validate_file(path: Path) -> ValidationReport:
    report = ValidationReport(path=str(path))
    seen_fingerprints: dict[str, int] = {}
    seen_assistant_replies: Counter = Counter()

    if not path.exists():
        report.errors.append(f"file not found: {path}")
        return report

    with open(path, encoding="utf-8") as f:
        for line_no, raw_line in enumerate(f, start=1):
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            report.total_lines += 1
            try:
                record = json.loads(raw_line)
            except json.JSONDecodeError as e:
                report.errors.append(f"line {line_no}: invalid JSON ({e})")
                continue

            record_errors = validate_record(record, line_no)
            if record_errors:
                report.errors.extend(record_errors)
                continue

            fingerprint = _conversation_fingerprint(record)
            if fingerprint in seen_fingerprints:
                report.warnings.append(
                    f"line {line_no}: exact duplicate of line {seen_fingerprints[fingerprint]}"
                )
            else:
                seen_fingerprints[fingerprint] = line_no

            messages = record["messages"]
            report.valid_conversations += 1
            report.message_count += len(messages)

            conv_chars = sum(len(m["content"]) for m in messages)
            report.conversation_char_lengths.append(conv_chars)
            report.approx_token_count += _approx_tokens(
                " ".join(m["content"] for m in messages)
            )
            if conv_chars > LONG_SAMPLE_CHAR_THRESHOLD:
                report.warnings.append(
                    f"line {line_no}: unusually long conversation ({conv_chars} chars)"
                )

            for m in messages:
                if m["role"] == "user":
                    report.language_counts[detect_language(m["content"])] += 1
                if m["role"] == "assistant":
                    seen_assistant_replies[m["content"]] += 1

    for reply, count in seen_assistant_replies.items():
        if count >= 3:
            report.warnings.append(
                f"suspiciously repetitive assistant reply used {count} times: {reply[:60]!r}..."
            )

    return report


def _length_distribution(lengths: list[int]) -> dict:
    if not lengths:
        return {}
    sorted_lengths = sorted(lengths)
    n = len(sorted_lengths)
    return {
        "min": sorted_lengths[0],
        "max": sorted_lengths[-1],
        "median": sorted_lengths[n // 2],
        "p90": sorted_lengths[int(n * 0.9)] if n > 1 else sorted_lengths[0],
    }


def print_report(report: ValidationReport) -> None:
    print(f"\n=== {report.path} ===")
    print(f"Lines read:            {report.total_lines}")
    print(f"Valid conversations:   {report.valid_conversations}")
    print(f"Total messages:        {report.message_count}")
    print(f"Approx. token count:   {report.approx_token_count}")
    print(f"Language distribution: {dict(report.language_counts)}")
    print(f"Length distribution (chars/conversation): {_length_distribution(report.conversation_char_lengths)}")

    if report.errors:
        print(f"\nERRORS ({len(report.errors)}):")
        for e in report.errors:
            print(f"  - {e}")
    else:
        print("\nNo hard errors.")

    if report.warnings:
        print(f"\nWARNINGS ({len(report.warnings)}):")
        for w in report.warnings:
            print(f"  - {w}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", nargs="+", default=["data/examples/starter_conversations.jsonl"]
    )
    args = parser.parse_args()

    all_valid = True
    for input_path in args.input:
        report = validate_file(Path(input_path))
        print_report(report)
        all_valid = all_valid and report.is_valid

    if not all_valid:
        print("\nValidation FAILED — see ERRORS above.")
        sys.exit(1)
    print("\nValidation passed.")


if __name__ == "__main__":
    main()
