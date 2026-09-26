#!/usr/bin/env python3
"""Validate a Rupsaa production configuration WITHOUT starting anything or touching the GPU.

    RUPSAA_ENV=production python scripts/check_production_config.py [--json]

Reads the same settings as the API (.env + environment). Exit 0 = safe to start, 1 = problems.
Checks: production settings (owner key, adapter files, explicit CORS), adapter <-> base model
match, optional expected adapter SHA-256 (RUPSAA_ADAPTER_SHA256), prompt version, knowledge
stores readable, ports free, no Rupsaa server already running, and enough free GPU memory
(read via nvidia-smi — no CUDA context is created).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rupsaa.config import PROJECT_ROOT, get_settings, load_model_config  # noqa: E402

MIN_FREE_GPU_MIB = int(os.getenv("RUPSAA_MIN_FREE_GPU_MIB", "9000"))  # 7B 4-bit + KV cache headroom


def port_free(port: int) -> bool:
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(("0.0.0.0", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def gpu_free_mib() -> int | None:
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10).stdout.strip().splitlines()
        return int(out[0]) if out else None
    except Exception:
        return None


def running_rupsaa() -> list[str]:
    try:
        out = subprocess.run(["pgrep", "-af", "start_rupsaa.py|uvicorn api.main:app|web/dev_server.py"],
                             capture_output=True, text=True).stdout.splitlines()
    except FileNotFoundError:
        return []
    return [line for line in out if "pgrep" not in line and "check_production_config" not in line]


def check(skip_runtime: bool = False) -> dict:
    s = get_settings()
    problems, warnings, info = list(s.production_problems()) if s.is_production else [], [], {}
    if not s.is_production:
        warnings.append("RUPSAA_ENV is not 'production' — running this check against development settings")
        problems += s.production_problems()
    adapter = s.resolve_path(s.adapter_path)
    info["adapter"] = adapter.name
    info["base_model"] = load_model_config()["base_model_id"]
    cfg_path = adapter / "adapter_config.json"
    if cfg_path.is_file():
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        trained_on = cfg.get("base_model_name_or_path", "")
        if trained_on and Path(trained_on).name != Path(info["base_model"]).name:
            problems.append(f"adapter was trained on {trained_on!r} but the configured base model is {info['base_model']!r}")
        weights = adapter / "adapter_model.safetensors"
        if weights.is_file():
            info["adapter_sha256"] = hashlib.sha256(weights.read_bytes()).hexdigest()
            expected = os.getenv("RUPSAA_ADAPTER_SHA256", "").strip().lower()
            if expected and expected != info["adapter_sha256"]:
                problems.append(f"adapter sha256 {info['adapter_sha256'][:12]}… != RUPSAA_ADAPTER_SHA256 {expected[:12]}…")
            elif not expected:
                warnings.append("RUPSAA_ADAPTER_SHA256 not set — the exact adapter file is not pinned")
    from rupsaa.personality.system_prompt import PROMPT_VERSIONS, resolve_prompt_version
    try:
        info["prompt_version"] = resolve_prompt_version(str(adapter), s.prompt_version)
    except ValueError as e:
        problems.append(str(e))
    if s.prompt_version and s.prompt_version not in PROMPT_VERSIONS:
        problems.append(f"RUPSAA_PROMPT_VERSION {s.prompt_version!r} not in {PROMPT_VERSIONS}")
    from rupsaa.rag.dance import DanceStore
    from rupsaa.rag.terminology import TerminologyStore
    try:
        info["terminology_entries"] = len(TerminologyStore(s.resolve_path(s.knowledge_terminology_dir)).list())
        info["dance_entries"] = len(DanceStore(s.resolve_path(s.knowledge_dance_dir)).list())
    except Exception as e:  # corrupt JSON etc.
        problems.append(f"knowledge store unreadable: {type(e).__name__}: {e}")
    if s.is_production and s.api_host not in ("127.0.0.1", "localhost"):
        warnings.append(f"API_HOST={s.api_host}: the API is reachable directly, not only through the web proxy "
                        "(production launcher defaults to 127.0.0.1)")
    if os.getenv("RUPSAA_TRACE_FILE"):
        warnings.append("RUPSAA_TRACE_FILE is set — user messages are written to disk")
    if not skip_runtime:
        web_port = int(os.getenv("WEB_PORT", "5500"))
        for port in (s.api_port, web_port):
            if not port_free(port):
                problems.append(f"port {port} is already in use (another Rupsaa or service is running)")
        others = running_rupsaa()
        if others:
            problems.append("a Rupsaa server is already running: " + "; ".join(o.split(" ", 1)[0] for o in others))
        free = gpu_free_mib()
        info["gpu_free_mib"] = free
        if free is None:
            warnings.append("no GPU visible to nvidia-smi — the model would load on CPU (unusably slow)")
        elif free < MIN_FREE_GPU_MIB:
            problems.append(f"only {free} MiB GPU memory free (< {MIN_FREE_GPU_MIB}); is training or another model running?")
    return {"ok": not problems, "problems": problems, "warnings": warnings, "info": info}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--skip-runtime", action="store_true", help="skip port/process/GPU checks (config only)")
    args = ap.parse_args()
    result = check(skip_runtime=args.skip_runtime)
    if args.json:
        print(json.dumps(result, indent=1))
    else:
        for k, v in result["info"].items():
            print(f"  {k}: {v}")
        for w in result["warnings"]:
            print(f"  WARNING: {w}")
        for p in result["problems"]:
            print(f"  PROBLEM: {p}")
        print("CONFIG OK" if result["ok"] else "CONFIG NOT OK — fix the problems above")
    sys.exit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
