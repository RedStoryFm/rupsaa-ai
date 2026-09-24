#!/usr/bin/env bash
# Start the Rupsaa app (FastAPI + web UI/proxy) serving Qwen2.5-7B-Instruct
# + the trained Rupsaa V0.1 LoRA adapter (4-bit, not merged).
#
# Usage:  bash scripts/start_rupsaa_v01.sh
#   env:  RUPSAA_ADAPTER_PATH  override the adapter (default: <root>/adapters/rupsaa-v0.1)
#         WEB_PORT / API_PORT  passed through to start_rupsaa.py (defaults 5500 / 8000)
#
# This only sets the adapter path and hands off to the existing launcher
# (start_rupsaa.py); the app itself is unchanged. The model still loads
# lazily on the first chat message. To run the base model instead, use
# `python start_rupsaa.py` without RUPSAA_ADAPTER_PATH (the loader falls
# back to base-only when the configured adapter doesn't exist).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

export RUPSAA_ADAPTER_PATH="${RUPSAA_ADAPTER_PATH:-$ROOT/adapters/rupsaa-v0.1}"

die() { echo "ERROR: $*" >&2; exit 1; }

[ -f "$RUPSAA_ADAPTER_PATH/adapter_config.json" ] \
  || die "no adapter_config.json in $RUPSAA_ADAPTER_PATH — V0.1 adapter missing. (Base model only: python start_rupsaa.py)"
[ -f "$RUPSAA_ADAPTER_PATH/adapter_model.safetensors" ] \
  || die "no adapter_model.safetensors in $RUPSAA_ADAPTER_PATH"

PY="$(command -v python3 || true)"
[ -n "$PY" ] || PY=/home/zeus/miniconda3/envs/cloudspace/bin/python3

echo "Rupsaa V0.1: base Qwen/Qwen2.5-7B-Instruct + adapter $RUPSAA_ADAPTER_PATH"
echo "Open/forward ONLY port ${WEB_PORT:-5500}. Check: <web url>/api/model/info -> \"adapter_loaded\": true (after the first message)."
exec "$PY" "$ROOT/start_rupsaa.py"
