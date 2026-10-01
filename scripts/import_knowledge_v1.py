#!/usr/bin/env python3
"""Integrate the frozen Knowledge V1 staging pack (data/staging/knowledge_v1/) into the live knowledge stores.

    python scripts/import_knowledge_v1.py --dry-run     # verify + show what would change, write nothing
    python scripts/import_knowledge_v1.py               # verify, merge 6 overlaps, import the rest

Steps:
1. Verify reports/CHECKSUMS.sha256. On any mismatch, stop and write nothing.
2. Merge the 6 concepts that overlap production Terminology into the existing term-* records. The production id
   wins. Staging aliases, content and sources are added; the merged-in content keeps its own provenance in
   `merged_from` (import, unverified, not owner-approved). Aliases that are ordinary-language false positives are
   left out deliberately (see SKIPPED_ALIASES). Each record is backed up to knowledge/terminology/.history/ first.
3. Import the other 352 records through the real General Knowledge importer, from the canonical JSONL (lossless:
   stable ids, sources, approved_by kept exactly as supplied — blank stays blank).

The private evaluation set (evaluation/) is never read here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rupsaa.rag import general_knowledge_import as gki  # noqa: E402
from rupsaa.rag.general_knowledge import GeneralKnowledgeStore  # noqa: E402
from rupsaa.rag.terminology import TerminologyStore  # noqa: E402

PACK = ROOT / "data/staging/knowledge_v1"
CANONICAL = PACK / "general_knowledge.jsonl"

# Ordinary-language words/phrases that would attach adult knowledge to unrelated messages.
SKIPPED_ALIASES = {
    "অনুমতি": "generic 'permission' (e.g. 'আমাকে অনুমতি দাও')",
    "পরবর্তী যত্ন": "generic 'follow-up care' (e.g. after an operation)",
    "tying up": "'tying up loose ends', 'tying up the boat'",
    "restraints": "'budget restraints', medical/physical restraints",
    "বন্ধন": "'bond' (রাখী বন্ধন, ভালোবাসার বন্ধন)",
}

# One canonical active concept per overlap: production id wins; what the staging record contributes.
MERGES = {
    "gk-consent": {
        "target": "term-consent",
        # Production one-liner ("Permission and agreement…") is fully contained in the staging summary.
        "definition": "staging_summary",
        "details_add": "key_points",
        "guidance_add": "Consent applies in every relationship, including marriage.",
    },
    "gk-foreplay": {
        "target": "term-foreplay",
        "details_add": ["It can also be the main event itself, not only something before intercourse.", "key_points"],
    },
    "gk-aftercare": {
        "target": "term-aftercare",
        "details_add": ["key_points"],
        "guidance_add": "Aftercare isn't only for BDSM — it applies to any intimacy.",
    },
    "gk-edging": {
        "target": "term-edging",
        "details_add": ["People use it to prolong arousal, intensify the eventual orgasm or practise ejaculatory control.",
                        "key_points"],
    },
    "gk-bondage": {
        # Same scope: production already covers restraint with handcuffs, ropes or similar items.
        "target": "term-handcuffs_bondage",
        "details_add": ["Safety basics: never restrain the neck, check circulation often, and keep safety scissors nearby."],
    },
    "gk-oral_sex": {
        # Scope resolved deliberately: ONE concept covering mouth-on-body play in general AND oral sex specifically
        # (production already listed "oral sex" as an alias). Title makes both senses explicit; id is kept.
        "target": "term-oral_play",
        "term": "Oral Play / Oral Sex",
        "definition": ("Using the mouth, lips or tongue on a partner's body for sexual pleasure. Oral sex specifically "
                       "means stimulating a partner's genitals or anus with the mouth."),
        "details_add": ["Oral sex can't cause pregnancy but can pass STIs such as herpes, gonorrhoea, syphilis and HPV.",
                        "key_points"],
    },
}


def verify_checksums() -> list[str]:
    bad = []
    for line in (PACK / "reports/CHECKSUMS.sha256").read_text().splitlines():
        if not line.strip():
            continue
        digest, name = line.split(None, 1)
        path = PACK / name.strip()
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            bad.append(name.strip())
    return bad


def _sentences(items: list[str]) -> str:
    return " ".join(x if x.rstrip().endswith((".", "!", "?")) else x.rstrip() + "." for x in items)


def merged_changes(term, staging: dict, plan: dict) -> dict:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    aliases = list(term.aliases)
    keys = term.keys()
    added, skipped = [], []
    for a in staging["aliases"]:
        if a in SKIPPED_ALIASES:
            skipped.append(a)
        elif a.lower() not in {x.lower() for x in aliases} and a.lower() not in keys:
            aliases.append(a)
            added.append(a)
    extra = []
    for item in plan.get("details_add", []) if isinstance(plan.get("details_add"), list) else [plan["details_add"]]:
        if item == "key_points":
            extra.append(_sentences(staging["key_points"]))
        else:
            extra.append(item)
    details = " ".join(x for x in [term.details, *extra] if x).strip()
    guidance = term.answer_guidance
    if plan.get("guidance_add") and plan["guidance_add"] not in guidance:
        guidance = f"{guidance.rstrip()} {plan['guidance_add']}".strip()
    definition = term.definition
    if plan.get("definition") == "staging_summary":
        definition = staging["summary"]
    elif plan.get("definition"):
        definition = plan["definition"]
    seen = {s["url"] for s in term.sources}
    sources = list(term.sources) + [s for s in staging["sources"] if s["url"] not in seen]
    provenance = {
        "id": staging["id"], "title": staging["title"], "pack": "knowledge_v1", "merged_at": now,
        "source_type": staging["source_type"], "source": staging["source"], "verified": staging["verified"],
        "approved_by": staging["approved_by"], "sources": staging["sources"],
        "fields": [f for f, used in (("aliases", added), ("definition", plan.get("definition")),
                                     ("details", extra), ("answer_guidance", plan.get("guidance_add")),
                                     ("term", plan.get("term"))) if used],
        "aliases_added": added, "aliases_skipped": {a: SKIPPED_ALIASES[a] for a in skipped},
    }
    changes = {"aliases": aliases, "details": details, "answer_guidance": guidance, "definition": definition,
               "sources": sources, "merged_from": [*term.merged_from, provenance]}
    if plan.get("term"):
        changes["term"] = plan["term"]
    return changes


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    bad = verify_checksums()
    if bad:
        print("STOP: checksum mismatch for", ", ".join(bad))
        return 1
    print("checksums: OK")
    records = [json.loads(line) for line in CANONICAL.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(records) == 358, len(records)

    terms = TerminologyStore(ROOT / "knowledge/terminology")
    general = GeneralKnowledgeStore(ROOT / "knowledge/general")
    by_id = {r["id"]: r for r in records}
    for sid, plan in MERGES.items():
        if any(m.get("id") == sid for m in terms.get(plan["target"]).merged_from):
            print(f"merge {sid} -> {plan['target']}: already merged, skipped")
            continue
        changes = merged_changes(terms.get(plan["target"]), by_id[sid], plan)
        print(f"merge {sid} -> {plan['target']}: +aliases {changes['merged_from'][-1]['aliases_added']}, "
              f"skipped {list(changes['merged_from'][-1]['aliases_skipped'])}, +{len(by_id[sid]['sources'])} source(s)")
        if not args.dry_run:
            terms.update(plan["target"], changes)  # backs up the previous version first

    rest = [r for r in records if r["id"] not in MERGES]
    payload = "\n".join(json.dumps(r, ensure_ascii=False) for r in rest).encode("utf-8")
    pv = gki.preview("general_knowledge.jsonl", payload, general)
    print(f"general knowledge: {len(rest)} rows → {pv['counts']}")
    problems = [r for r in pv["rows"] if r["status"] not in ("valid", "warning")]
    for r in problems[:20]:
        print("  ", r["row"], r["status"], r["data"].get("id"), r["errors"])
    if problems:
        print("STOP: rows that are not new+valid — nothing imported")
        return 1
    if not args.dry_run:
        res = gki.commit("general_knowledge.jsonl", payload, general)
        print("imported:", res["counts"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
