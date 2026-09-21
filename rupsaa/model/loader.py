"""Model + tokenizer loading for Rupsaa.

Centralizes: base model resolution (configs/model.yaml, overridable via
MODEL_ID env var — see rupsaa/config.py), 4-bit QLoRA quantization config,
compute-dtype selection based on actual detected GPU capability, and
optional LoRA adapter attachment. Both scripts/chat.py and api/services.py
go through this module rather than loading the model independently.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import torch
from peft import PeftModel
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    PreTrainedModel,
    PreTrainedTokenizerBase,
)

from rupsaa.config import PROJECT_ROOT, get_settings, load_model_config

logger = logging.getLogger("rupsaa.model.loader")


def resolve_compute_dtype() -> torch.dtype:
    """bf16 if the detected GPU supports it (e.g. NVIDIA L4 / Ada+), else fp16.
    Falls back to fp32 compute dtype only when CUDA isn't available at all
    (quantization itself is skipped in that case — see load_model)."""
    if torch.cuda.is_available() and torch.cuda.is_bf16_supported():
        return torch.bfloat16
    if torch.cuda.is_available():
        return torch.float16
    return torch.float32


def build_quantization_config(model_cfg: dict) -> BitsAndBytesConfig | None:
    q = model_cfg.get("quantization", {})
    if not q.get("load_in_4bit", False) or not torch.cuda.is_available():
        if not torch.cuda.is_available():
            logger.warning("No CUDA device detected — loading in full precision on CPU.")
        return None
    compute_dtype = resolve_compute_dtype()
    return BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type=q.get("bnb_4bit_quant_type", "nf4"),
        bnb_4bit_use_double_quant=q.get("bnb_4bit_use_double_quant", True),
        bnb_4bit_compute_dtype=compute_dtype,
    )


@dataclass
class LoadedModel:
    model: PreTrainedModel
    tokenizer: PreTrainedTokenizerBase
    base_model_id: str
    adapter_path: str | None
    quantized: bool


def load_tokenizer(model_id: str) -> PreTrainedTokenizerBase:
    settings = get_settings()
    model_cfg = load_model_config()
    tok_cfg = model_cfg.get("tokenizer", {})
    tokenizer = AutoTokenizer.from_pretrained(
        model_id,
        token=settings.huggingface_token or None,
        padding_side=tok_cfg.get("padding_side", "right"),
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    return tokenizer


def load_model(
    *,
    model_id: str | None = None,
    adapter_path: str | Path | None = None,
    use_adapter: bool = True,
    device_map: str | dict = "auto",
) -> LoadedModel:
    """Load the base model (4-bit QLoRA quantized when CUDA is available)
    and optionally attach a trained LoRA adapter.

    If use_adapter is True but no adapter exists at adapter_path, this logs
    a warning and returns the base model rather than raising — the pipeline
    must work before any adapter has been trained.
    """
    settings = get_settings()
    model_cfg = load_model_config()
    resolved_model_id = model_id or model_cfg["base_model_id"]

    tokenizer = load_tokenizer(resolved_model_id)
    quant_config = build_quantization_config(model_cfg)
    compute_dtype = resolve_compute_dtype()

    logger.info("Loading base model %s (quantized=%s, dtype=%s)", resolved_model_id, quant_config is not None, compute_dtype)
    model = AutoModelForCausalLM.from_pretrained(
        resolved_model_id,
        quantization_config=quant_config,
        torch_dtype=compute_dtype if quant_config is None else None,
        device_map=device_map,
        token=settings.huggingface_token or None,
    )

    resolved_adapter_path = None
    if use_adapter:
        candidate = Path(adapter_path or settings.adapter_path)
        if not candidate.is_absolute():
            candidate = PROJECT_ROOT / candidate
        if candidate.exists() and any(candidate.iterdir()):
            logger.info("Attaching LoRA adapter from %s", candidate)
            model = PeftModel.from_pretrained(model, str(candidate))
            resolved_adapter_path = str(candidate)
        else:
            logger.warning(
                "use_adapter=True but no adapter found at %s — serving base model only.",
                candidate,
            )

    model.eval()
    return LoadedModel(
        model=model,
        tokenizer=tokenizer,
        base_model_id=resolved_model_id,
        adapter_path=resolved_adapter_path,
        quantized=quant_config is not None,
    )
