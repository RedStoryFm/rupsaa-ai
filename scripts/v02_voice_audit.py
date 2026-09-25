#!/usr/bin/env python3
"""Voice / repetition audit of the V0.2 post-training generations (V0.2 vs V0.1 vs base).

    python scripts/v02_voice_audit.py [--results <posttrain_results.json>]

Reads every generated reply in posttrain_results.json (terminology suite, live
checks, supplementary checks) and measures, per model: catchphrases, repeated
openings, repeated sentence frames, emoji, English filler, mixed-script
corruption (Bengali and Latin letters inside one word), verbosity and question
density. Writes voice_audit.json next to the results. Heuristic counts that
point a reader at replies; the verdict is human.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rupsaa.config import PROJECT_ROOT  # noqa: E402

DEFAULT = PROJECT_ROOT / "data/production/reports/rupsaa_v0.2_posttraining/posttrain_results.json"
CATCHPHRASES = ["honestly", "actually", "fair call", "fair enough", "heyy", "bindaas", "baby", "babe", "basically"]
FILLER = ["well,", "so,", "you know", "i mean", "like,", "literally", "totally", "anyway"]
EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF☀-➿]")
MIXED_WORD_RE = re.compile(r"(?:[A-Za-z]+[ঀ-৿]+|[ঀ-৿]+[A-Za-z]+)")
CJK_RE = re.compile(r"[一-鿿぀-ヿ가-힯]")


def collect(results: dict) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for section in ("terminology", "live", "supplementary"):
        for case in (results.get(section) or {}).get("cases", []):
            for variant, run in case["runs"].items():
                for t in run["turns"]:
                    out.setdefault(variant, []).append({"section": section, "case": case["id"], "user": t["user"], "reply": t["reply"]})
    return out


def opening(text: str, n: int = 2) -> str:
    return " ".join(re.findall(r"[\wঀ-৿']+", text.lower())[:n])


def audit(replies: list[dict]) -> dict:
    texts = [r["reply"] for r in replies]
    low = [t.lower() for t in texts]
    n = len(texts) or 1
    word = lambda p: re.compile(r"(?<![a-z])" + re.escape(p) + r"(?![a-z])")  # noqa: E731
    catch = {p: sum(1 for t in low if word(p).search(t)) for p in CATCHPHRASES}
    openings = Counter(opening(t) for t in texts if t.strip())
    frames = Counter(re.sub(r"[^\wঀ-৿ ]", "", s.strip().lower())[:25]
                     for t in texts for s in re.split(r"(?<=[.!?।])\s+", t) if len(s.strip()) > 15)
    lengths = [len(t) for t in texts]
    return {
        "replies": len(texts),
        "catchphrases_replies_containing": catch,
        "catchphrase_reply_rate": round(sum(1 for t in low if any(word(p).search(t) for p in CATCHPHRASES)) / n, 3),
        "top_openings": openings.most_common(8),
        "most_common_opening_share": round(openings.most_common(1)[0][1] / n, 3) if openings else 0,
        "repeated_sentence_frames": [(f, c) for f, c in frames.most_common(8) if c >= 3],
        "emoji_replies": sum(1 for t in texts if EMOJI_RE.search(t)),
        "english_filler_replies": sum(1 for t in low if any(f in t for f in FILLER)),
        "mixed_script_words": sum(len(MIXED_WORD_RE.findall(t)) for t in texts),
        "mixed_script_examples": [m for t in texts for m in MIXED_WORD_RE.findall(t)][:10],
        "foreign_script_replies": sum(1 for t in texts if CJK_RE.search(t)),
        "chars_mean": round(statistics.mean(lengths), 1) if lengths else 0,
        "chars_median": statistics.median(lengths) if lengths else 0,
        "chars_max": max(lengths) if lengths else 0,
        "over_600_chars": sum(1 for x in lengths if x > 600),
        "questions_per_reply": round(sum(t.count("?") for t in texts) / n, 2),
        "replies_with_2plus_questions": sum(1 for t in texts if t.count("?") >= 2),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", type=Path, default=DEFAULT)
    args = ap.parse_args()
    results = json.loads(args.results.read_text(encoding="utf-8"))
    by_variant = collect(results)
    out = {v: audit(r) for v, r in by_variant.items()}
    (args.results.parent / "voice_audit.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    for v, a in out.items():
        print(f"== {v}: {a['replies']} replies")
        for k, val in a.items():
            if k != "replies":
                print(f"   {k}: {val}")


if __name__ == "__main__":
    main()
