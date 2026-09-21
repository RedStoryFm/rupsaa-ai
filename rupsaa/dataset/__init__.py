"""Rupsaa dataset production pipeline.

Independent of the core `rupsaa` inference/training packages — importing
anything under `rupsaa.dataset` never pulls in torch/transformers, so
dataset tooling stays fast to run and safe for CI. It only ever *produces*
data compatible with the existing QLoRA pipeline (data/train.jsonl format);
it does not modify how that pipeline consumes data.
"""
