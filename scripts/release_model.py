#!/usr/bin/env python3
"""Build and (optionally) publish a Rupsaa LoRA adapter release.

    # 1. Build/refresh the local release record (manifest, checksums, model card). No network.
    python scripts/release_model.py prepare v0.1 adapters/rupsaa-v0.1

    # 2. Show exactly what would be uploaded (no upload).
    python scripts/release_model.py upload v0.1 --repo <hf-user>/rupsaa

    # 3. Actually upload — needs `hf auth login` first and an explicit --yes.
    python scripts/release_model.py upload v0.1 --repo <hf-user>/rupsaa --yes

Future versions use the same commands (e.g. `prepare v0.2 adapters/rupsaa-v0.2`).

Safety rules enforced here:
  * only the adapter weights/config + small training metadata + model card +
    manifest/checksums are published — never checkpoints, optimizer state,
    pickled training args, base-model weights, caches or credentials
  * each release goes to its own subfolder (rupsaa-vX) AND gets its own HF
    tag, so a new version can never overwrite an older one
  * an existing release (same subfolder or tag on the Hub, or a local release
    record with a DIFFERENT adapter checksum) is never overwritten
  * the repo must already exist — this script never creates a repo or changes
    its visibility
  * nothing is uploaded without --yes
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml  # noqa: E402

from rupsaa.config import PROJECT_ROOT  # noqa: E402
from rupsaa.release import (  # noqa: E402
    ADAPTER_OPTIONAL_FILES,
    ADAPTER_REQUIRED_FILES,
    RELEASES_DIR,
    build_manifest,
    read_checksums,
    sha256_file,
    snapshot_dataset_sha256,
    write_checksums,
)

RELEASE_CONFIG = PROJECT_ROOT / "configs/release.yaml"

# Per-version facts that can't be derived from files. Add an entry per release.
VERSION_INFO = {
    "v0.1": {
        "dataset": {
            "version": "rupsaa_v0.1",
            "snapshot_dir": "data/production/snapshots/rupsaa_v0.1_training",
            "snapshot_manifest": "data/production/snapshots/rupsaa_v0.1_training/V01_TRAINING_MANIFEST.json",
            "export_dir": "data/production/exports/rupsaa_v0.1",
            "expected_sha256": "2df533999559d5f873be9e5dc5350812e874dd18c8e4017741f5b8c18666fa2a",
            "storage": "Versioned in the GitHub repository (snapshot records + exported splits); "
                       "NOT uploaded to Hugging Face.",
        },
        "training_configs": [
            "configs/training/llamafactory_webui_rupsaa_v0.1.yaml",
            "configs/training/llamafactory_rupsaa_v0.1.yaml",
            "configs/training/rupsaa_v0.1_qlora.yaml",
            "configs/model.yaml",
            "configs/inference.yaml",
            "data/dataset_info.json",
        ],
        "compatibility_notes": [
            "Loads with transformers 4.46.3 + peft 0.21.0 + bitsandbytes 0.50.2 on torch 2.8.0+cu128 (NVIDIA L4, 23 GB).",
            "Base model is downloaded from the Hub on first load (Qwen/Qwen2.5-7B-Instruct, ~15 GB); the adapter is never merged.",
            "Chat template: Qwen ChatML via tokenizer.apply_chat_template (LLaMA-Factory template 'qwen' in training).",
            "Top-level adapter = best-eval checkpoint (checkpoint-100 of 135 steps, load_best_model_at_end).",
            "Trained with system prompt 'You are Rupsaa.'; the app serves a longer persona prompt (see V0.2 preparation report).",
            "LLaMA-Factory 0.7.1 GUI needs scripts/setup_llamafactory.sh (pinned gradio 4.38.1 + two compatibility patches).",
        ],
        "limitations": [
            "Strong verbal tic: 'honestly'/'actually' in most replies (inherited from the V0.1 dataset; 863/1129 training replies).",
            "Bengali-script and Banglish replies are often incoherent or semantically wrong; English is the strongest language.",
            "Flirting can come out flat or dismissive.",
            "Occasional overclaiming of capabilities (browsing, live data).",
            "Held-out test loss 3.345 -> 1.515 vs base; this measures fit to the dataset style, not overall quality.",
            "18+ adult-oriented persona. Not a general-purpose assistant.",
        ],
        "eval_summary": "data/production/reports/rupsaa_v0.1_evaluation/HUMAN_REVIEW_V01_VS_BASE.md",
    },
    "v0.2": {
        "dataset": {
            "version": "rupsaa_v0.2",
            "snapshot_dir": "data/production/snapshots/rupsaa_v0.2_training",
            "snapshot_manifest": "data/production/snapshots/rupsaa_v0.2_training/V02_TRAINING_MANIFEST.json",
            "export_dir": "data/production/exports/rupsaa_v0.2",
            # V0.2 identity = sha256 of the frozen records file (see V02_TRAINING_MANIFEST.json).
            "sha256_file": "data/production/snapshots/rupsaa_v0.2_training/frozen_records.jsonl",
            "sha256_definition": "sha256 of snapshots/rupsaa_v0.2_training/frozen_records.jsonl (one sorted-key JSON "
                                 "object per record, sorted by id, including split and frozen messages)",
            "expected_sha256": "96e0125e39ab2754c8540a29b6d3fee0a3132d46ae72adb9a4c3c7dcd067da33",
            "storage": "Versioned in the GitHub repository (frozen records + exported splits); NOT uploaded to Hugging Face.",
        },
        "training_configs": [
            "configs/training/llamafactory_webui_rupsaa_v0.2.yaml",
            "configs/training/llamafactory_rupsaa_v0.2.yaml",
            "configs/model.yaml",
            "configs/inference.yaml",
            "data/dataset_info.json",
            "rupsaa/personality/system_prompt_v02.py",
        ],
        "compatibility_notes": [
            "Loads with transformers 4.46.3 + peft 0.21.0 + bitsandbytes 0.50.2 on torch 2.8.0+cu128 (NVIDIA L4, 23 GB).",
            "Base model is downloaded from the Hub on first load (Qwen/Qwen2.5-7B-Instruct, ~15 GB); the adapter is never merged.",
            "Chat template: Qwen ChatML via tokenizer.apply_chat_template (LLaMA-Factory template 'qwen' in training).",
            "Top-level adapter = best-eval checkpoint (checkpoint-160 of 164 steps, load_best_model_at_end).",
            "Train-as-serve: trained with the exact app system prompt V02_SYSTEM_PROMPT "
            "(rupsaa/personality/system_prompt_v02.py); serve with RUPSAA_PROMPT_VERSION=v0.2.",
        ],
        "limitations": [
            "Banglish and Bengali-script definitions are often semantically garbled or ungrammatical (post-training eval).",
            "'এটা বাংলায় বুঝিয়ে বলো' follow-ups often stay in Banglish instead of Bengali script.",
            "Weak recall for 'ami age ki bolechilam?'-style questions about earlier turns.",
            "English is the strongest language; the V0.1 'honestly'/'actually' tic is gone (0 of 89 replies).",
            "18+ adult-oriented persona. Not a general-purpose assistant.",
        ],
        "eval_summary": "data/production/reports/rupsaa_v0.2_posttraining/POSTTRAINING_REPORT.md",
        "serve_command": "bash scripts/start_rupsaa_v02.sh",
        "example_system_literal": "V02_SYSTEM_PROMPT",  # defined in rupsaa/personality/system_prompt_v02.py
    },
}


def load_release_config() -> dict:
    return yaml.safe_load(RELEASE_CONFIG.read_text(encoding="utf-8")) or {}


def release_name(version: str) -> str:
    return f"rupsaa-{version}"


def validate_adapter(adapter_dir: Path) -> list[str]:
    problems = []
    if not adapter_dir.is_dir():
        return [f"adapter directory not found: {adapter_dir}"]
    for f in ADAPTER_REQUIRED_FILES:
        if not (adapter_dir / f).is_file():
            problems.append(f"missing required file: {f}")
    if not problems:
        cfg = json.loads((adapter_dir / "adapter_config.json").read_text(encoding="utf-8"))
        if cfg.get("peft_type") != "LORA":
            problems.append(f"peft_type is {cfg.get('peft_type')!r}, expected LORA")
        if not cfg.get("base_model_name_or_path"):
            problems.append("adapter_config.json has no base_model_name_or_path")
        if (adapter_dir / "adapter_model.safetensors").stat().st_size > 2 * 1024**3:
            problems.append("adapter_model.safetensors > 2 GB — this looks like merged/base weights, not a LoRA adapter")
    return problems


def release_files(adapter_dir: Path) -> list[Path]:
    files = [adapter_dir / f for f in ADAPTER_REQUIRED_FILES]
    # Explicit whitelist: nothing else in the training dir can ever be selected.
    files += [adapter_dir / f for f in ADAPTER_OPTIONAL_FILES if (adapter_dir / f).is_file()]
    return files


def model_card(manifest: dict, version: str, repo: str | None) -> str:
    t, a, d = manifest["training"], manifest["adapter"], manifest["dataset"]
    info = VERSION_INFO[version]
    repo_ref = repo or "<your-hf-username>/rupsaa"
    sub = manifest["huggingface"]["subfolder"]
    rev = manifest["huggingface"]["revision"]
    res = t.get("results", {})
    fmt = lambda v: f"{v:.4g}" if isinstance(v, (int, float)) else "n/a"  # noqa: E731
    lim = "\n".join(f"- {x}" for x in manifest["known_limitations"])
    notes = "\n".join(f"- {x}" for x in manifest["compatibility_notes"])
    return f"""---
base_model: {manifest['base_model_id']}
library_name: peft
pipeline_tag: text-generation
tags:
- lora
- qlora
- peft
- sft
- llama-factory
- bengali
- banglish
- not-for-all-audiences
language:
- bn
- en
---

# Rupsaa {version.upper()} — LoRA adapter

Rupsaa is an 18+ multilingual (Bengali / Banglish / English / code-switched)
conversational companion. **This repository holds only the LoRA adapter**; it
must be attached to the base model below. The application (API, web UI,
knowledge/RAG, terminology, training and evaluation tooling) lives in the
Rupsaa GitHub repository, whose `setup_rupsaa.sh` downloads this adapter
automatically.

| | |
|---|---|
| Release | `{manifest['release_name']}` (HF tag `{rev}`, folder `{sub}/`) |
| Base model | [`{manifest['base_model_id']}`](https://huggingface.co/{manifest['base_model_id']}) (not included here) |
| Method | Supervised fine-tuning (SFT) + QLoRA, LLaMA-Factory 0.7.1 |
| Adapter type | LoRA (PEFT {a['peft_version']}) — never merged into the base |
| Quantization | {t['quantization']['training']} during training; 4-bit NF4 + double quant at inference |
| LoRA rank / alpha / dropout | {t['lora_rank']} / {t['lora_alpha']} / {t['lora_dropout']} |
| Target modules | {', '.join(t['target_modules'])} (all 7 attention + MLP projection types) |
| Training | {t['epochs']} epochs, LR {t['learning_rate']}, cosine, cutoff {t['cutoff_len']}, batch {t['per_device_batch_size']} × grad-acc {t['gradient_accumulation_steps']} |
| Selected checkpoint | best eval loss (`load_best_model_at_end`) |
| Train loss (mean) / eval loss | {fmt(res.get('train_loss'))} / {fmt(res.get('eval_loss'))} |
| Dataset | `{d['version']}` — {d['records']} approved conversations, splits {d['splits']} |
| Dataset SHA-256 | `{d['sha256']}` |
| Adapter SHA-256 | `{a['adapter_model_sha256']}` ({a['adapter_model_bytes']:,} bytes) |

## Load the adapter

```python
import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

base_id = "{manifest['base_model_id']}"
bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                         bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=torch.bfloat16)
tokenizer = AutoTokenizer.from_pretrained(base_id)
base = AutoModelForCausalLM.from_pretrained(base_id, quantization_config=bnb, device_map="auto")
model = PeftModel.from_pretrained(base, "{repo_ref}", subfolder="{sub}", revision="{rev}")
model.eval()

messages = [{{"role": "system", "content": {info.get("example_system_literal", '"You are Rupsaa."')}}}, {{"role": "user", "content": "kemon acho?"}}]
inputs = tokenizer.apply_chat_template(messages, add_generation_prompt=True, return_tensors="pt").to(model.device)
print(tokenizer.decode(model.generate(inputs, max_new_tokens=128)[0][inputs.shape[1]:], skip_special_tokens=True))
```

With the Rupsaa application:
`git clone <rupsaa repo> && cd rupsaa-ai && bash setup_rupsaa.sh && {info.get("serve_command", "bash scripts/start_rupsaa_v01.sh")}`.

## Files

- `{sub}/adapter_model.safetensors`, `{sub}/adapter_config.json` — the adapter
- `{sub}/trainer_*`, `*_results.json`, `training_*loss.png` — training metadata
- `{sub}/manifest.json` — full release manifest (code commit, environment, dataset identity)
- `{sub}/checksums.sha256` — SHA-256 of every published file

Intermediate checkpoints, optimizer state and base-model weights are intentionally not published.

## Known limitations

{lim}

## Compatibility

{notes}

## Intended use

Adult (18+) conversational companion research and product development by the
Rupsaa owner. Not intended for minors, for factual advice without retrieval
grounding, or as a general assistant. The application enforces essential hard
boundaries (e.g. anything sexual involving minors is refused before the model
is called).

License: not yet specified by the owner; the base model is released under its own license.
"""


def cmd_prepare(args) -> None:
    version = args.version
    if version not in VERSION_INFO:
        sys.exit(f"No VERSION_INFO entry for {version!r} — add one to scripts/release_model.py first.")
    info = VERSION_INFO[version]
    name = release_name(version)
    adapter_dir = (PROJECT_ROOT / args.adapter_dir).resolve()
    problems = validate_adapter(adapter_dir)
    if problems:
        sys.exit("Adapter validation failed:\n  " + "\n  ".join(problems))

    out_dir = RELEASES_DIR / name
    new_sha = sha256_file(adapter_dir / "adapter_model.safetensors")
    manifest_path = out_dir / "manifest.json"
    previous = None
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        if previous["adapter"]["adapter_model_sha256"] != new_sha:
            sys.exit(f"REFUSING: {manifest_path} records a DIFFERENT adapter "
                     f"({previous['adapter']['adapter_model_sha256'][:12]}… vs {new_sha[:12]}…). "
                     f"A published release is never silently replaced — use a new version number.")

    ds = info["dataset"]
    if ds.get("sha256_file"):
        path = PROJECT_ROOT / ds["sha256_file"]
        n, actual = sum(1 for _ in open(path, encoding="utf-8")), sha256_file(path)
    else:
        n, actual = snapshot_dataset_sha256(PROJECT_ROOT / ds["snapshot_dir"])
    if actual != ds["expected_sha256"]:
        sys.exit(f"Dataset identity mismatch: snapshot hashes to {actual}, expected {ds['expected_sha256']}")
    export_dir = PROJECT_ROOT / ds["export_dir"]
    splits = {s: sum(1 for _ in open(export_dir / f"{s}.jsonl", encoding="utf-8")) for s in ("train", "validation", "test")}

    cfg = load_release_config()
    rel_cfg = cfg.get("releases", {}).get(name, {})
    hf_repo = args.repo or cfg.get("hf_repo_id") or None
    dataset = {
        "version": ds["version"],
        "sha256": actual,
        "sha256_definition": ds.get("sha256_definition") or
                             "rupsaa.release.dataset_sha256: sorted json.dumps(record, sort_keys=True) lines of the "
                             "approved records, joined by '\\n', SHA-256 of UTF-8",
        "records": n,
        "splits": splits,
        "snapshot_manifest": ds["snapshot_manifest"],
        "export_dir": ds["export_dir"],
        "storage": ds["storage"],
    }
    manifest = build_manifest(
        release_name=name,
        release_version=version,
        adapter_dir=adapter_dir,
        hf_repo=hf_repo,
        hf_revision=rel_cfg.get("revision", name),
        hf_subfolder=rel_cfg.get("subfolder", name),
        dataset=dataset,
        training_config_paths=[PROJECT_ROOT / p for p in info["training_configs"]],
        compatibility_notes=info["compatibility_notes"],
        limitations=info["limitations"],
    )
    if previous and previous["huggingface"].get("uploaded"):
        manifest["huggingface"] = previous["huggingface"]  # keep the record of what was published
    manifest["evaluation"] = {"human_review": info["eval_summary"]}

    # A release dir may already hold the training-freeze checksums (release/rupsaa-v0.2): they must still
    # match, and they are carried into the release checksums rather than overwritten.
    freeze = {}
    if not previous and (out_dir / "checksums.sha256").exists():
        freeze = read_checksums(out_dir / "checksums.sha256")
        changed = [rel for rel, h in freeze.items() if sha256_file(PROJECT_ROOT / rel) != h]
        if changed:
            sys.exit("REFUSING: frozen training inputs changed since the freeze:\n  " + "\n  ".join(changed))

    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    checksum_targets = release_files(adapter_dir)
    checksum_targets += [export_dir / f"{s}.jsonl" for s in ("train", "validation", "test")]
    checksum_targets += [PROJECT_ROOT / ds["snapshot_manifest"]]
    if (PROJECT_ROOT / ds["snapshot_dir"] / "MANIFEST.json").exists():
        checksum_targets.append(PROJECT_ROOT / ds["snapshot_dir"] / "MANIFEST.json")
    checksum_targets += [PROJECT_ROOT / p for p in info["training_configs"]]
    checksum_targets += [PROJECT_ROOT / rel for rel in freeze]
    checksum_targets = list(dict.fromkeys(p.resolve() for p in checksum_targets))
    write_checksums(checksum_targets, out_dir / "checksums.sha256")
    (out_dir / "MODEL_CARD.md").write_text(model_card(manifest, version, hf_repo), encoding="utf-8")
    (out_dir / "UPLOAD_FILES.txt").write_text(
        "# Files published to Hugging Face for this release (relative to the adapter dir)\n"
        + "\n".join(p.name for p in release_files(adapter_dir))
        + "\nREADME.md  (from MODEL_CARD.md)\nmanifest.json\nchecksums.sha256  (adapter files only)\n",
        encoding="utf-8",
    )
    print(f"Release record written: {out_dir.relative_to(PROJECT_ROOT)}/")
    print(f"  adapter sha256 : {new_sha}")
    print(f"  dataset sha256 : {actual} ({n} records, splits {splits})")
    print(f"  HF target      : {hf_repo or '(not configured — set hf_repo_id in configs/release.yaml)'}"
          f" / {manifest['huggingface']['subfolder']} @ {manifest['huggingface']['revision']}")


def _staging(version: str, adapter_dir: Path, tmp: Path) -> Path:
    name = release_name(version)
    rel_dir = RELEASES_DIR / name
    stage = tmp / name
    stage.mkdir(parents=True)
    for f in release_files(adapter_dir):
        shutil.copy2(f, stage / f.name)
    shutil.copy2(rel_dir / "manifest.json", stage / "manifest.json")
    shutil.copy2(rel_dir / "MODEL_CARD.md", stage / "README.md")
    # Checksums of the adapter files as they sit in the HF subfolder.
    lines = [f"{sha256_file(stage / f.name)}  {f.name}\n" for f in release_files(adapter_dir)]
    (stage / "checksums.sha256").write_text("".join(lines), encoding="utf-8")
    for p in stage.iterdir():  # final guard
        low = p.name.lower()
        if any(pat in low for pat in (".bin", ".pt", ".pth", ".gguf", "optimizer", "checkpoint", ".env")):
            sys.exit(f"REFUSING: forbidden file staged for upload: {p.name}")
    return stage


def cmd_upload(args) -> None:
    from huggingface_hub import HfApi
    from huggingface_hub.utils import HfHubHTTPError

    version = args.version
    name = release_name(version)
    manifest_path = RELEASES_DIR / name / "manifest.json"
    if not manifest_path.exists():
        sys.exit(f"No local release record — run: python scripts/release_model.py prepare {version} <adapter_dir>")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    repo = args.repo or manifest["huggingface"].get("repo_id") or load_release_config().get("hf_repo_id")
    if not repo:
        sys.exit("No Hugging Face repo given. Pass --repo <user>/<name> or set hf_repo_id in configs/release.yaml.")
    subfolder, revision = manifest["huggingface"]["subfolder"], manifest["huggingface"]["revision"]
    adapter_dir = PROJECT_ROOT / manifest["adapter"]["local_path"]
    if sha256_file(adapter_dir / "adapter_model.safetensors") != manifest["adapter"]["adapter_model_sha256"]:
        sys.exit("REFUSING: local adapter no longer matches the release manifest.")

    api = HfApi()
    try:
        who = api.whoami()
    except Exception:
        sys.exit("Not logged in to Hugging Face. Run: hf auth login   (then re-run this command)")
    try:
        info = api.model_info(repo)
    except HfHubHTTPError:
        sys.exit(f"Repo {repo!r} not found or not accessible as {who.get('name')}. Create it on huggingface.co "
                 f"(Private recommended) — this script never creates repos or changes visibility.")
    existing = set(api.list_repo_files(repo))
    refs = api.list_repo_refs(repo)
    tags = {t.name for t in refs.tags}
    if revision in tags:
        sys.exit(f"REFUSING: tag {revision!r} already exists on {repo} — releases are never overwritten.")
    if any(f.startswith(subfolder + "/") for f in existing):
        sys.exit(f"REFUSING: {repo} already contains {subfolder}/ — releases are never overwritten.")

    with tempfile.TemporaryDirectory() as tmp:
        stage = _staging(version, adapter_dir, Path(tmp))
        files = sorted(p.name for p in stage.iterdir())
        total = sum(p.stat().st_size for p in stage.iterdir())
        print(f"Repo        : {repo} (private={info.private}; visibility is left unchanged)")
        print(f"Destination : {subfolder}/  then tag {revision!r}")
        print(f"Files ({total / 1e6:.1f} MB): " + ", ".join(files))
        root_readme = "README.md" not in existing
        print(f"Root README : {'will be created from this model card' if root_readme else 'exists — left unchanged'}")
        if not args.yes:
            print("\nDry run only. Re-run with --yes to upload.")
            return
        api.upload_folder(repo_id=repo, folder_path=str(stage), path_in_repo=subfolder,
                          commit_message=f"Add {name} LoRA adapter release")
        if root_readme:
            api.upload_file(repo_id=repo, path_or_fileobj=str(stage / "README.md"), path_in_repo="README.md",
                            commit_message=f"Add model card ({name})")
        api.create_tag(repo, tag=revision, tag_message=f"{name} adapter release")

    # Verify what landed on the Hub against local checksums (LFS sha256 for the weights).
    expected = read_checksums(RELEASES_DIR / name / "checksums.sha256")
    weights_rel = f"{manifest['adapter']['local_path']}/adapter_model.safetensors"
    remote = api.get_paths_info(repo, [f"{subfolder}/adapter_model.safetensors", f"{subfolder}/adapter_config.json"],
                                revision=revision, expand=True)
    by_path = {p.path: p for p in remote}
    lfs = getattr(by_path.get(f"{subfolder}/adapter_model.safetensors"), "lfs", None)
    remote_sha = getattr(lfs, "sha256", None) if lfs else None
    if remote_sha != expected[weights_rel]:
        sys.exit(f"UPLOAD VERIFICATION FAILED: remote adapter sha256 {remote_sha} != {expected[weights_rel]}")
    manifest["huggingface"].update({"repo_id": repo, "uploaded": True, "verified_remote_sha256": remote_sha})
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Uploaded and verified: https://huggingface.co/{repo}/tree/{revision}/{subfolder}")
    print("Commit the updated release/ record to git (scripts/sync_project.sh).")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("prepare", help="validate adapter, write release/<name>/ manifest + checksums + model card")
    sp.add_argument("version")
    sp.add_argument("adapter_dir")
    sp.add_argument("--repo", help="HF repo id to record (default: configs/release.yaml hf_repo_id)")
    sp.set_defaults(fn=cmd_prepare)
    sp = sub.add_parser("upload", help="publish a prepared release to Hugging Face (dry run unless --yes)")
    sp.add_argument("version")
    sp.add_argument("--repo")
    sp.add_argument("--yes", action="store_true", help="actually upload")
    sp.set_defaults(fn=cmd_upload)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
