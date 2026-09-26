#!/usr/bin/env python3
"""Regenerate rupsaa/rag/known_words.txt from a Qwen2.5 tokenizer.json.

    python scripts/build_known_words.py adapters/rupsaa-v0.2/tokenizer.json

Whole-word vocabulary tokens ("Ġcontent") are common real English words, so a
terminology candidate that is one of them is never treated as a typo.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "rupsaa/rag/known_words.txt"
HEADER = ("# Common English words (whole-word tokens of the Qwen2.5 tokenizer vocabulary, lowercase, 4-14 letters).\n"
          "# Used by rupsaa/rag/terminology.py to keep typo matching off real words (\"content\" is not a typo of \"consent\").\n"
          "# Regenerate: see scripts/build_known_words.py\n")


def main() -> None:
    vocab = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))["model"]["vocab"]
    words = sorted({t[1:].lower() for t in vocab
                    if t.startswith("Ġ") and t[1:].isalpha() and t[1:].isascii() and 4 <= len(t) - 1 <= 14})
    OUT.write_text(HEADER + "\n".join(words) + "\n", encoding="utf-8")
    print(f"{len(words)} words -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
