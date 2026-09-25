#!/usr/bin/env python3
"""Rupsaa V0.2 post-training evaluation. Run ONLY after training has finished.

    bash scripts/posttrain_rupsaa_v02.sh            # wrapper: preconditions + this script
    python scripts/posttrain_v02.py [--dry-run] [--skip-generation]

Never trains, never merges, never modifies the frozen data, V0.1, or the app's
default configuration. One 4-bit base-model load; the V0.2 and V0.1 LoRAs are
attached as named adapters and "base" is the same weights with adapters disabled.

  1. locate the best V0.2 checkpoint (trainer_state.json: best_model_checkpoint / eval curve)
  2. verify adapter integrity (config, finite weights, root adapter == best checkpoint,
     trained from rupsaa_v0.2_train into adapters/rupsaa-v0.2); V0.1 still matches its release checksums
  3. frozen validation loss            (A: full 77)
  4. frozen test loss                  (A: full 76)
  5. clean V0.1-vs-V0.2 comparison     (B: 41 validation / 38 test, records V0.1 never trained on)
  6. unseen-terminology generalisation (24 cases, data/production/evaluation/rupsaa_v0.2/)
  7. the 10 live-behaviour checks      (real runtime context builder + live terminology store)
  8. V0.1 vs V0.2 vs base Qwen         (each model with the system prompt it was trained/served with)
  9. human-review report               data/production/reports/rupsaa_v0.2_posttraining/POSTTRAIN_REPORT.md
 10. app-integration instructions      APP_INTEGRATION.md — written only if the automatic gate passes;
                                       nothing is switched automatically
--dry-run: steps 1-2 plus input checks, no model load.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rupsaa.config import PROJECT_ROOT  # noqa: E402
from rupsaa.dataset.language_quality import dominant_script  # noqa: E402
from rupsaa.personality.system_prompt import build_system_prompt  # noqa: E402

V02_ADAPTER = PROJECT_ROOT / "adapters/rupsaa-v0.2"
V01_ADAPTER = PROJECT_ROOT / "adapters/rupsaa-v0.1"
V01_CHECKSUMS = PROJECT_ROOT / "release/rupsaa-v0.1/checksums.sha256"
TRAINING_COMMIT = PROJECT_ROOT / "release/rupsaa-v0.2/TRAINING_COMMIT.json"
EVAL_DIR = PROJECT_ROOT / "data/production/evaluation/rupsaa_v0.2"
SNAPSHOT = PROJECT_ROOT / "data/production/snapshots/rupsaa_v0.2_training"
DEFAULT_OUT = PROJECT_ROOT / "data/production/reports/rupsaa_v0.2_posttraining"
BASE_MODEL = "Qwen/Qwen2.5-7B-Instruct"
EXPECTED_TARGETS = {"q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"}
CUTOFF_LEN = 2048
VARIANTS = ("rupsaa_v02", "rupsaa_v01", "base")
PROMPT_VERSION = {"rupsaa_v02": "v0.2", "rupsaa_v01": "v0.1", "base": "v0.2"}
TERM_MARKER = "\n\nReference terminology:\n"
RAG_MARKER = "Retrieved context:\n"
CATCHPHRASES = ["honestly", "actually", "fair call", "fair enough", "heyy", "bindaas", "baby", "babe", "basically"]
BANGLISH_MARKERS = ["mane", "kore", "hoy", "ekta", "jokhon", "kichu", "theke", "tomar", "jate", "moto", "hote", "na "]

# Gate for *recommending* integration. The owner still decides after human review.
GATE = {"min_term_pass_rate": 0.80, "min_live_script_pass": 9}


# ---------------------------------------------------------------------------
# 1-2. checkpoint + integrity (no model needed)
# ---------------------------------------------------------------------------

def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def locate_best_checkpoint(adapter_dir: Path) -> dict:
    state_path = adapter_dir / "trainer_state.json"
    if not state_path.is_file():
        raise FileNotFoundError(f"{state_path} not found — has V0.2 training finished?")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    evals = [{"step": e["step"], "epoch": round(e["epoch"], 3), "eval_loss": round(e["eval_loss"], 4)}
             for e in state.get("log_history", []) if "eval_loss" in e]
    train = [{"step": e["step"], "loss": round(e["loss"], 4)} for e in state.get("log_history", []) if "loss" in e]
    best = state.get("best_model_checkpoint")
    best_dir = Path(best) if best else None
    if best_dir is not None and not best_dir.is_absolute():
        best_dir = PROJECT_ROOT / best_dir
    lowest = min(evals, key=lambda e: e["eval_loss"]) if evals else None
    return {
        "best_model_checkpoint": str(best_dir) if best_dir else None,
        "best_checkpoint_exists": bool(best_dir and best_dir.is_dir()),
        "best_metric": state.get("best_metric"),
        "lowest_logged_eval": lowest,
        "best_matches_lowest_eval": bool(lowest and best_dir and best_dir.name == f"checkpoint-{lowest['step']}"),
        "global_step": state.get("global_step"),
        "max_steps": state.get("max_steps"),
        "epochs": state.get("num_train_epochs"),
        "eval_curve": evals,
        "train_curve": train,
    }


def _load_safetensors(path: Path) -> dict:
    from safetensors.torch import load_file
    return load_file(str(path))


def verify_adapter(adapter_dir: Path, best: dict, load_tensors=_load_safetensors) -> dict:
    checks: dict[str, dict] = {}

    def check(name, ok, detail):
        checks[name] = {"pass": bool(ok), "detail": detail}

    cfg_path, weights = adapter_dir / "adapter_config.json", adapter_dir / "adapter_model.safetensors"
    check("files_present", cfg_path.is_file() and weights.is_file(), [p.name for p in (cfg_path, weights) if p.is_file()])
    if not checks["files_present"]["pass"]:
        return {"passed": False, "checks": checks}
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    check("base_model", cfg.get("base_model_name_or_path") == BASE_MODEL, cfg.get("base_model_name_or_path"))
    check("lora_shape", (cfg.get("peft_type"), cfg.get("r"), cfg.get("lora_alpha"), cfg.get("lora_dropout"))
          == ("LORA", 16, 32, 0.05), {k: cfg.get(k) for k in ("peft_type", "r", "lora_alpha", "lora_dropout")})
    check("target_modules", set(cfg.get("target_modules") or []) == EXPECTED_TARGETS, sorted(cfg.get("target_modules") or []))

    tensors = load_tensors(weights)
    finite = all(bool(t.float().isfinite().all()) for t in tensors.values())
    check("weights_finite", bool(tensors) and finite, f"{len(tensors)} tensors")

    best_dir = Path(best["best_model_checkpoint"]) if best.get("best_model_checkpoint") else None
    if best_dir and (best_dir / "adapter_model.safetensors").is_file():
        best_t = load_tensors(best_dir / "adapter_model.safetensors")
        same = best_t.keys() == tensors.keys() and all(bool((best_t[k] == tensors[k]).all()) for k in tensors)
        check("root_adapter_is_best_checkpoint", same, best_dir.name)
    else:
        check("root_adapter_is_best_checkpoint", False, f"best checkpoint weights not found: {best_dir}")

    tc_path = adapter_dir / "trainer_config.yaml"
    if tc_path.is_file():
        tc = yaml.safe_load(tc_path.read_text(encoding="utf-8"))
        check("trained_on_v02", str(tc.get("dataset")) == "rupsaa_v0.2_train"
              and Path(str(tc.get("output_dir"))).resolve() == adapter_dir.resolve(),
              {"dataset": tc.get("dataset"), "output_dir": tc.get("output_dir")})
    else:
        check("trained_on_v02", False, "trainer_config.yaml missing (GUI runs write it)")

    mismatch = []
    for line in V01_CHECKSUMS.read_text(encoding="utf-8").splitlines():
        digest, rel = line.split(maxsplit=1)
        if rel.startswith("adapters/rupsaa-v0.1/") and sha256_file(PROJECT_ROOT / rel) != digest:
            mismatch.append(rel)
    check("v01_adapter_untouched", not mismatch, mismatch or "matches release/rupsaa-v0.1/checksums.sha256")
    return {"passed": all(c["pass"] for c in checks.values()), "checks": checks,
            "adapter_model_sha256": sha256_file(weights)}


def training_commit_state() -> dict:
    if not TRAINING_COMMIT.is_file():
        return {"recorded": False}
    rec = json.loads(TRAINING_COMMIT.read_text(encoding="utf-8"))
    paths = ["configs/training", "data/production/exports/rupsaa_v0.2", "data/production/snapshots/rupsaa_v0.2_training",
             "rupsaa/personality", "data/dataset_info.json"]
    diff = subprocess.run(["git", "diff", "--name-only", rec["training_commit"], "--", *paths], cwd=PROJECT_ROOT,
                          capture_output=True, text=True).stdout.split()
    return {"recorded": True, **rec, "training_inputs_changed_since": diff}


# ---------------------------------------------------------------------------
# automatic checks (pure; unit-tested)
# ---------------------------------------------------------------------------

def script_of(text: str) -> str:
    return dominant_script(text)


def check_turn(reply: str, expect: dict, previous: str | None, forbidden: list[str]) -> dict:
    """Heuristic flags for one reply. They direct human attention; they are not the verdict."""
    low = reply.lower()
    out: dict[str, bool] = {}
    want = expect.get("script", "any")
    if want != "any":
        out["script"] = script_of(reply) == want
    if "max_chars" in expect:
        out["max_chars"] = len(reply) <= expect["max_chars"]
    if "min_chars" in expect:
        out["min_chars"] = len(reply) >= expect["min_chars"]
    if expect.get("shorter_than_previous") and previous is not None:
        out["shorter_than_previous"] = len(reply) < len(previous)
    if expect.get("grounding_any"):
        out["grounding"] = any(k.lower() in low for k in expect["grounding_any"])
    if expect.get("banglish_markers"):
        out["banglish_markers"] = sum(1 for m in BANGLISH_MARKERS if re.search(r"(?<![a-z])" + re.escape(m.strip()) + r"(?![a-z])", low)) >= 2
    out["no_forbidden_phrase"] = not any(f in low for f in forbidden)
    out["non_empty"] = bool(reply.strip())
    return {"checks": out, "pass": all(out.values())}


def catchphrase_counts(texts: list[str]) -> dict[str, int]:
    return {p: sum(1 for t in texts if re.search(r"(?<![a-z])" + re.escape(p) + r"(?![a-z])", t.lower())) for p in CATCHPHRASES}


def gate(integrity: dict, loss: dict | None, term: dict | None, live: dict | None) -> dict:
    reasons, ok = [], True
    if not integrity.get("passed"):
        ok = False
        reasons.append("adapter integrity failed")
    if loss:
        clean = loss["B_clean_v01_vs_v02"]["test"]["overall"]
        if not clean["loss_rupsaa_v02"] < clean["loss_rupsaa_v01"]:
            ok = False
            reasons.append("V0.2 does not beat V0.1 on the clean test subset")
        if not clean["loss_rupsaa_v02"] < clean["loss_base"]:
            ok = False
            reasons.append("V0.2 does not beat base Qwen on the clean test subset")
    if term:
        r02, r01 = term["pass_rate"]["rupsaa_v02"], term["pass_rate"].get("rupsaa_v01", 0)
        if r02 < GATE["min_term_pass_rate"] or r02 < r01:
            ok = False
            reasons.append(f"terminology generalisation pass rate {r02:.0%} (need >= {GATE['min_term_pass_rate']:.0%} and >= V0.1 {r01:.0%})")
    if live:
        if live["script_pass"]["rupsaa_v02"] < GATE["min_live_script_pass"]:
            ok = False
            reasons.append(f"live checks: expected script in {live['script_pass']['rupsaa_v02']}/10")
        if live["catchphrases"]["rupsaa_v02"].get("honestly", 0):
            ok = False
            reasons.append("'honestly' appears in V0.2 live outputs")
    return {"recommend_integration": ok, "reasons": reasons or ["all automatic criteria met"],
            "note": "Automatic recommendation only — integrate after reading the human-review report."}


# ---------------------------------------------------------------------------
# model back-end (real); tests substitute a fake with the same two methods
# ---------------------------------------------------------------------------

@dataclass
class Backend:
    model: object
    tokenizer: object

    @classmethod
    def load(cls, v02: Path, v01: Path) -> "Backend":
        from peft import PeftModel

        from rupsaa.model.loader import load_model
        loaded = load_model(adapter_path=v02, use_adapter=True)
        if not isinstance(loaded.model, PeftModel):
            raise SystemExit(f"V0.2 adapter did not attach from {v02}")
        loaded.model.load_adapter(str(v01), adapter_name="rupsaa_v01")
        return cls(loaded.model, loaded.tokenizer)

    def _with(self, variant: str, fn):
        if variant == "base":
            with self.model.disable_adapter():
                return fn()
        self.model.set_adapter("default" if variant == "rupsaa_v02" else "rupsaa_v01")
        return fn()

    def loss(self, variant: str, messages: list[dict]) -> tuple[float, int]:
        import torch

        from scripts.evaluate_v01 import assistant_token_labels
        ids, labels = assistant_token_labels(self.tokenizer, messages)
        input_ids = torch.tensor([ids], device=self.model.device)
        label_t = torch.tensor([labels], device=self.model.device)
        n = int((label_t[:, 1:] != -100).sum())

        def _go():
            with torch.no_grad():
                return float(self.model(input_ids=input_ids, labels=label_t).loss)
        return self._with(variant, _go), n

    def generate(self, variant: str, messages: list[dict], seed: int) -> str:
        import torch

        from rupsaa.model.generation import ChatMessage, GenerationParams, generate_reply
        params = GenerationParams.from_config()
        chat = [ChatMessage(role=m["role"], content=m["content"]) for m in messages]

        def _go():
            torch.manual_seed(seed)
            torch.cuda.manual_seed_all(seed)
            return generate_reply(self.model, self.tokenizer, chat, params).text
        return self._with(variant, _go)


# ---------------------------------------------------------------------------
# 3-5. held-out loss
# ---------------------------------------------------------------------------

def heldout_loss(backend, frozen: dict, candidate: dict, manifests: dict) -> dict:
    per_record: dict[str, dict] = {}
    needed = set()
    for block in ("A_full", "B_clean_v01_vs_v02"):
        for split in ("validation", "test"):
            needed.update(manifests[block][split]["ids"])
    for rid in sorted(needed):
        rec = frozen[rid]
        v02_msgs = rec["messages"]
        # V0.1 is scored on the prompt it was trained with ("You are Rupsaa." + the same retrieved-context
        # layout), V0.2 and base on the frozen V0.2 prompt; user/assistant turns are identical.
        v01_msgs = [{"role": "system", "content": candidate[rid][0]["content"]}] + v02_msgs[1:]
        row = {"id": rid, "language": rec["language"], "category": rec["category"]}
        for variant, msgs in (("rupsaa_v02", v02_msgs), ("base", v02_msgs), ("rupsaa_v01", v01_msgs)):
            row[f"loss_{variant}"], row["assistant_tokens"] = backend.loss(variant, msgs)
        per_record[rid] = row
        print(f"  loss {rid} v02={row['loss_rupsaa_v02']:.3f} v01={row['loss_rupsaa_v01']:.3f} base={row['loss_base']:.3f}", flush=True)

    def summarize(rows):
        tok = sum(r["assistant_tokens"] for r in rows) or 1
        s = {"records": len(rows), "assistant_tokens": tok}
        for v in VARIANTS:
            loss = sum(r[f"loss_{v}"] * r["assistant_tokens"] for r in rows) / tok
            s[f"loss_{v}"], s[f"ppl_{v}"] = round(loss, 4), round(math.exp(loss), 3)
        s["v02_better_than_v01_records"] = sum(1 for r in rows if r["loss_rupsaa_v02"] < r["loss_rupsaa_v01"])
        return s

    out = {"metric": "token-weighted assistant-token cross-entropy (content + <|im_end|>), cutoff 2048; ppl = exp(loss). "
                     "V0.2 and base scored with the frozen V0.2 system prompt; V0.1 with its training prompt."}
    for block in ("A_full", "B_clean_v01_vs_v02"):
        out[block] = {}
        for split in ("validation", "test"):
            rows = [per_record[i] for i in manifests[block][split]["ids"]]
            by_lang = defaultdict(list)
            for r in rows:
                by_lang[r["language"]].append(r)
            out[block][split] = {"overall": summarize(rows),
                                 "by_language": {k: summarize(v) for k, v in sorted(by_lang.items())}}
    out["per_record"] = list(per_record.values())
    return out


# ---------------------------------------------------------------------------
# 6. unseen terminology generalisation
# ---------------------------------------------------------------------------

def run_terminology_suite(backend, cases: list[dict], variants=VARIANTS) -> dict:
    results = []
    for ci, case in enumerate(cases):
        entry = {"id": case["id"], "language": case["language"], "term": case["term"], "behaviours": case["behaviours"],
                 "review_note": case["review_note"], "runs": {}}
        for variant in variants:
            system = build_system_prompt(prompt_version=PROMPT_VERSION[variant], terminology_context=case["terminology_context"])
            history: list[dict] = []
            turns, previous = [], None
            for ti, (user, expect) in enumerate(zip(case["turns"], case["expect"])):
                messages = [{"role": "system", "content": system}] + history + [{"role": "user", "content": user}]
                reply = backend.generate(variant, messages, seed=5000 + ci * 10 + ti)
                verdict = check_turn(reply, expect, previous, case["forbidden_phrases"])
                turns.append({"user": user, "reply": reply, **verdict})
                history += [{"role": "user", "content": user}, {"role": "assistant", "content": reply}]
                previous = reply
            entry["runs"][variant] = {"turns": turns, "pass": all(t["pass"] for t in turns)}
        results.append(entry)
        print(f"  term {case['id']} " + " ".join(f"{v}={'PASS' if entry['runs'][v]['pass'] else 'flag'}" for v in variants), flush=True)
    rate = {v: round(sum(r["runs"][v]["pass"] for r in results) / len(results), 3) for v in variants}
    by_lang = {v: {lang: f"{sum(r['runs'][v]['pass'] for r in results if r['language'] == lang)}/"
                         f"{sum(1 for r in results if r['language'] == lang)}"
                   for lang in sorted({r['language'] for r in results})} for v in variants}
    return {"cases": results, "pass_rate": rate, "by_language": by_lang}


# ---------------------------------------------------------------------------
# 7. live behaviour checks through the real runtime context builder
# ---------------------------------------------------------------------------

def run_live_checks(backend, checks: list[dict], variants=VARIANTS, seed_base: int = 7000, tag: str = "live") -> dict:
    from rupsaa.rag.context_builder import build_turn_knowledge
    from rupsaa.rag.terminology import TerminologyStore

    store = TerminologyStore(PROJECT_ROOT / "knowledge/terminology")
    results = []
    for ci, case in enumerate(checks):
        entry = {"id": case["id"], "look_for": case["look_for"], "runs": {}}
        for variant in variants:
            history: list[dict] = []
            previous_terms: list[str] = []
            turns = []
            for ti, user in enumerate(case["turns"]):
                k = build_turn_knowledge(user, use_rag=False, rag_query=None, terminology=store,
                                         previous_terms=previous_terms, history_messages=len(history))
                if k.terms_used:
                    previous_terms = k.terms_used
                system = build_system_prompt(prompt_version=PROMPT_VERSION[variant], retrieved_context=k.retrieved_context,
                                             terminology_context=k.terminology_context, conversation_note=k.conversation_note)
                messages = [{"role": "system", "content": system}] + history + [{"role": "user", "content": user}]
                reply = backend.generate(variant, messages, seed=seed_base + ci * 10 + ti)
                turns.append({"user": user, "route": k.route, "terms_used": k.terms_used, "reply": reply})
                history += [{"role": "user", "content": user}, {"role": "assistant", "content": reply}]
            last = turns[-1]["reply"]
            script_ok = case["expect"].get("script", "any") == "any" or script_of(last) == case["expect"]["script"]
            if "max_chars" in case["expect"]:
                script_ok = script_ok and len(last) <= case["expect"]["max_chars"]
            entry["runs"][variant] = {"turns": turns, "script_ok": script_ok}
        results.append(entry)
        print(f"  {tag} {case['id']} " + " ".join(f"{v}={'ok' if entry['runs'][v]['script_ok'] else 'flag'}" for v in variants), flush=True)
    replies = {v: [t["reply"] for r in results for t in r["runs"][v]["turns"]] for v in variants}
    return {"cases": results,
            "script_pass": {v: sum(r["runs"][v]["script_ok"] for r in results) for v in variants},
            "catchphrases": {v: catchphrase_counts(replies[v]) for v in variants}}


# ---------------------------------------------------------------------------
# 9-10. reports
# ---------------------------------------------------------------------------

def render_report(result: dict) -> str:
    L = ["# Rupsaa V0.2 post-training evaluation", "",
         f"Generated {result['timestamp']}. Automatic flags are heuristics that point at replies to read; "
         "the decision is the human review below.", ""]
    g = result.get("gate")
    if g:
        L += [f"**Automatic recommendation:** {'INTEGRATE after human review' if g['recommend_integration'] else 'DO NOT INTEGRATE yet'}",
              "", *[f"- {r}" for r in g["reasons"]], ""]
    b = result["best_checkpoint"]
    L += ["## 1. Best checkpoint", "",
          f"- best_model_checkpoint: `{b['best_model_checkpoint']}` (best eval_loss {b['best_metric']})",
          f"- matches lowest logged eval loss: {b['best_matches_lowest_eval']}; steps {b['global_step']}/{b['max_steps']}", "",
          "| step | epoch | eval_loss |", "|---|---|---|", *[f"| {e['step']} | {e['epoch']} | {e['eval_loss']} |" for e in b["eval_curve"]], ""]
    L += ["## 2. Adapter integrity", "", "| check | result | detail |", "|---|---|---|",
          *[f"| {k} | {'PASS' if v['pass'] else 'FAIL'} | {str(v['detail']).replace('|', '/')} |"
            for k, v in result["integrity"]["checks"].items()], ""]
    tc = result.get("training_commit", {})
    if tc.get("recorded"):
        L += [f"Training commit `{tc['training_commit']}`; training inputs changed since: {tc['training_inputs_changed_since'] or 'none'}", ""]
    loss = result.get("heldout_loss")
    if loss:
        L += ["## 3-5. Held-out loss (lower is better)", "", loss["metric"], "",
              "| set | split | records | V0.2 | V0.1 | base | V0.2 < V0.1 records |", "|---|---|---|---|---|---|---|"]
        for block, label in (("A_full", "A. full"), ("B_clean_v01_vs_v02", "B. clean (fair V0.1 vs V0.2)")):
            for split in ("validation", "test"):
                o = loss[block][split]["overall"]
                L.append(f"| {label} | {split} | {o['records']} | {o['loss_rupsaa_v02']} | {o['loss_rupsaa_v01']} | "
                         f"{o['loss_base']} | {o['v02_better_than_v01_records']}/{o['records']} |")
        L += ["", "Clean test by language:", "", "| language | V0.2 | V0.1 | base |", "|---|---|---|---|"]
        for lang, s in loss["B_clean_v01_vs_v02"]["test"]["by_language"].items():
            L.append(f"| {lang} | {s['loss_rupsaa_v02']} | {s['loss_rupsaa_v01']} | {s['loss_base']} |")
        L.append("")
    term = result.get("terminology")
    if term:
        L += ["## 6. Unseen-terminology generalisation", "",
              "| model | pass rate | by language |", "|---|---|---|",
              *[f"| {v} | {term['pass_rate'][v]:.0%} | {term['by_language'][v]} |" for v in term["pass_rate"]], ""]
        for c in term["cases"]:
            L += [f"### {c['id']} — {c['term']} ({c['language']}; {', '.join(c['behaviours'])})", f"_{c['review_note']}_", ""]
            for v, run in c["runs"].items():
                for t in run["turns"]:
                    failed = [k for k, ok in t["checks"].items() if not ok]
                    L.append(f"- **{v}** · USER: {t['user']}  \n  RUPSAA: {t['reply']}  \n  "
                             f"flags: {', '.join(failed) if failed else 'none'}")
            L.append("")
    live = result.get("live")
    if live:
        L += ["## 7. Live behaviour checks", "", f"Expected script met: {live['script_pass']}", "",
              f"Catchphrases in all live replies: {live['catchphrases']}", ""]
        for c in live["cases"]:
            L += [f"### {c['id']} — {c['look_for']}", ""]
            for v, run in c["runs"].items():
                for t in run["turns"]:
                    L.append(f"- **{v}** [{t['route']}{' ' + ','.join(t['terms_used']) if t['terms_used'] else ''}] "
                             f"USER: {t['user']}  \n  RUPSAA: {t['reply']}")
                L.append(f"  - last reply script/length ok: {run['script_ok']}")
            L.append("")
    supp = result.get("supplementary")
    if supp:
        L += ["## 7b. Supplementary owner-failure + general checks (not gated)", "", f"Expected script met: {supp['script_pass']}", "",
              f"Catchphrases: {supp['catchphrases']}", ""]
        for c in supp["cases"]:
            L += [f"### {c['id']} — {c['look_for']}", ""]
            for v, run in c["runs"].items():
                for t in run["turns"]:
                    L.append(f"- **{v}** [{t['route']}{' ' + ','.join(t['terms_used']) if t['terms_used'] else ''}] "
                             f"USER: {t['user']}  \n  RUPSAA: {t['reply']}")
                L.append(f"  - last reply script/length ok: {run['script_ok']}")
            L.append("")
    L += ["## Human review", "", "For each section, mark: CORRECT / NATURAL / CONTEXTUAL / PERSONALITY (in that priority). "
          "Integrate only if V0.2 is at least as good as V0.1 on the clean subset and clearly better on Banglish, "
          "terminology use and memory.", ""]
    return "\n".join(L)


def integration_doc(result: dict) -> str:
    sha = result["integrity"].get("adapter_model_sha256")
    return "\n".join([
        "# Rupsaa V0.2 — app integration (prepared, NOT applied)", "",
        "The automatic gate passed. Nothing has been switched: the app still serves V0.1 by default.", "",
        "After you have read POSTTRAIN_REPORT.md and agree:", "",
        "```", "bash scripts/start_rupsaa_v02.sh", "```", "",
        "- serves `adapters/rupsaa-v0.2` with `RUPSAA_PROMPT_VERSION=v0.2` (the exact training prompt)",
        "- open only port 5500; check `<web url>/api/model/info` → `adapter_loaded: true` after the first message",
        f"- adapter_model.safetensors sha256: `{sha}`",
        "- roll back at any time: `bash scripts/start_rupsaa_v01.sh`", "",
        "Publishing the adapter (Hugging Face + release/rupsaa-v0.2 manifest/checksums) is a separate, explicit step.", ""])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--adapter", type=Path, default=V02_ADAPTER)
    ap.add_argument("--v01-adapter", type=Path, default=V01_ADAPTER)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--dry-run", action="store_true", help="steps 1-2 and input checks only; no model load")
    ap.add_argument("--skip-generation", action="store_true", help="losses only (skip steps 6-7)")
    args = ap.parse_args()

    result = {"timestamp": datetime.now(timezone.utc).isoformat(), "training_commit": training_commit_state()}
    print("1. locating best checkpoint", flush=True)
    result["best_checkpoint"] = locate_best_checkpoint(args.adapter)
    print(json.dumps({k: v for k, v in result["best_checkpoint"].items() if "curve" not in k}, indent=2), flush=True)
    print("2. verifying adapter integrity", flush=True)
    result["integrity"] = verify_adapter(args.adapter, result["best_checkpoint"])
    for k, v in result["integrity"]["checks"].items():
        print(f"  [{'PASS' if v['pass'] else 'FAIL'}] {k}: {v['detail']}", flush=True)

    manifests = json.loads((EVAL_DIR / "eval_manifests.json").read_text(encoding="utf-8"))
    cases = [json.loads(line) for line in open(EVAL_DIR / "terminology_generalization.jsonl", encoding="utf-8")]
    live_checks = json.loads((EVAL_DIR / "live_behavior_checks.json").read_text(encoding="utf-8"))
    supp_path = EVAL_DIR / "posttrain_supplementary_checks.json"
    supplementary = json.loads(supp_path.read_text(encoding="utf-8")) if supp_path.exists() else []
    frozen = {json.loads(line)["id"]: json.loads(line) for line in open(SNAPSHOT / "frozen_records.jsonl", encoding="utf-8")}
    candidate = {json.loads(line)["id"]: json.loads(line)["messages"]
                 for line in open(SNAPSHOT / "inputs/candidate_set.jsonl", encoding="utf-8")}
    print(f"inputs: {len(cases)} terminology cases, {len(live_checks)} live checks, "
          f"{manifests['A_full']['test']['count']} test / {manifests['B_clean_v01_vs_v02']['test']['count']} clean test", flush=True)
    args.out.mkdir(parents=True, exist_ok=True)
    if args.dry_run:
        (args.out / "posttrain_dry_run.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print("dry run complete (no model loaded)")
        return
    if not result["integrity"]["passed"]:
        (args.out / "posttrain_results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        sys.exit("adapter integrity failed — not evaluating (see posttrain_results.json)")

    t0 = time.time()
    backend = Backend.load(args.adapter, args.v01_adapter)
    print(f"model loaded in {time.time() - t0:.0f}s (4-bit base + V0.2 + V0.1 adapters, not merged)", flush=True)
    print("3-5. held-out loss (A full + B clean)", flush=True)
    result["heldout_loss"] = loss = heldout_loss(backend, frozen, candidate, manifests)
    term = live = None
    if not args.skip_generation:
        print("6. unseen terminology generalisation", flush=True)
        result["terminology"] = term = run_terminology_suite(backend, cases)
        print("7. live behaviour checks", flush=True)
        result["live"] = live = run_live_checks(backend, live_checks)
        if supplementary:
            print("7b. supplementary owner-failure + general generation checks (not gated; human-judged)", flush=True)
            result["supplementary"] = run_live_checks(backend, supplementary, seed_base=9000, tag="supp")
    result["gate"] = gate(result["integrity"], loss, term, live)
    (args.out / "posttrain_results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.out / "POSTTRAIN_REPORT.md").write_text(render_report(result), encoding="utf-8")
    if result["gate"]["recommend_integration"] and not args.skip_generation:
        (args.out / "APP_INTEGRATION.md").write_text(integration_doc(result), encoding="utf-8")
    print(f"\nrecommendation: {'INTEGRATE after human review' if result['gate']['recommend_integration'] else 'DO NOT INTEGRATE yet'}")
    for r in result["gate"]["reasons"]:
        print(f"  - {r}")
    print(f"report: {(args.out / 'POSTTRAIN_REPORT.md').relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
