#!/usr/bin/env bash
# Install the Python packages Gemma 3 needs into a SEPARATE folder, next to the repo (../.gemma_stack).
#
#   bash scripts/setup_gemma_stack.sh            # idempotent; prints the PYTHONPATH to use
#
# Why a separate folder: the project environment pins transformers 4.46.3 (LLaMA-Factory 0.7.1, Qwen history),
# which predates Gemma 3; Lightning Studios allow only one conda env and no venvs. The Gemma app and tools run with
# PYTHONPATH=<this folder>, which shadows only these three packages (torch, peft, bitsandbytes, accelerate and
# numpy come from the project environment: torch 2.8.0+cu128, peft 0.21.0, bitsandbytes 0.50.2, accelerate 1.15.0).
set -euo pipefail
STACK="${GEMMA_STACK:-$(cd "$(dirname "$0")/../.." && pwd)/.gemma_stack}"
PY="${RUPSAA_PYTHON:-/home/zeus/miniconda3/envs/cloudspace/bin/python3}"
[ -x "$PY" ] || PY="$(command -v python3)"
PINS=("transformers==4.57.6" "tokenizers==0.22.2" "huggingface_hub==0.36.2")
if PYTHONPATH="$STACK" "$PY" -c "import transformers,tokenizers,huggingface_hub as h;assert (transformers.__version__,tokenizers.__version__,h.__version__)==('4.57.6','0.22.2','0.36.2')" 2>/dev/null; then
  echo "Gemma stack already present: $STACK"
else
  "$PY" -m pip install --quiet --no-deps --target "$STACK" "${PINS[@]}"
  echo "Gemma stack installed: $STACK"
fi
PYTHONPATH="$STACK" "$PY" -c "import transformers,peft,torch;print('transformers',transformers.__version__,'| peft',peft.__version__,'| torch',torch.__version__)"
echo "Use: PYTHONPATH=$STACK bash scripts/start_rupsaa_production.sh"
