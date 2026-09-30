#!/usr/bin/env python3
"""Release record + (optional) Hugging Face upload for the FINAL Gemma adapter (rupsaa-v0.3-gemma3-final).

    python scripts/release_gemma_final.py prepare            # write release/rupsaa-v0.3-gemma3-final/ (no network)
    python scripts/release_gemma_final.py upload             # dry run: shows repo, visibility, files
    python scripts/release_gemma_final.py upload --yes       # actually upload + tag + verify remote sha256

Same conventions as scripts/release_model.py (which is LLaMA-Factory/Qwen-specific): one release = one subfolder
of the configured HF repo + one HF tag; a published release is never overwritten; the uploaded weights are verified
against the local sha256; the release record (manifest.json + checksums.sha256) is what scripts/fetch_adapter.py
uses to restore the adapter. Only the adapter is published — never Gemma base weights, checkpoints, optimizer
state or the dataset. The script never creates repos and never changes visibility.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rupsaa.config import PROJECT_ROOT  # noqa: E402
from rupsaa.release import read_checksums, sha256_file, write_checksums  # noqa: E402

NAME = "rupsaa-v0.3-gemma3-final"
ADAPTER = PROJECT_ROOT / "adapters" / NAME
OUT = PROJECT_ROOT / "release" / NAME
BASE = "google/gemma-3-12b-it"
ADAPTER_SHA = "3c79e394578261cdb04033867a9d6a96bb20784d5b0fc9d78d20e1b057724f05"
DATASET = "rupsaa_v0.3_final"
DATASET_DIR = PROJECT_ROOT / "data/production/exports" / DATASET
DATASET_SHA = "6eedeb105c5ebd069d59aca751a4df849767a192ad96944c6de79fbe87fbdc69"
DATASET_FILES = ["train.jsonl", "validation.jsonl", "test.jsonl", "corrective_holdout.jsonl", "dance_holdout.jsonl"]
PUBLISH = ["adapter_model.safetensors", "adapter_config.json", "train_summary.json"]  # tokenizer = base model's


def dataset_sha() -> str:
    import hashlib
    lines = "".join(f"{sha256_file(DATASET_DIR / f)}  {f}\n" for f in DATASET_FILES)
    return hashlib.sha256(lines.encode()).hexdigest()


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=PROJECT_ROOT, capture_output=True, text=True).stdout.strip()


def model_card(m: dict) -> str:
    t = m["training"]
    return f"""---
base_model: {BASE}
library_name: peft
pipeline_tag: text-generation
license: gemma
tags: [lora, qlora, peft, sft, gemma3, bengali, banglish, not-for-all-audiences]
language: [bn, en]
---

# Rupsaa — final Gemma 3 12B LoRA adapter (`{NAME}`)

Rupsaa is a multilingual (Bengali / Banglish / English) conversational companion. **This folder holds only the
LoRA adapter.** The base model `{BASE}` is **not included** — obtain it separately from Hugging Face after
accepting Google's Gemma terms. The application (FastAPI, web UI, RAG knowledge, routing, memory) is in the
Rupsaa GitHub repository.

Gemma is provided under and subject to the Gemma Terms of Use found at ai.google.dev/gemma/terms. This adapter is a
Gemma derivative and its use must comply with those terms and the Gemma Prohibited Use Policy.

| | |
|---|---|
| Base model | `{BASE}` (not included; gated — accept the Gemma license) |
| Adapter SHA-256 | `{m['adapter']['adapter_model_sha256']}` ({m['adapter']['adapter_model_bytes']:,} bytes) |
| Method | SFT + QLoRA: 4-bit NF4 + double quant, bf16 compute; LoRA r{t['lora_rank']} / α{t['lora_alpha']} / dropout {t['lora_dropout']} on q,k,v,o,gate,up,down of the language model |
| Training | {t['epochs']} epochs, LR {t['learning_rate']} cosine, effective batch {t['effective_batch']}, {t['steps']} steps; eval loss {t['eval_loss_first']} → {t['eval_loss_last']} |
| Selected checkpoint | final adapter (step {t['steps']}) |
| Dataset | `{DATASET}` — {m['dataset']['conversations']} conversations (not published) |
| Dataset SHA-256 | `{DATASET_SHA}` |
| Prompt version | `v0.2` persona prompt + runtime blocks (terminology / dance / recall / language directive) |
| Serving notes | enabled in production (identity + conversational style; `RUPSAA_SERVING_NOTES=0` disables) |
| Recommended generation | temperature 0.55, top-p 0.9, top-k 50, repetition penalty 1.1 |

## Inference requirements
- transformers ≥ 4.57 (Gemma 3), peft 0.21, bitsandbytes; the Rupsaa app runs it with `PYTHONPATH=.gemma_stack`.
- Load with an explicit bf16 compute dtype (fp16 gives NaN logits with Gemma 3).
- Stop generation on `<end_of_turn>` as well as `<eos>`.
- Use the base model's tokenizer and chat template (unchanged); the system turn is folded into the first user turn.
- About 11.6 GB VRAM at 4-bit on an NVIDIA L4 (23 GB).

## Load
```python
import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
                         bnb_4bit_compute_dtype=torch.bfloat16)
tok = AutoTokenizer.from_pretrained("{BASE}")
base = AutoModelForCausalLM.from_pretrained("{BASE}", quantization_config=bnb, torch_dtype=torch.bfloat16,
                                            device_map="auto")
model = PeftModel.from_pretrained(base, "<repo>", subfolder="{NAME}", revision="{NAME}")
```

## Files
`adapter_model.safetensors`, `adapter_config.json`, `train_summary.json` (training metrics), `manifest.json`,
`checksums.sha256`. Checkpoints, optimizer state, base weights and training data are intentionally not published.

## Known limitations
- Occasional awkward Banglish phrasing; a trained tendency to answer shared preferences with a question.
- Base-model identity can leak without the serving notes (e.g. "created by Google").
- Facts about dances/terminology come from the app's RAG records, not from the adapter.
"""


def cmd_prepare(_args) -> None:
    got = sha256_file(ADAPTER / "adapter_model.safetensors")
    if got != ADAPTER_SHA:
        sys.exit(f"REFUSING: adapter sha256 {got} != expected {ADAPTER_SHA}")
    if dataset_sha() != DATASET_SHA:
        sys.exit("REFUSING: dataset files do not hash to the frozen rupsaa_v0.3_final sha256")
    cfg = json.loads((ADAPTER / "adapter_config.json").read_text(encoding="utf-8"))
    if cfg.get("base_model_name_or_path") != BASE or cfg.get("peft_type") != "LORA":
        sys.exit("REFUSING: adapter_config.json does not describe a LoRA on " + BASE)
    summary = json.loads((ADAPTER / "train_summary.json").read_text(encoding="utf-8"))
    if summary.get("dataset_sha256") != DATASET_SHA:
        sys.exit("REFUSING: train_summary.json was not trained on rupsaa_v0.3_final")
    evals = [x for x in summary["log_history"] if "eval_loss" in x]
    steps = max(x.get("step", 0) for x in summary["log_history"])
    perf = summary.get("perf", {})
    manifest = {
        "release_name": NAME, "created_at": datetime.now(timezone.utc).isoformat(), "base_model_id": BASE,
        "code": {"git_commit": git("rev-parse", "HEAD"), "git_remote": git("remote", "get-url", "origin")},
        "adapter": {"local_path": f"adapters/{NAME}", "adapter_model_sha256": got,
                    "adapter_model_bytes": (ADAPTER / "adapter_model.safetensors").stat().st_size,
                    "adapter_config_sha256": sha256_file(ADAPTER / "adapter_config.json"), "peft_type": "LORA",
                    "target_modules": cfg.get("target_modules"), "published_files": PUBLISH},
        "training": {"script": "scripts/gemma_train_qlora.py", "lora_rank": cfg["r"], "lora_alpha": cfg["lora_alpha"],
                     "lora_dropout": cfg["lora_dropout"], "quantization": "4-bit NF4 + double quant, bf16 compute",
                     "learning_rate": 1e-4, "epochs": 2, "steps": steps,
                     "micro_batch": perf.get("micro_batch"), "grad_accum": perf.get("grad_accum"),
                     "effective_batch": (perf.get("micro_batch") or 0) * (perf.get("grad_accum") or 0),
                     "cutoff": 2048, "gpu": perf.get("gpu"), "train_loss": summary["metrics"].get("train_loss"),
                     "eval_loss_first": round(evals[0]["eval_loss"], 3), "eval_loss_last": round(evals[-1]["eval_loss"], 3),
                     "train_examples": summary["train_examples"], "eval_examples": summary["eval_examples"]},
        "dataset": {"version": DATASET, "sha256": DATASET_SHA,
                    "sha256_definition": "sha256 of the lines '<sha256>  <file>\\n' for " + ", ".join(DATASET_FILES),
                    "conversations": sum(1 for _ in open(DATASET_DIR / "train.jsonl", encoding="utf-8")),
                    "export_dir": f"data/production/exports/{DATASET}", "files": DATASET_FILES,
                    "location": f"data/production/exports/{DATASET}/ (GitHub repository); not uploaded to Hugging Face"},
        "serving": {"prompt_version": "v0.2", "serving_notes": "enabled (RUPSAA_SERVING_NOTES=1)",
                    "temperature": 0.55, "top_p": 0.9, "top_k": 50, "repetition_penalty": 1.1,
                    "python_env": "PYTHONPATH=.gemma_stack (transformers 4.57.x)",
                    "fixes": ["bf16 compute dtype for quantized Gemma", "stop on <end_of_turn>"]},
        "huggingface": {"repo_id": (yaml.safe_load((PROJECT_ROOT / "configs/release.yaml").read_text()) or {}).get("hf_repo_id"),
                        "subfolder": NAME, "revision": NAME, "uploaded": False},
    }
    prev = OUT / "manifest.json"
    if prev.exists():
        old = json.loads(prev.read_text(encoding="utf-8"))
        if old["adapter"]["adapter_model_sha256"] != got:
            sys.exit("REFUSING: an existing release record describes a different adapter")
        if old["huggingface"].get("uploaded"):
            manifest["huggingface"] = old["huggingface"]
    OUT.mkdir(parents=True, exist_ok=True)
    prev.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_checksums([ADAPTER / f for f in PUBLISH] + [DATASET_DIR / f for f in DATASET_FILES]
                    + [DATASET_DIR / "V03_FINAL_MANIFEST.json"], OUT / "checksums.sha256")
    (OUT / "MODEL_CARD.md").write_text(model_card(manifest), encoding="utf-8")
    print(f"release record: {OUT.relative_to(PROJECT_ROOT)}/  adapter {got}  dataset {DATASET_SHA}")


def cmd_upload(args) -> None:
    from huggingface_hub import HfApi
    m = json.loads((OUT / "manifest.json").read_text(encoding="utf-8"))
    if sha256_file(ADAPTER / "adapter_model.safetensors") != m["adapter"]["adapter_model_sha256"]:
        sys.exit("REFUSING: local adapter no longer matches the release record")
    repo, sub, rev = m["huggingface"]["repo_id"], m["huggingface"]["subfolder"], m["huggingface"]["revision"]
    api = HfApi()
    info = api.model_info(repo)
    if rev in {t.name for t in api.list_repo_refs(repo).tags} or any(f.startswith(sub + "/") for f in api.list_repo_files(repo)):
        sys.exit(f"REFUSING: {repo} already has {sub}/ or tag {rev} — releases are never overwritten")
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp) / sub
        stage.mkdir()
        for f in PUBLISH:
            shutil.copy2(ADAPTER / f, stage / f)
        shutil.copy2(OUT / "manifest.json", stage / "manifest.json")
        shutil.copy2(OUT / "MODEL_CARD.md", stage / "README.md")
        (stage / "checksums.sha256").write_text("".join(f"{sha256_file(stage / f)}  {f}\n" for f in PUBLISH))
        for p in stage.iterdir():
            if any(x in p.name.lower() for x in (".env", "optimizer", "checkpoint", ".bin", ".pt", "token")):
                sys.exit(f"REFUSING: forbidden file staged: {p.name}")
        size = sum(p.stat().st_size for p in stage.iterdir()) / 1e6
        print(f"Repo: {repo}  (private={info.private}; visibility unchanged)\nDestination: {sub}/ then tag {rev}\n"
              f"Files ({size:.1f} MB): {', '.join(sorted(p.name for p in stage.iterdir()))}")
        if not args.yes:
            print("Dry run only — nothing uploaded. Re-run with --yes to publish.")
            return
        api.upload_folder(repo_id=repo, folder_path=str(stage), path_in_repo=sub, commit_message=f"Add {NAME} LoRA adapter")
        api.create_tag(repo, tag=rev, tag_message=f"{NAME} adapter release")
    remote = api.get_paths_info(repo, [f"{sub}/adapter_model.safetensors"], revision=rev, expand=True)[0]
    if remote.lfs.sha256 != m["adapter"]["adapter_model_sha256"]:
        sys.exit(f"UPLOAD VERIFICATION FAILED: remote {remote.lfs.sha256}")
    m["huggingface"].update({"uploaded": True, "verified_remote_sha256": remote.lfs.sha256})
    (OUT / "manifest.json").write_text(json.dumps(m, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"uploaded and verified: https://huggingface.co/{repo}/tree/{rev}/{sub}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("prepare")
    up = sub.add_parser("upload")
    up.add_argument("--yes", action="store_true")
    args = ap.parse_args()
    {"prepare": cmd_prepare, "upload": cmd_upload}[args.cmd](args)


if __name__ == "__main__":
    main()
