#!/usr/bin/env python3
"""Final pre-training preflight for Rupsaa V0.2. Never trains, never loads model weights.

    python scripts/v02_preflight.py [--with-tests]

Runs, in order, and stops at nothing (it reports every result, exit 1 if any fail):
  1. frozen-state verification         scripts/v02_verify_frozen.py
  2. LLaMA-Factory data/config smoke   scripts/v02_pretrain_smoke.py (tokenizer only; all 1380 rows
                                       token-identical to the runtime prompt)
  3. train-as-we-serve by category     formatted samples: Banglish, Bengali, English, mixed,
                                       terminology, multi-turn/memory, follow-up; runtime prompt
                                       selection; V0.1 runtime prompt byte-identical to the
                                       pre-V0.2 commit
  4. CLI config values                 configs/training/llamafactory_rupsaa_v0.2.yaml
  5. GUI config                        render via the real launcher (dry run), load through
                                       LLaMA-Factory's own load_args, check nothing would reset
  6. no V0.2 config points at V0.1
  7. secret / large-file / forbidden-path audit   scripts/repo_audit.py
  8. output-directory safety           adapters/rupsaa-v0.2 absent or empty (anything else is moved
                                       aside to adapters/_preserved/, never deleted)
  9. (--with-tests) full pytest suite
Writes data/production/reports/rupsaa_v0.2_training/PREFLIGHT.{json,md}.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import shutil
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")

from rupsaa.dataset.config import PROJECT_ROOT  # noqa: E402

PY = sys.executable
REPORT_DIR = PROJECT_ROOT / "data/production/reports/rupsaa_v0.2_training"
FROZEN = PROJECT_ROOT / "data/production/snapshots/rupsaa_v0.2_training/frozen_records.jsonl"
CLI_CONFIG = PROJECT_ROOT / "configs/training/llamafactory_rupsaa_v0.2.yaml"
GUI_TEMPLATE = PROJECT_ROOT / "configs/training/llamafactory_webui_rupsaa_v0.2.yaml"
GUI_RENDERED = PROJECT_ROOT / "config/rupsaa_v0.2.yaml"
OUTPUT_DIR = PROJECT_ROOT / "adapters/rupsaa-v0.2"
V01_ADAPTER = PROJECT_ROOT / "adapters/rupsaa-v0.1"
PRE_V02_COMMIT = "4043342"
PROJECTIONS = "q_proj,k_proj,v_proj,o_proj,gate_proj,up_proj,down_proj"

EXPECTED_CLI = {
    "model_name_or_path": "Qwen/Qwen2.5-7B-Instruct", "template": "qwen", "stage": "sft", "finetuning_type": "lora",
    "quantization_bit": 4, "quantization_type": "nf4", "double_quantization": True, "bf16": True,
    "lora_rank": 16, "lora_alpha": 32, "lora_dropout": 0.05, "lora_target": PROJECTIONS,
    "cutoff_len": 2048, "per_device_train_batch_size": 2, "gradient_accumulation_steps": 8,
    "learning_rate": 2.0e-4, "num_train_epochs": 2.0, "lr_scheduler_type": "cosine", "optim": "paged_adamw_8bit",
    "max_grad_norm": 0.3, "save_steps": 20, "eval_steps": 20, "val_size": 0.05, "load_best_model_at_end": True,
    "metric_for_best_model": "eval_loss", "dataset": "rupsaa_v0.2_train", "output_dir": "adapters/rupsaa-v0.2",
}
EXPECTED_GUI = {
    "top.model_name": "Custom", "top.model_path": "Qwen/Qwen2.5-7B-Instruct", "top.finetuning_type": "lora",
    "top.quantization_bit": "4", "top.template": "qwen", "train.training_stage": "Supervised Fine-Tuning",
    "train.dataset_dir": "data", "train.dataset": ["rupsaa_v0.2_train"], "train.learning_rate": "2e-4",
    "train.num_train_epochs": "2.0", "train.max_grad_norm": "0.3", "train.compute_type": "bf16",
    "train.cutoff_len": 2048, "train.batch_size": 2, "train.gradient_accumulation_steps": 8, "train.val_size": 0.05,
    "train.lr_scheduler_type": "cosine", "train.save_steps": 20, "train.warmup_steps": 5,
    "train.optim": "paged_adamw_8bit", "train.lora_rank": 16, "train.lora_alpha": 32, "train.lora_dropout": 0.05,
    "train.lora_target": PROJECTIONS, "train.output_dir": str(OUTPUT_DIR),
}

RESULTS: dict[str, dict] = {}
SAMPLES: list[dict] = []


def check(name: str, ok: bool, detail) -> None:
    RESULTS[name] = {"pass": bool(ok), "detail": detail}
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}", flush=True)


def run(cmd: list[str], env: dict | None = None, timeout: int = 1800) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=timeout,
                          env={**os.environ, **(env or {})})


def step_frozen() -> None:
    p = run([PY, "scripts/v02_verify_frozen.py"])
    lines = [ln for ln in p.stdout.splitlines() if ln.startswith("[")]
    check("frozen_state", p.returncode == 0, f"{sum('[PASS]' in ln for ln in lines)}/{len(lines)} checks pass")


def step_smoke() -> None:
    p = run([PY, "scripts/v02_pretrain_smoke.py"], env={"HF_HUB_OFFLINE": "1"})
    summary = json.loads((REPORT_DIR / "smoke_check.json").read_text(encoding="utf-8"))
    ok = p.returncode == 0 and summary["all_passed"] and summary["optimizer_steps_run"] == 0
    check("llamafactory_smoke", ok, f"{sum(c['pass'] for c in summary['checks'].values())}/{len(summary['checks'])} "
          f"checks; {summary['counts']['total_steps']} steps; max {summary['counts']['max_tokens']} tokens; 0 optimizer steps")
    tok = summary["checks"]["prompt_tokens_identical_to_runtime"]
    check("train_as_serve_all_rows_token_identical", tok["pass"], tok["detail"])


def _old_system_prompt_module() -> dict:
    src = run(["git", "show", f"{PRE_V02_COMMIT}:rupsaa/personality/system_prompt.py"]).stdout
    ns: dict = {}
    exec(compile(src, "system_prompt_pre_v02", "exec"), ns)  # the repository's own earlier source
    return ns


def step_train_as_serve() -> None:
    from llamafactory.data.template import get_template_and_fix_tokenizer
    from transformers import AutoTokenizer

    from rupsaa.personality import system_prompt as sp
    from rupsaa.personality.system_prompt_v02 import V02_SYSTEM_PROMPT

    records = [json.loads(line) for line in open(FROZEN, encoding="utf-8")]
    train = [r for r in records if r["split"] == "train"]
    term = "\n\nReference terminology:\n"

    def first(pred):
        return next(r for r in train if pred(r))

    buckets = {
        "banglish": first(lambda r: r["language"] == "banglish" and term not in r["messages"][0]["content"] and len(r["messages"]) == 3),
        "bengali": first(lambda r: r["language"] == "bn" and len(r["messages"]) == 3),
        "english": first(lambda r: r["language"] == "en" and len(r["messages"]) == 3),
        "mixed": first(lambda r: r["language"] == "mixed" and term not in r["messages"][0]["content"]),
        "terminology": first(lambda r: term in r["messages"][0]["content"] and r["language"] == "banglish"),
        "multi_turn_memory": next((r for r in train if r["id"] == "rup-001500"), None)
                             or first(lambda r: r["category"] == "multi_turn" and len(r["messages"]) >= 7),
        "follow_up": first(lambda r: r["category"] == "follow_up_questions" and len(r["messages"]) >= 5),
    }

    tokenizer = AutoTokenizer.from_pretrained("Qwen/Qwen2.5-7B-Instruct", local_files_only=True)
    template = get_template_and_fix_tokenizer(tokenizer, "qwen")
    all_ok = True
    for name, rec in buckets.items():
        msgs = rec["messages"]
        system, turns = msgs[0]["content"], msgs[1:]
        ids = []
        for src, tgt in template.encode_multiturn(tokenizer, turns, system, "", 2048, 1):
            ids += src + tgt
        text = tokenizer.decode(ids, skip_special_tokens=False)
        if term in system:
            expected = sp.build_system_prompt(prompt_version="v0.2", terminology_context=system.split(term, 1)[1])
        elif "Retrieved context:\n" in system:
            expected = sp.build_system_prompt(prompt_version="v0.2", retrieved_context=system.split("Retrieved context:\n", 1)[1])
        else:
            expected = sp.build_system_prompt(prompt_version="v0.2")
        runtime = tokenizer.apply_chat_template(msgs[:-1], tokenize=True, add_generation_prompt=True)
        ok = (system == expected and system.startswith(V02_SYSTEM_PROMPT)
              and text.startswith(f"<|im_start|>system\n{V02_SYSTEM_PROMPT}")
              and "You are Rupsaa.\n" not in text and "You are a helpful assistant." not in text
              and ids[: len(runtime)] == runtime)
        all_ok &= ok
        SAMPLES.append({"bucket": name, "id": rec["id"], "language": rec["language"], "category": rec["category"],
                        "pass": ok, "formatted": text})
    check("train_as_serve_category_samples", all_ok,
          f"{sum(s['pass'] for s in SAMPLES)}/{len(SAMPLES)} ({', '.join(f'{s['bucket']}={s['id']}' for s in SAMPLES)})")

    check("v02_runtime_base_prompt", sp.build_system_prompt(prompt_version="v0.2") == V02_SYSTEM_PROMPT
          and sp.resolve_prompt_version(str(OUTPUT_DIR)) == "v0.2" and sp.resolve_prompt_version(str(V01_ADAPTER)) == "v0.1",
          "build_system_prompt('v0.2') == V02_SYSTEM_PROMPT; adapters/rupsaa-v0.2 -> v0.2, adapters/rupsaa-v0.1 -> v0.1")

    old = _old_system_prompt_module()
    probes = [{}, {"retrieved_context": "[Source: a.md]\nX"}, {"terminology_context": "Term: Y\nDefinition: Z"},
              {"conversation_note": "note"}, {"retrieved_context": "C", "terminology_context": "T", "conversation_note": "N"}]
    same = all(old["build_system_prompt"](**p) == sp.build_system_prompt(**p) == sp.build_system_prompt(prompt_version="v0.1", **p)
               for p in probes)
    consts = all(old[k] == getattr(sp, k) for k in ("BASE_PERSONA", "RAG_INSTRUCTIONS", "TERMINOLOGY_INSTRUCTIONS"))
    check("v01_runtime_prompt_unchanged", same and consts,
          f"build_system_prompt output identical to commit {PRE_V02_COMMIT} for {len(probes)} probe inputs; persona constants identical")


def step_cli_config() -> None:
    cfg = yaml.safe_load(CLI_CONFIG.read_text(encoding="utf-8"))
    diffs = {k: (cfg.get(k), v) for k, v in EXPECTED_CLI.items() if cfg.get(k) != v}
    check("cli_config_values", not diffs, diffs or f"{len(EXPECTED_CLI)} values as specified (effective batch 16)")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("0.0.0.0", 0))
        return s.getsockname()[1]


def step_gui_config() -> None:
    p = run(["bash", "scripts/start_llamafactory_gui.sh", "v0.2"],
            env={"RUPSAA_GUI_DRY_RUN": "1", "LLAMAFACTORY_GUI_PORT": str(_free_port())}, timeout=600)
    check("gui_launcher_dry_run", p.returncode == 0 and GUI_RENDERED.is_file(),
          "rendered + verified by LLaMA-Factory load_args/list_dataset, export hashes re-checked" if p.returncode == 0
          else (p.stderr or p.stdout)[-400:])
    if not GUI_RENDERED.is_file():
        return

    cwd = os.getcwd()
    os.chdir(PROJECT_ROOT)
    try:
        import gradio as gr
        from llamafactory.webui.common import get_model_path, list_dataset, load_args, load_config
        from llamafactory.webui.components import create_top, create_train_tab
        from llamafactory.webui.engine import Engine

        cfg = load_args("rupsaa_v0.2.yaml")
        diffs = {k: (cfg.get(k), v) for k, v in EXPECTED_GUI.items() if cfg.get(k) != v}
        check("gui_config_values", not diffs, diffs or f"{len(EXPECTED_GUI)} fields as specified")

        engine = Engine(pure_chat=False)
        with gr.Blocks():
            engine.manager.add_elems("top", create_top())
            engine.manager.add_elems("train", create_train_tab(engine))
        unknown = [k for k in cfg if k not in {engine.manager.get_id_by_elem(e) for e in engine.manager.get_elem_list()}]
        page = {engine.manager.get_id_by_elem(e): getattr(e, "value", None) for e in engine.manager.get_elem_list()}
        # A loaded value that differs from the page default fires that component's .change handler.
        # These three have handlers that would reset the template / blank the dataset / reload the model list.
        uc = load_config()
        no_reset = (uc.get("last_model") == cfg["top.model_name"] and get_model_path("Custom") == cfg["top.model_path"]
                    and page.get("train.dataset_dir") == cfg["train.dataset_dir"]
                    and page.get("train.training_stage") == cfg["train.training_stage"])
        choices = [c[0] if isinstance(c, tuple) else c for c in list_dataset(cfg["train.dataset_dir"]).choices]
        check("gui_no_reset_on_load", not unknown and no_reset and "rupsaa_v0.2_train" in choices,
              f"all {len(cfg)} keys are real WebUI elements; page-load model/path/dataset_dir/stage equal the loaded "
              f"values so no .change handler fires; rupsaa_v0.2_train listed")
    finally:
        os.chdir(cwd)


def step_no_v01_pointer() -> None:
    offenders = []
    for path in [CLI_CONFIG, GUI_TEMPLATE, GUI_RENDERED,
                 PROJECT_ROOT / "configs/training/llamafactory_rupsaa_v0.2_eval_validation.yaml"]:
        if not path.is_file():
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            body = line.split("#", 1)[0]
            if "rupsaa-v0.1" in body or "rupsaa_v0.1" in body:
                offenders.append(f"{path.relative_to(PROJECT_ROOT)}:{n}")
    check("no_v02_config_points_at_v01", not offenders, offenders or "no non-comment reference to V0.1 paths/datasets")


def step_repo_audit() -> None:
    p = run([PY, "scripts/repo_audit.py"])
    check("secret_largefile_forbidden_path_audit", p.returncode == 0, (p.stdout.strip().splitlines() or ["ok"])[-1])


def step_output_dir() -> None:
    moved = None
    if OUTPUT_DIR.exists() and any(OUTPUT_DIR.iterdir()):
        dest = PROJECT_ROOT / "adapters/_preserved" / f"rupsaa-v0.2_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(OUTPUT_DIR), str(dest))
        moved = str(dest.relative_to(PROJECT_ROOT))
    leftovers = [p for p in (PROJECT_ROOT / "saves", PROJECT_ROOT / "checkpoints/rupsaa_v0.2_llamafactory") if p.exists()]
    v01_ok = (V01_ADAPTER / "adapter_model.safetensors").is_file()
    ok = not (OUTPUT_DIR.exists() and any(OUTPUT_DIR.iterdir())) and v01_ok and not leftovers
    check("output_dir_safety", ok, (f"moved earlier contents to {moved}; " if moved else "")
          + f"adapters/rupsaa-v0.2 {'absent' if not OUTPUT_DIR.exists() else 'empty'}; no saves/ or stray checkpoints; "
            f"adapters/rupsaa-v0.1 present and untouched")


def step_tests() -> None:
    p = run([PY, "-m", "pytest", "-q"], timeout=3600)
    tail = [ln for ln in p.stdout.splitlines() if " passed" in ln or " failed" in ln]
    check("pytest", p.returncode == 0, tail[-1] if tail else p.stdout[-300:])


def write_report() -> bool:
    passed = all(r["pass"] for r in RESULTS.values())
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "PREFLIGHT.json").write_text(json.dumps(
        {"created_at": datetime.now(timezone.utc).isoformat(), "all_passed": passed, "checks": RESULTS,
         "train_as_serve_samples": SAMPLES, "optimizer_steps_run": 0, "model_weights_loaded": False},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# Rupsaa V0.2 preflight", "", f"**{'ALL CHECKS PASSED' if passed else 'FAILED'}** — "
             "no training, no optimizer steps, no model weights loaded.", "", "| Check | Result | Detail |", "|---|---|---|"]
    for k, v in RESULTS.items():
        lines.append(f"| {k} | {'PASS' if v['pass'] else 'FAIL'} | {str(v['detail']).replace('|', '/')} |")
    lines += ["", "## Train-as-we-serve: formatted training samples (exactly what LLaMA-Factory feeds the model)", ""]
    for s in SAMPLES:
        lines += [f"### {s['bucket']} — {s['id']} ({s['language']} / {s['category']}) — {'PASS' if s['pass'] else 'FAIL'}",
                  "", "```", s["formatted"], "```", ""]
    (REPORT_DIR / "PREFLIGHT.md").write_text("\n".join(lines), encoding="utf-8")
    return passed


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-tests", action="store_true")
    args = ap.parse_args()
    for step in (step_frozen, step_smoke, step_train_as_serve, step_cli_config, step_gui_config,
                 step_no_v01_pointer, step_repo_audit, step_output_dir):
        try:
            step()
        except Exception as exc:  # report and keep going; one failing step must not hide the others
            check(step.__name__, False, f"{type(exc).__name__}: {exc}")
    if args.with_tests:
        step_tests()
    passed = write_report()
    print(f"\n{'PREFLIGHT PASSED' if passed else 'PREFLIGHT FAILED'} -> {(REPORT_DIR / 'PREFLIGHT.md').relative_to(PROJECT_ROOT)}")
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
