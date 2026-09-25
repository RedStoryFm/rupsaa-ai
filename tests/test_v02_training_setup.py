"""Rupsaa V0.2 training setup: the frozen export, train-as-you-serve system
prompt, LLaMA-Factory configs, and runtime prompt selection.

No model weights are loaded; the WebUI config test uses LLaMA-Factory's own
load_args + component registry, like the V0.1 test.
"""

import hashlib
import json
import os
from unittest.mock import MagicMock

import pytest
import yaml

from rupsaa.config import PROJECT_ROOT
from rupsaa.personality.system_prompt import (
    BASE_PERSONA,
    build_system_prompt,
    resolve_prompt_version,
)
from rupsaa.personality.system_prompt_v02 import V02_SYSTEM_PROMPT

EXPORT_DIR = PROJECT_ROOT / "data/production/exports/rupsaa_v0.2"
SNAPSHOT_DIR = PROJECT_ROOT / "data/production/snapshots/rupsaa_v0.2_training"
MANIFEST_PATH = SNAPSHOT_DIR / "V02_TRAINING_MANIFEST.json"
V01_EXPORT = PROJECT_ROOT / "data/production/exports/rupsaa_v0.1"
SPLITS = ("train", "validation", "test")

frozen = pytest.mark.skipif(not MANIFEST_PATH.exists(), reason="V0.2 frozen export not present in this checkout")


def _manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _rows(split: str) -> list[list[dict]]:
    return [json.loads(line)["messages"] for line in open(EXPORT_DIR / f"{split}.jsonl", encoding="utf-8")]


# --- Frozen export ------------------------------------------------------------------------------

@frozen
def test_v02_export_matches_manifest_counts_and_hashes():
    m = _manifest()
    assert m["status"] == "OWNER_APPROVED_FROZEN"
    assert (m["conversations"], m["assistant_replies"]) == (1533, 2144)
    total = 0
    for s in SPLITS:
        path = EXPORT_DIR / f"{s}.jsonl"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == m["export_files_sha256"][s], f"{s}.jsonl changed after freeze"
        rows = _rows(s)
        assert len(rows) == m["splits"][s]["conversations"] == len(m["splits"][s]["ids"])
        total += len(rows)
    assert total == 1533
    assert hashlib.sha256((SNAPSHOT_DIR / "frozen_records.jsonl").read_bytes()).hexdigest() == m["dataset_sha256"]


@frozen
def test_v02_split_ratios_and_language_stratification():
    m = _manifest()
    counts = {s: m["splits"][s]["conversations"] for s in SPLITS}
    assert counts["train"] / 1533 == pytest.approx(0.90, abs=0.01)
    assert counts["validation"] / 1533 == pytest.approx(0.05, abs=0.01)
    assert counts["test"] / 1533 == pytest.approx(0.05, abs=0.01)
    for s in ("validation", "test"):
        assert set(m["splits"][s]["language_distribution"]) == {"banglish", "bn", "en", "mixed"}


@frozen
def test_v02_no_leakage_across_splits():
    def fingerprints(split):
        return {json.dumps([x for x in r if x["role"] != "system"], sort_keys=True, ensure_ascii=False) for r in _rows(split)}

    fp = {s: fingerprints(s) for s in SPLITS}
    assert not fp["train"] & fp["validation"]
    assert not fp["train"] & fp["test"]
    assert not fp["validation"] & fp["test"]
    ids = {s: set(_manifest()["splits"][s]["ids"]) for s in SPLITS}
    assert not (ids["train"] & ids["validation"] or ids["train"] & ids["test"] or ids["validation"] & ids["test"])
    assert _manifest()["split"]["leakage_check"]["groups_spanning_splits"] == 0


@frozen
def test_v02_every_record_uses_the_runtime_v02_system_prompt():
    """Train as you serve: every system turn is what build_system_prompt(prompt_version='v0.2')
    returns for that record's retrieved-context / terminology block — never 'You are Rupsaa.'"""
    rag_prefix = build_system_prompt(prompt_version="v0.2", retrieved_context="X").split("Retrieved context:\n")[0]
    for s in SPLITS:
        for messages in _rows(s):
            system = messages[0]
            assert system["role"] == "system"
            content = system["content"]
            assert content.startswith(V02_SYSTEM_PROMPT)
            assert not content.startswith("You are Rupsaa.")
            if "\n\nReference terminology:\n" in content:
                ctx = content.split("\n\nReference terminology:\n", 1)[1]
                assert content == build_system_prompt(prompt_version="v0.2", terminology_context=ctx)
            elif "Retrieved context:\n" in content:
                assert content.startswith(rag_prefix)
                ctx = content.split("Retrieved context:\n", 1)[1]
                assert content == build_system_prompt(prompt_version="v0.2", retrieved_context=ctx)
            else:
                assert content == build_system_prompt(prompt_version="v0.2")
            roles = [x["role"] for x in messages[1:]]
            assert roles and roles[-1] == "assistant" and all(
                r == ("user" if i % 2 == 0 else "assistant") for i, r in enumerate(roles))


@frozen
def test_v02_terminology_examples_all_in_train_with_full_blocks():
    term = [r for r in _rows("train") if "\n\nReference terminology:\n" in r[0]["content"]]
    assert len(term) == 30
    for r in term:
        block = r[0]["content"].split("\n\nReference terminology:\n", 1)[1]
        assert block.startswith("Term: ") and "\nCategory: " in block and "\nDefinition: " in block


@frozen
def test_v02_freeze_left_v01_export_untouched():
    recorded = _manifest()["v01_untouched"]["export_sha256"]
    for s in SPLITS:
        assert hashlib.sha256((V01_EXPORT / f"{s}.jsonl").read_bytes()).hexdigest() == recorded[s]


def test_dataset_info_registers_v02_without_changing_v01():
    info = json.loads((PROJECT_ROOT / "data/dataset_info.json").read_text(encoding="utf-8"))
    for version in ("v0.1", "v0.2"):
        for s in SPLITS:
            entry = info[f"rupsaa_{version}_{s}"]
            assert entry["file_name"] == f"production/exports/rupsaa_{version}/{s}.jsonl"
            assert entry["formatting"] == "sharegpt"
            assert entry["tags"]["system_tag"] == "system"


# --- LLaMA-Factory configs -----------------------------------------------------------------------

CLI_CONFIG = PROJECT_ROOT / "configs/training/llamafactory_rupsaa_v0.2.yaml"
WEBUI_TEMPLATE = PROJECT_ROOT / "configs/training/llamafactory_webui_rupsaa_v0.2.yaml"
EVAL_CONFIG = PROJECT_ROOT / "configs/training/llamafactory_rupsaa_v0.2_eval_validation.yaml"


def test_v02_cli_config_values():
    cfg = yaml.safe_load(CLI_CONFIG.read_text(encoding="utf-8"))
    assert cfg["model_name_or_path"] == "Qwen/Qwen2.5-7B-Instruct"
    assert (cfg["stage"], cfg["finetuning_type"], cfg["template"]) == ("sft", "lora", "qwen")
    assert (cfg["quantization_bit"], cfg["quantization_type"], cfg["double_quantization"]) == (4, "nf4", True)
    assert (cfg["lora_rank"], cfg["lora_alpha"], cfg["lora_dropout"]) == (16, 32, 0.05)
    assert cfg["lora_target"] == "q_proj,k_proj,v_proj,o_proj,gate_proj,up_proj,down_proj"
    assert (cfg["per_device_train_batch_size"], cfg["gradient_accumulation_steps"], cfg["cutoff_len"]) == (2, 8, 2048)
    assert (cfg["optim"], cfg["max_grad_norm"], cfg["lr_scheduler_type"], cfg["bf16"]) == ("paged_adamw_8bit", 0.3, "cosine", True)
    assert (cfg["learning_rate"], cfg["num_train_epochs"], cfg["warmup_steps"]) == (2e-4, 2.0, 5)
    assert cfg["eval_steps"] == cfg["save_steps"] == 20 and cfg["load_best_model_at_end"] is True
    assert cfg["dataset"] == "rupsaa_v0.2_train" and cfg["output_dir"] == "adapters/rupsaa-v0.2"
    assert "rupsaa_v0.2_test" not in json.dumps(cfg) and "rupsaa_v0.2_validation" not in json.dumps(cfg)


def test_v02_eval_config_never_trains_and_never_uses_test():
    cfg = yaml.safe_load(EVAL_CONFIG.read_text(encoding="utf-8"))
    assert cfg["do_train"] is False and cfg["do_eval"] is True
    assert cfg["dataset"] == "rupsaa_v0.2_validation"
    assert "adapters" not in cfg["output_dir"]


def _llamafactory_available() -> bool:
    try:
        import llamafactory.webui.common  # noqa: F401
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _llamafactory_available(), reason="llamafactory not installed")
def test_v02_webui_template_loads_through_llamafactory(tmp_path, monkeypatch):
    monkeypatch.setenv("GRADIO_ANALYTICS_ENABLED", "False")
    import gradio as gr
    from llamafactory.webui.common import load_args
    from llamafactory.webui.components import create_top, create_train_tab
    from llamafactory.webui.engine import Engine

    fake_root = str(tmp_path)
    (tmp_path / "config").mkdir()
    rendered = WEBUI_TEMPLATE.read_text(encoding="utf-8").replace("@RUPSAA_ROOT@", fake_root)
    (tmp_path / "config" / "rupsaa_v0.2.yaml").write_text(rendered, encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    cfg = load_args("rupsaa_v0.2.yaml")
    assert cfg is not None
    engine = Engine(pure_chat=False)
    with gr.Blocks():
        engine.manager.add_elems("top", create_top())
        engine.manager.add_elems("train", create_train_tab(engine))
    for elem_id in cfg:
        engine.manager.get_elem_by_id(elem_id)

    assert (cfg["top.model_name"], cfg["top.model_path"]) == ("Custom", "Qwen/Qwen2.5-7B-Instruct")
    assert (cfg["top.template"], cfg["top.quantization_bit"], cfg["top.finetuning_type"]) == ("qwen", "4", "lora")
    assert cfg["train.dataset_dir"] == "data" and cfg["train.dataset"] == ["rupsaa_v0.2_train"]
    assert float(cfg["train.learning_rate"]) == 2e-4 and float(cfg["train.num_train_epochs"]) == 2.0
    assert (cfg["train.save_steps"], cfg["train.warmup_steps"], cfg["train.val_size"]) == (20, 5, 0.05)
    assert (cfg["train.batch_size"], cfg["train.gradient_accumulation_steps"], cfg["train.cutoff_len"]) == (2, 8, 2048)
    assert (cfg["train.lora_rank"], cfg["train.lora_alpha"], cfg["train.lora_dropout"]) == (16, 32, 0.05)
    assert cfg["train.optim"] == "paged_adamw_8bit" and cfg["train.compute_type"] == "bf16"
    assert cfg["train.output_dir"] == os.path.join(fake_root, "adapters", "rupsaa-v0.2")
    assert os.path.join("saves", "Custom", "lora", cfg["train.output_dir"]) == cfg["train.output_dir"]


# --- Runtime system prompt selection ------------------------------------------------------------

def test_v01_runtime_prompt_unchanged_by_default():
    assert build_system_prompt().startswith(BASE_PERSONA.strip())
    assert build_system_prompt() == build_system_prompt(prompt_version="v0.1")
    assert V02_SYSTEM_PROMPT not in build_system_prompt()


def test_v02_runtime_prompt_is_the_training_prompt():
    assert build_system_prompt(prompt_version="v0.2") == V02_SYSTEM_PROMPT
    assert BASE_PERSONA not in build_system_prompt(prompt_version="v0.2", terminology_context="Term: X")


@pytest.mark.parametrize("adapter,override,expected", [
    ("adapters/rupsaa-v0.2", None, "v0.2"),
    ("/abs/rupsaa-ai/adapters/rupsaa-v0.2/", None, "v0.2"),
    ("adapters/rupsaa-v0.1", None, "v0.1"),
    (None, None, "v0.1"),
    ("adapters/rupsaa-v0.1", "v0.2", "v0.2"),
])
def test_resolve_prompt_version(adapter, override, expected):
    assert resolve_prompt_version(adapter, override) == expected


def test_resolve_prompt_version_rejects_unknown():
    with pytest.raises(ValueError):
        resolve_prompt_version("adapters/rupsaa-v0.2", "v9")


def test_engine_serves_v02_adapter_with_v02_prompt(monkeypatch):
    import rupsaa.model.inference as inference

    captured = {}

    def fake_generate(model, tokenizer, messages, params):
        captured["system"] = messages[0].content
        return MagicMock(text="ok", prompt_tokens=1, completion_tokens=1)

    monkeypatch.setattr(inference, "generate_reply", fake_generate)
    monkeypatch.delenv("RUPSAA_PROMPT_VERSION", raising=False)
    inference.get_settings.cache_clear()

    loaded = MagicMock(adapter_path="/x/adapters/rupsaa-v0.2")
    inference.RupsaaEngine(loaded).chat(history=[], user_message="hi")
    assert captured["system"] == V02_SYSTEM_PROMPT

    loaded = MagicMock(adapter_path="/x/adapters/rupsaa-v0.1")
    inference.RupsaaEngine(loaded).chat(history=[], user_message="hi")
    assert captured["system"].startswith(BASE_PERSONA.strip())
