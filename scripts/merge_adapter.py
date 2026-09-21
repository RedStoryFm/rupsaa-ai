#!/usr/bin/env python3
"""Merge a trained Rupsaa LoRA adapter into the base model's weights.

Usage:
    python scripts/merge_adapter.py --adapter adapters/rupsaa-v1 --output merged_model/rupsaa-v1

This produces a standalone, deployable model directory under merged_model/ —
the original base model weights (cached by Hugging Face) and the adapter
directory are never modified or overwritten. Merging loads the base model in
full precision (not 4-bit) because PEFT cannot merge LoRA deltas into
quantized weights; this needs more VRAM/RAM than 4-bit inference/training
does, so it is a separate, explicit step rather than something inference
does automatically.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import torch  # noqa: E402
from peft import PeftConfig, PeftModel  # noqa: E402
from transformers import AutoModelForCausalLM, AutoTokenizer  # noqa: E402

from rupsaa.config import PROJECT_ROOT, get_settings, load_model_config  # noqa: E402
from rupsaa.model.loader import resolve_compute_dtype  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("rupsaa.merge_adapter")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter", default=None, help="Path to the trained LoRA adapter (default: settings.adapter_path)")
    parser.add_argument("--output", default="merged_model/rupsaa-v1")
    args = parser.parse_args()

    settings = get_settings()
    adapter_path = Path(args.adapter or settings.adapter_path)
    if not adapter_path.is_absolute():
        adapter_path = PROJECT_ROOT / adapter_path
    output_path = PROJECT_ROOT / args.output

    if not adapter_path.exists():
        logger.error("Adapter not found at %s. Train one first with scripts/train_qlora.py.", adapter_path)
        sys.exit(1)

    peft_config = PeftConfig.from_pretrained(str(adapter_path))
    expected_base = load_model_config()["base_model_id"]
    if peft_config.base_model_name_or_path != expected_base:
        logger.error(
            "Adapter was trained against base model '%s', but configs/model.yaml currently "
            "specifies '%s'. Refusing to merge a mismatched adapter/base pair.",
            peft_config.base_model_name_or_path,
            expected_base,
        )
        sys.exit(1)

    logger.info("Loading base model %s in full precision for merging...", expected_base)
    dtype = resolve_compute_dtype()
    base_model = AutoModelForCausalLM.from_pretrained(
        expected_base,
        dtype=dtype,
        device_map="auto",
        token=settings.huggingface_token or None,
    )
    tokenizer = AutoTokenizer.from_pretrained(expected_base, token=settings.huggingface_token or None)

    logger.info("Attaching adapter from %s...", adapter_path)
    model = PeftModel.from_pretrained(base_model, str(adapter_path))

    logger.info("Merging LoRA weights into base weights...")
    merged_model = model.merge_and_unload()

    if output_path.exists() and any(output_path.iterdir()):
        logger.error("Output directory %s already exists and is non-empty. Refusing to overwrite silently.", output_path)
        sys.exit(1)
    output_path.mkdir(parents=True, exist_ok=True)

    merged_model.save_pretrained(str(output_path), safe_serialization=True)
    tokenizer.save_pretrained(str(output_path))

    manifest = {
        "base_model_id": expected_base,
        "adapter_path": str(adapter_path),
        "merge_dtype": str(dtype),
    }
    with open(output_path / "rupsaa_merge_manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    logger.info("Merged model saved to %s", output_path)


if __name__ == "__main__":
    main()
