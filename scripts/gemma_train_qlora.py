#!/usr/bin/env python3
"""Rupsaa V0.3 — fresh QLoRA SFT of google/gemma-3-12b-it on the frozen rupsaa_v0.2.2 corpus.

    PYTHONPATH=/teamspace/studios/this_studio/.gemma_stack python scripts/gemma_train_qlora.py

Why not LLaMA-Factory: the project's LLaMA-Factory 0.7.1 / transformers 4.46.3 predate Gemma 3. This script runs
on transformers 4.57 (supplied only through PYTHONPATH; the project environment is unchanged) with the installed
peft/bitsandbytes and keeps the V0.2.2 recipe:
  data     data/production/exports/rupsaa_v0.2.2/train.jsonl (frozen, sha checked), every conversation once;
           internal eval = datasets.train_test_split(test_size=0.05, seed=42), as LLaMA-Factory did
  template the model's own chat template (Gemma folds the system turn into the first user turn — the same
           rendering the app uses at inference); loss on every assistant turn incl. <end_of_turn>, nothing else
  model    official google/gemma-3-12b-it, 4-bit NF4 + double quant, bf16 compute, SDPA, gradient checkpointing
  LoRA     r16 / alpha 32 / dropout 0.05 on q,k,v,o,gate,up,down of the LANGUAGE model only (vision tower untouched)
  train    LR 1e-4 cosine, warmup 6 steps, 2 epochs, batch 2 x accum 8 = 16, cutoff 2048, paged_adamw_8bit,
           max_grad_norm 0.3, eval + save every 20 steps, seed 42
Output: adapters/rupsaa-v0.3-gemma3 (checkpoint-N folders + top-level final adapter). Never overwrites.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parent.parent
# Defaults = the Gemma V1 run (rupsaa_v0.2.2 -> adapters/rupsaa-v0.3-gemma3). The FINAL corrective run sets
# RUPSAA_DATA_DIR / RUPSAA_DATASET_SHA / RUPSAA_OUT (see data/production/exports/rupsaa_v0.3_final).
DATA = ROOT / os.environ.get("RUPSAA_DATA_DIR", "data/production/exports/rupsaa_v0.2.2")
DATASET_SHA = os.environ.get("RUPSAA_DATASET_SHA", "df6277b205b83f245d4d2fe8463a6640efbff165b17f3d1560c03fc60d57fd35")
BASE = "google/gemma-3-12b-it"
OUT = ROOT / os.environ.get("RUPSAA_OUT", "adapters/rupsaa-v0.3-gemma3")
CUTOFF = 2048
TARGETS = r".*language_model.*\.(q_proj|k_proj|v_proj|o_proj|gate_proj|up_proj|down_proj)"
# Throughput-only knobs (objective unchanged; effective batch stays MICRO x ACCUM ≈ 16). Defaults = original L4 run.
MICRO = int(os.environ.get("RUPSAA_MICRO_BATCH", 2))
ACCUM = int(os.environ.get("RUPSAA_GRAD_ACCUM", 8))
GRAD_CKPT = os.environ.get("RUPSAA_GRAD_CKPT", "1") == "1"
TF32 = os.environ.get("RUPSAA_TF32", "0") == "1"
EVAL_BATCH = int(os.environ.get("RUPSAA_EVAL_BATCH", 2))
WORKERS = int(os.environ.get("RUPSAA_WORKERS", 2))


def check_dataset():
    order = ["train.jsonl", "validation.jsonl", "test.jsonl", "corrective_holdout.jsonl", "dance_holdout.jsonl"]
    lines = "".join(f"{hashlib.sha256((DATA / n).read_bytes()).hexdigest()}  {n}\n" for n in order)
    got = hashlib.sha256(lines.encode()).hexdigest()
    if got != DATASET_SHA:
        raise SystemExit(f"dataset sha mismatch: {got}")


def encode(tok, messages):
    """input_ids + labels: labels only on assistant replies (incl. the end-of-turn token)."""
    ids, labels = [], []
    prev = []
    for i, m in enumerate(messages):
        if m["role"] != "assistant":
            continue
        prompt = tok.apply_chat_template(messages[:i], add_generation_prompt=True, tokenize=True)
        full = tok.apply_chat_template(messages[:i + 1], tokenize=True)
        if full[:len(prompt)] != prompt or prompt[:len(prev)] != prev:
            raise ValueError("chat template is not prefix-consistent")
        ids += prompt[len(prev):]
        labels += [-100] * (len(prompt) - len(prev))
        ids += full[len(prompt):]
        labels += full[len(prompt):]
        prev = full
    return {"input_ids": ids[:CUTOFF], "labels": labels[:CUTOFF]}


def main():
    from datasets import Dataset
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import (AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, Trainer, TrainingArguments,
                              set_seed)

    check_dataset()
    if TF32:
        torch.backends.cuda.matmul.allow_tf32 = True
        torch.backends.cudnn.allow_tf32 = True
    print(f"perf: micro {MICRO} x accum {ACCUM} = {MICRO * ACCUM}; grad_ckpt {GRAD_CKPT}; tf32 {TF32}; "
          f"eval batch {EVAL_BATCH}; workers {WORKERS}; gpu {torch.cuda.get_device_name(0)}", flush=True)
    if OUT.exists() and any(OUT.iterdir()):
        raise SystemExit(f"{OUT} exists — refusing to overwrite")
    set_seed(42)
    tok = AutoTokenizer.from_pretrained(BASE)
    rows = [json.loads(line)["messages"] for line in open(DATA / "train.jsonl", encoding="utf-8")]
    enc = [encode(tok, m) for m in rows]
    truncated = sum(len(e["input_ids"]) == CUTOFF for e in enc)
    ds = Dataset.from_list(enc).train_test_split(test_size=0.05, seed=42)
    print(f"train {len(ds['train'])} / eval {len(ds['test'])}; truncated {truncated}; "
          f"max len {max(len(e['input_ids']) for e in enc)}; supervised tokens "
          f"{sum(sum(x != -100 for x in e['labels']) for e in enc)}", flush=True)

    model = AutoModelForCausalLM.from_pretrained(
        BASE, device_map={"": 0}, attn_implementation="sdpa", torch_dtype=torch.bfloat16,
        quantization_config=BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                               bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=torch.bfloat16))
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=GRAD_CKPT,
                                            gradient_checkpointing_kwargs={"use_reentrant": False})
    model = get_peft_model(model, LoraConfig(r=16, lora_alpha=32, lora_dropout=0.05, target_modules=TARGETS,
                                             task_type="CAUSAL_LM"))
    model.print_trainable_parameters()

    pad = tok.pad_token_id

    def collate(batch):
        n = max(len(b["input_ids"]) for b in batch)
        ids = torch.full((len(batch), n), pad, dtype=torch.long)
        lab = torch.full((len(batch), n), -100, dtype=torch.long)
        att = torch.zeros((len(batch), n), dtype=torch.long)
        for i, b in enumerate(batch):
            L = len(b["input_ids"])
            ids[i, :L], lab[i, :L], att[i, :L] = torch.tensor(b["input_ids"]), torch.tensor(b["labels"]), 1
        return {"input_ids": ids, "labels": lab, "attention_mask": att, "token_type_ids": torch.zeros_like(ids)}

    args = TrainingArguments(
        output_dir=str(OUT), per_device_train_batch_size=MICRO, per_device_eval_batch_size=EVAL_BATCH,
        gradient_accumulation_steps=ACCUM, tf32=TF32 or None,
        learning_rate=1e-4, lr_scheduler_type="cosine", warmup_steps=6, num_train_epochs=2, optim="paged_adamw_8bit",
        max_grad_norm=0.3, bf16=True, logging_steps=10, eval_strategy="steps", eval_steps=20, save_strategy="steps",
        save_steps=20, save_total_limit=None, report_to="none", seed=42, remove_unused_columns=False,
        gradient_checkpointing=GRAD_CKPT, gradient_checkpointing_kwargs={"use_reentrant": False},
        dataloader_num_workers=WORKERS)

    from transformers import TrainerCallback

    class Speed(TrainerCallback):
        """Prints seconds/step, ETA and peak VRAM at each log step."""
        def on_train_begin(self, args, state, control, **kw):
            self.t0 = time.time()

        def on_log(self, args, state, control, logs=None, **kw):
            if state.global_step:
                sps = (time.time() - self.t0) / state.global_step
                print(f"[speed] step {state.global_step}/{state.max_steps} {sps:.2f} s/step (incl. evals) "
                      f"eta {sps * (state.max_steps - state.global_step) / 60:.1f} min "
                      f"peak_vram {torch.cuda.max_memory_allocated() / 2**30:.1f} GiB", flush=True)

    trainer = Trainer(model=model, args=args, train_dataset=ds["train"], eval_dataset=ds["test"], data_collator=collate,
                      callbacks=[Speed()])
    result = trainer.train()
    trainer.save_model(str(OUT))  # final adapter at the top level (checkpoint choice is made by generation quality)
    tok.save_pretrained(str(OUT))
    (OUT / "train_summary.json").write_text(json.dumps({
        "base": BASE, "dataset": DATA.name, "dataset_sha256": DATASET_SHA, "train_examples": len(ds["train"]),
        "eval_examples": len(ds["test"]), "truncated": truncated, "metrics": result.metrics,
        "perf": {"micro_batch": MICRO, "grad_accum": ACCUM, "grad_ckpt": GRAD_CKPT, "tf32": TF32,
                 "gpu": torch.cuda.get_device_name(0), "peak_vram_gib": round(torch.cuda.max_memory_allocated() / 2**30, 2)},
        "log_history": trainer.state.log_history}, indent=1), encoding="utf-8")
    print("done", result.metrics, flush=True)


if __name__ == "__main__":
    sys.exit(main())
