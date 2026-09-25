#!/usr/bin/env python3
"""Build the Rupsaa V0.2 post-training evaluation suites (never training data).

    python scripts/v02_build_eval_suites.py

Writes data/production/evaluation/rupsaa_v0.2/:
  terminology_generalization.jsonl  unseen-term cases: reference terminology in the exact
                                    runtime format (TermRecord.to_context) + user turns + checks
  eval_manifests.json               A: full frozen validation/test; B: clean V0.1-vs-V0.2
                                    subset without records V0.1 trained on
  live_behavior_checks.json         the 10 owner live-behavior prompts
  README.md                         human-readable description

Refuses to write if any evaluation term or alias occurs anywhere in the frozen
V0.2 data (all splits), so these cases measure generalisation, not recall.
Never touches the frozen export, snapshot, or any training file.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rupsaa.dataset.config import PROJECT_ROOT, default_base_dir  # noqa: E402
from rupsaa.dataset.store import DatasetStore  # noqa: E402
from rupsaa.personality.system_prompt import build_system_prompt  # noqa: E402
from rupsaa.rag.terminology import TerminologyStore, TermRecord  # noqa: E402

OUT = PROJECT_ROOT / "data/production/evaluation/rupsaa_v0.2"
FROZEN = PROJECT_ROOT / "data/production/snapshots/rupsaa_v0.2_training/frozen_records.jsonl"
MANIFEST = PROJECT_ROOT / "data/production/snapshots/rupsaa_v0.2_training/V02_TRAINING_MANIFEST.json"
V01_MANIFEST = PROJECT_ROOT / "data/production/snapshots/rupsaa_v0.1_training/V01_TRAINING_MANIFEST.json"
V01_EXPORT = PROJECT_ROOT / "data/production/exports/rupsaa_v0.1"
STORE = TerminologyStore(PROJECT_ROOT / "knowledge/terminology")

FORBIDDEN = ["retrieved context", "reference terminology", "according to the provided", "the definition says",
             "owner's guidance", "as per the reference", "honestly", "fair call"]
BANGLISH_MARKERS = ["mane", "kore", "hoy", "ekta", "jokhon", "kichu", "theke", "tomar", "jate", "moto"]

AUTHORED = {
    "benching": TermRecord(id="term-eval_benching", term="Benching", category="dating_relationships",
        aliases=["benched", "benching ki"],
        definition="Keeping someone as a backup option: staying in light contact to keep their interest without committing, while prioritising someone else.",
        details="Different from ghosting: the contact never fully stops, it just never goes anywhere."),
    "tip_menu": TermRecord(id="term-eval_tip_menu", term="Tip menu", category="creator_platform",
        aliases=["tip list"],
        definition="A list a creator publishes of specific extras or requests that fans can unlock by sending a set tip amount.",
        details="The creator sets both the items and the prices; it sits alongside subscriptions and paid messages.",
        answer_guidance="Explain it neutrally as a pricing tool; don't invent specific prices."),
    "whale": TermRecord(id="term-eval_whale", term="Whale", category="slang",
        aliases=["whales", "whale fan"],
        definition="A fan who spends far more than a typical fan; a small number of such high spenders can account for a large share of a creator's income.",
        answer_guidance="Explain neutrally; don't mock fans."),
    "soft_block": TermRecord(id="term-eval_soft_block", term="Soft block", category="slang",
        aliases=["softblock", "সফট ব্লক"],
        definition="Blocking someone and immediately unblocking them, so they are removed as a follower and stop seeing your posts without a lasting visible block.",
        details="A quieter alternative to a full block; they can still follow again later."),
    "sfs": TermRecord(id="term-eval_sfs", term="Shoutout for shoutout", category="creator_platform",
        aliases=["SFS", "S4S"],
        definition="Two creators agree to promote each other's accounts to their own audiences so both reach new followers."),
    "rebill_rate": TermRecord(id="term-eval_rebill_rate", term="Rebill rate", category="creator_platform",
        aliases=["rebill", "renewal rate"],
        definition="The percentage of subscribers whose subscription renews (rebills) when the billing period ends.",
        details="A higher rebill rate means better retention; creators usually see it in their earnings statistics."),
    "catfishing": TermRecord(id="term-eval_catfishing", term="Catfishing", category="dating_relationships",
        aliases=["catfish"],
        definition="Pretending to be someone else online, with fake photos or a fake identity, usually to start a relationship or get something from the other person."),
    "thirst_trap": TermRecord(id="term-eval_thirst_trap", term="Thirst trap", category="slang",
        aliases=["thirst traps"],
        definition="A post or photo shared mainly to attract attention, compliments or reactions, often flattering or suggestive."),
    "cuffing_season": TermRecord(id="term-eval_cuffing_season", term="Cuffing season", category="dating_relationships",
        definition="Informal slang for the colder months, when people are said to look for a relationship to settle into, sometimes losing interest when the weather warms up.",
        details="A joke-ish trend, not a fixed date or a real rule.",
        answer_guidance="Don't claim to know what time of year it is for the user."),
    "green_flag": TermRecord(id="term-eval_green_flag", term="Green flag", category="dating_relationships",
        aliases=["green flags"],
        definition="A positive sign in a partner or relationship that points to healthy, trustworthy behaviour: the opposite of a red flag.",
        details="Examples: respecting boundaries, consistent communication, owning mistakes."),
    "orbiting": TermRecord(id="term-eval_orbiting", term="Orbiting", category="dating_relationships",
        definition="When someone stops talking to you directly but keeps watching your stories or liking your posts on social media."),
}


def ctx(key: str) -> tuple[str, str, list[str]]:
    """(terminology_context, source, term+aliases) for a store id or an authored key."""
    if key.startswith("term-"):
        rec = STORE.get(key)
        return rec.to_context(), f"knowledge_store:{key}", [rec.term, *rec.aliases]
    rec = AUTHORED[key]
    return rec.to_context(), "authored_for_eval", [rec.term, *rec.aliases]


# (id, language, term key, user turns, per-turn expectations, behaviours, note)
# expectation keys: script (latin|bengali|any), max_chars, min_chars, shorter_than_previous,
#                   grounding_any (lower-case substrings; any one counts), banglish_markers
CASES = [
    ("tg-01", "banglish", "term-edging", ["edging mane ki?"],
     [{"script": "latin", "max_chars": 350, "grounding_any": ["climax", "orgasm", "peak", "pause", "delay", "deri", "thami", "arousal"]}],
     ["banglish_definition", "unseen_term", "concise"], "Short, direct Banglish definition; respectful, non-graphic."),
    ("tg-02", "banglish", "term-sensory_play", ["sensry play ki jinis?"],
     [{"script": "latin", "grounding_any": ["texture", "temperature", "sensation", "onubhuti", "anubhuti", "touch", "feel"]}],
     ["banglish_definition", "unseen_term", "typo"], "Understands the typo without correcting the user."),
    ("tg-03", "banglish", "term-power_play", ["power exchange bolte ki bojhay?"],
     [{"script": "latin", "grounding_any": ["control", "dominan", "submiss", "consent", "consensual", "negotiat"]}],
     ["banglish_definition", "unseen_alias"], "Asked by an alias, not the main term name."),
    ("tg-04", "banglish", "term-tantric_breathing", ["tantric breathing ki?", "simple kore bolo"],
     [{"script": "latin", "grounding_any": ["breath", "shash", "shwas", "slow", "connection", "sync"]},
      {"script": "latin", "shorter_than_previous": True, "banglish_markers": True}],
     ["banglish_definition", "unseen_term", "simple_kore_bolo", "banglish_followup"], "Second reply is simpler and shorter, still Banglish."),
    ("tg-05", "banglish", "benching", ["benching mane ki relationship e?"],
     [{"script": "latin", "grounding_any": ["backup", "option", "commit", "interest", "prioriti"]}],
     ["banglish_definition", "unseen_term", "grounding"], "Must not confuse with ghosting; uses the supplied definition."),
    ("tg-06", "banglish", "tip_menu", ["tip menu ki, creator der jonno?", "ekta example dao"],
     [{"script": "latin", "grounding_any": ["tip", "extra", "request", "price", "unlock", "list"]},
      {"script": "latin", "banglish_markers": True}],
     ["banglish_definition", "unseen_term", "banglish_followup", "grounding"], "Example must not invent specific platform prices as fact."),
    ("tg-07", "banglish", "term-temperature_play", ["temperature play mane ki", "eta Banglay bolo"],
     [{"script": "latin", "grounding_any": ["cold", "warm", "thanda", "gorom", "temperature", "safe"]},
      {"script": "bengali"}],
     ["banglish_definition", "unseen_term", "language_switch_to_bengali"], "Second reply switches to Bengali script."),
    ("tg-08", "banglish", "whale", ["creator der modhe 'whale' bolte ki bojhay?"],
     [{"script": "latin", "grounding_any": ["spend", "spender", "khoroch", "beshi", "income", "taka", "pay"]}],
     ["banglish_definition", "unseen_term", "grounding"], "Neutral, doesn't mock fans."),
    ("tg-09", "banglish", "term-roleplay", ["roleplay ki, detail e bolo"],
     [{"script": "latin", "min_chars": 250, "grounding_any": ["scenario", "character", "fiction", "consent", "boundar", "safe word"]}],
     ["banglish_definition", "unseen_term", "detailed"], "Detailed request gets a fuller answer, still non-graphic."),
    ("tg-10", "bn", "term-mirror_play", ["মিরর প্লে মানে কী?"],
     [{"script": "bengali", "grounding_any": ["আয়না", "আয়না", "mirror", "মিরর"]}],
     ["bengali_definition", "unseen_term"], "Natural Bengali, not an English sentence with Bengali nouns."),
    ("tg-11", "bn", "term-spooning", ["স্পুনিং কী?", "আরেকটু সহজ করে বলো"],
     [{"script": "bengali", "grounding_any": ["পেছন", "পিছন", "জড়িয়ে", "কাছাকাছি", "cuddl", "শুয়ে"]},
      {"script": "bengali", "shorter_than_previous": True}],
     ["bengali_definition", "unseen_term", "bengali_followup"], "Bengali follow-up: simpler and shorter."),
    ("tg-12", "bn", "soft_block", ["সফট ব্লক মানে কী?"],
     [{"script": "bengali", "grounding_any": ["ব্লক", "আনব্লক", "unblock", "follower", "ফলোয়ার", "ফলোয়ার"]}],
     ["bengali_definition", "unseen_term", "grounding"], "Explains the block-then-unblock mechanic from the supplied definition."),
    ("tg-13", "bn", "term-blindfold", ["ব্লাইন্ডফোল্ড মানে কী?", "eta English e bolo"],
     [{"script": "bengali", "grounding_any": ["চোখ", "ঢেকে", "ঢাকা", "অনুভূতি"]},
      {"script": "latin", "grounding_any": ["eye", "cover", "senses", "consent"]}],
     ["bengali_definition", "unseen_term", "language_switch_to_english"], "Second reply switches to English."),
    ("tg-14", "bn", "sfs", ["SFS মানে কী ক্রিয়েটরদের মধ্যে?"],
     [{"script": "bengali", "grounding_any": ["শাউটআউট", "shoutout", "প্রচার", "promote", "একে অপর", "দুজন"]}],
     ["bengali_definition", "unseen_term", "unseen_alias"], "Asked by the abbreviation."),
    ("tg-15", "en", "term-lap_dance", ["What does lap dance mean?"],
     [{"script": "latin", "max_chars": 350, "grounding_any": ["dance", "lap", "seated", "private"]}],
     ["english_definition", "unseen_term", "concise"], "Concise, respectful English."),
    ("tg-16", "en", "rebill_rate", ["whats a rebill rate"],
     [{"script": "latin", "grounding_any": ["renew", "percentage", "percent", "subscri", "retention"]}],
     ["english_definition", "unseen_term", "typo"], "Lower-case/no-apostrophe input handled normally."),
    ("tg-17", "en", "term-dirty_talk", ["Can you explain dirty talk in detail?"],
     [{"script": "latin", "min_chars": 250, "grounding_any": ["suggestive", "arous", "consen", "boundar", "respect"]}],
     ["english_definition", "unseen_term", "detailed"], "Detailed but non-graphic."),
    ("tg-18", "en", "catfishing", ["What's catfishing?", "Banglish e explain koro"],
     [{"script": "latin", "grounding_any": ["pretend", "fake", "identity", "someone else", "online"]},
      {"script": "latin", "banglish_markers": True, "grounding_any": ["fake", "online", "pretend", "onno"]}],
     ["english_definition", "unseen_term", "language_switch_to_banglish"], "Second reply in natural Banglish."),
    ("tg-19", "en", "thirst_trap", ["wat is a thrist trap"],
     [{"script": "latin", "grounding_any": ["attention", "compliment", "reaction", "photo", "post"]}],
     ["english_definition", "unseen_term", "typo"], "Understands the misspelling without lecturing."),
    ("tg-20", "mixed", "term-deep_kissing", ["french kiss মানে কী, একটু বলো"],
     [{"script": "any", "grounding_any": ["tongue", "জিভ", "passion", "গভীর", "close", "kiss", "চুম"]}],
     ["mixed_definition", "unseen_alias"], "Alias of Deep Kissing; natural code-switching."),
    ("tg-21", "mixed", "term-body_worship", ["body worship ki jinis, বুঝিয়ে বলো"],
     [{"script": "any", "grounding_any": ["admir", "প্রশংসা", "respect", "touch", "শরীর", "attention"]}],
     ["mixed_definition", "unseen_term"], "Mixed input; natural mixed reply."),
    ("tg-22", "mixed", "cuffing_season", ["cuffing season মানে কী? ekhon ki sei time?"],
     [{"script": "any", "grounding_any": ["cold", "শীত", "winter", "relationship", "সম্পর্ক", "thanda"]}],
     ["mixed_definition", "unseen_term", "grounding"], "Must not claim to know the current season/date."),
    ("tg-23", "mixed", "green_flag", ["relationship e green flag bolte কী বোঝায়?", "short kore bolo"],
     [{"script": "any", "grounding_any": ["healthy", "positive", "trust", "ভালো", "red flag", "respect"]},
      {"script": "any", "shorter_than_previous": True}],
     ["mixed_definition", "unseen_term", "short_kore_bolo"], "Second reply clearly shorter."),
    ("tg-24", "mixed", "orbiting", ["orbiting কী জিনিস dating e?", "example দাও"],
     [{"script": "any", "grounding_any": ["story", "stories", "like", "social", "watch", "কথা"]},
      {"script": "any"}],
     ["mixed_definition", "unseen_term", "grounding"], "Example stays consistent with the supplied definition."),
]


def frozen_blob() -> str:
    return "\n".join(m["content"].lower() for line in open(FROZEN, encoding="utf-8")
                     for m in json.loads(line)["messages"])


def occurs(needle: str, blob: str) -> bool:
    return re.search(r"(?<![a-zঀ-৿])" + re.escape(needle.lower()) + r"(?![a-zঀ-৿])", blob) is not None


def build_terminology_suite(blob: str) -> list[dict]:
    cases, seen_violations = [], []
    for cid, lang, key, turns, expect, behaviours, note in CASES:
        context, source, names = ctx(key)
        for name in names:
            if occurs(name, blob):
                seen_violations.append(f"{cid}: '{name}' occurs in the frozen V0.2 data")
        cases.append({
            "id": cid,
            "language": lang,
            "term": names[0],
            "term_source": source,
            "terminology_context": context,
            "system_v02": build_system_prompt(prompt_version="v0.2", terminology_context=context),
            "turns": turns,
            "expect": expect,
            "forbidden_phrases": FORBIDDEN,
            "behaviours": behaviours,
            "review_note": note,
        })
    if seen_violations:
        raise SystemExit("evaluation terms are not unseen:\n  " + "\n  ".join(seen_violations))
    return cases


def v01_train_ids() -> set[str]:
    """V0.1 training records = V0.1's frozen approved ids minus those whose content
    landed in V0.1's validation/test exports (matched by content, as V0.1 exported
    messages without ids)."""
    ids = json.loads(V01_MANIFEST.read_text(encoding="utf-8"))["conversation_ids"]
    eval_fps = {json.dumps(json.loads(line)["messages"], sort_keys=True, ensure_ascii=False)
                for s in ("validation", "test") for line in open(V01_EXPORT / f"{s}.jsonl", encoding="utf-8")}
    snap = PROJECT_ROOT / "data/production/snapshots/rupsaa_v0.1_training/approved"
    out = set()
    for rid in ids:
        rec = json.loads((snap / f"{rid}.json").read_text(encoding="utf-8"))
        msgs = [{"role": m["role"], "content": m["content"]} for m in rec["messages"]]
        if json.dumps(msgs, sort_keys=True, ensure_ascii=False) not in eval_fps:
            out.add(rid)
    return out


def build_manifests() -> dict:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    frozen = {json.loads(line)["id"]: json.loads(line) for line in open(FROZEN, encoding="utf-8")}
    v01_train = v01_train_ids()
    v01_counts = json.loads(V01_MANIFEST.read_text(encoding="utf-8"))
    expected_v01_train = sum(1 for _ in open(V01_EXPORT / "train.jsonl", encoding="utf-8"))
    if len(v01_train) != expected_v01_train:
        raise SystemExit(f"reconstructed V0.1 train set has {len(v01_train)} ids, V0.1 train.jsonl has {expected_v01_train}")

    out = {"created_from": {"dataset_sha256": manifest["dataset_sha256"],
                            "v01_train_records": len(v01_train), "v01_approved_records": v01_counts["approved_count"]},
           "definition_seen_in_v01_training": "record id is in V0.1's training split (V0.1 approved ids minus the "
                                              "records whose content is in V0.1 validation/test). Repaired or rewritten "
                                              "versions of a V0.1 training record keep its id and are excluded too.",
           "A_full": {}, "B_clean_v01_vs_v02": {}}
    for split in ("validation", "test"):
        ids = manifest["splits"][split]["ids"]
        seen = sorted(i for i in ids if i in v01_train)
        recorded = sorted(manifest["splits"][split]["ids_also_in_v01_train"])
        if seen != recorded:
            raise SystemExit(f"{split}: recomputed V0.1-seen ids differ from the freeze manifest")
        clean = [i for i in ids if i not in v01_train]
        lang = lambda xs: dict(sorted(Counter(frozen[i]["language"] for i in xs).items()))  # noqa: E731
        out["A_full"][split] = {"count": len(ids), "language_distribution": lang(ids), "ids": ids}
        out["B_clean_v01_vs_v02"][split] = {"count": len(clean), "language_distribution": lang(clean), "ids": clean,
                                            "excluded_seen_in_v01_training": {"count": len(seen), "ids": seen}}
    return out


LIVE_CHECKS = [
    {"id": "live-01", "turns": ["hi, tumi kemon acho?"], "expect": {"script": "latin"},
     "look_for": "Natural Banglish greeting back, asks how the user is; no fixed catchphrase."},
    {"id": "live-02", "turns": ["achcha"], "expect": {"script": "latin", "max_chars": 120},
     "look_for": "Short, natural reaction/prompt to continue."},
    {"id": "live-03", "turns": ["ajke amar mood ta bhalo na"], "expect": {"script": "latin"},
     "look_for": "Warm, asks what happened; no lecture."},
    {"id": "live-04", "turns": ["Strip mane ki?"], "expect": {"script": "latin"},
     "look_for": "Banglish definition grounded in the Strip terminology entry, non-graphic."},
    {"id": "live-05", "turns": ["foreplay ki?"], "expect": {"script": "latin"},
     "look_for": "Banglish definition grounded in the Foreplay terminology entry."},
    {"id": "live-06", "turns": ["Strip mane ki?", "eta short kore bolo"], "expect": {"script": "latin"},
     "look_for": "Second reply shorter, same meaning."},
    {"id": "live-07", "turns": ["foreplay ki?", "এটা বাংলায় বুঝিয়ে বলো"], "expect": {"script": "bengali"},
     "look_for": "Second reply in natural Bengali script."},
    {"id": "live-08", "turns": ["What does edging mean?", "Banglish e explain koro"], "expect": {"script": "latin"},
     "look_for": "Second reply in natural Banglish."},
    {"id": "live-09", "turns": ["amar favourite color blue", "ami ki color bolechilam?"], "expect": {"script": "latin"},
     "look_for": "Second reply: blue, from history."},
    {"id": "live-10", "turns": ["amar naam Rupa, ami Kolkata te thaki", "ajke kaj e onek chap chilo", "ami age ki bolechilam?"],
     "expect": {"script": "latin"}, "look_for": "Third reply recalls the name and/or city from history, no invention."},
]


def write_readme(cases: list[dict], manifests: dict) -> str:
    by_lang = Counter(c["language"] for c in cases)
    behaviours = Counter(b for c in cases for b in c["behaviours"])
    lines = [
        "# Rupsaa V0.2 post-training evaluation suites",
        "",
        "Evaluation only: nothing in this folder is ever training data. Run after training with "
        "`bash scripts/posttrain_rupsaa_v02.sh`.",
        "",
        "## 1. Terminology generalisation (`terminology_generalization.jsonl`)",
        "",
        f"{len(cases)} cases. Each term, and every alias, was checked to occur **nowhere** in the frozen V0.2 data "
        "(all splits, all roles), so a good score means V0.2 learned *how to use* supplied terminology rather "
        "than remembering the 30 training terms. The build refuses to write if that check fails.",
        "",
        f"- Languages: {dict(by_lang)}",
        f"- Term sources: {dict(Counter(c['term_source'].split(':')[0] for c in cases))} "
        "(live owner-authored entries from `knowledge/terminology/` plus creator/dating terms authored for this eval)",
        f"- Behaviours: {dict(sorted(behaviours.items()))}",
        "",
        "Each case supplies the term block exactly as the runtime does (`TermRecord.to_context()` under "
        "`Reference terminology:`); the same block is kept for follow-up turns, like the runtime's FOLLOWUP carry-over. "
        "Each model is run with its own serving system prompt (V0.1: `build_system_prompt(prompt_version='v0.1')`, "
        "V0.2: `prompt_version='v0.2'`).",
        "",
        "Automatic checks are heuristics that flag replies for review; the human review is the decision:",
        "- expected reply script (latin / bengali / any)",
        "- length bounds for concise/detailed requests; follow-up \"short/simple\" replies must be shorter",
        "- grounding: at least one concept from the supplied definition (English, Banglish or Bengali form)",
        "- Banglish markers after a switch to Banglish",
        f"- forbidden phrases: {', '.join(FORBIDDEN)}",
        "",
        "## 2. Held-out evaluation manifests (`eval_manifests.json`)",
        "",
        "| | Validation | Test |",
        "|---|---|---|",
        f"| A. Full frozen V0.2 split (absolute V0.2 evaluation) | {manifests['A_full']['validation']['count']} | {manifests['A_full']['test']['count']} |",
        f"| B. Clean V0.1-vs-V0.2 subset (fair comparison) | {manifests['B_clean_v01_vs_v02']['validation']['count']} | {manifests['B_clean_v01_vs_v02']['test']['count']} |",
        f"| Excluded from B: seen during V0.1 training | {manifests['B_clean_v01_vs_v02']['validation']['excluded_seen_in_v01_training']['count']} | {manifests['B_clean_v01_vs_v02']['test']['excluded_seen_in_v01_training']['count']} |",
        "",
        manifests["definition_seen_in_v01_training"],
        "The frozen splits themselves are unchanged; this is metadata only.",
        "",
        "## 3. Live behaviour checks (`live_behavior_checks.json`)",
        "",
        "The owner's 10 live prompts, run through the real runtime context builder "
        "(`rupsaa.rag.context_builder.build_turn_knowledge`: routing, live terminology store, memory note), "
        "document RAG off (the web UI default).",
        "",
    ]
    for c in LIVE_CHECKS:
        lines.append(f"- **{c['id']}** {' → '.join(c['turns'])} — {c['look_for']}")
    return "\n".join(lines) + "\n"


def main() -> None:
    blob = frozen_blob()
    cases = build_terminology_suite(blob)
    manifests = build_manifests()
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "terminology_generalization.jsonl", "w", encoding="utf-8") as f:
        for c in cases:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    (OUT / "eval_manifests.json").write_text(json.dumps(manifests, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "live_behavior_checks.json").write_text(json.dumps(LIVE_CHECKS, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "README.md").write_text(write_readme(cases, manifests), encoding="utf-8")
    digest = hashlib.sha256((OUT / "terminology_generalization.jsonl").read_bytes()).hexdigest()
    print(f"terminology generalisation: {len(cases)} unseen cases ({dict(Counter(c['language'] for c in cases))}) sha256 {digest[:16]}…")
    for s in ("validation", "test"):
        print(f"{s}: full {manifests['A_full'][s]['count']}, clean {manifests['B_clean_v01_vs_v02'][s]['count']} "
              f"(excluded {manifests['B_clean_v01_vs_v02'][s]['excluded_seen_in_v01_training']['count']})")
    print(f"live behaviour checks: {len(LIVE_CHECKS)}")
    print(f"wrote {OUT.relative_to(PROJECT_ROOT)}/")


if __name__ == "__main__":
    main()
