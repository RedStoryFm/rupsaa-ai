#!/usr/bin/env python3
"""Print a concise environment report for Rupsaa development.

Usage:
    python scripts/environment_check.py

Checks GPU/CUDA/driver, Python/PyTorch, key package versions, and whether
the base model configured in configs/model.yaml is reachable, without
downloading it.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rupsaa.config import load_model_config  # noqa: E402


def _run(cmd: list[str]) -> str | None:
    try:
        return subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return None


def check_gpu() -> None:
    print("=== GPU ===")
    if shutil.which("nvidia-smi") is None:
        print("nvidia-smi not found — no NVIDIA GPU driver detected.")
        return
    query = _run(
        [
            "nvidia-smi",
            "--query-gpu=name,memory.total,memory.used,driver_version,compute_cap",
            "--format=csv,noheader",
        ]
    )
    print(query or "Could not query GPU details.")


def check_python_and_torch() -> None:
    print("\n=== Python / PyTorch ===")
    print(f"Python: {platform.python_version()}")
    try:
        import torch

        print(f"torch: {torch.__version__}")
        print(f"CUDA available: {torch.cuda.is_available()}")
        if torch.cuda.is_available():
            print(f"CUDA (torch build): {torch.version.cuda}")
            print(f"Device: {torch.cuda.get_device_name(0)}")
            print(f"bf16 supported: {torch.cuda.is_bf16_supported()}")
            total_mem = torch.cuda.get_device_properties(0).total_memory / (1024**3)
            print(f"Total VRAM: {total_mem:.1f} GiB")
    except ImportError:
        print("torch not installed.")


def check_packages() -> None:
    print("\n=== Key packages ===")
    packages = [
        "transformers", "accelerate", "peft", "trl", "bitsandbytes",
        "datasets", "sentence_transformers", "faiss", "huggingface_hub",
        "fastapi", "uvicorn", "pydantic",
    ]
    for pkg in packages:
        try:
            mod = __import__(pkg)
            print(f"{pkg}: {getattr(mod, '__version__', 'unknown')}")
        except ImportError:
            print(f"{pkg}: NOT INSTALLED")


def check_system() -> None:
    print("\n=== System ===")
    total, used, free = shutil.disk_usage(Path(__file__).resolve().parent.parent)
    print(f"Disk free: {free / (1024**3):.1f} GiB / {total / (1024**3):.1f} GiB total")
    try:
        import os

        print(f"CPU count: {os.cpu_count()}")
    except Exception:
        pass


def check_model_config() -> None:
    print("\n=== Configured base model ===")
    cfg = load_model_config()
    print(f"base_model_id: {cfg['base_model_id']}")
    print(f"fallback_model_id: {cfg['fallback_model_id']}")
    print(f"4-bit quantization: {cfg['quantization']['load_in_4bit']}")


def main() -> None:
    check_gpu()
    check_python_and_torch()
    check_packages()
    check_system()
    check_model_config()


if __name__ == "__main__":
    main()
