#!/usr/bin/env python3
"""Post-training evaluation of Rupsaa V0.1: base Qwen vs base + V0.1 LoRA.

Usage:
    python scripts/evaluate_v01.py
    python scripts/evaluate_v01.py --adapter adapters/rupsaa-v0.1 --out data/production/reports/rupsaa_v0.1_evaluation

What it does (one model load, never merges the adapter):
  1. Loads Qwen + the adapter through the normal inference stack
     (rupsaa.model.loader.load_model, 4-bit NF4). The "base" side is the
     SAME loaded weights with the LoRA disabled via PeftModel.disable_adapter(),
     so the only difference between A and B is the adapter.
  2. Generation suite = the prepared cases in scripts/evaluate.py
     (EVAL_CASES + MULTI_TURN_EVAL_CASES), unchanged. Every case is run for
     both models with identical messages, generation params
     (configs/inference.yaml) and a per-case sampling seed, under two system
     prompts:
       - "production": rupsaa.personality.system_prompt.build_system_prompt()
         — what the app actually sends.
       - "training": "You are Rupsaa." — the system prompt the V0.1 dataset
         was trained with.
     Single-turn cases for which the existing RAG pipeline retrieves context
     above its min_score are additionally run with that context (rule-based,
     not hand-picked).
  3. Held-out test split (data/production/exports/rupsaa_v0.1/test.jsonl,
     never trained on): assistant-token cross-entropy loss and perplexity,
     base vs adapter, overall and per language/category (metadata joined
     from the frozen snapshot by message fingerprint). This is the same
     quantity LLaMA-Factory reports as eval_loss.

It does NOT grade response quality — outputs are written side by side for
human review (see scripts/evaluate.py for the rationale).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import torch  # noqa: E402
from peft import PeftModel  # noqa: E402

from rupsaa.config import PROJECT_ROOT  # noqa: E402
from rupsaa.guardrails.essential_boundaries import check_text  # noqa: E402
from rupsaa.model.generation import ChatMessage, GenerationParams, generate_reply  # noqa: E402
from rupsaa.model.loader import load_model  # noqa: E402
from rupsaa.personality.system_prompt import build_system_prompt  # noqa: E402
from scripts.evaluate import EVAL_CASES, MULTI_TURN_EVAL_CASES  # noqa: E402

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

TRAINING_SYSTEM_PROMPT = "You are Rupsaa."
EXPORT_DIR = PROJECT_ROOT / "data/production/exports/rupsaa_v0.1"
SNAPSHOT_APPROVED = PROJECT_ROOT / "data/production/snapshots/rupsaa_v0.1_training/approved"
CUTOFF_LEN = 2048  # same as training


def system_prompt_for(mode: str, retrieved_context: str | None) -> str:
    if mode == "production":
        return build_system_prompt(retrieved_context=retrieved_context)
    if retrieved_context:  # same layout as the rag_aware training records
        return f"{TRAINING_SYSTEM_PROMPT}\n\nRetrieved context:\n{retrieved_context}"
    return TRAINING_SYSTEM_PROMPT


class Variants:
    """Runs a callable with the LoRA enabled ("rupsaa_v01") or disabled ("base")."""

    def __init__(self, model: PeftModel):
        self.model = model

    def run(self, variant: str, fn):
        if variant == "base":
            with self.model.disable_adapter():
                return fn()
        return fn()


def generate(loaded, variants: Variants, variant: str, messages: list[ChatMessage], params: GenerationParams, seed: int) -> dict:
    def _go():
        torch.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
        t0 = time.time()
        r = generate_reply(loaded.model, loaded.tokenizer, messages, params)
        return {"response": r.text, "completion_tokens": r.completion_tokens, "seconds": round(time.time() - t0, 2)}

    return variants.run(variant, _go)


def run_generation_suite(loaded, variants: Variants, rag_pipeline) -> dict:
    params = GenerationParams.from_config()
    out = {"generation_params": params.__dict__, "single_turn": [], "multi_turn": []}

    for idx, case in enumerate(EVAL_CASES):
        seed = 1000 + idx
        entry = {"category": case["category"], "prompt": case["prompt"], "seed": seed, "runs": {}}
        if not check_text(case["prompt"]).allowed:
            entry["blocked_by_guardrail"] = True
            out["single_turn"].append(entry)
            print(f"  [{case['category']}] blocked by essential_boundaries pre-check (not sent to model)", flush=True)
            continue

        retrieved_context, sources = (None, [])
        if rag_pipeline is not None:
            retrieved_context, sources = rag_pipeline.query(case["prompt"])
        entry["rag_sources"] = sources

        conditions = [("production", None), ("training", None)]
        if retrieved_context:
            conditions.append(("production+rag", retrieved_context))
            conditions.append(("training+rag", retrieved_context))
        for cond, ctx in conditions:
            mode = cond.split("+")[0]
            messages = [
                ChatMessage(role="system", content=system_prompt_for(mode, ctx)),
                ChatMessage(role="user", content=case["prompt"]),
            ]
            for variant in ("base", "rupsaa_v01"):
                entry["runs"].setdefault(cond, {})[variant] = generate(loaded, variants, variant, messages, params, seed)
        out["single_turn"].append(entry)
        print(f"  [{case['category']}] done ({', '.join(c for c, _ in conditions)})", flush=True)

    for idx, case in enumerate(MULTI_TURN_EVAL_CASES):
        entry = {"category": case["category"], "runs": {}}
        for mode in ("production", "training"):
            for variant in ("base", "rupsaa_v01"):
                history: list[ChatMessage] = []
                turns = []
                for t_idx, user_text in enumerate(case["turns"]):
                    seed = 2000 + idx * 10 + t_idx
                    messages = [ChatMessage(role="system", content=system_prompt_for(mode, None))] + history + [ChatMessage(role="user", content=user_text)]
                    r = generate(loaded, variants, variant, messages, params, seed)
                    turns.append({"user": user_text, **r})
                    history += [ChatMessage(role="user", content=user_text), ChatMessage(role="assistant", content=r["response"])]
                entry["runs"].setdefault(mode, {})[variant] = turns
        out["multi_turn"].append(entry)
        print(f"  [{case['category']}] done", flush=True)
    return out


def _fingerprint(messages: list[dict]) -> str:
    return hashlib.sha256(json.dumps(messages, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _snapshot_metadata() -> dict[str, dict]:
    """Map export-record fingerprint -> {id, language, category} from the frozen snapshot."""
    meta = {}
    for path in SNAPSHOT_APPROVED.glob("*.json"):
        rec = json.loads(path.read_text(encoding="utf-8"))
        msgs = [{"role": m["role"], "content": m["content"]} for m in rec["messages"]]
        meta[_fingerprint(msgs)] = {"id": rec["id"], "language": rec.get("language"), "category": rec.get("category")}
    return meta


def assistant_token_labels(tokenizer, messages: list[dict]) -> tuple[list[int], list[int]]:
    """Token ids for the full ChatML conversation and labels that are -100
    everywhere except assistant replies (content + <|im_end|>)."""
    input_ids: list[int] = []
    labels: list[int] = []
    for i, m in enumerate(messages):
        if m["role"] != "assistant":
            continue
        prefix = tokenizer.apply_chat_template(messages[:i], tokenize=True, add_generation_prompt=True)
        full = tokenizer.apply_chat_template(messages[: i + 1], tokenize=True, add_generation_prompt=False)
        assert full[: len(prefix)] == prefix, "chat template is not prefix-stable"
        new_prompt = prefix[len(input_ids):]
        answer = full[len(prefix):]
        if answer and tokenizer.decode(answer[-1:]) == "\n":  # trailing newline after <|im_end|>
            answer = answer[:-1]
        input_ids += new_prompt + answer
        labels += [-100] * len(new_prompt) + answer
        # keep the stripped newline so the next turn's prefix lines up
        tail = full[len(prefix) + len(answer):]
        input_ids += tail
        labels += [-100] * len(tail)
    return input_ids[:CUTOFF_LEN], labels[:CUTOFF_LEN]


def run_test_loss(loaded, variants: Variants) -> dict:
    meta = _snapshot_metadata()
    records = [json.loads(line) for line in open(EXPORT_DIR / "test.jsonl", encoding="utf-8")]
    per_record = []
    for rec in records:
        ids, labels = assistant_token_labels(loaded.tokenizer, rec["messages"])
        input_ids = torch.tensor([ids], device=loaded.model.device)
        label_t = torch.tensor([labels], device=loaded.model.device)
        n_tokens = int((label_t[:, 1:] != -100).sum())
        row = {**meta.get(_fingerprint(rec["messages"]), {"id": None, "language": None, "category": None}), "assistant_tokens": n_tokens}
        for variant in ("base", "rupsaa_v01"):
            def _loss():
                with torch.no_grad():
                    return float(loaded.model(input_ids=input_ids, labels=label_t).loss)
            row[f"loss_{variant}"] = variants.run(variant, _loss)
        per_record.append(row)

    def summarize(rows):
        tok = sum(r["assistant_tokens"] for r in rows)
        s = {"records": len(rows), "assistant_tokens": tok}
        for v in ("base", "rupsaa_v01"):
            loss = sum(r[f"loss_{v}"] * r["assistant_tokens"] for r in rows) / tok  # token-weighted mean
            s[f"loss_{v}"] = round(loss, 4)
            s[f"ppl_{v}"] = round(math.exp(loss), 3)
        s["adapter_better_records"] = sum(1 for r in rows if r["loss_rupsaa_v01"] < r["loss_base"])
        return s

    by_lang, by_cat = defaultdict(list), defaultdict(list)
    for r in per_record:
        by_lang[r["language"]].append(r)
        by_cat[r["category"]].append(r)
    return {
        "split": str(EXPORT_DIR.relative_to(PROJECT_ROOT) / "test.jsonl"),
        "metric": "token-weighted mean cross-entropy over assistant tokens (content + <|im_end|>), cutoff 2048; ppl = exp(loss)",
        "metadata_joined": sum(1 for r in per_record if r["id"]),
        "overall": summarize(per_record),
        "by_language": {k: summarize(v) for k, v in sorted(by_lang.items(), key=lambda kv: str(kv[0]))},
        "by_category": {k: summarize(v) for k, v in sorted(by_cat.items(), key=lambda kv: str(kv[0]))},
        "per_record": per_record,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--adapter", default="adapters/rupsaa-v0.1")
    parser.add_argument("--out", default="data/production/reports/rupsaa_v0.1_evaluation")
    parser.add_argument("--skip-generation", action="store_true")
    parser.add_argument("--no-rag", action="store_true")
    args = parser.parse_args()

    out_dir = PROJECT_ROOT / args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading base + adapter {args.adapter} (4-bit, not merged)...", flush=True)
    t0 = time.time()
    loaded = load_model(adapter_path=args.adapter, use_adapter=True)
    if not isinstance(loaded.model, PeftModel) or not loaded.adapter_path:
        sys.exit(f"ERROR: adapter did not attach from {args.adapter}")
    lora_modules = sum(1 for n, _ in loaded.model.named_modules() if n.endswith("lora_A"))
    load_info = {
        "base_model_id": loaded.base_model_id,
        "adapter_path": loaded.adapter_path,
        "quantized_4bit": loaded.quantized,
        "peft_model": True,
        "active_adapter": loaded.model.active_adapter,
        "lora_A_modules": lora_modules,
        "merged": False,
        "load_seconds": round(time.time() - t0, 1),
        "gpu_memory_allocated_gb": round(torch.cuda.memory_allocated() / 1e9, 2) if torch.cuda.is_available() else None,
    }
    variants = Variants(loaded.model)

    # Proof the adapter changes the forward pass (and disable_adapter really gives the base model).
    probe = loaded.tokenizer.apply_chat_template(
        [{"role": "system", "content": TRAINING_SYSTEM_PROMPT}, {"role": "user", "content": "kemon acho?"}],
        tokenize=True, add_generation_prompt=True, return_tensors="pt",
    ).to(loaded.model.device)
    with torch.no_grad():
        logits_on = loaded.model(probe).logits[0, -1].float()
        with loaded.model.disable_adapter():
            logits_off = loaded.model(probe).logits[0, -1].float()
    load_info["probe_max_abs_logit_diff"] = round(float((logits_on - logits_off).abs().max()), 4)
    print(json.dumps(load_info, indent=2), flush=True)

    result = {"timestamp": datetime.now(timezone.utc).isoformat(), "load": load_info}

    print("Held-out test split loss (base vs adapter)...", flush=True)
    result["held_out_test"] = run_test_loss(loaded, variants)
    print(json.dumps(result["held_out_test"]["overall"], indent=2), flush=True)
    (out_dir / "held_out_test_loss.json").write_text(json.dumps(result["held_out_test"], ensure_ascii=False, indent=2), encoding="utf-8")

    if not args.skip_generation:
        rag_pipeline = None
        if not args.no_rag:
            from rupsaa.rag.pipeline import RagPipeline
            rag_pipeline = RagPipeline()
        print("Generation suite (scripts/evaluate.py cases)...", flush=True)
        result["generation"] = run_generation_suite(loaded, variants, rag_pipeline)
        (out_dir / "generation_comparison.json").write_text(json.dumps(result["generation"], ensure_ascii=False, indent=2), encoding="utf-8")

    (out_dir / "evaluation_results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Written to {out_dir}", flush=True)


if __name__ == "__main__":
    main()
