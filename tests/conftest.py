import os
import sys
from pathlib import Path

# Test isolation: never read the project's real .env (it may hold production settings and the
# owner key). Must run before anything imports rupsaa.config; subprocess-based tests inherit it.
os.environ["RUPSAA_ENV_FILE"] = ""
# Production-only variables a developer shell might export must not leak into tests either.
for _var in ("RUPSAA_ENV", "RUPSAA_MODEL_PATH", "MODEL_ID", "RUPSAA_ADAPTER_PATH", "ADAPTER_PATH",
             "RUPSAA_ADAPTER_SHA256", "RUPSAA_PROMPT_VERSION", "OWNER_API_KEY", "RUPSAA_PRELOAD_MODEL"):
    os.environ.pop(_var, None)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
