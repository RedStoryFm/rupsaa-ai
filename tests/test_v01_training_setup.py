"""Tests for the Rupsaa V0.1 training setup: the frozen dataset/export,
adapter-path configuration fallback, and training config validation.

None of these load real model weights — the model loader's adapter-
resolution logic is exercised with AutoModelForCausalLM/PeftModel mocked
out, matching the "no multi-GB model downloads in unit tests" constraint.
"""

import hashlib
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from rupsaa.config import PROJECT_ROOT, Settings, load_training_config


# --- Frozen dataset / export ---

MANIFEST_PATH = PROJECT_ROOT / "data/production/snapshots/rupsaa_v0.1_training/V01_TRAINING_MANIFEST.json"
EXPORT_DIR = PROJECT_ROOT / "data/production/exports/rupsaa_v0.1"


@pytest.mark.skipif(not MANIFEST_PATH.exists(), reason="V0.1 training manifest not present in this checkout")
def test_v01_manifest_matches_export_files():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["quality_status"] == "approved"
    assert len(manifest["conversation_ids"]) == manifest["approved_count"]
    assert len(set(manifest["conversation_ids"])) == manifest["approved_count"], "duplicate IDs in manifest"

    train_count = sum(1 for _ in open(EXPORT_DIR / "train.jsonl", encoding="utf-8"))
    val_count = sum(1 for _ in open(EXPORT_DIR / "validation.jsonl", encoding="utf-8"))
    test_count = sum(1 for _ in open(EXPORT_DIR / "test.jsonl", encoding="utf-8"))
    assert train_count + val_count + test_count == manifest["approved_count"]


@pytest.mark.skipif(not EXPORT_DIR.exists(), reason="V0.1 export not present in this checkout")
def test_v01_export_no_leakage_across_splits():
    def fingerprints(path: Path) -> set[str]:
        out = set()
        with open(path, encoding="utf-8") as f:
            for line in f:
                record = json.loads(line)
                digest = hashlib.sha256(
                    json.dumps(record["messages"], sort_keys=True, ensure_ascii=False).encode("utf-8")
                ).hexdigest()
                out.add(digest)
        return out

    train_fp = fingerprints(EXPORT_DIR / "train.jsonl")
    val_fp = fingerprints(EXPORT_DIR / "validation.jsonl")
    test_fp = fingerprints(EXPORT_DIR / "test.jsonl")

    assert train_fp & val_fp == set()
    assert train_fp & test_fp == set()
    assert val_fp & test_fp == set()


@pytest.mark.skipif(not EXPORT_DIR.exists(), reason="V0.1 export not present in this checkout")
def test_v01_export_schema_valid():
    for name in ("train.jsonl", "validation.jsonl", "test.jsonl"):
        with open(EXPORT_DIR / name, encoding="utf-8") as f:
            for line in f:
                record = json.loads(line)
                messages = record["messages"]
                assert messages, f"{name}: empty messages"
                for m in messages:
                    assert m["role"] in ("system", "user", "assistant")
                    assert m["content"] and m["content"].strip()


# --- Adapter configuration fallback ---

def test_adapter_path_defaults_when_env_unset(monkeypatch):
    monkeypatch.delenv("RUPSAA_ADAPTER_PATH", raising=False)
    monkeypatch.delenv("ADAPTER_PATH", raising=False)
    settings = Settings()
    assert settings.adapter_path == "adapters/rupsaa-v1"


def test_adapter_path_overridden_by_rupsaa_adapter_path_env(monkeypatch):
    monkeypatch.setenv("RUPSAA_ADAPTER_PATH", "adapters/rupsaa-v0.1")
    settings = Settings()
    assert settings.adapter_path == "adapters/rupsaa-v0.1"


def test_load_model_falls_back_to_base_when_adapter_missing(tmp_path):
    """If the configured adapter path doesn't exist, load_model must still
    return a usable (base-only) model rather than raising."""
    from rupsaa.model.loader import load_model

    fake_model = MagicMock()
    fake_tokenizer = MagicMock()
    fake_tokenizer.pad_token = "<pad>"

    missing_adapter = tmp_path / "adapters" / "does-not-exist"

    with patch("rupsaa.model.loader.AutoModelForCausalLM.from_pretrained", return_value=fake_model), \
         patch("rupsaa.model.loader.load_tokenizer", return_value=fake_tokenizer), \
         patch("rupsaa.model.loader.PeftModel.from_pretrained") as mock_peft:
        loaded = load_model(adapter_path=missing_adapter, use_adapter=True, device_map=None)

    mock_peft.assert_not_called()
    assert loaded.adapter_path is None
    assert loaded.model is fake_model


def test_load_model_attaches_adapter_when_present(tmp_path):
    """If the configured adapter path exists and is non-empty, load_model
    must attach it via PeftModel."""
    from rupsaa.model.loader import load_model

    adapter_dir = tmp_path / "adapters" / "rupsaa-v0.1"
    adapter_dir.mkdir(parents=True)
    (adapter_dir / "adapter_config.json").write_text("{}", encoding="utf-8")

    fake_base_model = MagicMock()
    fake_peft_model = MagicMock()
    fake_tokenizer = MagicMock()
    fake_tokenizer.pad_token = "<pad>"

    with patch("rupsaa.model.loader.AutoModelForCausalLM.from_pretrained", return_value=fake_base_model), \
         patch("rupsaa.model.loader.load_tokenizer", return_value=fake_tokenizer), \
         patch("rupsaa.model.loader.PeftModel.from_pretrained", return_value=fake_peft_model) as mock_peft:
        loaded = load_model(adapter_path=adapter_dir, use_adapter=True, device_map=None)

    mock_peft.assert_called_once()
    assert loaded.adapter_path == str(adapter_dir)
    assert loaded.model is fake_peft_model


# --- Training config validation ---

def test_rupsaa_v01_qlora_config_loads_and_is_well_formed():
    cfg = load_training_config("configs/training/rupsaa_v0.1_qlora.yaml")
    assert cfg["data"]["train_path"] == "data/production/exports/rupsaa_v0.1/train.jsonl"
    assert cfg["data"]["validation_path"] == "data/production/exports/rupsaa_v0.1/validation.jsonl"
    assert "test.jsonl" not in cfg["data"].values()  # held-out test must never be referenced here
    assert cfg["lora"]["r"] > 0
    assert cfg["training"]["final_adapter_dir"] == "adapters/rupsaa-v0.1"
    assert cfg["seed"] == 42


def test_default_training_config_unaffected_by_v01_config():
    """Loading the versioned V0.1 config must not change what the default
    (unqualified) training config resolves to."""
    default_cfg = load_training_config()
    assert default_cfg["data"]["train_path"] == "data/train.jsonl"
    assert default_cfg["training"]["final_adapter_dir"] == "adapters/rupsaa-v1"


# --- LLaMA-Factory WebUI "Load arguments" config ---

WEBUI_TEMPLATE = PROJECT_ROOT / "configs/training/llamafactory_webui_rupsaa_v0.1.yaml"


def _llamafactory_available() -> bool:
    try:
        import llamafactory.webui.common  # noqa: F401
        return True
    except Exception:
        return False


def test_llamafactory_dataset_info_registers_frozen_splits():
    info = json.loads((PROJECT_ROOT / "data/dataset_info.json").read_text(encoding="utf-8"))
    for name, split in [("rupsaa_v0.1_train", "train"), ("rupsaa_v0.1_validation", "validation"), ("rupsaa_v0.1_test", "test")]:
        assert info[name]["file_name"] == f"production/exports/rupsaa_v0.1/{split}.jsonl"
        assert info[name]["formatting"] == "sharegpt"


@pytest.mark.skipif(not _llamafactory_available(), reason="llamafactory not installed")
def test_webui_config_template_loads_through_llamafactory(tmp_path, monkeypatch):
    """Render the template the way scripts/start_llamafactory_gui.sh does and
    load it through LLaMA-Factory's own WebUI load_args + component registry."""
    import os

    monkeypatch.setenv("GRADIO_ANALYTICS_ENABLED", "False")
    import gradio as gr
    from llamafactory.webui.common import load_args
    from llamafactory.webui.components import create_top, create_train_tab
    from llamafactory.webui.engine import Engine

    fake_root = str(tmp_path)
    (tmp_path / "config").mkdir()
    rendered = WEBUI_TEMPLATE.read_text(encoding="utf-8").replace("@RUPSAA_ROOT@", fake_root)
    (tmp_path / "config" / "rupsaa_v0.1.yaml").write_text(rendered, encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    cfg = load_args("rupsaa_v0.1.yaml")
    assert cfg is not None

    engine = Engine(pure_chat=False)
    with gr.Blocks():
        engine.manager.add_elems("top", create_top())
        engine.manager.add_elems("train", create_train_tab(engine))
    for elem_id in cfg:
        engine.manager.get_elem_by_id(elem_id)  # KeyError if not a real WebUI component

    assert cfg["top.model_path"] == "Qwen/Qwen2.5-7B-Instruct"
    assert cfg["top.template"] == "qwen"
    assert cfg["top.quantization_bit"] == "4"
    assert cfg["train.dataset"] == ["rupsaa_v0.1_train"]
    assert cfg["train.cutoff_len"] == 2048
    assert float(cfg["train.learning_rate"]) == 2e-4
    assert float(cfg["train.num_train_epochs"]) == 3.0
    assert (cfg["train.batch_size"], cfg["train.gradient_accumulation_steps"]) == (2, 8)
    assert (cfg["train.lora_rank"], cfg["train.lora_alpha"], cfg["train.lora_dropout"]) == (16, 32, 0.05)
    # absolute output_dir so os.path.join("saves", model, method, output_dir) returns it unchanged
    assert cfg["train.output_dir"] == os.path.join(fake_root, "adapters", "rupsaa-v0.1")
    assert os.path.join("saves", "Custom", "lora", cfg["train.output_dir"]) == cfg["train.output_dir"]
