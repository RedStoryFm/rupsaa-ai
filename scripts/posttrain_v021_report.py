#!/usr/bin/env python3
"""Analyse posttrain_results.json from scripts/posttrain_v021.py -> metrics JSON + raw-output markdown.

    python scripts/posttrain_v021_report.py

Writes (data/production/reports/rupsaa_v0.2.1_posttraining/):
  posttrain_metrics.json   every automatic check, per variant (V0.2.1 vs V0.2)
  RAW_OUTPUTS.md           every generated reply verbatim, with route / attached records / flags
The human verdict lives in POSTTRAINING_REPORT.md (written after reading RAW_OUTPUTS.md).
Heuristic flags point at replies to read; they are not the verdict.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rupsaa.config import PROJECT_ROOT  # noqa: E402
from rupsaa.rag.dance import DanceStore  # noqa: E402
from scripts.v02_voice_audit import CATCHPHRASES as _V02_CATCH  # noqa: E402,F401
from scripts.v02_voice_audit import audit  # noqa: E402

OUT = PROJECT_ROOT / "data/production/reports/rupsaa_v0.2.1_posttraining"
R2 = PROJECT_ROOT / "data/production/exports/rupsaa_v0.2.1_r2"
V02_VOICE = PROJECT_ROOT / "data/production/reports/rupsaa_v0.2_posttraining/voice_audit.json"
BN = re.compile(r"[ঀ-৿]")
CATCH = ["honestly", "actually", "fair call", "fair enough", "heyy", "bindaas", "baby", "babe", "basically"]
STEP_RE = re.compile(r"\b(step \d|first step|step one|prothom step|1\.\s)", re.I)
TERM_EXPECT = {"Strip mane ki?": "term-strip_stripping", "strip ta ektu simple kore bojhao": "term-strip_stripping",
               "Foreplay ki?": "term-foreplay", "foreplay ki?": "term-foreplay", "Forplay ki?": "term-foreplay"}


def script(text: str) -> str:
    b, lat = len(BN.findall(text)), len(re.findall(r"[A-Za-z]", text))
    return "bn" if b and b >= lat else ("latin" if not b else "mix")


def load():
    return json.loads((OUT / "posttrain_results.json").read_text(encoding="utf-8"))


def dance_expectations() -> dict[str, list[str]]:
    from scripts.posttrain_v021 import SHOWCASE_EXPECT
    exp = dict((k, [v]) for k, v in SHOWCASE_EXPECT.items())
    for line in open(R2 / "dance_holdout.jsonl", encoding="utf-8"):
        r = json.loads(line)
        for u, tr in zip([m["content"] for m in r["messages"] if m["role"] == "user"], r["runtime_trace"]):
            exp[u] = sorted(t for t in tr["terms_used"] if t.startswith("dance-"))
    return exp


_PLACES: set[str] | None = None


def place_flags(reply: str, attached: list[str], store: DanceStore) -> list[str]:
    global _PLACES
    if _PLACES is None:
        _PLACES = {w for d in store.list() for w in re.findall(r"[A-Z][a-zA-Zāó]+", d.origin)} - {
            "United", "States", "India", "South", "North", "New", "Middle", "East", "Africa", "French", "Southern"}
    allowed = " ".join(store.get(t).origin + " " + store.get(t).description for t in attached if t.startswith("dance-"))
    return [p for p in _PLACES if re.search(r"\b" + re.escape(p) + r"\b", reply) and p not in allowed]


def turn_checks(t: dict, dance_exp: dict, store: DanceStore) -> dict:
    reply, user = t["reply"], t["user"]
    want = t.get("response_language") or ("bn" if BN.search(user) else "latin")
    want = {"banglish": "latin", "en": "latin"}.get(want, want)
    got = script(reply)
    c = {"script_ok": got == want or (want == "bn" and got == "mix"), "expected_script": want, "got_script": got,
         "catchphrases": [p for p in CATCH if re.search(r"(?<![a-z])" + re.escape(p) + r"(?![a-z])", reply.lower())],
         "ends_with_question": reply.strip().endswith("?"), "empty": not reply.strip()}
    exp_terms = dance_exp.get(user) or ([TERM_EXPECT[user]] if user in TERM_EXPECT else None)
    if exp_terms:
        c["expected_records"] = exp_terms
        c["records_attached"] = all(e in t["terms_used"] for e in exp_terms)
    dances = [x for x in t["terms_used"] if x.startswith("dance-")]
    if dances:
        c["foreign_places"] = place_flags(reply, dances, store)
        c["step_instructions"] = bool(STEP_RE.search(reply))
    return c


def main() -> None:
    res = load()
    store = DanceStore(PROJECT_ROOT / "knowledge/dance")
    dance_exp = dance_expectations()
    metrics = {"loss": {k: {kk: vv for kk, vv in v.items() if kk != "per_record"} for k, v in res["loss"].items() if k != "metric"}}
    if "terminology" in res:
        metrics["terminology_generalisation"] = {"pass_rate": res["terminology"]["pass_rate"], "by_language": res["terminology"]["by_language"]}
    gen = res.get("generation", {})
    replies = {"rupsaa_v021": [], "rupsaa_v02": []}
    group_stats = {}
    raw = ["# Rupsaa V0.2.1 R2 — raw generated outputs (verbatim, unedited)", "",
           "Every reply below is exactly what the model produced through the production service path "
           "(router, language control, recall note, terminology + dance stores). `[route · records · reply-language]`; "
           "flags are heuristics.", ""]

    def add_session(group, sid, runs):
        raw.append(f"### {group} · {sid}")
        for v, turns in runs.items():
            for t in turns:
                c = turn_checks(t, dance_exp, store)
                t["checks"] = c
                replies[v].append({"reply": t["reply"], "section": group, "case": sid})
                st = group_stats.setdefault(group, {}).setdefault(v, Counter())
                st["turns"] += 1
                st["script_ok"] += c["script_ok"]
                st["catchphrase_replies"] += bool(c["catchphrases"])
                st["ends_with_question"] += c["ends_with_question"]
                if "records_attached" in c:
                    st["record_turns"] += 1
                    st["records_attached"] += c["records_attached"]
                if "foreign_places" in c:
                    st["dance_turns"] += 1
                    st["dance_foreign_place_flags"] += bool(c["foreign_places"])
                    st["dance_step_flags"] += c["step_instructions"]
                flags = [k for k, ok in (("wrong script", not c["script_ok"]), ("catchphrase", c["catchphrases"]),
                                         ("record missing", c.get("records_attached") is False),
                                         ("place not in record", c.get("foreign_places")), ("steps", c.get("step_instructions"))) if ok]
                raw.append(f"- **{v}** [{t['route']} · {','.join(t['terms_used']) or '-'} · {t.get('response_language') or 'mirror'}] "
                           f"USER: {t['user']}  \n  RUPSAA: {t['reply']}" + (f"  \n  _flags: {', '.join(flags)}_" if flags else ""))
        raw.append("")

    raw += ["## Owner live conversation (one session each)", ""]
    for v, runs in gen.get("owner_live", {}).items():
        for run in runs:
            add_session("owner_live", f"{v} seed {run['seed']}", {v: run["turns"]})
    for group, cases in gen.get("sessions", {}).items():
        raw += [f"## {group}", ""]
        for case in cases:
            add_session(group, case["id"], case["runs"])
    if "terminology" in res:
        raw += ["## unseen terminology generalisation (24; fixed reference block, not the router)", ""]
        for case in res["terminology"]["cases"]:
            raw.append(f"### {case['id']} — {case['term']} ({case['language']})")
            for v, run in case["runs"].items():
                for t in run["turns"]:
                    failed = [k for k, ok in t["checks"].items() if not ok]
                    raw.append(f"- **{v}** USER: {t['user']}  \n  RUPSAA: {t['reply']}  \n  _checks failed: {', '.join(failed) or 'none'}_")
                    if v in replies:
                        replies[v].append({"reply": t["reply"], "section": "terminology", "case": case["id"]})
            raw.append("")
    metrics["sessions"] = {g: {v: dict(c) for v, c in d.items()} for g, d in group_stats.items()}
    metrics["style"] = {v: audit(r) for v, r in replies.items() if r}
    if V02_VOICE.exists():
        old = json.loads(V02_VOICE.read_text(encoding="utf-8"))
        metrics["style_previous_eval"] = {v: {k: old[v][k] for k in ("catchphrase_reply_rate", "most_common_opening_share",
                                                                        "mixed_script_words", "questions_per_reply", "chars_mean")}
                                          for v in old}
    metrics["isolation"] = gen.get("isolation")
    # owner live conversation attribution
    attrib = []
    for v, runs in gen.get("owner_live", {}).items():
        for run in runs:
            for t in run["turns"]:
                c = t["checks"]
                runtime_ok = c.get("records_attached", True)
                model_ok = c["script_ok"] and not c["catchphrases"] and not c.get("foreign_places")
                attrib.append({"variant": v, "seed": run["seed"], "user": t["user"], "route": t["route"],
                               "records": t["terms_used"], "runtime_ok": runtime_ok, "model_checks_ok": model_ok})
    metrics["owner_live_attribution"] = attrib
    (OUT / "posttrain_metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "RAW_OUTPUTS.md").write_text("\n".join(raw) + "\n", encoding="utf-8")
    print(json.dumps({"sessions": metrics["sessions"], "terminology": metrics.get("terminology_generalisation"),
                      "style": {v: {k: s[k] for k in ("catchphrase_reply_rate", "most_common_opening_share", "mixed_script_words",
                                                      "questions_per_reply", "chars_mean")} for v, s in metrics["style"].items()}},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
