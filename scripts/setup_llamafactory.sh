#!/usr/bin/env bash
# Installs LLaMA-Factory's WebUI as an ADDITIONAL GUI training interface,
# alongside (not replacing) the existing scripts/train_qlora.py CLI pipeline.
#
# Why this exists / what it does:
#
# This Lightning AI Studio does not allow creating an isolated venv/conda
# env (`python3 -m venv` and `conda create` are both blocked by the
# platform: "A Studio has a default conda environment (max 1
# environment)"). So LLaMA-Factory has to install into the SAME
# environment that runs the existing Rupsaa QLoRA pipeline
# (torch==2.8.0+cu128, transformers==4.46.3, peft==0.21.0, trl==0.12.2,
# accelerate==1.15.0) — installing it carelessly risks upgrading/downgrading
# those and breaking scripts/train_qlora.py and rupsaa/model/loader.py.
#
# `llamafactory==0.7.1` is the newest LLaMA-Factory release whose
# dependency floor (transformers>=4.37.2, accelerate>=0.27.2,
# peft>=0.10.0, trl>=0.8.1 — all with NO upper bound) is already satisfied
# by the current installed versions, so pinning those four packages
# explicitly during install makes pip resolve everything WITHOUT touching
# them — verified via `pip install --dry-run` before ever installing for
# real, and via a before/after `pip list --format=freeze` diff afterward
# (only new, unrelated packages were added: gradio, fire, altair, etc.).
# Newer llamafactory releases (0.9.x) pin much newer transformers/trl and
# much older peft/accelerate than what's installed — installing those
# would force exactly the breaking upgrade/downgrade this script exists
# to avoid.
#
# `gradio` additionally needs pinning to the 4.x line (not the very
# latest) because llamafactory 0.7.1's WebUI code uses an older Gradio
# component API (gr.Chatbot(show_copy_button=...), removed in Gradio 6).
#
# Three small, surgical monkey-patches are applied to already-installed
# THIRD-PARTY packages (gradio_client, gradio) below — never to Rupsaa's
# own code — because this environment's fastapi/starlette/pydantic are
# much newer than anything llamafactory 0.7.1 / gradio 4.x was tested
# against in 2024, and two genuine upstream compatibility bugs surface as
# a result:
#   1. gradio_client's JSON-schema-to-python-type converter assumes every
#      sub-schema is a dict, but newer pydantic can legally emit a bare
#      bool (e.g. `"additionalProperties": false`) per the JSON Schema
#      spec — crashes with `TypeError: argument of type 'bool' is not
#      iterable`.
#   2. gradio's routes.py calls the OLD Starlette
#      `TemplateResponse(name, context)` calling convention; this
#      environment's Starlette (1.6.0) requires the newer
#      `TemplateResponse(request, name, context)` signature — crashes with
#      `TypeError: unhashable type: 'dict'` (the context dict gets bound to
#      the `name` parameter).
# These patches are idempotent (guarded) and safe to re-run.
#
# Usage:
#   bash scripts/setup_llamafactory.sh

set -euo pipefail

echo "== Installing llamafactory==0.7.1 without touching the existing training stack =="
pip install \
    "llamafactory==0.7.1" \
    "gradio==4.38.1" \
    "pillow==10.4.0" \
    "transformers==4.46.3" \
    "trl==0.12.2" \
    "peft==0.21.0" \
    "accelerate==1.15.0"

GRADIO_CLIENT_UTILS=$(python3 -c "import gradio_client.utils as u; print(u.__file__)")
GRADIO_ROUTES=$(python3 -c "import gradio.routes as r; print(r.__file__)")

echo "== Patching gradio_client bool-schema bug: $GRADIO_CLIENT_UTILS =="
python3 - "$GRADIO_CLIENT_UTILS" <<'PYEOF'
import sys
path = sys.argv[1]
src = open(path, encoding="utf-8").read()

marker = "if isinstance(schema, bool):"
if marker in src:
    print("  already patched, skipping")
else:
    old = '''def _json_schema_to_python_type(schema: Any, defs) -> str:
    """Convert the json schema into a python type hint"""
    if schema == {}:
        return "Any"'''
    new = '''def _json_schema_to_python_type(schema: Any, defs) -> str:
    """Convert the json schema into a python type hint"""
    if isinstance(schema, bool):
        # JSON Schema allows `additionalProperties`/`items` to be a bare
        # bool instead of a schema object; newer pydantic emits this and
        # this gradio_client release predates handling it.
        return "Any"
    if schema == {}:
        return "Any"'''
    assert old in src, "gradio_client/utils.py structure changed — patch no longer applies, investigate manually"
    src = src.replace(old, new)
    open(path, "w", encoding="utf-8").write(src)
    print("  patched")
PYEOF

echo "== Patching gradio TemplateResponse calling convention: $GRADIO_ROUTES =="
python3 - "$GRADIO_ROUTES" <<'PYEOF'
import sys
path = sys.argv[1]
src = open(path, encoding="utf-8").read()

old = '''                gradio_api_info = api_info(False)
                return templates.TemplateResponse(
                    template,
                    {
                        "request": request,
                        "config": config,
                        "gradio_api_info": gradio_api_info,'''
new = '''                gradio_api_info = api_info(False)
                return templates.TemplateResponse(
                    request,
                    template,
                    {
                        "request": request,
                        "config": config,
                        "gradio_api_info": gradio_api_info,'''

if "TemplateResponse(\n                    request,\n                    template," in src:
    print("  already patched, skipping")
else:
    assert old in src, "gradio/routes.py structure changed — patch no longer applies, investigate manually"
    src = src.replace(old, new)
    open(path, "w", encoding="utf-8").write(src)
    print("  patched")
PYEOF

echo "== Verifying the existing Rupsaa training stack is untouched =="
python3 -c "
import torch, transformers, peft, trl, accelerate
assert transformers.__version__ == '4.46.3', transformers.__version__
assert peft.__version__ == '0.21.0', peft.__version__
assert trl.__version__ == '0.12.2', trl.__version__
assert accelerate.__version__ == '1.15.0', accelerate.__version__
print('OK — torch', torch.__version__, 'transformers', transformers.__version__,
      'peft', peft.__version__, 'trl', trl.__version__, 'accelerate', accelerate.__version__)
"

echo "== Done. Launch with: =="
echo "  bash scripts/start_llamafactory_gui.sh"
