#!/usr/bin/env python3
"""Parse the owner's authoritative 60-dance list and import it into knowledge/dance/.

    python scripts/import_owner_dance_list.py            # parse + verify + import (fails on any problem)
    python scripts/import_owner_dance_list.py --dry-run  # parse + verify only

Source of truth: data/owner/dance_knowledge_owner_60.txt (the owner's text, verbatim).
  * name, origin, description are stored EXACTLY as the owner wrote them
  * aliases: only structural variants of the owner's name (slash parts, hyphen/space/accent
    forms, "X dancing") + Bengali-script spellings of the NAME for retrieval (transliteration,
    not facts — listed in the import report for owner review)
  * category/tags: only when the owner's description literally says it ("ballroom dance",
    "street dance", "classical Indian dance", "folk dance", ...)
  * key_movements and every choreography field stay EMPTY (nothing is invented)
Fails (exit 1) unless exactly 60 are supplied, parsed, stored and enabled, and every stored
name/origin/description is byte-identical to the source.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rupsaa.config import PROJECT_ROOT, get_settings  # noqa: E402
from rupsaa.rag import dance_import  # noqa: E402
from rupsaa.rag.dance import FUTURE_FIELDS, DanceStore  # noqa: E402

SOURCE = PROJECT_ROOT / "data/owner/dance_knowledge_owner_60.txt"
PARSED = PROJECT_ROOT / "data/owner/dance_knowledge_owner_60.json"
REPORT = PROJECT_ROOT / "data/production/reports/rupsaa_v0.2.1_preparation/dance_import_report.json"
EXPECTED = 60

# Bengali-script spellings of dance NAMES (retrieval only; not facts). Only names with a settled spelling.
BENGALI_NAMES = {
    "Belly Dance": ["বেলি ডান্স"], "Ballet": ["ব্যালে"], "Tap Dance": ["ট্যাপ ডান্স"], "Jazz Dance": ["জ্যাজ ডান্স"],
    "Hip-Hop": ["হিপ হপ"], "Breaking / Breakdance": ["ব্রেকডান্স", "ব্রেকিং"], "Salsa": ["সালসা"], "Samba": ["সাম্বা"],
    "Tango": ["ট্যাঙ্গো"], "Flamenco": ["ফ্লামেঙ্কো"], "Waltz": ["ওয়াল্টজ"], "Bharatanatyam": ["ভরতনাট্যম"],
    "Kathak": ["কথক"], "Kathakali": ["কথাকলি"], "Kuchipudi": ["কুচিপুড়ি"], "Odissi": ["ওড়িশি"], "Bhangra": ["ভাংড়া"],
    "Garba": ["গরবা"], "Lavani": ["লাবণী"], "Hula": ["হুলা"], "Haka": ["হাকা"],
}
# (phrase in the owner's description, category label) — first match is the category; all matches are tags.
CATEGORY_RULES = [
    ("classical indian dance", "Indian classical"), ("classical japanese dance-drama", "classical dance-drama"),
    ("classical dance-drama", "classical dance-drama"), ("ballroom dance", "ballroom"), ("classical dance", "classical"),
    ("street dance", "street"), ("club dance", "club"), ("partner dance", "partner"), ("folk dance", "folk"),
    ("folkloric", "folk"), ("dance-drama", "dance-drama"), ("social dance", "social"), ("group dance", "group"),
    ("solo dance", "solo"), ("avant-garde", "avant-garde"),
]
BLOCK_RE = re.compile(r"^(\d+)\)\s*(.+?)\s*\nOrigin:\s*(.+?)\s*\nDescription:\s*(.+?)\s*$", re.S)


def fold(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")


def parse(text: str) -> list[dict]:
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text.strip()) if b.strip()]
    out = []
    for b in blocks:
        m = BLOCK_RE.match(b)
        if not m:
            raise SystemExit(f"UNPARSEABLE BLOCK (refusing to drop it):\n{b}")
        n, name, origin, desc = int(m.group(1)), m.group(2), m.group(3), m.group(4)
        if "\n" in name or "\n" in origin or "\n" in desc:
            raise SystemExit(f"record {n}: unexpected line break inside a field")
        out.append({"n": n, "name": name, "origin": origin, "description": desc})
    nums = [r["n"] for r in out]
    if nums != list(range(1, EXPECTED + 1)):
        raise SystemExit(f"expected records numbered 1..{EXPECTED}, got {nums}")
    return out


def derive(rec: dict) -> dict:
    name = rec["name"]
    parts = [p.strip() for p in re.split(r"\s*/\s*", name)]
    aliases: list[str] = []

    def add(v: str) -> None:
        if v and v.lower() != name.lower() and v.lower() not in [a.lower() for a in aliases]:
            aliases.append(v)

    for p in parts:
        for v in (p, fold(p), p.replace("-", " "), p.replace("-", ""), fold(p).replace("-", " "), fold(p).replace("-", "")):
            add(v)
        m = re.match(r"^(.*)\bdance$", p, re.I)
        if m and m.group(1).strip():
            add(f"{m.group(1).strip()} dancing")
        if p.lower() == "breakdance":
            add("breakdancing")
    for b in BENGALI_NAMES.get(name, []):
        add(b)
    desc = rec["description"].lower()
    hits = list(dict.fromkeys(label for phrase, label in CATEGORY_RULES if phrase in desc))
    return {
        "name": name, "origin": rec["origin"], "description": rec["description"], "aliases": aliases,
        "category": hits[0] if hits else "", "tags": hits + ["owner-dance-list"], "key_movements": "",
        "answer_guidance": "", "languages": ["en", "bn", "banglish"], "enabled": True,
        "source": f"owner dance list #{rec['n']} (data/owner/dance_knowledge_owner_60.txt)",
        **{f: "" for f in FUTURE_FIELDS},
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    text = SOURCE.read_text(encoding="utf-8")
    supplied = len(re.findall(r"^\d+\)", text, re.M))
    raw = parse(text)
    records = [derive(r) for r in raw]
    print(f"supplied {supplied} · parsed {len(records)}")
    if supplied != EXPECTED or len(records) != EXPECTED:
        raise SystemExit("count mismatch")
    src_sha = hashlib.sha256(text.encode()).hexdigest()
    PARSED.write_text(json.dumps({"source_sha256": src_sha, "dances": records}, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    store = DanceStore(PROJECT_ROOT / get_settings().knowledge_dance_dir)
    content = PARSED.read_bytes()
    pv = dance_import.preview(PARSED.name, content, store)
    bad = [(r.row, r.data.get("name"), r.status, r.errors) for r in pv.rows if r.status not in ("valid", "warning", "existing_match")]
    if bad or len(pv.rows) != EXPECTED:
        raise SystemExit(f"preview problems: {bad} ({len(pv.rows)} rows)")
    if args.dry_run:
        print("dry run: parsed and validated, nothing stored")
        return
    res = dance_import.commit(PARSED.name, content, store, {r.row for r in pv.rows if r.status == "existing_match"}).to_dict()
    stored = {d.name: d for d in store.list() if "owner-dance-list" in d.tags}
    mismatch = [r["name"] for r in raw if r["name"] not in stored
                or (stored[r["name"]].origin, stored[r["name"]].description) != (r["origin"], r["description"])]
    enabled = sum(d.enabled for d in stored.values())
    filled = [d.name for d in stored.values() if d.key_movements or any(getattr(d, f) for f in FUTURE_FIELDS)]
    report = {"source": str(SOURCE.relative_to(PROJECT_ROOT)), "source_sha256": src_sha,
              "supplied": supplied, "parsed": len(records), "stored": len(stored), "enabled": enabled,
              "import_counts": res["counts"], "failed": res["failed"], "verbatim_mismatches": mismatch,
              "choreography_fields_filled": filled,
              "derived": {"aliases_rule": "slash parts, hyphen/space/accent variants and 'X dancing' of the owner's name",
                          "bengali_script_name_spellings_for_retrieval_review_please": BENGALI_NAMES,
                          "category_rule": "first description phrase from CATEGORY_RULES; all matches become tags",
                          "key_movements": "left empty — the owner's description already carries the movements"},
              "records": [{"id": stored[r["name"]].id, "name": r["name"], "category": stored[r["name"]].category,
                           "aliases": stored[r["name"]].aliases} for r in raw if r["name"] in stored]}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("supplied", "parsed", "stored", "enabled", "import_counts",
                                             "verbatim_mismatches", "choreography_fields_filled")}, ensure_ascii=False))
    if (supplied, len(records), len(stored), enabled) != (EXPECTED,) * 4 or mismatch or filled or res["failed"]:
        raise SystemExit("IMPORT VERIFICATION FAILED")
    print("60/60 supplied, parsed, stored, enabled; name/origin/description verbatim")


if __name__ == "__main__":
    main()
