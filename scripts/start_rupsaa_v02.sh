#!/usr/bin/env bash
# Start the Rupsaa app serving Qwen2.5-7B-Instruct + the Rupsaa V0.2 LoRA (4-bit, not merged)
# for OWNER LIVE TESTING. V0.2 is not the release (verdict FAIL, see
# data/production/reports/rupsaa_v0.2_posttraining/POSTTRAINING_REPORT.md).
# Roll back any time with: bash scripts/start_rupsaa_v01.sh
#
# Usage (from anywhere):  bash /teamspace/studios/this_studio/rupsaa-ai/scripts/start_rupsaa_v02.sh
#   env:  RUPSAA_ADAPTER_PATH  override the adapter (default: <root>/adapters/rupsaa-v0.2 =
#                              the evaluated best checkpoint-160)
#
# Sets RUPSAA_PROMPT_VERSION=v0.2 so the app sends exactly the system prompt V0.2 was
# trained with (rupsaa/personality/system_prompt_v02.py), then hands off to start_rupsaa.py.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

# adapter_model.safetensors of adapters/rupsaa-v0.2 (== checkpoint-160) as evaluated.
EVALUATED_SHA256=c7ca61842d58fb2b68a813a6b09f4df1fdab66717128e0112d5014235a410559

export RUPSAA_ADAPTER_PATH="${RUPSAA_ADAPTER_PATH:-$ROOT/adapters/rupsaa-v0.2}"
export RUPSAA_PROMPT_VERSION=v0.2
API_PORT="${API_PORT:-8000}"
WEB_PORT="${WEB_PORT:-5500}"

die() { echo "ERROR: $*" >&2; exit 1; }

[ -f "$RUPSAA_ADAPTER_PATH/adapter_config.json" ] || die "no adapter_config.json in $RUPSAA_ADAPTER_PATH"
[ -f "$RUPSAA_ADAPTER_PATH/adapter_model.safetensors" ] || die "no adapter_model.safetensors in $RUPSAA_ADAPTER_PATH"

# A Python that can actually run the app. In a fresh Lightning terminal `python3` may be a
# shell alias (not visible to bash) and PATH's python3 may lack torch.
PY=""
for cand in "${RUPSAA_PYTHON:-}" /home/zeus/miniconda3/envs/cloudspace/bin/python3 "$(command -v python3 || true)"; do
  if [ -n "$cand" ] && [ -x "$cand" ] && "$cand" -c "import torch, peft, fastapi" >/dev/null 2>&1; then
    PY="$cand"; break
  fi
done
[ -n "$PY" ] || die "no Python with torch/peft/fastapi found (set RUPSAA_PYTHON=/path/to/python3)"

if [ "$RUPSAA_ADAPTER_PATH" = "$ROOT/adapters/rupsaa-v0.2" ]; then
  sha="$(sha256sum "$RUPSAA_ADAPTER_PATH/adapter_model.safetensors" | cut -d' ' -f1)"
  [ "$sha" = "$EVALUATED_SHA256" ] || die "adapter sha256 $sha is not the evaluated V0.2 adapter ($EVALUATED_SHA256)"
fi

# Never let a stale (possibly V0.1) server answer instead of V0.2.
for port in "$API_PORT" "$WEB_PORT"; do
  if ss -ltn 2>/dev/null | awk '{print $4}' | grep -qE "[:.]$port\$"; then
    die "port $port is already in use — a Rupsaa server (maybe V0.1) is still running. Stop it first (Ctrl+C in its terminal)."
  fi
done

echo "Rupsaa V0.2 (owner live test): Qwen/Qwen2.5-7B-Instruct + $RUPSAA_ADAPTER_PATH, system prompt v0.2"
echo "python: $PY"
echo "Open/forward ONLY port $WEB_PORT. Check: <web url>/api/model/info -> adapter_loaded true, prompt_version v0.2 (after the first message)."
exec "$PY" "$ROOT/start_rupsaa.py"
