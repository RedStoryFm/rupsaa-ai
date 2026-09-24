#!/usr/bin/env python3
"""Pre-commit audit: secrets, large files and forbidden paths.

    python scripts/repo_audit.py            # files git would commit (tracked + untracked, not ignored)
    python scripts/repo_audit.py --staged   # only what is staged right now

Fails (exit 1) on:
  * credential-looking content (HF/GitHub/OpenAI/AWS/Slack tokens, private keys,
    non-empty secret assignments such as OWNER_API_KEY=<value>)
  * files larger than 5 MB (model weights, caches and datasets go to Hugging
    Face or are rebuilt — never plain git)
  * forbidden paths: .env, weights (*.safetensors/*.bin/*.pt/*.gguf),
    checkpoints/, adapters/<weights>, caches, __pycache__, virtualenvs, logs
Secret VALUES are never printed — only file, line number and rule name.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAX_BYTES = 5 * 1024 * 1024

SECRET_RULES = {
    "huggingface_token": re.compile(r"\bhf_[A-Za-z0-9]{30,}\b"),
    "github_token": re.compile(r"\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b|\bgithub_pat_[A-Za-z0-9_]{30,}\b"),
    "openai_like_key": re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}\b"),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "slack_token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    "private_key": re.compile(r"-----BEGIN (RSA |OPENSSH |EC |DSA |PGP )?PRIVATE KEY"),
    # KEY=value lines in env-style files with a real-looking value (placeholders/empty are fine)
    "secret_assignment": re.compile(
        r"^\s*(export\s+)?(OWNER_API_KEY|HUGGINGFACE_TOKEN|HF_TOKEN|GITHUB_TOKEN|GH_TOKEN|API_KEY|SECRET_KEY|PASSWORD)"
        r"\s*=\s*['\"]?(?!<|\$|your|changeme|xxx|\"?$)[^\s'\"#]{8,}", re.IGNORECASE),
}
FORBIDDEN = [
    (re.compile(r"(^|/)\.env$"), ".env file"),
    (re.compile(r"\.(safetensors|bin|pt|pth|ckpt|gguf|onnx)$"), "model weights"),
    (re.compile(r"^checkpoints/(?!\.gitkeep$)"), "training checkpoints"),
    (re.compile(r"^adapters/.+/(checkpoint-|optimizer|scheduler|rng_state)"), "adapter checkpoint state"),
    (re.compile(r"^merged_model/(?!\.gitkeep$)"), "merged model"),
    (re.compile(r"(^|/)(\.cache|__pycache__|\.pytest_cache|\.venv|venv|node_modules)/"), "cache / environment dir"),
    (re.compile(r"^(cache|saves|config)/"), "runtime state dir"),
    (re.compile(r"^knowledge/index/(?!\.gitkeep$)"), "generated RAG index"),
    (re.compile(r"\.(log|partial|tmp)$|(^|/)nohup\.out$"), "log / temp file"),
]
TEXT_SUFFIXES = {".py", ".sh", ".md", ".txt", ".json", ".jsonl", ".yaml", ".yml", ".toml", ".cfg", ".ini",
                 ".js", ".html", ".css", ".csv", ".example", ".env", ""}


def candidate_files(staged: bool) -> list[str]:
    if staged:
        cmd = ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"]
    else:
        cmd = ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"]
    out = subprocess.check_output(cmd, cwd=ROOT)
    return [f for f in out.decode("utf-8").split("\0") if f and (ROOT / f).is_file()]


def audit(files: list[str]) -> tuple[list[str], list[str]]:
    secrets, other = [], []
    for rel in files:
        path = ROOT / rel
        for pattern, why in FORBIDDEN:
            if pattern.search(rel):
                other.append(f"forbidden ({why}): {rel}")
                break
        size = path.stat().st_size
        if size > MAX_BYTES:
            other.append(f"too large ({size / 1e6:.1f} MB > {MAX_BYTES / 1e6:.0f} MB): {rel}")
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES and not rel.endswith(".env.example"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for rule, rx in SECRET_RULES.items():
                if rx.search(line):
                    secrets.append(f"possible secret [{rule}] at {rel}:{lineno}")
    return secrets, other


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--staged", action="store_true")
    args = ap.parse_args()
    files = candidate_files(args.staged)
    secrets, other = audit(files)
    total = sum((ROOT / f).stat().st_size for f in files)
    print(f"Audited {len(files)} file(s), {total / 1e6:.1f} MB{' (staged)' if args.staged else ''}")
    print(f"  secret audit     : {'FAIL' if secrets else 'PASS'}")
    print(f"  large-file audit : {'FAIL' if any('too large' in o for o in other) else 'PASS'}")
    print(f"  forbidden paths  : {'FAIL' if any('forbidden' in o for o in other) else 'PASS'}")
    for line in secrets + other:
        print(f"    - {line}")
    sys.exit(1 if secrets or other else 0)


if __name__ == "__main__":
    main()
