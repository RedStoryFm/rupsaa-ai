#!/usr/bin/env python3
"""Pre-training smoke validation for Rupsaa V0.2.1 (R2 freeze) — tokenizer only, no model weights, no optimizer steps.

    python scripts/v021_pretrain_smoke.py

Runs LLaMA-Factory 0.7.1's own argument parser and data pipeline on
configs/training/llamafactory_rupsaa_v0.2.1.yaml and the frozen rupsaa_v0.2.1 export, and checks:
  * every export file matches the freeze manifest; validation/test are byte-identical to frozen V0.2;
    the parent V0.2 export still matches its own manifest
  * the config parses: fresh LoRA from Qwen2.5-7B-Instruct, QLoRA/LoRA settings, lr/epochs/warmup,
    val_size, seed, best-model retention, output dir adapters/rupsaa-v0.2.1 (absent; not V0.1/V0.2)
  * no row is dropped in preprocessing; the seed-42 5% resplit gives 1578 / 84 and the 84 eval rows are
    exactly the single-copy V0.2 rows the freeze placed there (no corrective row in eval)
  * every example starts with its own system turn — never the qwen default "You are a helpful
    assistant." nor a bare "You are Rupsaa."; terminology blocks, recall notes and language
    directives survive formatting
  * corrective rows' system prompts are exactly what the runtime builds today (train-as-serve)
  * labels are exactly the assistant turns (+ <|im_end|>)
  * prompt tokens are identical to tokenizer.apply_chat_template (the runtime path)
  * nothing is truncated at cutoff 2048; expected optimizer steps
Writes data/production/reports/rupsaa_v0.2.1_preparation/smoke_check.json.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from collections import Counter
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")

from rupsaa.config import PROJECT_ROOT  # noqa: E402

CLI_CONFIG = PROJECT_ROOT / "configs/training/llamafactory_rupsaa_v0.2.1.yaml"
EXPORT = PROJECT_ROOT / "data/production/exports/rupsaa_v0.2.1_r2"  # R2 freeze (supersedes the never-trained first freeze)
MANIFEST = EXPORT / "V021_R2_TRAINING_MANIFEST.json"
DATASET = "rupsaa_v0.2.1_r2_train"
V02_EXPORT = PROJECT_ROOT / "data/production/exports/rupsaa_v0.2"
V02_MANIFEST = PROJECT_ROOT / "data/production/snapshots/rupsaa_v0.2_training/V02_TRAINING_MANIFEST.json"
OUT = PROJECT_ROOT / "data/production/reports/rupsaa_v0.2.1_preparation/smoke_check.json"
IGNORE_INDEX = -100


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> None:
    os.chdir(PROJECT_ROOT)
    checks: dict[str, dict] = {}

    def check(name: str, ok: bool, detail) -> None:
        checks[name] = {"pass": bool(ok), "detail": detail}
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    actual = {n: sha(EXPORT / n) for n in manifest["files_sha256"]}
    check("export_matches_freeze_manifest", actual == manifest["files_sha256"], f"{len(actual)} files")
    v02m = json.loads(V02_MANIFEST.read_text(encoding="utf-8"))
    check("parent_v02_export_unchanged", all(sha(V02_EXPORT / f"{s}.jsonl") == h for s, h in v02m["export_files_sha256"].items()),
          "rupsaa_v0.2 train/validation/test == V02 manifest")
    check("external_validation_test_identical_to_v02", all(actual[f"{s}.jsonl"] == v02m["export_files_sha256"][s]
                                                           for s in ("validation", "test")), "byte-identical copies")

    from llamafactory.data import get_dataset, split_dataset
    from llamafactory.hparams import get_train_args
    from llamafactory.model import load_tokenizer

    cfg = yaml.safe_load(CLI_CONFIG.read_text(encoding="utf-8"))
    cfg["output_dir"] = str(PROJECT_ROOT / cfg["output_dir"])
    model_args, data_args, training_args, finetuning_args, _ = get_train_args(dict(cfg))
    names = [d.strip() for d in data_args.dataset.split(",")] if isinstance(data_args.dataset, str) else list(data_args.dataset)
    check("dataset_is_v021_r2_train", names == [DATASET]
          and Path(data_args.dataset_dir).resolve() == EXPORT.resolve(), f"{names} in {data_args.dataset_dir}")
    check("fresh_lora_from_base", model_args.model_name_or_path == "Qwen/Qwen2.5-7B-Instruct"
          and not model_args.adapter_name_or_path, f"base={model_args.model_name_or_path} adapter={model_args.adapter_name_or_path}")
    out_dir = Path(training_args.output_dir).resolve()
    check("output_dir_safe", out_dir == (PROJECT_ROOT / "adapters/rupsaa-v0.2.1").resolve()
          and out_dir.name not in ("rupsaa-v0.1", "rupsaa-v0.2") and not (out_dir.exists() and any(out_dir.iterdir()))
          and not training_args.overwrite_output_dir, f"{out_dir} ({'absent' if not out_dir.exists() else 'exists'})")
    check("qlora_settings", model_args.quantization_bit == 4 and model_args.quantization_type == "nf4"
          and model_args.double_quantization and not model_args.disable_gradient_checkpointing
          and training_args.bf16 and training_args.optim == "paged_adamw_8bit",
          f"4bit {model_args.quantization_type} double={model_args.double_quantization} "
          f"grad_ckpt={not model_args.disable_gradient_checkpointing} bf16={training_args.bf16} {training_args.optim}")
    check("lora_settings", (finetuning_args.lora_rank, finetuning_args.lora_alpha, finetuning_args.lora_dropout) == (16, 32, 0.05)
          and sorted(finetuning_args.lora_target) == sorted("q_proj,k_proj,v_proj,o_proj,gate_proj,up_proj,down_proj".split(",")),
          f"r={finetuning_args.lora_rank} a={finetuning_args.lora_alpha} d={finetuning_args.lora_dropout} {finetuning_args.lora_target}")
    check("schedule", training_args.learning_rate == 2e-4 and training_args.num_train_epochs == 2.0
          and training_args.warmup_steps == 6 and training_args.lr_scheduler_type == "cosine"
          and training_args.per_device_train_batch_size == 2 and training_args.gradient_accumulation_steps == 8
          and data_args.cutoff_len == 2048 and training_args.seed == 42 and data_args.val_size == 0.05,
          f"lr={training_args.learning_rate} epochs={training_args.num_train_epochs} warmup={training_args.warmup_steps} "
          f"batch={training_args.per_device_train_batch_size}x{training_args.gradient_accumulation_steps} seed={training_args.seed}")
    check("best_model_retention", training_args.load_best_model_at_end and training_args.eval_steps == training_args.save_steps == 20
          and training_args.metric_for_best_model == "eval_loss", f"eval/save every {training_args.eval_steps}")

    tok_module = load_tokenizer(model_args)
    tokenizer = tok_module["tokenizer"] if isinstance(tok_module, dict) else tok_module
    dataset = get_dataset(model_args, data_args, training_args, stage="sft", tokenizer=tokenizer)
    rows = [json.loads(line)["messages"] for line in open(EXPORT / "train.jsonl", encoding="utf-8")]
    row_map = [json.loads(line) for line in open(EXPORT / "train_row_map.jsonl", encoding="utf-8")]
    check("no_rows_dropped", len(dataset) == len(rows) == len(row_map), f"{len(dataset)} tokenized / {len(rows)} rows")
    parts = split_dataset(dataset, data_args, training_args)
    n_train, n_eval = len(parts["train_dataset"]), len(parts["eval_dataset"])
    check("resplit_counts", (n_train, n_eval) == (manifest["splits"]["internal_train_rows"], manifest["splits"]["internal_eval_rows"]),
          f"train={n_train} eval={n_eval}")
    eval_ids = Counter(tuple(x) for x in parts["eval_dataset"]["input_ids"])
    planned = Counter(tuple(dataset[m["row"]]["input_ids"]) for m in row_map if m["internal_split"] == "eval")
    check("internal_eval_is_the_planned_v02_rows", eval_ids == planned
          and all(m["source"] == "rupsaa_v0.2_train" for m in row_map if m["internal_split"] == "eval"),
          f"{sum(planned.values())} planned eval rows, all single-copy V0.2")
    corr_ids = {tuple(dataset[m["row"]]["input_ids"]) for m in row_map if m["source"] != "rupsaa_v0.2_train"}
    check("no_corrective_or_dance_row_in_internal_eval", not (set(eval_ids) & corr_ids),
          f"{len(corr_ids)} distinct corrective+dance rows, 0 in eval")
    batches = -(-n_train // training_args.per_device_train_batch_size)
    per_epoch = batches // training_args.gradient_accumulation_steps
    total = int(per_epoch * training_args.num_train_epochs)
    check("expected_steps", total == manifest["training"]["expected_total_steps"] == 202, f"{per_epoch}/epoch x 2 = {total}")

    # Train-as-serve for the corrective rows: rebuild with the runtime today.
    from scripts.v021_build_corrective import build_all
    outputs, errors = build_all()
    by_id = {r["id"]: r["messages"] for recs in outputs.values() for r in recs}
    snap_dance = PROJECT_ROOT / "data/production/snapshots/rupsaa_v0.2.1_r2_training/dance_knowledge"
    live_dance = PROJECT_ROOT / "knowledge/dance"
    check("dance_knowledge_equals_frozen_copy", sorted(p.name for p in snap_dance.glob("dance-*.json")) ==
          sorted(p.name for p in live_dance.glob("dance-*.json")) and all(sha(p) == sha(live_dance / p.name)
          for p in snap_dance.glob("dance-*.json")), f"{len(list(snap_dance.glob('dance-*.json')))} records")
    mismatch = [m["id"] for m in row_map if m["source"] != "rupsaa_v0.2_train" and rows[m["row"]] != by_id.get(m["id"])]
    check("corrective_and_dance_rows_equal_runtime_rebuild", not errors and not mismatch, f"mismatches: {mismatch[:5]}")

    from rupsaa.personality.system_prompt_v02 import V02_SYSTEM_PROMPT
    bad_system, bad_labels, bad_runtime, truncated, max_len = [], [], [], 0, 0
    blocks = Counter()
    for i, (row, ex) in enumerate(zip(rows, dataset)):
        ids, labels = ex["input_ids"], ex["labels"]
        max_len = max(max_len, len(ids))
        truncated += len(ids) >= data_args.cutoff_len
        text = tokenizer.decode(ids, skip_special_tokens=False)
        system = row[0]["content"]
        if (not text.startswith(f"<|im_start|>system\n{system}<|im_end|>\n") or "You are a helpful assistant." in text
                or system.strip() == "You are Rupsaa." or not system.startswith(V02_SYSTEM_PROMPT)):
            bad_system.append(i)
        for key, marker in (("terminology", "Reference terminology:\nTerm: "), ("recall_note", "they said earlier"),
                            ("recall_note_empty", "asks about earlier messages"), ("language_directive", "Response language: in the message"),
                            ("dance", "Reference dance knowledge:\nDance: ")):
            if marker in system:
                blocks[key] += marker in text
        label_text = tokenizer.decode([t for t in labels if t != IGNORE_INDEX], skip_special_tokens=False)
        if label_text != "".join(m["content"] + "<|im_end|>" for m in row if m["role"] == "assistant"):
            bad_labels.append(i)
        runtime_prompt = tokenizer.apply_chat_template(row[:-1], tokenize=True, add_generation_prompt=True)
        if ids[: len(runtime_prompt)] != runtime_prompt:
            bad_runtime.append(i)
    check("system_turn_is_v02_runtime_prompt_in_every_row", not bad_system,
          f"{len(rows) - len(bad_system)}/{len(rows)} (no qwen default, no bare 'You are Rupsaa.')")
    check("dynamic_blocks_survive_formatting", blocks["terminology"] > 0 and blocks["language_directive"] > 0
          and blocks["recall_note"] > 0 and blocks["dance"] == 48,
          dict(blocks))
    check("labels_are_assistant_turns_only", not bad_labels, f"mismatches: {bad_labels[:10]}")
    check("prompt_tokens_identical_to_runtime", not bad_runtime, f"{len(rows) - len(bad_runtime)}/{len(rows)}")
    check("no_truncation_at_cutoff", truncated == 0, f"max tokens {max_len} / {data_args.cutoff_len}")

    summary = {"all_passed": all(c["pass"] for c in checks.values()), "checks": checks,
               "counts": {"train_file_rows": len(rows), "internal_train": n_train, "internal_eval": n_eval,
                          "steps_per_epoch": per_epoch, "total_steps": total, "max_tokens": max_len},
               "optimizer_steps_run": 0, "model_weights_loaded": False}
    OUT.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"\n{'ALL SMOKE CHECKS PASSED' if summary['all_passed'] else 'SMOKE CHECKS FAILED'} -> {OUT.relative_to(PROJECT_ROOT)}")
    sys.exit(0 if summary["all_passed"] else 1)


if __name__ == "__main__":
    main()
