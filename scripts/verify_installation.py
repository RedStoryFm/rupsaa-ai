#!/usr/bin/env python3
"""Verify a Rupsaa installation WITHOUT loading the 7B model.

    python scripts/verify_installation.py            # full check
    python scripts/verify_installation.py --no-adapter   # skip adapter checks (e.g. before download)

Checks: Python + key package imports, application modules, required
directories/files (API, web, launchers, configs), the release manifest and
checksums, the LoRA adapter (files, parseable config, checksums), the frozen
V0.1 dataset identity, knowledge documents, terminology storage and the RAG
index. Prints "RUPSAA INSTALLATION VERIFIED" or a list of failures and exits 1.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FAILS: list[str] = []
WARNS: list[str] = []


def ok(msg: str) -> None:
    print(f"  ok    {msg}")


def fail(msg: str) -> None:
    FAILS.append(msg)
    print(f"  FAIL  {msg}")


def warn(msg: str) -> None:
    WARNS.append(msg)
    print(f"  warn  {msg}")


def section(title: str) -> None:
    print(f"\n== {title}")


def check_python() -> None:
    section("Python / packages")
    v = sys.version_info
    (ok if (3, 10) <= v[:2] <= (3, 12) else warn)(f"Python {v.major}.{v.minor}.{v.micro} (known-good: 3.12)")
    expected = {  # known-working versions (configs/environment/rupsaa-v0.1-environment.txt)
        "transformers": "4.46.3", "peft": "0.21.0", "accelerate": "1.15.0", "bitsandbytes": "0.50.2",
        "sentence-transformers": "5.7.0", "faiss-cpu": "1.15.1", "fastapi": "0.141.1", "openpyxl": "3.1.5",
    }
    import importlib.metadata as md

    for pkg, want in expected.items():
        try:
            have = md.version(pkg)
        except md.PackageNotFoundError:
            fail(f"{pkg} not installed (want {want})")
            continue
        (ok if have == want else warn)(f"{pkg} {have}" + ("" if have == want else f" (known-good {want})"))
    for mod in ("torch", "yaml", "faiss", "multipart", "pypdf", "dotenv", "pydantic_settings", "uvicorn"):
        try:
            importlib.import_module(mod)
            ok(f"import {mod}")
        except Exception as e:
            fail(f"import {mod}: {e.__class__.__name__}: {e}")
    try:
        import torch

        if torch.cuda.is_available():
            ok(f"torch {torch.__version__}, CUDA {torch.version.cuda}, GPU {torch.cuda.get_device_name(0)}")
        else:
            warn(f"torch {torch.__version__} but no CUDA GPU visible — the 7B model needs an NVIDIA GPU (L4 23 GB known-good)")
    except Exception:
        pass


def check_app() -> None:
    section("Application modules")
    for mod in ("rupsaa.config", "rupsaa.model.loader", "rupsaa.model.inference", "rupsaa.rag.pipeline",
                "rupsaa.rag.router", "rupsaa.rag.terminology", "rupsaa.rag.terminology_import",
                "rupsaa.rag.context_builder", "rupsaa.dataset.diversity", "rupsaa.release", "api.main"):
        try:
            importlib.import_module(mod)
            ok(mod)
        except Exception as e:
            fail(f"{mod}: {e.__class__.__name__}: {e}")
    try:
        from api.main import app

        paths = set(app.openapi()["paths"])  # works across FastAPI router implementations
        for p in ("/health", "/model/info", "/chat", "/conversation/reset", "/owner/terminology",
                  "/owner/terminology/import/preview", "/owner/terminology/template.xlsx"):
            (ok if p in paths else fail)(f"route {p}")
    except Exception as e:
        fail(f"API routes: {e}")


def check_files() -> None:
    section("Files and directories")
    required = [
        "setup_rupsaa.sh", "start_rupsaa.py", "scripts/start_rupsaa_v01.sh", "scripts/setup_llamafactory.sh",
        "scripts/start_llamafactory_gui.sh", "scripts/fetch_adapter.py", "scripts/release_model.py",
        "api/main.py", "api/services.py", "api/owner_routes.py",
        "web/index.html", "web/app.js", "web/config.js", "web/dev_server.py", "web/knowledge.html",
        "web/knowledge.js", "web/terminology.js", "web/teach.html",
        "configs/model.yaml", "configs/inference.yaml", "configs/rag.yaml", "configs/dataset_production.yaml",
        "configs/release.yaml", "requirements.txt", "configs/environment/rupsaa-v0.1-environment.txt",
        "data/production/RUPSAA_VOICE_BIBLE_V1.md",
    ]
    for rel in required:
        (ok if (ROOT / rel).is_file() else fail)(rel)
    for rel in ("adapters", "knowledge/documents", "knowledge/index", "knowledge/terminology", "data/production"):
        (ok if (ROOT / rel).is_dir() else fail)(f"{rel}/")


def check_release(check_adapter: bool) -> None:
    import yaml

    from rupsaa.release import dataset_sha256, read_checksums, sha256_file

    section("Release manifest / adapter / dataset")
    cfg = yaml.safe_load((ROOT / "configs/release.yaml").read_text(encoding="utf-8"))
    name = cfg["current_release"]
    rel = cfg["releases"][name]
    manifest_path, checks_path = ROOT / rel["manifest"], ROOT / rel["checksums"]
    if not manifest_path.is_file() or not checks_path.is_file():
        fail(f"release record for {name} missing ({rel['manifest']}, {rel['checksums']})")
        return
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    ok(f"manifest {name}: base {manifest['base_model_id']}, LoRA r={manifest['training']['lora_rank']} "
       f"alpha={manifest['training']['lora_alpha']}")
    checks = read_checksums(checks_path)

    adapter_rel = os.environ.get("RUPSAA_ADAPTER_PATH") or rel["local_adapter_path"]
    adapter = Path(adapter_rel) if Path(adapter_rel).is_absolute() else ROOT / adapter_rel
    if check_adapter:
        cfg_file = adapter / "adapter_config.json"
        if not cfg_file.is_file():
            fail(f"adapter missing at {adapter} — run: python scripts/fetch_adapter.py")
        else:
            acfg = json.loads(cfg_file.read_text(encoding="utf-8"))
            (ok if acfg.get("peft_type") == "LORA" else fail)(f"adapter_config.json parses (peft_type={acfg.get('peft_type')})")
            (ok if acfg.get("base_model_name_or_path") == manifest["base_model_id"] else fail)(
                f"adapter base model {acfg.get('base_model_name_or_path')}")
            prefix = rel["local_adapter_path"].rstrip("/") + "/"
            for key, digest in checks.items():
                if key.startswith(prefix):
                    p = adapter / key[len(prefix):]
                    if not p.is_file():
                        fail(f"adapter file missing: {p.name}")
                    elif sha256_file(p) != digest:
                        fail(f"adapter checksum mismatch: {p.name}")
            if not any(f.startswith("adapter checksum") or f.startswith("adapter file") for f in FAILS):
                ok(f"adapter checksums ({sum(k.startswith(prefix) for k in checks)} files) — sha256 "
                   f"{manifest['adapter']['adapter_model_sha256'][:16]}…")
    else:
        warn("adapter checks skipped (--no-adapter)")

    for key, digest in checks.items():  # dataset exports + training configs
        if key.startswith(rel["local_adapter_path"]):
            continue
        p = ROOT / key
        if not p.is_file():
            fail(f"missing release file {key}")
        elif sha256_file(p) != digest:
            (fail if "exports/" in key or "snapshots/" in key else warn)(
                f"{key} differs from the {name} release record" + ("" if "exports/" in key or "snapshots/" in key
                                                                    else " (config edited since release)"))
    ds = manifest["dataset"]
    snap = ROOT / Path(ds["snapshot_manifest"]).parent / "approved"
    if snap.is_dir():
        from rupsaa.dataset.schema import ConversationRecord

        records = [ConversationRecord.from_dict(json.loads(p.read_text(encoding="utf-8"))) for p in snap.glob("*.json")]
        actual = dataset_sha256(records)
        (ok if actual == ds["sha256"] else fail)(f"frozen dataset {ds['version']}: {len(records)} records, sha256 {actual[:16]}…")
    else:
        fail(f"frozen dataset snapshot missing: {snap}")


def check_knowledge() -> None:
    section("Knowledge / terminology / RAG index")
    from rupsaa.config import get_settings, load_rag_config
    from rupsaa.rag.terminology import TerminologyStore

    s = get_settings()
    docs = [p for p in (ROOT / s.knowledge_docs_dir).iterdir() if p.is_file() and not p.name.startswith(".")]
    ok(f"knowledge documents: {len(docs)}")
    try:
        terms = TerminologyStore(ROOT / s.knowledge_terminology_dir).list()
        ok(f"terminology records: {len(terms)} (readable)")
    except Exception as e:
        fail(f"terminology store unreadable: {e}")
    vs = load_rag_config()["vector_store"]
    idx = ROOT / vs["index_dir"] / vs["index_filename"]
    (ok if idx.is_file() else warn)(f"RAG index {'present' if idx.is_file() else 'missing — run: python scripts/ingest_knowledge.py'}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-adapter", action="store_true")
    args = ap.parse_args()
    os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")
    print(f"Rupsaa installation check — {ROOT}")
    check_python()
    check_app()
    check_files()
    check_release(check_adapter=not args.no_adapter)
    check_knowledge()
    print()
    if FAILS:
        print(f"RUPSAA INSTALLATION NOT VERIFIED — {len(FAILS)} failure(s), {len(WARNS)} warning(s):")
        for f in FAILS:
            print(f"  - {f}")
        sys.exit(1)
    print(f"RUPSAA INSTALLATION VERIFIED ({len(WARNS)} warning(s))")


if __name__ == "__main__":
    main()
