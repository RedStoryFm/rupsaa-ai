#!/usr/bin/env bash
# Rupsaa V0.2 post-training evaluation — run ONLY after the LLaMA-Factory run has finished.
#
# Usage:  bash scripts/posttrain_rupsaa_v02.sh [--dry-run] [--skip-generation]
#
# Never trains, merges, or switches the app. Steps (see scripts/posttrain_v02.py):
#   best checkpoint -> adapter integrity -> frozen validation/test loss -> clean V0.1-vs-V0.2
#   subset -> unseen-terminology suite -> 10 live-behaviour checks -> V0.1 / V0.2 / base
#   comparison -> data/production/reports/rupsaa_v0.2_posttraining/POSTTRAIN_REPORT.md
#   (+ APP_INTEGRATION.md only if the automatic gate passes).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

die() { echo "ERROR: $*" >&2; exit 1; }

PY="$(command -v python3 || true)"
[ -n "$PY" ] || PY=/home/zeus/miniconda3/envs/cloudspace/bin/python3

ADAPTER="$ROOT/adapters/rupsaa-v0.2"
[ -f "$ADAPTER/adapter_model.safetensors" ] && [ -f "$ADAPTER/trainer_state.json" ] \
  || die "no finished V0.2 run in $ADAPTER (adapter_model.safetensors + trainer_state.json). Train first."
[ -f "$ROOT/adapters/rupsaa-v0.1/adapter_model.safetensors" ] || die "V0.1 adapter missing (needed for the comparison)"

if pgrep -f "llamafactory.*train" >/dev/null 2>&1; then
  die "a LLaMA-Factory training process still seems to be running — wait for it to finish"
fi

echo "== frozen dataset / V0.1 protection check"
"$PY" scripts/v02_verify_frozen.py || die "frozen-state verification failed — not evaluating"

echo "== post-training evaluation"
exec "$PY" scripts/posttrain_v02.py "$@"
