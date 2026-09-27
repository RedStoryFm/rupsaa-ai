#!/usr/bin/env bash
# Turn an owner-approved adapter into a ready-to-start production config. Run this AFTER
# the owner has evaluated the adapter and approved it (post-training report + live chat) —
# this script does not judge quality and does not approve anything.
#
# Usage:
#   bash scripts/finalize_release.sh <adapter_path> <adapter_sha256> [prompt_version]
#
#   adapter_path     e.g. adapters/rupsaa-v0.2.2   (directory with adapter_config.json +
#                    adapter_model.safetensors; relative paths are resolved from the repo root)
#   adapter_sha256   sha256 of adapter_model.safetensors, from the training/evaluation report
#                    (sha256sum adapters/rupsaa-v0.2.2/adapter_model.safetensors)
#   prompt_version   optional; leave empty to let the app infer it from the adapter name
#
# Does, in order: (1) validate the adapter on disk matches the given sha256 and base model,
# (2) back up current owner knowledge, (3) write RUPSAA_ENV=production, RUPSAA_ADAPTER_PATH,
# RUPSAA_ADAPTER_SHA256[, RUPSAA_PROMPT_VERSION] into .env (generating OWNER_API_KEY if .env
# doesn't exist yet), (4) run the full production config check.
#
# Does NOT start the model, does NOT touch the GPU, and NEVER runs while a Rupsaa process or
# a training job holds the GPU (the config check at the end refuses if the GPU isn't free —
# that's expected and fine to see here; it just means "don't start yet", not "this failed").
#
# Starting the server is a separate, explicit step after this script prints OK:
#   bash scripts/start_rupsaa_production.sh --check
#   bash scripts/start_rupsaa_production.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

die() { echo "ERROR: $*" >&2; exit 1; }

ADAPTER_PATH="${1:-}"
ADAPTER_SHA256="${2:-}"
PROMPT_VERSION="${3:-}"

[ -n "$ADAPTER_PATH" ] && [ -n "$ADAPTER_SHA256" ] || die \
  "usage: bash scripts/finalize_release.sh <adapter_path> <adapter_sha256> [prompt_version]"

PY=""
for cand in "${RUPSAA_PYTHON:-}" /home/zeus/miniconda3/envs/cloudspace/bin/python3 "$(command -v python3 || true)"; do
  if [ -n "$cand" ] && [ -x "$cand" ]; then PY="$cand"; break; fi
done
[ -n "$PY" ] || die "no python3 found (set RUPSAA_PYTHON)"

echo "== 1/5 validating adapter on disk"
ADAPTER_ABS="$ADAPTER_PATH"
[ "${ADAPTER_ABS:0:1}" = "/" ] || ADAPTER_ABS="$ROOT/$ADAPTER_PATH"
[ -d "$ADAPTER_ABS" ] || die "adapter directory not found: $ADAPTER_ABS"
[ -f "$ADAPTER_ABS/adapter_config.json" ] || die "missing $ADAPTER_ABS/adapter_config.json"
WEIGHTS="$ADAPTER_ABS/adapter_model.safetensors"
[ -f "$WEIGHTS" ] || die "missing $WEIGHTS"

ACTUAL_SHA="$(sha256sum "$WEIGHTS" | cut -d' ' -f1)"
EXPECTED_SHA="$(echo "$ADAPTER_SHA256" | tr '[:upper:]' '[:lower:]')"
[ "$ACTUAL_SHA" = "$EXPECTED_SHA" ] || die \
  "adapter sha256 mismatch: got ${ACTUAL_SHA:0:12}…, expected ${EXPECTED_SHA:0:12}… — wrong adapter or corrupted file, refusing to proceed"
echo "   adapter sha256 verified: ${ACTUAL_SHA:0:12}…"

BASE_MODEL="$("$PY" -c "
import sys
sys.path.insert(0, '$ROOT')
from rupsaa.config import load_model_config
print(load_model_config()['base_model_id'])
")"
TRAINED_ON="$("$PY" -c "
import json
cfg = json.load(open('$ADAPTER_ABS/adapter_config.json'))
print(cfg.get('base_model_name_or_path', ''))
")"
if [ -n "$TRAINED_ON" ] && [ "$(basename "$TRAINED_ON")" != "$(basename "$BASE_MODEL")" ]; then
  die "adapter was trained on '$TRAINED_ON' but the configured base model is '$BASE_MODEL'"
fi
echo "   base model matches: $BASE_MODEL"

echo "== 2/5 backing up current owner knowledge"
bash "$SCRIPT_DIR/backup_knowledge.sh"

echo "== 3/5 preparing production environment (.env)"
ENV_FILE="$ROOT/.env"
if [ ! -f "$ENV_FILE" ]; then
  cp "$ROOT/.env.example" "$ENV_FILE"
  echo "   created .env from .env.example"
fi

set_env_var() {
  local key="$1" value="$2"
  if grep -qE "^${key}=" "$ENV_FILE"; then
    # Escape & and | for sed's replacement side.
    local esc_value
    esc_value="$(printf '%s' "$value" | sed -e 's/[&|]/\\&/g')"
    sed -i "s|^${key}=.*|${key}=${esc_value}|" "$ENV_FILE"
  else
    printf '%s=%s\n' "$key" "$value" >> "$ENV_FILE"
  fi
}

set_env_var RUPSAA_ENV production
set_env_var RUPSAA_ADAPTER_PATH "$ADAPTER_PATH"
set_env_var RUPSAA_ADAPTER_SHA256 "$ACTUAL_SHA"
[ -n "$PROMPT_VERSION" ] && set_env_var RUPSAA_PROMPT_VERSION "$PROMPT_VERSION"

if ! grep -qE '^OWNER_API_KEY=.{24,}' "$ENV_FILE"; then
  NEW_KEY="$("$PY" -c "import secrets; print(secrets.token_urlsafe(32))")"
  set_env_var OWNER_API_KEY "$NEW_KEY"
  echo "   generated a new OWNER_API_KEY (shown once — save it now):"
  echo "   $NEW_KEY"
else
  echo "   OWNER_API_KEY already set in .env — left unchanged"
fi

if grep -qE '^CORS_ORIGINS=\*?$|^CORS_ORIGINS=$|^CORS_ORIGINS=\*$' "$ENV_FILE" || ! grep -q '^CORS_ORIGINS=' "$ENV_FILE"; then
  echo "   NOTE: CORS_ORIGINS is empty or unset — edit .env and set it to your real public origin(s) before starting"
fi

echo "== 4/5 validating knowledge stores are readable"
"$PY" -c "
import sys
sys.path.insert(0, '$ROOT')
from rupsaa.config import get_settings
from rupsaa.rag.dance import DanceStore
from rupsaa.rag.terminology import TerminologyStore
s = get_settings()
t = len(TerminologyStore(s.resolve_path(s.knowledge_terminology_dir)).list())
d = len(DanceStore(s.resolve_path(s.knowledge_dance_dir)).list())
print(f'   terminology: {t} entries, dance: {d} entries')
"

echo "== 5/5 running full production config check (config only — no GPU/runtime probe)"
set +e
RUPSAA_ENV=production "$PY" "$SCRIPT_DIR/check_production_config.py" --skip-runtime
CHECK_STATUS=$?
set -e

echo
if [ "$CHECK_STATUS" -eq 0 ]; then
  echo "CONFIG READY. Nothing was started. Next steps:"
  echo "  1. review .env (especially CORS_ORIGINS) if you haven't already"
  echo "  2. bash scripts/start_rupsaa_production.sh --check   # full check incl. GPU/ports (fails while training is running — expected)"
  echo "  3. bash scripts/start_rupsaa_production.sh            # start (only once the GPU is free)"
  echo "  4. until curl -sf localhost:\${WEB_PORT:-5500}/api/ready; do sleep 10; done"
  echo "  5. OWNER_API_KEY=... python scripts/production_smoke.py --base http://127.0.0.1:\${WEB_PORT:-5500}/api --expect-adapter $(basename "$ADAPTER_PATH")"
else
  echo "CONFIG NOT READY — fix the PROBLEM lines above, then re-run this script."
  exit 1
fi
