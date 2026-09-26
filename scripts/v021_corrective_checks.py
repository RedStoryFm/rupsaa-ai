#!/usr/bin/env python3
"""Automatic corpus checks for the V0.2.1 corrective set + the human-review document.

    python scripts/v021_corrective_checks.py

Checks are gates for obvious defects only — they never approve data. Every
record is written into CORRECTIVE_DATA_REVIEW.md for the owner to read.
"""

from __future__ import annotations

import difflib
import json
import re
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rupsaa.config import PROJECT_ROOT  # noqa: E402

CORR = PROJECT_ROOT / "data/production/corrective/rupsaa_v0.2.1/corrective_records.jsonl"
FROZEN = PROJECT_ROOT / "data/production/snapshots/rupsaa_v0.2_training/frozen_records.jsonl"
EVAL = PROJECT_ROOT / "data/production/evaluation/rupsaa_v0.2"
REPORT_DIR = PROJECT_ROOT / "data/production/reports/rupsaa_v0.2.1_preparation"

CATCHPHRASES = ["honestly", "actually", "fair call", "fair enough", "heyy", "bindaas", "baby", "babe", "basically",
                "oh dear", "anything more"]
DANCE_TRAIN = PROJECT_ROOT / "data/production/corrective/rupsaa_v0.2.1/dance_records.jsonl"
DANCE_HOLDOUT = PROJECT_ROOT / "data/production/corrective/rupsaa_v0.2.1/dance_holdout_records.jsonl"
DANCE_DIR = PROJECT_ROOT / "knowledge/dance"
# Phrases from V0.2's garbled live replies ("jiggesh" itself is fine Banglish for "ask", so it is not listed).
BAD_BANGLISH = ["kichu niye kichu", "bishoy der", "onno der jonno", "make kora", "shobcheye beshi kichu"]
ROMANIZATION = {"shobcheye/sobcheye": ("shobcheye", "sobcheye"), "bhalo/valo": ("bhalo", "valo"),
                "shomoy/somoy": ("shomoy", "somoy"), "sheta/seta": ("sheta", "seta")}
EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿]")
BN = re.compile(r"[ঀ-৿]")
FOREIGN = re.compile("[\u0600-\u06FF\u0900-\u0963\u0966-\u097F\u4E00-\u9FFF\u3040-\u30FF\uAC00-\uD7AF]")  # not the danda "।" Bengali uses
MIXED_WORD = re.compile(r"[A-Za-z]+[ঀ-৿]+|[ঀ-৿]+[A-Za-z]+")
LIMITS = {"question_rate_all": 0.25, "question_rate_direct": 0.10, "top_opening_share": 0.06, "catchphrase_replies": 0,
          "top_first_token_share": 0.10, "top_skeleton_share": 0.05}
# Function words kept in a sentence "skeleton" (content words become "_"), to spot repeated sentence frames.
FUNCTION_WORDS = set("""ami tumi eta sheta oita ta ar o na je jodi tahole kintu karon mane hoy ache chilo kore korte
ekta ektu khub aro shudhu shob ki keno kivabe kothay kokhon tar er e te theke diye jonno moto sathe hole the a an
is are was it you i to of and but or if so that this with for in on be your my we they not no yes
আমি তুমি এটা সেটা আর ও না যে যদি তাহলে কিন্তু কারণ মানে হয় আছে ছিল করে করতে একটা একটু খুব আরও শুধু সব কী কেন কীভাবে
কোথায় কখন তার এর থেকে দিয়ে জন্য মতো সাথে হলে""".split())


def script(text: str) -> str:
    b, lat = len(BN.findall(text)), len(re.findall(r"[A-Za-z]", text))
    if b and b >= lat:
        return "bn"
    return "latin" if not b else "mix"


def expected_script(user: str, requested: str | None, state_lang: str | None) -> str:
    lang = requested or state_lang
    if lang == "bn":
        return "bn"
    if lang in ("banglish", "en"):
        return "latin"
    return "bn" if BN.search(user) else "latin"  # a Bengali-script question with an English word is still Bengali


def load_eval_prompts() -> list[str]:
    prompts = []
    for c in (json.loads(line) for line in open(EVAL / "terminology_generalization.jsonl", encoding="utf-8")):
        prompts += c["turns"]
    for name in ("live_behavior_checks.json", "posttrain_supplementary_checks.json"):
        for c in json.loads((EVAL / name).read_text(encoding="utf-8")):
            prompts += c["turns"]
    return prompts


_PLACE_VOCAB: set[str] | None = None


def dance_faithfulness(rec: dict) -> list[str]:
    """Every origin place named in a (Latin-script) reply must come from the dance entries the runtime
    attached to that conversation; a reply may not claim steps the owner never recorded."""
    global _PLACE_VOCAB
    from rupsaa.rag.dance import DanceStore
    store = DanceStore(DANCE_DIR)
    if _PLACE_VOCAB is None:
        _PLACE_VOCAB = {w for d in store.list() for w in re.findall(r"[A-Z][a-zA-Zāó]+", d.origin)} - {"United", "States", "India", "South", "North", "New", "Middle", "East", "Africa", "French", "Southern"}
    attached = {t for tr in rec["runtime_trace"] for t in tr["terms_used"] if t.startswith("dance-")}
    allowed = " ".join(store.get(t).origin + " " + store.get(t).description for t in attached)
    out = []
    for i, m in enumerate(x for x in rec["messages"] if x["role"] == "assistant"):
        for place in _PLACE_VOCAB:
            if re.search(r"\b" + re.escape(place) + r"\b", m["content"]) and place not in allowed:
                out.append(f"turn {i + 1}: names '{place}', which is not in the attached dance entries {sorted(attached)}")
        if re.search(r"\b(step \d|first step|step one|1\.|prothom step)", m["content"], re.I):
            out.append(f"turn {i + 1}: looks like step instructions — none are in the owner's records")
    if not attached:
        out.append("no dance entry attached by the runtime")
    return out


def main() -> None:
    from scripts.v021_replay_live import OWNER_SEQUENCE

    recs = [json.loads(line) for line in open(CORR, encoding="utf-8")]
    n_corr = len(recs)
    for extra in (DANCE_TRAIN, DANCE_HOLDOUT):
        if extra.exists():
            recs += [json.loads(line) for line in open(extra, encoding="utf-8")]
    dance_ids = {r["id"] for r in recs[n_corr:]}
    frozen = [json.loads(line) for line in open(FROZEN, encoding="utf-8")]
    frozen_users = {m["content"].strip().lower() for r in frozen for m in r["messages"] if m["role"] == "user"}
    eval_terms = [json.loads(line)["term"].lower() for line in open(EVAL / "terminology_generalization.jsonl", encoding="utf-8")]
    protected = [p.lower() for p in OWNER_SEQUENCE] + [p.lower() for p in load_eval_prompts()]

    flags: dict[str, list[str]] = {r["id"]: [] for r in recs}
    info: list[str] = []
    replies, direct_replies = [], []
    for r in recs:
        users = [m["content"] for m in r["messages"] if m["role"] == "user"]
        asst = [m["content"] for m in r["messages"] if m["role"] == "assistant"]
        state_lang = None
        for i, (u, a, tr) in enumerate(zip(users, asst, r["runtime_trace"])):
            state_lang = tr["requested_language"] or (state_lang if tr["route"] in ("followup", "memory") else None)
            want = expected_script(u, tr["requested_language"], state_lang)
            got = script(a)
            if got != want and not (want == "bn" and got == "mix"):
                flags[r["id"]].append(f"turn {i + 1}: reply script {got}, expected {want}")
            low = a.lower()
            for p in CATCHPHRASES:
                if re.search(r"(?<![a-z])" + re.escape(p) + r"(?![a-z])", low):
                    flags[r["id"]].append(f"turn {i + 1}: catchphrase '{p}'")
            for p in BAD_BANGLISH:
                if p in low:
                    flags[r["id"]].append(f"turn {i + 1}: known-bad Banglish '{p}'")
            if EMOJI.search(a):
                flags[r["id"]].append(f"turn {i + 1}: emoji")
            if FOREIGN.search(a) or FOREIGN.search(u):
                flags[r["id"]].append(f"turn {i + 1}: foreign-script characters")
            if MIXED_WORD.search(a):
                flags[r["id"]].append(f"turn {i + 1}: mixed-script word {MIXED_WORD.findall(a)}")
            replies.append(a)
            if r["category"] in ("direct_definition", "terminology", "typo_terminology", "acknowledgement", "memory_recall") \
                    or r["category"].startswith("dance_"):
                direct_replies.append(a)
        for u in users:
            ul = u.strip().lower()
            if ul in frozen_users:
                info.append(f"{r['id']}: user turn also in frozen V0.2 (short command, reply differs): {u!r}")
            for p in protected:
                # Fuzzy similarity is meaningless for one-word acknowledgements; those must just not be identical.
                close = len(ul) >= 12 and len(p) >= 12 and difflib.SequenceMatcher(None, ul, p).ratio() >= 0.9
                if ul == p or close:
                    flags[r["id"]].append(f"user turn too close to an evaluation/live-test prompt: {u!r} ~ {p!r}")
                    break
        if r["id"] in dance_ids:
            flags[r["id"]] += dance_faithfulness(r)
        blob = " ".join(m["content"].lower() for m in r["messages"][1:])
        for t in eval_terms + ["strip", "foreplay", "ফোরপ্লে", "স্ট্রিপ"]:
            if re.search(r"(?<![a-zঀ-৿])" + re.escape(t) + r"(?![a-zঀ-৿])", blob):
                flags[r["id"]].append(f"mentions held-out term '{t}'")

    q_all = sum(a.strip().endswith("?") for a in replies) / len(replies)
    q_direct = sum(a.strip().endswith("?") for a in direct_replies) / max(1, len(direct_replies))
    openings = Counter(" ".join(re.findall(r"[\wঀ-৿']+", a.lower())[:2]) for a in replies)
    top_open = openings.most_common(1)[0][1] / len(replies)
    dupes = [(a, b) for i, a in enumerate(replies) for b in replies[i + 1:]
             if difflib.SequenceMatcher(None, a, b).ratio() >= 0.85]
    catch_total = sum(1 for f in flags.values() for x in f if "catchphrase" in x)
    tokens = [re.findall(r"[\wঀ-৿']+", a.lower()) for a in replies]
    first_tokens = Counter(t[0] for t in tokens if t)
    top_first = first_tokens.most_common(1)[0][1] / len(replies)
    skeletons = Counter()
    for a in replies:
        for sent in re.split(r"(?<=[.!?।])\s+|\s+—\s+", a):
            words = re.findall(r"[\wঀ-৿']+", sent.lower())
            if len(words) < 4:
                continue
            sk = []
            for w in words:
                tok = w if w in FUNCTION_WORDS else "_"
                if not (tok == "_" and sk and sk[-1] == "_"):
                    sk.append(tok)
            if any(t != "_" for t in sk):  # a sentence with no function words has no frame to repeat
                skeletons[" ".join(sk[:6])] += 1
    n_sent = sum(skeletons.values()) or 1
    top_skel = skeletons.most_common(1)[0][1] / n_sent
    exact_dupes = [a for a, c in Counter(replies).items() if c > 1]
    emoji_rate = sum(bool(EMOJI.search(a)) for a in replies) / len(replies)
    defs = [a for r in recs if r["category"] in ("terminology", "typo_terminology", "direct_definition")
            for a in [m["content"] for m in r["messages"] if m["role"] == "assistant"][:1]]
    x_mane = sum(bool(re.match(r"^[\w\s'ঀ-৿-]{1,30}\s(mane|মানে|means|is)\b", a)) for a in defs)
    all_lengths = sorted(len(a) for a in replies)
    pct = lambda q: all_lengths[min(len(all_lengths) - 1, int(q * len(all_lengths)))]  # noqa: E731
    lat_text = " ".join(a.lower() for a in replies if script(a) == "latin")
    roman = {k: {v: len(re.findall(r"\b" + v + r"\b", lat_text)) for v in vs} for k, vs in ROMANIZATION.items()}
    lengths = {}
    for r in recs:
        for m in r["messages"]:
            if m["role"] == "assistant":
                lengths.setdefault(script(m["content"]), []).append(len(m["content"]))

    gates = {
        "no_flagged_records": sum(1 for f in flags.values() if f) == 0,
        "question_rate_all": q_all <= LIMITS["question_rate_all"],
        "question_rate_direct": q_direct <= LIMITS["question_rate_direct"],
        "top_opening_share": top_open <= LIMITS["top_opening_share"],
        "no_near_duplicate_replies": not dupes,
        "no_catchphrases": catch_total == 0,
        "top_first_token_share": top_first <= LIMITS["top_first_token_share"],
        "top_skeleton_share": top_skel <= LIMITS["top_skeleton_share"],
        "no_exact_duplicate_replies": not exact_dupes,
        "no_emoji": emoji_rate == 0,
    }
    summary = {
        "records": len(recs),
        "corrective_records": n_corr,
        "dance_train_records": sum(1 for r in recs[n_corr:] if r.get("review_status") != "held_out_never_train"),
        "dance_holdout_records": sum(1 for r in recs[n_corr:] if r.get("review_status") == "held_out_never_train"),
        "assistant_replies": len(replies),
        "by_category": dict(Counter(r["category"] for r in recs)),
        "by_final_language": dict(Counter(r["language"] for r in recs)),
        "turns": dict(Counter(len(r["runtime_trace"]) for r in recs)),
        "final_routes": dict(Counter(r["runtime_trace"][-1]["route"] for r in recs)),
        "with_terminology_block": sum("Reference terminology:" in r["messages"][0]["content"] for r in recs),
        "with_language_directive": sum("Response language:" in r["messages"][0]["content"] for r in recs),
        "with_recall_note": sum("asks about something they said earlier" in r["messages"][0]["content"]
                                or "asks about earlier messages" in r["messages"][0]["content"] for r in recs),
        "question_ending_rate_all": round(q_all, 3),
        "question_ending_rate_direct": round(q_direct, 3),
        "top_openings": openings.most_common(8),
        "top_opening_share": round(top_open, 3),
        "near_duplicate_reply_pairs": dupes[:10],
        "top_first_tokens": first_tokens.most_common(10),
        "top_first_token_share": round(top_first, 3),
        "opening_bigrams": openings.most_common(12),
        "top_sentence_skeletons": skeletons.most_common(10),
        "top_skeleton_share": round(top_skel, 3),
        "exact_duplicate_replies": exact_dupes,
        "emoji_rate": emoji_rate,
        "definition_replies_starting_X_mane": f"{x_mane}/{len(defs)} (expected: definitions answer first)",
        "reply_length_percentiles": {"p10": pct(0.1), "p50": pct(0.5), "p90": pct(0.9), "max": all_lengths[-1]},
        "assistant_reply_language": dict(Counter(script(a) for a in replies)),
        "romanization_counts": roman,
        "reply_chars_by_script": {k: {"n": len(v), "mean": round(statistics.mean(v)), "max": max(v)} for k, v in lengths.items()},
        "limits": LIMITS,
        "gates": gates,
        "all_gates_pass": all(gates.values()),
        "flags": {k: v for k, v in flags.items() if v},
        "info": info,
        "note": "Automatic gates catch defects; they do not approve data. Owner review is required.",
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "corrective_checks.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (REPORT_DIR / "CORRECTIVE_DATA_REVIEW.md").write_text(review_doc(recs, summary), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("records", "by_category", "by_final_language", "question_ending_rate_all",
                                              "question_ending_rate_direct", "top_opening_share", "gates", "flags",
                                              "romanization_counts")}, ensure_ascii=False, indent=1))


def review_doc(recs: list[dict], s: dict) -> str:
    L = ["# Rupsaa V0.2.1 corrective data — owner review", "",
         "**Status: reviewed by Claude against the Banglish style guide; frozen as rupsaa_v0.2.1 only after all "
         "gates passed (see PRETRAINING_REPORT.md). NOT trained — owner approval required before training.**", "",
         "These conversations were written by Claude (an AI), not by a native speaker. The automatic checks "
         "below catch mechanical defects only; whether the Banglish and Bengali sound natural is exactly what "
         "needs your judgement — please read every one.", "",
         f"{s['records']} hand-written conversations ({s['assistant_replies']} assistant replies). "
         "System prompts were generated by the real runtime (router, terminology store, recall note, language "
         "directive) for each conversation's final turn — exactly what the app sends.", "",
         "## How to review", "",
         "For each record mark one of: **OK** · **FIX** (say what) · **DROP**. Judge, in order: meaning correct → "
         "Banglish/Bengali sounds like a fluent speaker typing → right script → fits the conversation → personality "
         "without catchphrases. Edit `data/production/corrective/rupsaa_v0.2.1/source_conversations.py` (or tell me the "
         "changes) and rebuild with `python scripts/v021_build_corrective.py`.", "",
         "## Automatic checks (defect gates only)", "",
         f"- by category: {s['by_category']}",
         f"- by final-reply language: {s['by_final_language']}",
         f"- turns per conversation: {s['turns']}; final routes: {s['final_routes']}",
         f"- system prompt carries: terminology block {s['with_terminology_block']}, language directive "
         f"{s['with_language_directive']}, recall note {s['with_recall_note']}",
         f"- replies ending with '?': all {s['question_ending_rate_all']:.0%} (limit {s['limits']['question_rate_all']:.0%}); "
         f"direct answers/definitions/acks/recall {s['question_ending_rate_direct']:.0%} (limit {s['limits']['question_rate_direct']:.0%})",
         f"- most common 2-word opening share {s['top_opening_share']:.1%} (limit {s['limits']['top_opening_share']:.0%}); "
         f"top: {s['top_openings'][:5]}",
         f"- near-duplicate reply pairs (≥0.85 similar): {len(s['near_duplicate_reply_pairs'])}",
         f"- Banglish romanization (chosen style first): {s['romanization_counts']}",
         f"- gates: {s['gates']} → **{'all pass' if s['all_gates_pass'] else 'SOME FAIL'}**",
         f"- flagged records: {len(s['flags'])}", ""]
    if s["flags"]:
        L += ["### Flags", ""] + [f"- `{k}`: {'; '.join(v)}" for k, v in s["flags"].items()] + [""]
    log_path = PROJECT_ROOT / "data/production/corrective/rupsaa_v0.2.1/REVIEW_LOG.json"
    log = json.loads(log_path.read_text(encoding="utf-8")) if log_path.exists() else None
    status = {r["id"]: r for r in log["records"]} if log else {}
    if log:
        L += ["## Language review (Claude, full read)", "",
              f"{log['summary']} — every conversation was read; rewritten ones follow "
              "`BANGLISH_STYLE_GUIDE.md`. Each record below shows its review status and, if changed, why.", ""]
    cats = list(dict.fromkeys(r["category"] for r in recs))
    for cat in cats:
        group = [r for r in recs if r["category"] == cat]
        L += [f"## {cat} ({len(group)})", ""]
        for r in group:
            sysp = r["messages"][0]["content"]
            extra = []
            if "Reference terminology:" in sysp:
                extra.append("terminology: " + ", ".join(sorted({t for tr in r["runtime_trace"] for t in tr["terms_used"]})))
            if "Response language:" in sysp:
                extra.append("language directive")
            if "said earlier" in sysp or "earlier messages" in sysp:
                extra.append("recall note")
            routes = " → ".join(tr["route"] for tr in r["runtime_trace"])
            L.append(f"### {r['id']} · {r['language']} · routes: {routes}{' · ' + '; '.join(extra) if extra else ''}")
            if r["id"] in status:
                st = status[r["id"]]
                L.append(f"_review: {st['status']}{' — ' + st['reason'] if st['reason'] else ''}_")
            for m in r["messages"][1:]:
                L.append(f"- **{'USER' if m['role'] == 'user' else 'RUPSAA'}:** {m['content']}")
            L += ["- review: ☐ OK ☐ FIX ☐ DROP — notes:", ""]
    return "\n".join(L)


if __name__ == "__main__":
    main()
