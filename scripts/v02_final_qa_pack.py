#!/usr/bin/env python3
"""Generate the V0.2 Final Human QA pack.

READ-ONLY: never modifies the candidate, the V0.1 store, or any decision
file. Reads data/production/v0.2_workspace/candidate_set.jsonl (the EXACT
content currently intended for training) plus the triage/decision/
automation files that explain how each record got there, and writes one
report:

    data/production/reports/rupsaa_v0.2_preparation/FINAL_HUMAN_QA_V02.md

Usage:
    python scripts/v02_final_qa_pack.py
"""

from __future__ import annotations

import json
import random
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rupsaa.dataset.config import PROJECT_ROOT, default_base_dir  # noqa: E402
from rupsaa.dataset.diversity import opening, skeleton, tokenize  # noqa: E402
from rupsaa.dataset.language_quality import analyze_record  # noqa: E402
from rupsaa.dataset.schema import ConversationRecord  # noqa: E402
from rupsaa.dataset.store import DatasetStore  # noqa: E402

WORKSPACE = PROJECT_ROOT / "data/production/v0.2_workspace"
REPORT_DIR = PROJECT_ROOT / "data/production/reports/rupsaa_v0.2_preparation"
CANDIDATE = WORKSPACE / "candidate_set.jsonl"
TRIAGE = REPORT_DIR / "triage.jsonl"
DECISIONS = WORKSPACE / "review_decisions.jsonl"
AUTOMATION = WORKSPACE / "repair_automation.jsonl"
KEEP_REWRITES = WORKSPACE / "keep_rewrites.jsonl"
OUT = REPORT_DIR / "FINAL_HUMAN_QA_V02.md"
NEW_BATCH_MARKER = "V0.2 new-coverage batch"
WATCHLIST = [
    "honestly", "actually", "genuinely", "basically", "obviously", "literally",
    "fair call", "fair enough", "not gonna lie", "to be fair", "sotti bolte", "সত্যি বলতে",
]


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in open(path, encoding="utf-8")]


def main() -> None:
    store = DatasetStore(default_base_dir())
    triage = {t["record_id"]: t for t in load_jsonl(TRIAGE)}
    decisions = {d["record_id"]: d for d in load_jsonl(DECISIONS)}
    automation = {a["record_id"]: a for a in load_jsonl(AUTOMATION)}
    keep_rewrites = {k["record_id"]: k for k in load_jsonl(KEEP_REWRITES)}
    candidate = load_jsonl(CANDIDATE)

    # --- Build one metadata row per candidate record --------------------
    rows = []
    for c in candidate:
        rid = c["id"]
        messages = c["messages"]
        loc = store.load(rid)
        t = triage.get(rid)
        d = decisions.get(rid)
        a = automation.get(rid)
        k = keep_rewrites.get(rid)

        if t is None:
            # New-coverage record: not in the original triage at all.
            language = loc.record.language
            category = loc.record.category
            source_type = loc.record.source_type
            history = "NEW_COVERAGE — authored this session, AI-reviewed, not yet human-approved"
        else:
            language, category, source_type = t["language"], t["category"], t["source_type"]
            cls = t["classification"]
            if cls == "KEEP":
                if k is not None:
                    history = f"KEEP_REWRITTEN — {k['reason']}"
                else:
                    history = "KEEP — no actionable issue found by triage"
            elif cls == "REPAIR" and a is not None and a["confidence"] == "AUTO_ACCEPT_REPAIR":
                history = f"AUTO_ACCEPT_REPAIR — {a['repair_method']}"
            elif cls == "REPAIR":
                history = f"REPAIR -> flagged HUMAN_REVIEW by automation ({', '.join(a['reasons']) if a else '?'}) -> {d['action'] if d else '?'}: {d.get('reason', '') if d else ''}"
            elif cls == "HUMAN_REVIEW":
                history = f"HUMAN_REVIEW -> {d['action'] if d else '?'}: {d.get('reason', d.get('note', '')) if d else ''}"
            else:
                history = cls

        record = ConversationRecord(id=rid, language=language, category=category,
                                    source_type=source_type, quality_status="draft", messages=messages)
        lq = analyze_record(record)
        assistant_texts = [m["content"] for m in messages if m.get("role") == "assistant"]
        total_chars = sum(len(t) for t in assistant_texts)
        skeletons = [skeleton(t, WATCHLIST) for t in assistant_texts]
        openings = [opening(t, 1) for t in assistant_texts if t.strip()]
        opening_bigrams = [opening(t, 2) for t in assistant_texts if t.strip()]
        has_actually = any(re.search(r"(?<![A-Za-z])actually(?![A-Za-z])", t, re.IGNORECASE) for t in assistant_texts)

        rows.append({
            "id": rid, "language": language, "category": category, "source_type": source_type,
            "history": history, "messages": messages, "lq_issues": sorted(lq.codes),
            "total_chars": total_chars, "skeletons": skeletons, "openings": openings,
            "opening_bigrams": opening_bigrams, "has_actually": has_actually,
        })

    by_id = {r["id"]: r for r in rows}
    rng = random.Random(1729)  # fixed seed: deterministic sampling

    # --- Risk pools --------------------------------------------------------
    thats_opening = [r for r in rows if "that's" in r["openings"]]
    thats_a_bigram = [r for r in rows if "that's a" in r["opening_bigrams"]]
    s_dash = [r for r in rows if "S-" in r["skeletons"]]
    s_sq = [r for r in rows if "S|SQ" in r["skeletons"]]
    remaining_actually = [r for r in rows if r["has_actually"]]
    mixed_script = [r for r in rows if set(r["lq_issues"]) & {"INTRAWORD_SCRIPT_MIX", "SCRIPT_INCONSISTENT", "FOREIGN_SCRIPT"}]
    by_length = sorted(rows, key=lambda r: r["total_chars"])
    shortest = by_length[:5]
    longest = by_length[-5:]
    rewritten = [r for r in rows if r["history"].startswith("KEEP_REWRITTEN") or "edit" in r["history"]]
    auto_accept = [r for r in rows if r["history"].startswith("AUTO_ACCEPT_REPAIR")]
    human_reviewed = [r for r in rows if "HUMAN_REVIEW" in r["history"] and not r["history"].startswith("NEW_COVERAGE")]
    new_coverage = [r for r in rows if r["history"].startswith("NEW_COVERAGE")]

    def by_lang(pool, lang):
        return [r for r in pool if r["language"] == lang]

    def by_cat_kw(pool, *kws):
        return [r for r in pool if any(kw in r["category"] for kw in kws)]

    # --- Assemble the stratified sample (deterministic; ids used as a set
    # to dedupe while preserving intent to hit every requested bucket) ----
    selected: dict[str, dict] = {}

    def take(pool, n, tag):
        pool = sorted(pool, key=lambda r: r["id"])
        picked = rng.sample(pool, min(n, len(pool)))
        for r in picked:
            selected.setdefault(r["id"], {**r, "why": []})
            selected[r["id"]]["why"].append(tag)

    take(by_lang(rows, "banglish"), 15, "language stratum: banglish")
    take(by_lang(rows, "bn"), 12, "language stratum: bengali")
    take(by_lang(rows, "en"), 10, "language stratum: english")
    take(by_lang(rows, "mixed"), 8, "language stratum: mixed")
    take(by_cat_kw(rows, "casual", "rupsaa_personality"), 5, "category: casual/personality")
    take(by_cat_kw(rows, "terminology"), 3, "category: terminology behavior")
    take([r for r in rows if r["category"] == "multi_turn"] + by_cat_kw(rows, "memory"), 3, "category: memory/multi-turn")
    take(by_cat_kw(rows, "code_switch"), 2, "category: language-switching")
    take(by_cat_kw(rows, "follow_up", "adversarial_difficult"), 2, "category: typo/follow-up")

    # Risk/provenance tags: to keep the total near ~60 as requested (the
    # language/category strata above already give ~60 with overlap), prefer
    # tagging records ALREADY selected — only pull in a new record when the
    # risk pool has no overlap with the current selection at all.
    def tag_risk(pool, n, tag):
        pool_ids = {r["id"] for r in pool}
        already = [rid for rid in selected if rid in pool_ids]
        for rid in already[:n]:
            selected[rid]["why"].append(tag)
        remaining_n = n - len(already[:n])
        if remaining_n > 0:
            fresh = [r for r in pool if r["id"] not in selected]
            for r in rng.sample(fresh, min(remaining_n, len(fresh))):
                selected.setdefault(r["id"], {**r, "why": []})
                selected[r["id"]]["why"].append(tag)

    tag_risk(thats_opening, 4, "risk: \"that's\" opening")
    tag_risk(thats_a_bigram, 3, "risk: \"that's a\" opening bigram")
    tag_risk(s_dash, 4, "risk: S- skeleton")
    tag_risk(s_sq, 4, "risk: S|SQ skeleton")
    tag_risk(remaining_actually, 4, "risk: remaining 'actually'")
    tag_risk(mixed_script, min(4, len(mixed_script)), "risk: remaining mixed-script")

    def tag_exact(pool_sorted, n, tag):
        """Like tag_risk but preserves an exact ranking (longest/shortest) rather than random sampling."""
        already = [r for r in pool_sorted if r["id"] in selected]
        for r in already[:n]:
            selected[r["id"]]["why"].append(tag)
        remaining_n = n - len(already[:n])
        if remaining_n > 0:
            fresh = [r for r in pool_sorted if r["id"] not in selected][:remaining_n]
            for r in fresh:
                selected.setdefault(r["id"], {**r, "why": []})
                selected[r["id"]]["why"].append(tag)

    tag_exact(longest, 3, "risk: longest response")
    tag_exact(shortest, 3, "risk: shortest response")
    tag_risk(rewritten, 3, "provenance: rewritten record")
    tag_risk(auto_accept, 4, "provenance: AUTO_ACCEPT_REPAIR")
    tag_risk(human_reviewed, 4, "provenance: HUMAN_REVIEWED")
    tag_risk(new_coverage, 3, "provenance: NEW_COVERAGE")

    ordered = sorted(selected.values(), key=lambda r: r["id"])

    # --- Live-behavior check -------------------------------------------
    behavior_prompts = [
        "hi, tumi kemon acho?",
        "achcha",
        "ajke amar mood ta bhalo na",
        "Strip mane ki?",
        "foreplay ki?",
        "eta short kore bolo",
        "এটা বাংলায় বুঝিয়ে বলো",
        "Banglish e explain koro",
        "amar favourite color blue -> ami ki color bolechilam?",
        "ami age ki bolechilam?",
    ]

    def find_closest(prompt_text: str, keys: list[str]) -> dict | None:
        """Ranks by (keyword-match count, closeness of message length to the
        prompt's own key phrase) so a near-exact match (e.g. the prompt
        authored almost verbatim as a new-coverage example) wins over an
        unrelated record that merely contains the same short substring."""
        keys_lower = [k.lower() for k in keys]
        ref_len = len(prompt_text)
        best, best_score, best_len_diff = None, 0, None
        for r in rows:
            for m in r["messages"]:
                if m.get("role") != "user":
                    continue
                text_lower = m["content"].lower()
                score = sum(1 for k in keys_lower if k in text_lower)
                if score == 0:
                    continue
                len_diff = abs(len(text_lower) - ref_len)
                if score > best_score or (score == best_score and (best_len_diff is None or len_diff < best_len_diff)):
                    best, best_score, best_len_diff = r, score, len_diff
        return best if best_score > 0 else None

    behavior_matches = [
        find_closest("hi, tumi kemon acho?", ["kemon acho"]),
        find_closest("achcha", ["achcha"]),
        find_closest("ajke amar mood ta bhalo na", ["mon ta bhalo na", "mood ta bhalo na", "mood off"]),
        find_closest("Strip mane ki?", ["strip mane", "strip ki", "stripping"]),
        find_closest("foreplay ki?", ["foreplay", "forplay"]),
        find_closest("eta short kore bolo", ["short kore bolo"]),
        find_closest("এটা বাংলায় বুঝিয়ে বলো", ["বাংলায় বুঝিয়ে বলো", "বাংলায় বলো"]),
        find_closest("Banglish e explain koro", ["banglish e explain koro", "banglish e bolo"]),
        find_closest("amar favourite color blue -> ami ki color bolechilam?", ["ki color bolechilam", "favourite color"]),
        find_closest("ami age ki bolechilam?", ["age ki bolechilam", "ki bolechilam", "naam mone ache", "kothay thaki bolechilam"]),
    ]

    # --- Structural-warning cluster analysis ----------------------------
    def cluster_breakdown(pool):
        return {
            "by_language": dict(Counter(r["language"] for r in pool)),
            "by_category": dict(Counter(r["category"] for r in pool).most_common(8)),
            "by_source": dict(Counter(r["source_type"] for r in pool)),
        }

    structural_pool = list({r["id"]: r for r in (thats_opening + thats_a_bigram + s_dash + s_sq)}.values())
    struct_sample = sorted(rng.sample(structural_pool, min(10, len(structural_pool))), key=lambda r: r["id"])

    write_report(OUT, ordered, behavior_prompts, behavior_matches,
                 thats_opening, thats_a_bigram, s_dash, s_sq, cluster_breakdown, struct_sample, len(rows))
    print(f"wrote {OUT.relative_to(PROJECT_ROOT)}  ({len(ordered)} sampled records)")


def render_conv(r: dict) -> list[str]:
    lines = [
        f"**ID:** {r['id']}",
        f"**Language:** {r['language']}",
        f"**Category:** {r['category']}",
        f"**Source:** {r['source_type']}",
        f"**Decision/history:** {r['history']}",
        "",
    ]
    for m in r["messages"]:
        if m["role"] == "system":
            continue
        label = "USER" if m["role"] == "user" else "RUPSAA"
        lines.append(f"{label}: {m['content']}")
    lines.append("")
    flags = r["lq_issues"] or ["NONE"]
    lines.append(f"QA FLAGS: {', '.join(flags)}")
    return lines


def write_report(path, ordered, prompts, matches, thats_opening, thats_a_bigram, s_dash, s_sq,
                 cluster_breakdown, struct_sample, total_candidate) -> None:
    lines = [
        "# V0.2 Final Human QA Pack",
        "",
        f"Deterministic stratified sample (seed 1729) of {len(ordered)} of {total_candidate} candidate "
        "conversations — the EXACT content currently intended for training, not regenerated. Deliberately "
        "includes both ordinary and high-risk examples; nothing here was cherry-picked for quality.",
        "",
        "---",
        "",
        "## Sampled conversations",
        "",
    ]
    for r in ordered:
        lines.append(f"### {r['id']}  _(sampled for: {'; '.join(r['why'])})_")
        lines.append("")
        lines.extend(render_conv(r))
        lines.append("")
        lines.append("---")
        lines.append("")

    lines.append("## EXPECTED V0.2 BEHAVIOR CHECK")
    lines.append("")
    for prompt, match in zip(prompts, matches):
        lines.append(f"### Prompt: {prompt}")
        lines.append("")
        if match is None:
            lines.append("**COVERAGE GAP** — no candidate record's user message is a close match to this prompt.")
        else:
            lines.append(f"Closest existing candidate example: **{match['id']}** ({match['language']}/{match['category']}, {match['history']})")
            lines.append("")
            lines.extend(render_conv(match)[5:])  # skip repeated header block
        lines.append("")

    lines.append("## STRUCTURAL WARNINGS")
    lines.append("")
    for name, pool in (("\"that's\" opening", thats_opening), ("\"that's a\" opening bigram", thats_a_bigram),
                       ("S- skeleton", s_dash), ("S|SQ skeleton", s_sq)):
        b = cluster_breakdown(pool)
        lines.append(f"### {name} ({len(pool)} records)")
        lines.append(f"- by language: {b['by_language']}")
        lines.append(f"- by category (top 8): {b['by_category']}")
        lines.append(f"- by source: {b['by_source']}")
        lines.append("")
    lines.append("### 10 representative examples from the structural-warning cluster")
    lines.append("")
    for r in struct_sample:
        pools = [("that's opening", thats_opening), ("that's a bigram", thats_a_bigram),
                 ("S-", s_dash), ("S|SQ", s_sq)]
        matches_here = [name for name, pool in pools if r in pool]
        lines.append(f"#### {r['id']}  _(matches: {matches_here})_")
        lines.append("")
        lines.extend(render_conv(r))
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
