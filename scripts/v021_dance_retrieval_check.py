#!/usr/bin/env python3
"""Retrieval check for every dance in knowledge/dance/ through the real runtime router + store.

    python scripts/v021_dance_retrieval_check.py

For each of the 60 owner records: definition (Banglish), origin (Banglish), English "tell me about",
lowercase, every alias, Bengali-script names, and a generated typo (adjacent swap) where the
name is long enough and not a real English word. Plus the owner's representative queries and
ordinary-chat negatives. Writes data/production/reports/rupsaa_v0.2.1_preparation/dance_retrieval_check.json.
Exit 1 on any miss or false positive.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rupsaa.config import PROJECT_ROOT, get_settings  # noqa: E402
from rupsaa.rag.context_builder import build_turn_knowledge  # noqa: E402
from rupsaa.rag.dance import DanceStore  # noqa: E402
from rupsaa.rag.terminology import TerminologyStore, _all_known_words, normalize  # noqa: E402

OUT = PROJECT_ROOT / "data/production/reports/rupsaa_v0.2.1_preparation/dance_retrieval_check.json"
REPRESENTATIVE = {
    "Belly dance ki?": "dance-belly_dance", "belly dancing mane ki?": "dance-belly_dance", "Ballet ki?": "dance-ballet",
    "Kathak kothakar dance?": "dance-kathak", "Voguing ki?": "dance-voguing",
    "Breaking ar breakdance same?": "dance-breaking_breakdance", "Haka origin kothay?": "dance-haka",
    "আমাকে কথক সম্পর্কে বলো": "dance-kathak", "Bhangra ta banglish e bojhao": "dance-bhangra",
}
NEGATIVES = ["hi, tumi kemon acho?", "ajke amar mood ta bhalo na", "achcha", "Strip mane ki?", "Forplay ki?",
             "ami age ki bolechilam?", "breaking news dekhlam", "phone locking problem hocche", "salsa sauce banabo",
             "polka dot dress kinlam", "hula hoop kinechi", "everyone has a breaking point", "popping up everywhere",
             "house e party ache", "amar dragon fruit bhalo lage", "lion king dekhechi", "kal office e onek kaj",
             "What does a chargeback mean for a creator?", "consent ki jinis?", "tumi amar sathe banglish e kotha bolbe?"]


def typo(name: str) -> str | None:
    word = max(re.findall(r"[a-z]+", normalize(name)), key=len, default="")
    if len(word) < 6 or _all_known_words(word):
        return None
    i = len(word) // 2
    swapped = word[:i] + word[i + 1] + word[i] + word[i + 2:]
    if swapped == word:
        return None
    # multi-part names ("Breaking / Breakdance"): people misspell one word, not the whole slash name
    return swapped if "/" in name else normalize(name).replace(word, swapped)


def main() -> None:
    store = DanceStore(PROJECT_ROOT / get_settings().knowledge_dance_dir)
    terms = TerminologyStore(PROJECT_ROOT / get_settings().knowledge_terminology_dir)
    dances = store.list()

    def got(msg: str) -> list[str]:
        k = build_turn_knowledge(msg, use_rag=False, rag_query=None, terminology=terms, dance=store)
        return [t for t in k.terms_used if t.startswith("dance-")]

    cases, failures = [], []
    for d in dances:
        queries = [f"{d.name} ki?", f"{d.name.lower()} mane ki?", f"{d.name} kothakar dance?", f"tell me about {d.name}",
                   f"{d.name} origin kothay?"]
        queries += [f"{a} ki?" for a in d.aliases if not re.search(r"[ঀ-৿]", a)]
        queries += [f"আমাকে {a} সম্পর্কে বলো" for a in d.aliases if re.search(r"[ঀ-৿]", a)]
        t = typo(d.name)
        if t:
            queries.append(f"{t} ki?")
        for q in queries:
            ids = got(q)
            ok = bool(ids) and ids[0] == d.id
            cases.append({"dance": d.id, "query": q, "retrieved": ids, "pass": ok})
            if not ok:
                failures.append(cases[-1])
    rep = []
    for q, want in REPRESENTATIVE.items():
        ids = got(q)
        rep.append({"query": q, "expected": want, "retrieved": ids, "pass": bool(ids) and ids[0] == want})
    neg = [{"query": q, "retrieved": got(q)} for q in NEGATIVES]
    false_pos = [n for n in neg if n["retrieved"]]
    summary = {"dances": len(dances), "enabled": sum(d.enabled for d in dances), "queries": len(cases),
               "passed": sum(c["pass"] for c in cases), "dances_fully_passing": len({c["dance"] for c in cases} -
                                                                                   {f["dance"] for f in failures}),
               "typo_queries": sum(1 for d in dances if typo(d.name)),
               "representative": rep, "negatives": neg, "failures": failures, "false_positives": false_pos,
               "pass": not failures and all(r["pass"] for r in rep) and not false_pos and len(dances) == 60}
    OUT.write_text(json.dumps({**summary, "cases": cases}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k not in ("negatives",)}, ensure_ascii=False, indent=1)[:3000])
    sys.exit(0 if summary["pass"] else 1)


if __name__ == "__main__":
    main()
