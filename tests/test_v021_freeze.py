"""Frozen rupsaa_v0.2.1 dataset + training configs. No model, no tokenizer download."""

import hashlib
import json
import os
from collections import Counter

import pytest
import yaml

from rupsaa.config import PROJECT_ROOT

EXPORT = PROJECT_ROOT / "data/production/exports/rupsaa_v0.2.1"
SNAPSHOT = PROJECT_ROOT / "data/production/snapshots/rupsaa_v0.2.1_training"
V02_MANIFEST = PROJECT_ROOT / "data/production/snapshots/rupsaa_v0.2_training/V02_TRAINING_MANIFEST.json"
CLI = PROJECT_ROOT / "configs/training/llamafactory_rupsaa_v0.2.1.yaml"
GUI = PROJECT_ROOT / "configs/training/llamafactory_webui_rupsaa_v0.2.1.yaml"
frozen = pytest.mark.skipif(not (EXPORT / "V021_TRAINING_MANIFEST.json").exists(), reason="rupsaa_v0.2.1 not frozen")


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def load_manifest():
    return json.loads((EXPORT / "V021_TRAINING_MANIFEST.json").read_text(encoding="utf-8"))


@frozen
def test_export_matches_manifest_and_is_read_only():
    m = load_manifest()
    for name, expected in m["files_sha256"].items():
        path = EXPORT / name
        assert sha(path) == expected, name
        assert not os.access(path, os.W_OK) or os.geteuid() == 0, f"{name} should be read-only"
    order = ("train.jsonl", "validation.jsonl", "test.jsonl", "corrective_holdout.jsonl")
    assert m["dataset_sha256"] == hashlib.sha256("".join(f"{m['files_sha256'][n]}  {n}\n" for n in order).encode()).hexdigest()
    assert json.loads((SNAPSHOT / "V021_TRAINING_MANIFEST.json").read_text(encoding="utf-8")) == m
    for name, expected in m["snapshot_files_sha256"].items():
        if name != "V021_TRAINING_MANIFEST.json":
            assert sha(SNAPSHOT / name) == expected, name


@frozen
def test_parent_v02_untouched_and_external_eval_identical():
    m, v02 = load_manifest(), json.loads(V02_MANIFEST.read_text(encoding="utf-8"))
    assert m["parent_dataset"]["dataset_sha256"] == v02["dataset_sha256"]
    for split in ("validation", "test"):
        assert m["files_sha256"][f"{split}.jsonl"] == v02["export_files_sha256"][split]
    v02_train = open(PROJECT_ROOT / "data/production/exports/rupsaa_v0.2/train.jsonl", encoding="utf-8").readlines()
    rows = open(EXPORT / "train.jsonl", encoding="utf-8").readlines()
    row_map = [json.loads(line) for line in open(EXPORT / "train_row_map.jsonl", encoding="utf-8")]
    base = [rows[r["row"]] for r in row_map if r["source"] == "rupsaa_v0.2_train"]
    assert sorted(base) == sorted(v02_train)  # every frozen V0.2 train row exactly once, unchanged


@frozen
def test_weighting_holdout_and_internal_eval_placement():
    from scripts.v021_prepare_training_set import internal_eval_positions

    m = load_manifest()
    row_map = [json.loads(line) for line in open(EXPORT / "train_row_map.jsonl", encoding="utf-8")]
    corr = Counter(r["id"] for r in row_map if r["source"] == "rupsaa_v0.2.1_corrective")
    assert set(corr.values()) == {2} and len(corr) == m["conversations"]["corrective_train_unique"]
    hold = {json.loads(line)["id"] for line in open(EXPORT / "corrective_holdout.jsonl", encoding="utf-8")}
    assert len(hold) == 21 and not hold & set(corr) and sorted(hold) == m["holdout_ids"]
    eval_pos = internal_eval_positions(len(row_map))
    assert {r["row"] for r in row_map if r["internal_split"] == "eval"} == eval_pos
    assert all(row_map[i]["source"] == "rupsaa_v0.2_train" for i in eval_pos)
    assert m["training"]["expected_total_steps"] == 196 and m["splits"]["internal_train_rows"] == 1578


@frozen
def test_every_row_uses_the_v02_runtime_system_prompt():
    from rupsaa.personality.system_prompt_v02 import V02_SYSTEM_PROMPT

    for line in open(EXPORT / "train.jsonl", encoding="utf-8"):
        system = json.loads(line)["messages"][0]
        assert system["role"] == "system" and system["content"].startswith(V02_SYSTEM_PROMPT)
        assert system["content"].strip() != "You are Rupsaa."


def test_cli_and_gui_configs_agree():
    cli = yaml.safe_load(CLI.read_text(encoding="utf-8"))
    gui = yaml.safe_load(GUI.read_text(encoding="utf-8"))
    assert cli["model_name_or_path"] == gui["top.model_path"] == "Qwen/Qwen2.5-7B-Instruct"
    assert "adapter_name_or_path" not in cli  # fresh LoRA
    assert cli["dataset"] == "rupsaa_v0.2.1_train" and gui["train.dataset"] == ["rupsaa_v0.2.1_train"]
    assert cli["dataset_dir"] == gui["train.dataset_dir"] == "data/production/exports/rupsaa_v0.2.1"
    assert cli["output_dir"] == "adapters/rupsaa-v0.2.1" and gui["train.output_dir"].endswith("/adapters/rupsaa-v0.2.1")
    pairs = [("learning_rate", "train.learning_rate", 2e-4), ("num_train_epochs", "train.num_train_epochs", 2.0),
             ("warmup_steps", "train.warmup_steps", 6), ("per_device_train_batch_size", "train.batch_size", 2),
             ("gradient_accumulation_steps", "train.gradient_accumulation_steps", 8), ("cutoff_len", "train.cutoff_len", 2048),
             ("val_size", "train.val_size", 0.05), ("save_steps", "train.save_steps", 20), ("lora_rank", "train.lora_rank", 16),
             ("lora_alpha", "train.lora_alpha", 32), ("lora_dropout", "train.lora_dropout", 0.05)]
    for c, g, want in pairs:
        assert float(cli[c]) == float(gui[g]) == want, (c, cli[c], gui[g])
    assert cli["lora_target"] == gui["train.lora_target"]
    assert cli["quantization_bit"] == 4 and gui["top.quantization_bit"] == "4" and cli["double_quantization"]
    assert cli["bf16"] and gui["train.compute_type"] == "bf16"
    assert cli["load_best_model_at_end"] and cli["eval_steps"] == cli["save_steps"] == 20
    assert cli.get("seed", 42) == 42


@frozen
def test_leakage_and_corpus_gates_recorded_as_passing():
    reports = PROJECT_ROOT / "data/production/reports/rupsaa_v0.2.1_preparation"
    assert json.loads((reports / "leakage_report.json").read_text(encoding="utf-8"))["pass"]
    assert json.loads((reports / "corrective_checks.json").read_text(encoding="utf-8"))["all_gates_pass"]
