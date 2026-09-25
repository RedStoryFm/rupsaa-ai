#!/usr/bin/env python3
"""Pre-training smoke validation for Rupsaa V0.2 — no model weights, no optimizer steps.

    python scripts/v02_pretrain_smoke.py [--out data/production/reports/rupsaa_v0.2_training/smoke_check.json]

Runs LLaMA-Factory 0.7.1's own argument parser and data pipeline (tokenizer
only) on configs/training/llamafactory_rupsaa_v0.2.yaml and checks:
  * frozen export files match the manifest SHA-256
  * the config parses, points at rupsaa_v0.2_train, writes to adapters/rupsaa-v0.2
  * every row survives preprocessing and the seed-42 5% resplit gives 1311/69
  * every formatted example starts with the V0.2 runtime system prompt (never
    the qwen default "You are a helpful assistant." or "You are Rupsaa.")
  * the 30 terminology examples keep their full "Reference terminology:" block
  * labels cover exactly the assistant turns (+ <|im_end|>), nothing from
    system/user turns
  * prompt tokens are identical to what the runtime would send
    (tokenizer.apply_chat_template on build_system_prompt(prompt_version="v0.2"))
  * nothing is truncated at cutoff_len 2048
  * the frozen-validation eval config parses
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")

from rupsaa.dataset.config import PROJECT_ROOT  # noqa: E402
from rupsaa.personality.system_prompt import build_system_prompt  # noqa: E402

CLI_CONFIG = PROJECT_ROOT / "configs/training/llamafactory_rupsaa_v0.2.yaml"
EVAL_CONFIG = PROJECT_ROOT / "configs/training/llamafactory_rupsaa_v0.2_eval_validation.yaml"
MANIFEST = PROJECT_ROOT / "data/production/snapshots/rupsaa_v0.2_training/V02_TRAINING_MANIFEST.json"
FROZEN = PROJECT_ROOT / "data/production/snapshots/rupsaa_v0.2_training/frozen_records.jsonl"
EXPORT = PROJECT_ROOT / "data/production/exports/rupsaa_v0.2"
DEFAULT_OUT = PROJECT_ROOT / "data/production/reports/rupsaa_v0.2_training/smoke_check.json"
IGNORE_INDEX = -100


def dataset_names(value) -> list[str]:
    """0.7.1 keeps data_args.dataset as the raw comma-separated string."""
    return [d.strip() for d in value.split(",")] if isinstance(value, str) else list(value)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = p.parse_args()
    os.chdir(PROJECT_ROOT)

    checks: dict[str, dict] = {}

    def check(name: str, ok: bool, detail) -> None:
        checks[name] = {"pass": bool(ok), "detail": detail}
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    actual = {s: hashlib.sha256((EXPORT / f"{s}.jsonl").read_bytes()).hexdigest() for s in ("train", "validation", "test")}
    check("frozen_export_sha256", actual == manifest["export_files_sha256"], actual)

    from llamafactory.data import get_dataset, split_dataset
    from llamafactory.hparams import get_train_args
    from llamafactory.model import load_tokenizer

    cfg = yaml.safe_load(CLI_CONFIG.read_text(encoding="utf-8"))
    cfg["output_dir"] = str(PROJECT_ROOT / cfg["output_dir"])
    model_args, data_args, training_args, finetuning_args, _ = get_train_args(dict(cfg))
    check("config_parses", True, f"stage=sft lr={training_args.learning_rate} epochs={training_args.num_train_epochs}")
    check("dataset_is_v02_train", dataset_names(data_args.dataset) == ["rupsaa_v0.2_train"], data_args.dataset)
    out_dir = Path(training_args.output_dir).resolve()
    check("output_dir_is_v02", out_dir == (PROJECT_ROOT / "adapters/rupsaa-v0.2").resolve()
          and "rupsaa-v0.1" not in str(out_dir), str(out_dir))
    check("output_dir_not_populated", not (out_dir.exists() and any(out_dir.iterdir())),
          "absent" if not out_dir.exists() else "exists but empty")
    check("qlora_settings", model_args.quantization_bit == 4 and model_args.quantization_type == "nf4"
          and model_args.double_quantization and not model_args.disable_gradient_checkpointing
          and training_args.bf16 and training_args.optim == "paged_adamw_8bit",
          f"4bit={model_args.quantization_bit} {model_args.quantization_type} double={model_args.double_quantization} "
          f"grad_ckpt={not model_args.disable_gradient_checkpointing} bf16={training_args.bf16} optim={training_args.optim}")
    check("lora_settings", (finetuning_args.lora_rank, finetuning_args.lora_alpha, finetuning_args.lora_dropout) == (16, 32, 0.05)
          and sorted(finetuning_args.lora_target) == sorted("q_proj,k_proj,v_proj,o_proj,gate_proj,up_proj,down_proj".split(",")),
          f"r={finetuning_args.lora_rank} a={finetuning_args.lora_alpha} d={finetuning_args.lora_dropout} target={finetuning_args.lora_target}")
    check("best_model_retention", training_args.load_best_model_at_end and training_args.eval_steps == training_args.save_steps == 20
          and training_args.metric_for_best_model == "eval_loss", f"eval_steps={training_args.eval_steps} save_steps={training_args.save_steps}")

    tok_module = load_tokenizer(model_args)
    tokenizer = tok_module["tokenizer"] if isinstance(tok_module, dict) else tok_module
    dataset = get_dataset(model_args, data_args, training_args, stage="sft", tokenizer=tokenizer)
    n_rows = sum(1 for _ in open(EXPORT / "train.jsonl", encoding="utf-8"))
    check("no_rows_dropped_in_preprocessing", len(dataset) == n_rows, f"{len(dataset)} tokenized / {n_rows} frozen train rows")
    parts = split_dataset(dataset, data_args, training_args)
    n_train, n_eval = len(parts["train_dataset"]), len(parts["eval_dataset"])
    check("resplit_counts", (n_train, n_eval) == (1311, 69), f"train={n_train} eval={n_eval}")
    steps_per_epoch = -(-n_train // training_args.per_device_train_batch_size) // training_args.gradient_accumulation_steps
    total_steps = int(-(-training_args.num_train_epochs * steps_per_epoch // 1))
    check("expected_steps", total_steps == 164, f"{steps_per_epoch}/epoch x {training_args.num_train_epochs} = {total_steps}")

    # Row i of the tokenized dataset corresponds to row i of the frozen train file.
    train_rows = [json.loads(line)["messages"] for line in open(EXPORT / "train.jsonl", encoding="utf-8")]
    bad_system, bad_labels, bad_runtime, truncated, term_ok, term_total = [], [], [], 0, 0, 0
    max_len = 0
    for i, (row, ex) in enumerate(zip(train_rows, dataset)):
        ids, labels = ex["input_ids"], ex["labels"]
        max_len = max(max_len, len(ids))
        if len(ids) >= data_args.cutoff_len:
            truncated += 1
        text = tokenizer.decode(ids, skip_special_tokens=False)
        system = row[0]["content"]
        if not text.startswith(f"<|im_start|>system\n{system}<|im_end|>\n") or "You are a helpful assistant." in text:
            bad_system.append(i)
        if "\n\nReference terminology:\n" in system:
            term_total += 1
            term_ok += "Reference terminology:\nTerm: " in text

        label_text = tokenizer.decode([t for t in labels if t != IGNORE_INDEX], skip_special_tokens=False)
        expected_label = "".join(m["content"] + "<|im_end|>" for m in row if m["role"] == "assistant")
        if label_text != expected_label:
            bad_labels.append(i)

        # Runtime: system + history + last user, rendered by the tokenizer's own chat template.
        runtime_prompt = tokenizer.apply_chat_template(row[:-1], tokenize=True, add_generation_prompt=True)
        if ids[: len(runtime_prompt)] != runtime_prompt:
            bad_runtime.append(i)

    expected_v02_base = build_system_prompt(prompt_version="v0.2")
    n_base = sum(1 for r in train_rows if r[0]["content"] == expected_v02_base)
    n_v01 = sum(1 for r in train_rows if r[0]["content"].startswith("You are Rupsaa.\n") or r[0]["content"] == "You are Rupsaa.")
    check("v02_system_prompt_in_every_example", not bad_system and n_v01 == 0,
          f"{len(train_rows) - len(bad_system)}/{len(train_rows)} start with their V0.2 system turn "
          f"({n_base} exactly build_system_prompt('v0.2')), V0.1-style system turns: {n_v01}")
    check("terminology_blocks_survive_formatting", term_total == 30 and term_ok == term_total, f"{term_ok}/{term_total}")
    check("labels_are_assistant_turns_only", not bad_labels, f"mismatches: {bad_labels[:10]}")
    check("prompt_tokens_identical_to_runtime", not bad_runtime,
          f"{len(train_rows) - len(bad_runtime)}/{len(train_rows)} identical to tokenizer.apply_chat_template (runtime path)")
    check("no_truncation_at_cutoff", truncated == 0, f"max tokens {max_len} / cutoff {data_args.cutoff_len}, truncated {truncated}")

    ecfg = yaml.safe_load(EVAL_CONFIG.read_text(encoding="utf-8"))
    ecfg["output_dir"] = str(PROJECT_ROOT / ecfg["output_dir"])
    ecfg["adapter_name_or_path"] = None  # adapter doesn't exist yet; parse-only
    _, e_data, e_train, _, _ = get_train_args(ecfg)
    check("eval_validation_config_parses", dataset_names(e_data.dataset) == ["rupsaa_v0.2_validation"] and not e_train.do_train and e_train.do_eval,
          f"dataset={e_data.dataset} do_train={e_train.do_train} do_eval={e_train.do_eval}")

    summary = {
        "all_passed": all(c["pass"] for c in checks.values()),
        "checks": checks,
        "counts": {"frozen_train_rows": n_rows, "resplit_train": n_train, "resplit_eval": n_eval,
                   "steps_per_epoch": steps_per_epoch, "total_steps": total_steps, "max_tokens": max_len},
        "optimizer_steps_run": 0,
        "model_weights_loaded": False,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"\n{'ALL SMOKE CHECKS PASSED' if summary['all_passed'] else 'SMOKE CHECKS FAILED'} -> {args.out.relative_to(PROJECT_ROOT)}")
    sys.exit(0 if summary["all_passed"] else 1)


if __name__ == "__main__":
    main()
