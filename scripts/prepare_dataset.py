#!/usr/bin/env python3
"""Split source conversation data into train/validation/test JSONL files.

Usage:
    python scripts/prepare_dataset.py
    python scripts/prepare_dataset.py --input data/examples/starter_conversations.jsonl --seed 42

Reads one or more source JSONL files (canonical {"messages": [...]} format,
extra fields like "category" are dropped on write), shuffles deterministically
with --seed, and writes data/train.jsonl, data/validation.jsonl, data/test.jsonl.

Runs validate_dataset.py's validation logic first and refuses to write splits
if the source data has hard errors — never silently ships an invalid dataset.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.validate_dataset import validate_file, print_report  # noqa: E402


def load_records(paths: list[Path]) -> list[dict]:
    records = []
    for path in paths:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
    return records


def split_records(
    records: list[dict], seed: int, train_ratio: float, val_ratio: float
) -> tuple[list[dict], list[dict], list[dict]]:
    rng = random.Random(seed)
    shuffled = records[:]
    rng.shuffle(shuffled)

    n = len(shuffled)
    n_train = max(1, int(n * train_ratio))
    n_val = max(1, int(n * val_ratio)) if n - n_train > 1 else 0

    train = shuffled[:n_train]
    val = shuffled[n_train:n_train + n_val]
    test = shuffled[n_train + n_val:]
    return train, val, test


def write_jsonl(records: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            # Only the canonical field is written out — "category" and any
            # other bookkeeping fields from the source file are dropped.
            f.write(json.dumps({"messages": r["messages"]}, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", nargs="+", default=["data/examples/starter_conversations.jsonl"]
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--train-ratio", type=float, default=0.8)
    parser.add_argument("--val-ratio", type=float, default=0.1)
    parser.add_argument("--output-dir", default="data")
    args = parser.parse_args()

    input_paths = [Path(p) for p in args.input]

    print("Validating source data before splitting...")
    all_valid = True
    for path in input_paths:
        report = validate_file(path)
        print_report(report)
        all_valid = all_valid and report.is_valid
    if not all_valid:
        print("\nRefusing to prepare splits: source data has hard errors.")
        sys.exit(1)

    records = load_records(input_paths)
    train, val, test = split_records(records, args.seed, args.train_ratio, args.val_ratio)

    output_dir = Path(args.output_dir)
    write_jsonl(train, output_dir / "train.jsonl")
    write_jsonl(val, output_dir / "validation.jsonl")
    write_jsonl(test, output_dir / "test.jsonl")

    print(f"\nWrote {len(train)} train / {len(val)} validation / {len(test)} test examples")
    print(f"  -> {output_dir / 'train.jsonl'}")
    print(f"  -> {output_dir / 'validation.jsonl'}")
    print(f"  -> {output_dir / 'test.jsonl'}")


if __name__ == "__main__":
    main()
