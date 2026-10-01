#!/usr/bin/env python3
"""Knowledge V1 retrieval benchmark through Rupsaa's REAL chat pipeline (RupsaaService.chat).

    python scripts/eval_knowledge_v1.py --label before
    python scripts/eval_knowledge_v1.py --label after --compare before

- Real knowledge stores (knowledge/terminology, dance, general), real router / follow-up state / priority rules and
  the real multilingual-e5 embedder. Only Gemma is replaced by a stub (no second model on the GPU) and the web
  provider by a recorder (no network). The production UI default use_rag=False is used (documents off; curated
  stores are always consulted).
- The expected answers are never given to the retriever; follow-up queries replay their context turns first in the
  same conversation.
- The private evaluation file is read only: it is never written into knowledge, memory or the repository.
  Per-query RESULTS.json / FAILURES.json stay under data/production/reports/ (git-ignored); SUMMARY.md and
  METRICS.json contain aggregates only.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

EVAL = ROOT / "data/staging/knowledge_v1/evaluation/retrieval_eval.jsonl"
PACK = ROOT / "data/staging/knowledge_v1/general_knowledge.jsonl"
OUT = ROOT / "data/production/reports/knowledge_v1_eval"
ADULT = {"Sexual Education", "Adult Terminology"}


class _StubEngine:
    def chat(self, **kw):
        from rupsaa.model.inference import ChatResult
        return ChatResult(text="(assistant answered)", blocked=False)

    def complete(self, *a, **kw):
        raise RuntimeError("not used")


class _NoWeb:
    name, fresh_capable, supports_site_filter = "recorder", False, False

    def __init__(self):
        self.queries = []

    def search(self, query, fresh=False):
        self.queries.append(query)
        return []


def build_service(tmp: Path):
    import os

    os.environ["RUPSAA_USER_MEMORY_DIR"] = str(tmp / "mem")
    os.environ["RUPSAA_USER_PREFS_DIR"] = str(tmp / "prefs")
    os.environ["RUPSAA_TEACH_SECRET"] = ""
    from rupsaa.config import get_settings

    get_settings.cache_clear()
    import api.services as services

    svc = services.RupsaaService()
    svc._engine = _StubEngine()
    svc._web_provider, svc._web_provider_loaded = _NoWeb(), True
    captured = {}
    real = services.build_turn_knowledge

    def capture(*a, **kw):
        captured["k"] = real(*a, **kw)
        return captured["k"]

    services.build_turn_knowledge = capture
    return svc, captured


def category_of(rid: str, stores: dict, pack: dict) -> str:
    if rid.startswith("term-"):
        return "Terminology"
    if rid.startswith("dance-"):
        return "Dance"
    if rid in stores["general"]:
        return stores["general"][rid].category
    return pack.get(rid, {}).get("category", "?")


def bucket(case: dict, pack: dict) -> str:
    """Reporting category of a positive query: the store/category that should answer it."""
    if case["acceptable_production_ids"]:
        return "Terminology"
    cat = pack.get(case["expected_ids"][0], {}).get("category", "?")
    return cat if cat in ("Sexual Education", "Adult Terminology", "Relationships", "Dating") else "Other General Knowledge"


def classify_failure(case, res, diag) -> str:
    if case["context"]:
        return "follow-up context issue"
    if res["kind"] == "negative":
        m = res["retrieval"][0] if res["retrieval"] else {}
        return "threshold too loose" if m.get("match") == "semantic" else "semantic collision"
    if res["kind"] == "wrong":
        m = res["retrieval"][0] if res["retrieval"] else {}
        if m.get("match") in ("exact", "phrase", "fuzzy"):
            return "semantic collision"
        return "wrong category" if diag.get("expected_category") != m.get("category") else "embedding miss"
    # no result
    if not diag.get("gk_consulted"):
        return "other: routing gate (personal wording / not a question)"
    if diag.get("expected_rank") == 1 and diag.get("expected_score", 0) >= diag["threshold"]:
        return "threshold too strict"  # top semantic hit, rejected by the name-coverage guard
    if diag.get("expected_rank") == 1:
        return "threshold too strict" if case["language"] == "en" else "language/script issue"
    if case["language"] in ("bn", "mixed"):
        return "language/script issue"
    if diag.get("expected_rank") and diag["expected_rank"] <= 3:
        return "embedding miss"
    return "alias gap"


def run(label: str) -> dict:
    import tempfile

    from rupsaa.rag import general_knowledge as gkmod
    from rupsaa.rag.context_builder import _gk_candidate
    from rupsaa.rag.router import classify_message

    cases = [json.loads(line) for line in EVAL.read_text(encoding="utf-8").splitlines() if line.strip()]
    pack = {r["id"]: r for r in (json.loads(x) for x in PACK.read_text(encoding="utf-8").splitlines() if x.strip())}
    svc, captured = build_service(Path(tempfile.mkdtemp()))
    general = svc.general
    stores = {"general": {r.id: r for r in general.list(include_disabled=False)}}
    gk_records = general.list(include_disabled=False)
    index = general._semantic_index(gk_records)
    pos_in_index = {r.id: i for i, r in enumerate(gk_records)}

    results = []
    for case in cases:
        cid = None
        for turn in case["context"]:
            if turn["role"] == "user":
                cid = svc.chat(message=turn["content"], conversation_id=cid, use_rag=False, temperature=None,
                               top_p=None, max_new_tokens=None)["conversation_id"]
        web_before = len(svc._web_provider.queries)
        r = svc.chat(message=case["query"], conversation_id=cid, use_rag=False, temperature=None, top_p=None,
                     max_new_tokens=None)
        k = captured["k"]
        ids = list(r.get("terms_used") or [])
        retrieval = [dict(x, category=category_of(x["record_id"], stores, pack)) for x in k.retrieval]
        accept = set(case["expected_ids"]) | set(case["acceptable_production_ids"])
        if case["expect_no_match"] or not case["expected_ids"]:
            forb = case.get("forbidden") or {}
            bad = [x for x in retrieval if x["category"] in forb.get("categories", [])
                   or any(x["record_id"].startswith(p) for p in forb.get("id_prefixes", []))]
            ok = (not ids) if case["expect_no_match"] else not bad
            kind = "correct_reject" if ok else "negative"
        else:
            ok = bool(ids) and ids[0] in accept
            kind = "correct" if ok else ("none" if not ids else "wrong")
        res = {"id": case["id"], "query": case["query"], "language": case["language"], "type": case["type"],
               "expected": sorted(accept), "retrieved": ids, "retrieval": retrieval, "route": r.get("route"),
               "ok": ok, "kind": kind, "top3": bool(set(ids[:3]) & accept) if accept else ok,
               "web_requested": len(svc._web_provider.queries) > web_before or bool(r.get("pending_search")),
               "bucket": bucket(case, pack) if case["expected_ids"] else "Negative"}
        if not ok:
            diag = {"threshold": gkmod.SEMANTIC_MIN_SCORE}
            decision = classify_message(case["query"])
            diag["route"] = decision.route.value
            diag["gk_consulted"] = bool(case["context"]) or _gk_candidate(decision, case["query"])
            exp = [e for e in case["expected_ids"] if e in pos_in_index]
            if exp and index is not None:
                q = general._embed([decision.term_candidate or case["query"]], True)[0]
                scores = index @ q
                order = list(scores.argsort()[::-1])
                i = pos_in_index[exp[0]]
                diag["expected_score"] = round(float(scores[i]), 3)
                diag["expected_rank"] = order.index(i) + 1
                diag["top_semantic"] = [(gk_records[j].id, round(float(scores[j]), 3)) for j in order[:3]]
                diag["expected_category"] = gk_records[i].category
            res["diagnostics"] = diag
            res["failure_type"] = classify_failure(case, res, diag)
        results.append(res)
    return {"label": label, "results": results}


def metrics(results: list[dict]) -> dict:
    pos = [r for r in results if r["bucket"] != "Negative"]
    neg = [r for r in results if r["bucket"] == "Negative"]

    def rate(xs, key="ok"):
        return round(sum(1 for x in xs if x[key]) / len(xs), 4) if xs else None

    out = {
        "queries": len(results), "positive": len(pos), "negative": len(neg),
        "top1_accuracy_positive": rate(pos), "top3_accuracy_positive": rate(pos, "top3"),
        "positive_recall_any_result": round(sum(1 for r in pos if r["retrieved"]) / len(pos), 4),
        "positive_correct": sum(r["ok"] for r in pos), "positive_wrong_concept": sum(r["kind"] == "wrong" for r in pos),
        "positive_no_result": sum(r["kind"] == "none" for r in pos),
        "negative_correctly_rejected": sum(r["ok"] for r in neg), "negative_false_positive": sum(not r["ok"] for r in neg),
        "negative_rejection_accuracy": rate(neg), "false_positive_rate": round(1 - rate(neg), 4) if neg else None,
        "overall_accuracy": rate(results),
        "web_lookups_requested": sum(r["web_requested"] for r in results),
    }
    for key, field in (("by_language", "language"), ("by_category", "bucket"), ("by_type", "type")):
        groups = defaultdict(list)
        for r in results:
            groups[r[field]].append(r)
        out[key] = {g: {"n": len(xs), "accuracy": rate(xs)} for g, xs in sorted(groups.items())}
    out["failure_types"] = dict(Counter(r["failure_type"] for r in results if not r["ok"]).most_common())
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--compare", default=None)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    run_ = run(args.label)
    m = metrics(run_["results"])
    (OUT / f"RESULTS_{args.label}.json").write_text(json.dumps(run_, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / f"FAILURES_{args.label}.json").write_text(
        json.dumps([r for r in run_["results"] if not r["ok"]], ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / f"METRICS_{args.label}.json").write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in m.items() if not k.startswith("by_")}, indent=1))
    for key in ("by_language", "by_category"):
        print(key, {g: f"{v['accuracy']:.3f} (n={v['n']})" for g, v in m[key].items()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
