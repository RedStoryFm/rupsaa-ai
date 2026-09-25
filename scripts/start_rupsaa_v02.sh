#!/usr/bin/env bash
# Start the Rupsaa app serving Qwen2.5-7B-Instruct + the Rupsaa V0.2 LoRA (4-bit, not merged).
# Use only after reviewing data/production/reports/rupsaa_v0.2_posttraining/POSTTRAINING_REPORT.md (verdict: FAIL, opt-in only).
# Roll back any time with: bash scripts/start_rupsaa_v01.sh
#
# Usage:  bash scripts/start_rupsaa_v02.sh
#   env:  RUPSAA_ADAPTER_PATH  override the adapter (default: <root>/adapters/rupsaa-v0.2)
#
# Sets RUPSAA_PROMPT_VERSION=v0.2 explicitly so the app sends exactly the system prompt
# V0.2 was trained with (rupsaa/personality/system_prompt_v02.py), then hands off to start_rupsaa.py.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

export RUPSAA_ADAPTER_PATH="${RUPSAA_ADAPTER_PATH:-$ROOT/adapters/rupsaa-v0.2}"
export RUPSAA_PROMPT_VERSION=v0.2

die() { echo "ERROR: $*" >&2; exit 1; }

[ -f "$RUPSAA_ADAPTER_PATH/adapter_config.json" ] || die "no adapter_config.json in $RUPSAA_ADAPTER_PATH — V0.2 not trained yet?"
[ -f "$RUPSAA_ADAPTER_PATH/adapter_model.safetensors" ] || die "no adapter_model.safetensors in $RUPSAA_ADAPTER_PATH"

PY="$(command -v python3 || true)"
[ -n "$PY" ] || PY=/home/zeus/miniconda3/envs/cloudspace/bin/python3

echo "Rupsaa V0.2: base Qwen/Qwen2.5-7B-Instruct + adapter $RUPSAA_ADAPTER_PATH (system prompt v0.2)"
echo "Open/forward ONLY port ${WEB_PORT:-5500}. Check: <web url>/api/model/info -> \"adapter_loaded\": true (after the first message)."
exec "$PY" "$ROOT/start_rupsaa.py"
