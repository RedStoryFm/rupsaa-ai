#!/usr/bin/env bash
# Start Rupsaa in PRODUCTION mode: base model + the adapter named in RUPSAA_ADAPTER_PATH.
#
# Usage:  bash scripts/start_rupsaa_production.sh            # validate, then start (foreground; Ctrl+C stops)
#         bash scripts/start_rupsaa_production.sh --check    # validate only, start nothing (safe any time)
#         bash scripts/stop_rupsaa_production.sh             # stop a running instance cleanly
#
# Configuration: .env (see .env.example) and/or environment. Switching or rolling back a model
# version = change RUPSAA_ADAPTER_PATH (+ RUPSAA_ADAPTER_SHA256) and restart — no code changes.
#
# Refuses to start (non-zero exit, clear message) when: OWNER_API_KEY missing/short, the adapter
# is missing or was trained for another base model, the adapter hash differs from
# RUPSAA_ADAPTER_SHA256, CORS is "*", ports are taken / another Rupsaa is running, or the GPU
# lacks free memory (e.g. training is running). It never falls back to another adapter.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

die() { echo "ERROR: $*" >&2; exit 1; }

export RUPSAA_ENV=production
# Only the web server (WEB_PORT) should be reachable; it proxies /api/* to the API on loopback.
export API_HOST="${API_HOST:-127.0.0.1}"
export API_PORT="${API_PORT:-8000}"
export WEB_PORT="${WEB_PORT:-5500}"
# .env values are read by the app itself; export RUPSAA_ADAPTER_PATH from .env for the banner.
if [ -z "${RUPSAA_ADAPTER_PATH:-}" ] && [ -f .env ]; then
  RUPSAA_ADAPTER_PATH="$(grep -E '^RUPSAA_ADAPTER_PATH=' .env | tail -1 | cut -d= -f2- || true)"
fi
[ -n "${RUPSAA_ADAPTER_PATH:-}" ] || die "RUPSAA_ADAPTER_PATH is not set (in .env or the environment)"
export RUPSAA_ADAPTER_PATH

# A Python that can run the app (a fresh Lightning terminal may not have conda on PATH).
PY=""
for cand in "${RUPSAA_PYTHON:-}" /home/zeus/miniconda3/envs/cloudspace/bin/python3 "$(command -v python3 || true)"; do
  if [ -n "$cand" ] && [ -x "$cand" ] && "$cand" -c "import torch, peft, fastapi" >/dev/null 2>&1; then PY="$cand"; break; fi
done
[ -n "$PY" ] || die "no Python with torch/peft/fastapi found (set RUPSAA_PYTHON)"

PIDFILE="$ROOT/run/rupsaa-production.pid"
mkdir -p "$ROOT/run"
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  die "Rupsaa production is already running (pid $(cat "$PIDFILE")). Stop it: bash scripts/stop_rupsaa_production.sh"
fi

echo "== validating production configuration"
CHECK_ARGS=()
[ "${1:-}" = "--check-config-only" ] && CHECK_ARGS+=(--skip-runtime)
"$PY" scripts/check_production_config.py "${CHECK_ARGS[@]}" || die "configuration check failed — nothing was started"

if [ "${1:-}" = "--check" ] || [ "${1:-}" = "--check-config-only" ]; then
  echo "check only: configuration is valid; nothing started."
  exit 0
fi

echo "== starting Rupsaa (production) — adapter $(basename "$RUPSAA_ADAPTER_PATH"), API ${API_HOST}:${API_PORT}, web :${WEB_PORT}"
echo "   readiness: curl -s localhost:${WEB_PORT}/api/ready   (200 once the model is loaded)"
echo "   smoke test: python scripts/production_smoke.py --base http://127.0.0.1:${WEB_PORT}/api"
echo $$ > "$PIDFILE"
trap 'rm -f "$PIDFILE"' EXIT
# start_rupsaa.py supervises uvicorn + the web proxy and stops both on Ctrl+C / SIGTERM.
"$PY" "$ROOT/start_rupsaa.py"
