#!/usr/bin/env bash
# Launch the LLaMA-Factory WebUI for Rupsaa (GUI only — this script
# never starts training; you press Start in the browser yourself).
#
# Usage:  bash scripts/start_llamafactory_gui.sh [v0.1|v0.2|v0.2.1]   (default v0.1)
#   env:  LLAMAFACTORY_GUI_PORT (default 7860) — must not be 5500 or 8000
#         RUPSAA_TRAIN_VERSION  (alternative to the positional argument)
#
# What it does, and why (see configs/training/llamafactory_webui_rupsaa_v0.1.yaml
# for the source-level details):
#   1. cd to the rupsaa-ai root. LLaMA-Factory 0.7.1 resolves the GUI's
#      "Config path" as ./config/<name>, datasets as ./data/dataset_info.json,
#      and its own state as ./cache/ — all relative to the process CWD.
#   2. Seed ./cache/user_config.yaml (LLaMA-Factory's own persistence file)
#      so the page opens with Model = Custom / Qwen/Qwen2.5-7B-Instruct.
#   3. Render ./config/rupsaa_v0.1.yaml from the tracked template.
#   4. Verify it with LLaMA-Factory's own load_args()/list_dataset().
#   5. Start the WebUI on 0.0.0.0:<port>.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PORT="${LLAMAFACTORY_GUI_PORT:-7860}"
VERSION="${1:-${RUPSAA_TRAIN_VERSION:-v0.1}}"

die() { echo "ERROR: $*" >&2; exit 1; }

case "$VERSION" in
  v0.1) MANIFEST="data/production/snapshots/rupsaa_v0.1_training/V01_TRAINING_MANIFEST.json" ;;
  v0.2) MANIFEST="data/production/snapshots/rupsaa_v0.2_training/V02_TRAINING_MANIFEST.json" ;;
  v0.2.1) MANIFEST="data/production/exports/rupsaa_v0.2.1/V021_TRAINING_MANIFEST.json" ;;
  *) die "unknown version '$VERSION' (use v0.1, v0.2 or v0.2.1)" ;;
esac
CONFIG_NAME="rupsaa_${VERSION}.yaml"
TEMPLATE="configs/training/llamafactory_webui_rupsaa_${VERSION}.yaml"

case "$PORT" in
  5500|8000) die "port $PORT is reserved for Rupsaa (5500 = web UI, 8000 = internal API). Pick another LLAMAFACTORY_GUI_PORT." ;;
esac

cd "$ROOT"

# --- interpreter: the Studio's single conda env (no venvs allowed here) ---
LF_CLI="$(command -v llamafactory-cli || true)"
if [ -z "$LF_CLI" ] && [ -x /home/zeus/miniconda3/envs/cloudspace/bin/llamafactory-cli ]; then
  LF_CLI=/home/zeus/miniconda3/envs/cloudspace/bin/llamafactory-cli
fi
[ -n "$LF_CLI" ] || die "llamafactory-cli not found. Run: bash scripts/setup_llamafactory.sh"
PY="${LLAMAFACTORY_PYTHON:-$(dirname "$LF_CLI")/python}"
[ -x "$PY" ] || die "python interpreter not found next to $LF_CLI (set LLAMAFACTORY_PYTHON)"

# --- required files ---
DATASET_INFO=data/dataset_info.json
[ "$VERSION" = "v0.2.1" ] && DATASET_INFO=data/production/exports/rupsaa_v0.2.1/dataset_info.json
for f in \
  "$TEMPLATE" \
  "$DATASET_INFO" \
  "data/production/exports/rupsaa_${VERSION}/train.jsonl" \
  "data/production/exports/rupsaa_${VERSION}/validation.jsonl" \
  "$MANIFEST"
do
  [ -r "$f" ] || die "required file missing or unreadable: $ROOT/$f"
done

# --- environment sanity: pinned GUI stack + compatibility patches present ---
"$PY" - <<'PYEOF' || die "LLaMA-Factory GUI stack is not in the expected state. Run: bash scripts/setup_llamafactory.sh"
import sys, importlib.metadata as md
import gradio_client.utils as gcu, gradio.routes as gr_routes
problems = []
if md.version("llamafactory") != "0.7.1": problems.append("llamafactory != 0.7.1")
if not md.version("gradio").startswith("4."): problems.append("gradio is not 4.x")
if "isinstance(schema, bool)" not in open(gcu.__file__).read(): problems.append("gradio_client bool-schema patch missing")
if "TemplateResponse(\n                    request," not in open(gr_routes.__file__).read(): problems.append("gradio TemplateResponse patch missing")
for p in problems: print("  -", p, file=sys.stderr)
sys.exit(1 if problems else 0)
PYEOF

# --- port must be free ---
"$PY" - "$PORT" <<'PYEOF' || die "port $PORT is already in use (is the GUI already running? check: ss -ltnp | grep :$PORT)"
import socket, sys
s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    s.bind(("0.0.0.0", int(sys.argv[1])))
finally:
    s.close()
PYEOF

# --- seed LLaMA-Factory's own user_config (non-destructive merge) and
#     render the GUI-loadable config, then verify both with LF's own code ---
"$PY" - "$ROOT" "$TEMPLATE" "$CONFIG_NAME" "$VERSION" "$MANIFEST" <<'PYEOF' || die "config render/verification failed"
import hashlib, json, os, sys, yaml
root, template, config_name, version, manifest_path = sys.argv[1:6]

os.makedirs("cache", exist_ok=True)
uc_path = os.path.join("cache", "user_config.yaml")
uc = {}
if os.path.exists(uc_path):
    with open(uc_path, encoding="utf-8") as f:
        uc = yaml.safe_load(f) or {}
uc.setdefault("lang", "en")
uc.setdefault("cache_dir", None)
uc["last_model"] = "Custom"
uc.setdefault("path_dict", {})["Custom"] = "Qwen/Qwen2.5-7B-Instruct"
with open(uc_path, "w", encoding="utf-8") as f:
    yaml.safe_dump(uc, f)

with open(template, encoding="utf-8") as f:
    rendered = f.read().replace("@RUPSAA_ROOT@", root)
os.makedirs("config", exist_ok=True)
with open(os.path.join("config", config_name), "w", encoding="utf-8") as f:
    f.write("# GENERATED by scripts/start_llamafactory_gui.sh from " + template + " — edit the template, not this file.\n")
    f.write(rendered)

os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")
from llamafactory.webui.common import get_model_path, get_save_path, list_dataset, load_args, load_config

cfg = load_args(config_name)
assert cfg is not None, f"LLaMA-Factory load_args could not open {get_save_path(config_name)}"
assert cfg["train.output_dir"] == os.path.join(root, "adapters", f"rupsaa-{version}"), cfg["train.output_dir"]
assert cfg["train.dataset"] == [f"rupsaa_{version}_train"], cfg["train.dataset"]
assert cfg["top.template"] == "qwen" and cfg["top.quantization_bit"] == "4", "template/quantization drifted"
choices = [c[0] if isinstance(c, tuple) else c for c in list_dataset(cfg["train.dataset_dir"]).choices]
assert f"rupsaa_{version}_train" in choices, f"rupsaa_{version}_train not registered in {cfg['train.dataset_dir']}/dataset_info.json"
if version == "v0.2.1":
    # Frozen export: every file must still match the freeze manifest; never train into V0.1/V0.2.
    manifest = json.load(open(manifest_path, encoding="utf-8"))
    for name, expected in manifest["files_sha256"].items():
        path = os.path.join("data", "production", "exports", "rupsaa_v0.2.1", name)
        actual = hashlib.sha256(open(path, "rb").read()).hexdigest()
        assert actual == expected, f"{path} changed since freeze ({actual} != {expected})"
    for other in ("rupsaa-v0.1", "rupsaa-v0.2"):
        assert cfg["train.output_dir"] != os.path.join(root, "adapters", other), f"would overwrite the {other} adapter"
if version == "v0.2":
    # The frozen export must still be byte-identical to what the manifest recorded.
    manifest = json.load(open(manifest_path, encoding="utf-8"))
    for split, expected in manifest["export_files_sha256"].items():
        path = os.path.join("data", "production", "exports", "rupsaa_v0.2", f"{split}.jsonl")
        actual = hashlib.sha256(open(path, "rb").read()).hexdigest()
        assert actual == expected, f"{path} changed since freeze ({actual} != {expected})"
    assert cfg["train.output_dir"] != os.path.join(root, "adapters", "rupsaa-v0.1"), "would overwrite the V0.1 adapter"
assert load_config()["last_model"] == cfg["top.model_name"], "page-load model_name would differ from the loaded one"
assert get_model_path("Custom") == cfg["top.model_path"], "page-load model_path would differ from the loaded one"

out = cfg["train.output_dir"]
if os.path.isdir(out) and os.listdir(out):
    print(f"WARNING: {out} already exists and is not empty — LLaMA-Factory will refuse to train into it "
          "unless it's a resumable checkpoint dir. Move it aside before pressing Start.", file=sys.stderr)
PYEOF

echo "=============================================================="
echo " LLaMA-Factory WebUI for Rupsaa ${VERSION}"
echo "  project root : $ROOT"
echo "  config file  : $ROOT/config/$CONFIG_NAME (rendered from $TEMPLATE)"
echo "  GUI 'Config path' field — type exactly:  $CONFIG_NAME   then click 'Load arguments'"
if [ "$VERSION" = "v0.2.1" ]; then
  echo "  dataset      : rupsaa_v0.2.1_train  (Data dir: data/production/exports/rupsaa_v0.2.1)"
else
  echo "  dataset      : rupsaa_${VERSION}_train  (registered in data/dataset_info.json)"
fi
echo "  adapter out  : $ROOT/adapters/rupsaa-${VERSION}"
echo "  listening on : 0.0.0.0:$PORT   -> open/forward ONLY port $PORT in Lightning"
echo "  untouched    : 5500 (Rupsaa web), 8000 (Rupsaa API)"
echo "  Training does NOT start until you press Start in the GUI."
echo "=============================================================="

if [ "${RUPSAA_GUI_DRY_RUN:-0}" = "1" ]; then
  echo "RUPSAA_GUI_DRY_RUN=1: config rendered and verified; not starting the WebUI."
  exit 0
fi

export GRADIO_SERVER_NAME=0.0.0.0
export GRADIO_SERVER_PORT="$PORT"
export GRADIO_ANALYTICS_ENABLED=False
exec "$LF_CLI" webui
