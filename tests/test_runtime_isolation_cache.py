"""Regression tests: Gemma serving fixes (bf16 load, end-of-turn stop), test/.env isolation,
and the terminology/dance cache same-timestamp race. No model is loaded."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import torch

from rupsaa.model.generation import stop_token_ids
from rupsaa.rag.dance import DanceStore
from rupsaa.rag.terminology import TerminologyStore

ROOT = Path(__file__).resolve().parent.parent


# --- runtime fixes ------------------------------------------------------------------------------

class FakeTok:
    def __init__(self, eos_id: int, vocab: dict[str, int]):
        self.eos_token_id, self.unk_token_id, self.vocab = eos_id, 3, vocab

    def convert_tokens_to_ids(self, tok: str) -> int:
        return self.vocab.get(tok, self.unk_token_id)


def test_gemma_stops_on_end_of_turn_as_well_as_eos():
    tok = FakeTok(1, {"<eos>": 1, "<end_of_turn>": 106})
    model = SimpleNamespace(generation_config=SimpleNamespace(eos_token_id=[1, 106]))
    assert stop_token_ids(model, tok) == [1, 106]
    # even without a generation_config, the template's end-of-turn token is found
    assert stop_token_ids(SimpleNamespace(generation_config=None), tok) == [1, 106]


def test_qwen_stop_tokens_unchanged():
    tok = FakeTok(151645, {"<|im_end|>": 151645})
    assert stop_token_ids(SimpleNamespace(generation_config=SimpleNamespace(eos_token_id=151645)), tok) == [151645]


def test_quantized_load_always_passes_compute_dtype(tmp_path):
    from rupsaa.model import loader

    fake_tok = MagicMock(pad_token="<pad>")
    with patch.object(loader, "load_tokenizer", return_value=fake_tok), \
         patch.object(loader, "resolve_compute_dtype", return_value=torch.bfloat16), \
         patch.object(loader, "build_quantization_config", return_value=object()), \
         patch.object(loader.AutoModelForCausalLM, "from_pretrained", return_value=MagicMock()) as fp:
        loader.load_model(use_adapter=False, device_map=None)
    assert fp.call_args.kwargs["torch_dtype"] is torch.bfloat16  # fp16 default gave Gemma 3 NaN logits


# --- test / .env isolation ---------------------------------------------------------------------------

def test_tests_never_read_the_project_env_file():
    from rupsaa import config

    assert config.ENV_FILE is None
    s = config.Settings()
    assert s.owner_api_key == "" and s.model_id is None and not s.is_production


def test_explicit_env_file_is_still_honoured(tmp_path):
    env = tmp_path / "prod.env"
    env.write_text("RUPSAA_ENV=production\nRUPSAA_MODEL_PATH=google/gemma-3-12b-it\n", encoding="utf-8")
    code = ("from rupsaa.config import Settings; s = Settings(); "
            "print(s.is_production, s.model_id)")
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True,
                       env={**os.environ, "RUPSAA_ENV_FILE": str(env)})
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["True", "google/gemma-3-12b-it"]


# --- cache invalidation race ------------------------------------------------------------------------------

def test_terminology_update_is_never_served_stale():
    import tempfile

    for _ in range(40):  # the old float-mtime cache failed this intermittently
        with tempfile.TemporaryDirectory() as d:
            store = TerminologyStore(Path(d))
            rec = store.create({"term": "Strip", "definition": "Removing clothing."})
            assert store.lookup("strip mane ki?", "strip")
            store.update(rec.id, {"enabled": False})
            assert store.lookup("strip mane ki?", "strip") == []
            store.update(rec.id, {"enabled": True, "definition": "Taking clothes off."})
            assert store.list()[0].definition == "Taking clothes off."


def test_external_same_timestamp_rewrite_is_detected(tmp_path):
    store = TerminologyStore(tmp_path)
    rec = store.create({"term": "Strip", "definition": "AAAA"})
    path = tmp_path / f"{rec.id}.json"
    assert store.list()[0].definition == "AAAA"
    before = path.stat()
    data = json.loads(path.read_text(encoding="utf-8"))
    data["definition"] = "BBBB"  # same length → same size
    tmp = path.with_suffix(".edit")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))  # identical mtime, as in a same-tick write
    assert store.list()[0].definition == "BBBB"


def test_dance_store_delete_and_update_invalidate(tmp_path):
    store = DanceStore(tmp_path)
    rec = store.create({"name": "Kathak", "origin": "North India", "description": "Classical dance."})
    assert [r.id for r in store.list()] == [rec.id]
    store.update(rec.id, {"enabled": False})
    assert store.list(include_disabled=False) == []
    store.delete(rec.id, confirm=True)
    assert store.list() == []
