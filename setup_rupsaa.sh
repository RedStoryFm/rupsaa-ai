#!/usr/bin/env bash
# Rupsaa — one-command install / restore.
#
#   git clone <your rupsaa repo> rupsaa-ai && cd rupsaa-ai
#   bash setup_rupsaa.sh
#   bash scripts/start_rupsaa_v01.sh        # then open port 5500 only
#
# Safe to re-run: every step checks before it acts. It never trains, never
# merges the LoRA, never downloads the Qwen base weights (the app does that
# lazily on the first chat), and never reads/prints secrets.
#
# Environment overrides (all optional):
#   RUPSAA_HF_REPO          Hugging Face repo holding the adapter (else configs/release.yaml hf_repo_id)
#   RUPSAA_HF_REVISION      tag/branch/commit to download (else the release tag, e.g. rupsaa-v0.1)
#   RUPSAA_ADAPTER_PATH     where the adapter lives (default adapters/rupsaa-v0.1)
#   RUPSAA_ADAPTER_FROM_DIR restore the adapter from a local copy instead of the Hub
#   RUPSAA_ALLOW_NO_ADAPTER=1   finish setup without an adapter (base model only)
#   RUPSAA_PYTHON           interpreter to use (default: python3 on PATH)
#   RUPSAA_INSTALL_TORCH=1  install the known-good torch 2.8.0+cu128 even if another torch exists
#   RUPSAA_SKIP_PIP=1  RUPSAA_SKIP_LLAMAFACTORY=1  RUPSAA_SKIP_RAG=1  RUPSAA_SKIP_TESTS=1
# Private Hugging Face repo: run `hf auth login` once before this script
# (or export HF_TOKEN in your shell). Never put a token in this repository.

set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
PY="${RUPSAA_PYTHON:-$(command -v python3 || true)}"
TORCH_PIN="torch==2.8.0"
TORCH_INDEX="https://download.pytorch.org/whl/cu128"

step() { printf '\n\033[1m[%s] %s\033[0m\n' "$1" "$2"; }
info() { printf '   %s\n' "$*"; }
die() { printf '\n\033[31mSETUP FAILED:\033[0m %s\n' "$*" >&2; exit 1; }
trap 'die "unexpected error on line $LINENO (command: $BASH_COMMAND)"' ERR

# ---------------------------------------------------------------------------
step 1 "Project root"
[ -f "$ROOT/api/main.py" ] && [ -f "$ROOT/rupsaa/config.py" ] || die "run this from a Rupsaa checkout (api/main.py not found in $ROOT)"
info "$ROOT"

step 2 "Operating system / Python"
[ "$(uname -s)" = "Linux" ] || die "Linux is required (found $(uname -s))"
[ -n "$PY" ] && [ -x "$PY" ] || die "python3 not found — install Python 3.10–3.12 (3.12 known-good) or set RUPSAA_PYTHON"
PYVER="$("$PY" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')"
"$PY" -c 'import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,12) else 1)' \
  || die "Python $PYVER is not supported — use 3.10–3.12 (3.12.11 known-good)"
info "$(uname -srm) · Python $PYVER ($PY)"
if [ -n "${VIRTUAL_ENV:-}${CONDA_DEFAULT_ENV:-}" ]; then info "environment: ${VIRTUAL_ENV:-conda:${CONDA_DEFAULT_ENV}}"; fi

step 3 "GPU / CUDA"
if command -v nvidia-smi >/dev/null 2>&1; then
  info "$(nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader | head -1)"
else
  info "WARNING: no NVIDIA GPU detected. Setup continues, but chatting with the 7B model needs a CUDA GPU (NVIDIA L4 23 GB known-good)."
fi

step 4 "Directories"
mkdir -p adapters checkpoints merged_model data/processed knowledge/documents knowledge/index knowledge/terminology cache
info "adapters/ checkpoints/ knowledge/{documents,index,terminology}/ data/processed/ cache/"

step 5 "PyTorch"
if "$PY" -c 'import torch' >/dev/null 2>&1; then
  TV="$("$PY" -c 'import torch; print(torch.__version__)')"
  info "torch $TV already installed (known-good: 2.8.0+cu128)"
  if [ "${RUPSAA_INSTALL_TORCH:-0}" = "1" ] && [[ "$TV" != 2.8.0* ]]; then
    info "RUPSAA_INSTALL_TORCH=1 → installing $TORCH_PIN from $TORCH_INDEX"
    "$PY" -m pip install "$TORCH_PIN" --index-url "$TORCH_INDEX"
  elif [[ "$TV" != 2.8.0* ]]; then
    info "NOTE: different torch version kept as-is. If model loading fails, re-run with RUPSAA_INSTALL_TORCH=1."
  fi
elif [ "${RUPSAA_SKIP_PIP:-0}" = "1" ]; then
  die "torch is not installed and RUPSAA_SKIP_PIP=1"
else
  info "torch missing → installing $TORCH_PIN (CUDA 12.8 build)"
  "$PY" -m pip install "$TORCH_PIN" --index-url "$TORCH_INDEX"
fi

step 6 "Application dependencies (requirements.txt)"
if [ "${RUPSAA_SKIP_PIP:-0}" = "1" ]; then
  info "skipped (RUPSAA_SKIP_PIP=1)"
else
  "$PY" -m pip install -r requirements.txt
fi

step 7 "LLaMA-Factory 0.7.1 GUI + compatibility patches"
if [ "${RUPSAA_SKIP_LLAMAFACTORY:-0}" = "1" ] || [ "${RUPSAA_SKIP_PIP:-0}" = "1" ]; then
  info "skipped — run 'bash scripts/setup_llamafactory.sh' later if you want the training GUI"
else
  # Same interpreter for the helper script's bare pip/python3 calls.
  PATH="$(dirname "$PY"):$PATH" bash scripts/setup_llamafactory.sh
fi

step 8 "Hugging Face access"
HF_REPO="${RUPSAA_HF_REPO:-$("$PY" -c 'import yaml; print((yaml.safe_load(open("configs/release.yaml")) or {}).get("hf_repo_id") or "")')}"
if [ -n "$HF_REPO" ]; then
  if "$PY" -c 'from huggingface_hub import HfApi; HfApi().whoami()' >/dev/null 2>&1; then
    info "logged in to Hugging Face (token not shown); adapter repo: $HF_REPO"
  else
    info "not logged in to Hugging Face — fine for a public repo; for a PRIVATE repo run: hf auth login"
  fi
else
  info "no adapter repo configured (configs/release.yaml hf_repo_id / RUPSAA_HF_REPO)"
fi

step 9 "Rupsaa adapter (download / restore + checksum verification)"
FETCH_ARGS=()
[ -n "${RUPSAA_ADAPTER_FROM_DIR:-}" ] && FETCH_ARGS+=(--from-dir "$RUPSAA_ADAPTER_FROM_DIR")
set +e
RUPSAA_HF_REPO="$HF_REPO" "$PY" scripts/fetch_adapter.py "${FETCH_ARGS[@]}"
FETCH_RC=$?
set -e
ADAPTER_OK=1
if [ $FETCH_RC -ne 0 ]; then
  ADAPTER_OK=0
  if [ "${RUPSAA_ALLOW_NO_ADAPTER:-0}" = "1" ]; then
    info "continuing WITHOUT the adapter (RUPSAA_ALLOW_NO_ADAPTER=1) — the app will serve the base model only"
  else
    die "adapter not restored. Configure hf_repo_id in configs/release.yaml (or RUPSAA_HF_REPO), log in with
      'hf auth login' if the repo is private, or restore from a copy with RUPSAA_ADAPTER_FROM_DIR=<dir>.
      (RUPSAA_ALLOW_NO_ADAPTER=1 finishes setup for base-model-only use.)"
  fi
fi

step 10 "Knowledge / terminology / RAG index"
info "documents: $(find knowledge/documents -maxdepth 1 -type f ! -name '.*' | wc -l) · terminology records: $(find knowledge/terminology -maxdepth 1 -name 'term-*.json' | wc -l) (kept as-is)"
if [ "${RUPSAA_SKIP_RAG:-0}" = "1" ]; then
  info "RAG index build skipped (RUPSAA_SKIP_RAG=1)"
elif [ ! -f knowledge/index/rupsaa.index ] || [ -n "$(find knowledge/documents -type f ! -name '.*' -newer knowledge/index/rupsaa.index 2>/dev/null)" ]; then
  info "building RAG index from knowledge/documents (downloads the small multilingual-e5 embedding model on first run)"
  "$PY" scripts/ingest_knowledge.py
else
  info "RAG index up to date"
fi

step 11 "Unit tests (no model is loaded)"
if [ "${RUPSAA_SKIP_TESTS:-0}" = "1" ]; then
  info "skipped (RUPSAA_SKIP_TESTS=1)"
else
  GRADIO_ANALYTICS_ENABLED=False "$PY" -m pytest -q -p no:cacheprovider || die "unit tests failed — see output above"
fi

step 12 "Installation verification"
VERIFY_ARGS=()
[ "$ADAPTER_OK" = "0" ] && VERIFY_ARGS+=(--no-adapter)
"$PY" scripts/verify_installation.py "${VERIFY_ARGS[@]}" || die "installation verification failed — see output above"

trap - ERR
cat <<EOF

============================================================
 RUPSAA SETUP COMPLETE
   Start:        bash scripts/start_rupsaa_v01.sh
   Open:         port 5500 only (the API on 8000 stays internal)
   First chat:   downloads/loads Qwen/Qwen2.5-7B-Instruct (~15 GB, once) + the Rupsaa LoRA —
                 the first reply can take several minutes.
   Check:        <your 5500 URL>/api/model/info  →  "adapter_loaded": true, "quantized": true
============================================================
EOF
