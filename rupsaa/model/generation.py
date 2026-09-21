"""Chat-template-based generation for Rupsaa.

Always uses the model's own native chat template (tokenizer.apply_chat_template)
rather than a hand-rolled prompt format — Qwen2.5-Instruct ships a ChatML
template that transformers applies automatically.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import torch
from transformers import PreTrainedModel, PreTrainedTokenizerBase

from rupsaa.config import load_inference_config


@dataclass
class GenerationParams:
    max_new_tokens: int = 512
    temperature: float = 0.8
    top_p: float = 0.9
    top_k: int = 50
    repetition_penalty: float = 1.1
    do_sample: bool = True

    @classmethod
    def from_config(cls, overrides: dict | None = None) -> "GenerationParams":
        cfg = load_inference_config()["generation"]
        params = cls(**cfg)
        if overrides:
            for key, value in overrides.items():
                if value is not None and hasattr(params, key):
                    setattr(params, key, value)
        return params


@dataclass
class ChatMessage:
    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass
class GenerationResult:
    text: str
    prompt_tokens: int
    completion_tokens: int


def build_prompt(
    tokenizer: PreTrainedTokenizerBase,
    messages: list[ChatMessage],
) -> str:
    formatted = [{"role": m.role, "content": m.content} for m in messages]
    return tokenizer.apply_chat_template(
        formatted, tokenize=False, add_generation_prompt=True
    )


def generate_reply(
    model: PreTrainedModel,
    tokenizer: PreTrainedTokenizerBase,
    messages: list[ChatMessage],
    params: GenerationParams | None = None,
) -> GenerationResult:
    params = params or GenerationParams.from_config()
    prompt = build_prompt(tokenizer, messages)

    inputs = tokenizer(prompt, return_tensors="pt", add_special_tokens=False)
    inputs = {k: v.to(model.device) for k, v in inputs.items()}
    prompt_tokens = inputs["input_ids"].shape[1]

    with torch.no_grad():
        output_ids = model.generate(
            **inputs,
            max_new_tokens=params.max_new_tokens,
            temperature=params.temperature if params.do_sample else None,
            top_p=params.top_p if params.do_sample else None,
            top_k=params.top_k if params.do_sample else None,
            do_sample=params.do_sample,
            repetition_penalty=params.repetition_penalty,
            pad_token_id=tokenizer.pad_token_id,
            eos_token_id=tokenizer.eos_token_id,
        )

    completion_ids = output_ids[0][prompt_tokens:]
    text = tokenizer.decode(completion_ids, skip_special_tokens=True).strip()
    return GenerationResult(
        text=text,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_ids.shape[0],
    )
