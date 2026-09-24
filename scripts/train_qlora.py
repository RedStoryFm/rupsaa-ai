#!/usr/bin/env python3
"""QLoRA fine-tuning for Rupsaa.

Usage (real training — NOT run automatically by the setup process):
    python scripts/train_qlora.py --config configs/training.yaml

Resume from a checkpoint:
    python scripts/train_qlora.py --config configs/training.yaml --resume-from-checkpoint checkpoints/checkpoint-100

Smoke test only (tiny data slice, 1 step, confirms the pipeline works
end-to-end without a real training run):
    python scripts/train_qlora.py --config configs/training.yaml --smoke-test

What this does:
  1. Loads configs/model.yaml + configs/training.yaml (both editable, no
     hard-coded model ID or hyperparameters in this file).
  2. Loads the base model 4-bit quantized (NF4, double quant, bf16 compute
     on this L4 GPU) via rupsaa/model/loader.py.
  3. Attaches a fresh LoRA adapter (rank/alpha/dropout/target_modules all
     config-driven) via peft.
  4. Loads data/train.jsonl + data/validation.jsonl, formats each
     conversation with the model's native chat template, and trains with
     TRL's SFTTrainer.
  5. Saves the LoRA adapter to training.final_adapter_dir and intermediate
     checkpoints to training.output_dir.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import torch  # noqa: E402
from datasets import load_dataset  # noqa: E402
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training  # noqa: E402
from transformers import TrainingArguments, set_seed  # noqa: E402
from trl import SFTTrainer  # noqa: E402

from rupsaa.config import PROJECT_ROOT, load_model_config, load_training_config  # noqa: E402
from rupsaa.model.loader import load_model  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("rupsaa.train_qlora")


def build_lora_config(model_cfg: dict, training_cfg: dict) -> LoraConfig:
    lora_cfg = training_cfg["lora"]
    return LoraConfig(
        r=lora_cfg["r"],
        lora_alpha=lora_cfg["alpha"],
        lora_dropout=lora_cfg["dropout"],
        bias=lora_cfg["bias"],
        task_type=lora_cfg["task_type"],
        target_modules=model_cfg["lora_target_modules"],
    )


def format_example(example: dict, tokenizer) -> dict:
    text = tokenizer.apply_chat_template(
        example["messages"], tokenize=False, add_generation_prompt=False
    )
    return {"text": text}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/training.yaml", help="Path to a training config YAML (e.g. configs/training/rupsaa_v0.1_qlora.yaml)")
    parser.add_argument("--resume-from-checkpoint", default=None)
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Run a 1-step training pass on a 2-example slice to verify the pipeline, then exit. Does NOT save a real adapter.",
    )
    args = parser.parse_args()

    model_cfg = load_model_config()
    training_cfg = load_training_config(args.config)
    set_seed(training_cfg["seed"])

    logger.info("Base model: %s", model_cfg["base_model_id"])
    loaded = load_model(use_adapter=False)  # train from base, not on top of a prior adapter
    model, tokenizer = loaded.model, loaded.tokenizer

    if loaded.quantized:
        model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=training_cfg["training"]["gradient_checkpointing"])

    lora_config = build_lora_config(model_cfg, training_cfg)
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    data_cfg = training_cfg["data"]
    train_path = PROJECT_ROOT / data_cfg["train_path"]
    val_path = PROJECT_ROOT / data_cfg["validation_path"]

    if not train_path.exists():
        logger.error("Training data not found at %s — run scripts/prepare_dataset.py first.", train_path)
        sys.exit(1)

    dataset = load_dataset(
        "json",
        data_files={"train": str(train_path), "validation": str(val_path)},
    )
    dataset = dataset.map(lambda ex: format_example(ex, tokenizer), remove_columns=dataset["train"].column_names)

    if args.smoke_test:
        logger.info("SMOKE TEST MODE: slicing to 2 train / 2 val examples, 1 step, no adapter save.")
        dataset["train"] = dataset["train"].select(range(min(2, len(dataset["train"]))))
        dataset["validation"] = dataset["validation"].select(range(min(2, len(dataset["validation"]))))

    t_cfg = training_cfg["training"]
    output_dir = PROJECT_ROOT / (t_cfg["output_dir"] if not args.smoke_test else "checkpoints/_smoke_test")

    training_args = TrainingArguments(
        output_dir=str(output_dir),
        num_train_epochs=1 if args.smoke_test else t_cfg["num_train_epochs"],
        max_steps=1 if args.smoke_test else -1,
        per_device_train_batch_size=t_cfg["per_device_train_batch_size"],
        per_device_eval_batch_size=t_cfg["per_device_eval_batch_size"],
        gradient_accumulation_steps=t_cfg["gradient_accumulation_steps"],
        gradient_checkpointing=t_cfg["gradient_checkpointing"],
        learning_rate=t_cfg["learning_rate"],
        lr_scheduler_type=t_cfg["lr_scheduler_type"],
        warmup_ratio=t_cfg["warmup_ratio"],
        weight_decay=t_cfg["weight_decay"],
        optim=t_cfg["optim"],
        max_grad_norm=t_cfg["max_grad_norm"],
        logging_steps=1 if args.smoke_test else t_cfg["logging_steps"],
        eval_strategy="steps" if not args.smoke_test else "no",
        eval_steps=t_cfg["eval_steps"],
        save_strategy="no" if args.smoke_test else t_cfg["save_strategy"],
        save_steps=t_cfg["save_steps"],
        save_total_limit=t_cfg["save_total_limit"],
        load_best_model_at_end=False if args.smoke_test else t_cfg["load_best_model_at_end"],
        metric_for_best_model=t_cfg["metric_for_best_model"],
        report_to=t_cfg["report_to"],
        bf16=loaded.quantized and torch.cuda.is_bf16_supported(),
        fp16=loaded.quantized and not torch.cuda.is_bf16_supported(),
        seed=training_cfg["seed"],
    )

    trainer = SFTTrainer(
        model=model,
        args=training_args,
        train_dataset=dataset["train"],
        eval_dataset=dataset["validation"],
        processing_class=tokenizer,
        dataset_text_field="text",
        max_seq_length=data_cfg["max_seq_length"],
    )

    logger.info("Starting training (smoke_test=%s)...", args.smoke_test)
    trainer.train(resume_from_checkpoint=args.resume_from_checkpoint)

    if args.smoke_test:
        logger.info("Smoke test complete — pipeline verified. No adapter was saved.")
        return

    final_dir = PROJECT_ROOT / t_cfg["final_adapter_dir"]
    final_dir.mkdir(parents=True, exist_ok=True)
    trainer.save_model(str(final_dir))
    tokenizer.save_pretrained(str(final_dir))
    logger.info("Saved final Rupsaa LoRA adapter to %s", final_dir)


if __name__ == "__main__":
    main()
