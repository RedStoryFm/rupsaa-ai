"""Release / reproducibility helpers: checksums, dataset identity, environment
capture, release manifests.

Used by scripts/release_model.py (build + publish an adapter release),
scripts/fetch_adapter.py (restore an adapter and verify it), and
scripts/verify_installation.py (post-install checks). Pure standard library
+ the project's own modules — importing this never loads torch or a model.

Checksum files use the standard `sha256sum` format ("<hex>  <relative path>")
so they can also be checked with `sha256sum -c` from the project root.
"""

from __future__ import annotations

import hashlib
import importlib.metadata as md
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from rupsaa.config import PROJECT_ROOT

RELEASES_DIR = PROJECT_ROOT / "release"

# Files that make up a publishable LoRA adapter release. Anything else in the
# training output dir (checkpoints, optimizer/scheduler/rng state, pickled
# training_args.bin, full tokenizer copies, raw logs) is intentionally left out.
ADAPTER_REQUIRED_FILES = ["adapter_config.json", "adapter_model.safetensors"]
ADAPTER_OPTIONAL_FILES = [
    # training metadata / provenance (small, human-readable)
    "trainer_config.yaml",
    "all_results.json",
    "train_results.json",
    "eval_results.json",
    "trainer_state.json",
    "trainer_log.jsonl",
    "training_loss.png",
    "training_eval_loss.png",
]
# Never published, whatever the adapter dir contains.
FORBIDDEN_UPLOAD_PATTERNS = (
    "checkpoint-", "optimizer.pt", "scheduler.pt", "rng_state", "training_args.bin",
    ".bin", ".pt", ".pth", ".gguf", "model-0", "pytorch_model", ".env", "token",
)

KEY_PACKAGES = [
    "torch", "transformers", "peft", "accelerate", "bitsandbytes", "trl", "datasets",
    "sentence-transformers", "faiss-cpu", "safetensors", "tokenizers", "huggingface-hub",
    "fastapi", "uvicorn", "starlette", "pydantic", "pydantic-settings", "python-multipart",
    "gradio", "gradio_client", "llamafactory", "openpyxl", "numpy",
]


# --- hashing -----------------------------------------------------------------------------

def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


def dataset_sha256(records) -> str:
    """Canonical identity of an approved dataset (the definition used when
    Rupsaa V0.1 was frozen): every record serialized with sorted keys, the
    lines sorted, joined with newlines, SHA-256 of the UTF-8 bytes."""
    lines = sorted(json.dumps(json.loads(r.to_json()), sort_keys=True) for r in records)
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def snapshot_dataset_sha256(snapshot_dir: Path) -> tuple[int, str]:
    from rupsaa.dataset.schema import ConversationRecord

    records = [
        ConversationRecord.from_dict(json.loads(p.read_text(encoding="utf-8")))
        for p in sorted((snapshot_dir / "approved").glob("*.json"))
    ]
    return len(records), dataset_sha256(records)


def write_checksums(paths: list[Path], out_file: Path, root: Path = PROJECT_ROOT) -> dict[str, str]:
    entries = {}
    for p in paths:
        rel = p.resolve().relative_to(root.resolve()).as_posix()
        entries[rel] = sha256_file(p)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text("".join(f"{h}  {rel}\n" for rel, h in entries.items()), encoding="utf-8")
    return entries


def read_checksums(checksum_file: Path) -> dict[str, str]:
    out = {}
    for line in checksum_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        digest, rel = line.split(None, 1)
        out[rel.lstrip("*").strip()] = digest
    return out


def verify_checksums(checksum_file: Path, root: Path = PROJECT_ROOT, only_prefix: str | None = None) -> list[str]:
    """Returns a list of problems (empty = all good)."""
    problems = []
    for rel, expected in read_checksums(checksum_file).items():
        if only_prefix and not rel.startswith(only_prefix):
            continue
        path = root / rel
        if not path.is_file():
            problems.append(f"missing: {rel}")
        elif sha256_file(path) != expected:
            problems.append(f"checksum mismatch: {rel}")
    return problems


# --- environment ---------------------------------------------------------------------------

def _version(pkg: str) -> str | None:
    try:
        return md.version(pkg)
    except md.PackageNotFoundError:
        return None


def _run(cmd: list[str], cwd: Path = PROJECT_ROOT) -> str | None:
    try:
        return subprocess.check_output(cmd, cwd=cwd, text=True, stderr=subprocess.DEVNULL).strip() or None
    except Exception:
        return None


def environment_info() -> dict:
    """Versions only — never environment variables or anything secret."""
    info = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "packages": {p: _version(p) for p in KEY_PACKAGES},
    }
    try:
        import torch  # optional: absent on CPU-only helper machines

        info["torch_cuda"] = torch.version.cuda
        info["cuda_available"] = torch.cuda.is_available()
        info["gpu"] = torch.cuda.get_device_name(0) if torch.cuda.is_available() else None
    except Exception:
        info["torch_cuda"] = None
    smi = _run(["nvidia-smi", "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"])
    info["nvidia_smi"] = smi
    return info


def git_info() -> dict:
    return {
        "commit": _run(["git", "rev-parse", "HEAD"]),
        "branch": _run(["git", "rev-parse", "--abbrev-ref", "HEAD"]),
        "dirty": bool(_run(["git", "status", "--porcelain"])),
    }


# --- manifest ----------------------------------------------------------------------------------

def build_manifest(
    *,
    release_name: str,
    release_version: str,
    adapter_dir: Path,
    hf_repo: str | None,
    hf_revision: str | None,
    hf_subfolder: str | None,
    dataset: dict,
    training_config_paths: list[Path],
    compatibility_notes: list[str],
    limitations: list[str],
) -> dict:
    adapter_cfg = json.loads((adapter_dir / "adapter_config.json").read_text(encoding="utf-8"))
    weights = adapter_dir / "adapter_model.safetensors"
    trainer_cfg = {}
    tc_path = adapter_dir / "trainer_config.yaml"
    if tc_path.exists():
        import yaml

        trainer_cfg = yaml.safe_load(tc_path.read_text(encoding="utf-8")) or {}
    results = {}
    for name in ("train_results.json", "eval_results.json"):
        p = adapter_dir / name
        if p.exists():
            results.update(json.loads(p.read_text(encoding="utf-8")))
    try:
        from api.main import app  # FastAPI app version string

        app_version = app.version
    except Exception:
        app_version = None

    def rel(p: Path) -> str:
        try:
            return p.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
        except ValueError:
            return str(p)

    return {
        "manifest_schema": 1,
        "release_name": release_name,
        "release_version": release_version,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git": git_info(),
        "application_version": app_version,
        "base_model_id": adapter_cfg.get("base_model_name_or_path"),
        "huggingface": {
            "repo_id": hf_repo,
            "revision": hf_revision,
            "subfolder": hf_subfolder,
            "uploaded": False,
        },
        "adapter": {
            "local_path": rel(adapter_dir),
            "files": sorted(p.name for p in adapter_dir.iterdir() if p.is_file() and p.name in
                            ADAPTER_REQUIRED_FILES + ADAPTER_OPTIONAL_FILES),
            "adapter_model_sha256": sha256_file(weights),
            "adapter_model_bytes": weights.stat().st_size,
            "adapter_config_sha256": sha256_file(adapter_dir / "adapter_config.json"),
            "peft_type": adapter_cfg.get("peft_type"),
            "peft_version": adapter_cfg.get("peft_version"),
            "task_type": adapter_cfg.get("task_type"),
        },
        "training": {
            "method": "SFT + QLoRA (LLaMA-Factory)",
            "stage": trainer_cfg.get("stage"),
            "finetuning_type": trainer_cfg.get("finetuning_type"),
            "quantization": {
                "training": f"{trainer_cfg.get('quantization_bit', 4)}-bit NF4 (bitsandbytes), bf16 compute",
                "inference": "4-bit NF4, double quantization, bf16 compute (configs/model.yaml)",
            },
            "lora_rank": adapter_cfg.get("r"),
            "lora_alpha": adapter_cfg.get("lora_alpha"),
            "lora_dropout": adapter_cfg.get("lora_dropout"),
            "target_modules": sorted(adapter_cfg.get("target_modules") or []),
            "learning_rate": trainer_cfg.get("learning_rate"),
            "epochs": trainer_cfg.get("num_train_epochs"),
            "cutoff_len": trainer_cfg.get("cutoff_len"),
            "per_device_batch_size": trainer_cfg.get("per_device_train_batch_size"),
            "gradient_accumulation_steps": trainer_cfg.get("gradient_accumulation_steps"),
            "lr_scheduler": trainer_cfg.get("lr_scheduler_type"),
            "template": trainer_cfg.get("template"),
            "load_best_model_at_end": trainer_cfg.get("load_best_model_at_end"),
            "results": results,
            "config_files": [rel(p) for p in training_config_paths],
        },
        "dataset": dataset,
        "environment": environment_info(),
        "compatibility_notes": compatibility_notes,
        "known_limitations": limitations,
    }
