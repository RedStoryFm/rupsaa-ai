# Final launch

For everything else (architecture, security detail, hosting options, rollback), see
[PRODUCTION_DEPLOYMENT.md](PRODUCTION_DEPLOYMENT.md) and [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md).
This page is only the sequence to run once a new adapter has passed.

```
MODEL PASSED (owner tested it and approved it)
   ↓
bash scripts/finalize_release.sh <adapter_path> <adapter_sha256> [prompt_version]
   → validates the adapter, backs up knowledge, writes .env, runs the config check
   ↓
bash scripts/start_rupsaa_production.sh --check
   → full check incl. GPU/ports — only run once the GPU is free (no training running)
   ↓
bash scripts/start_rupsaa_production.sh
   → starts the API + web proxy (foreground, or under tmux/systemd)
   ↓
until curl -sf localhost:${WEB_PORT:-5500}/api/ready; do sleep 10; done
   → waits for the model to finish loading
   ↓
OWNER_API_KEY=... python scripts/production_smoke.py \
    --base http://127.0.0.1:${WEB_PORT:-5500}/api --expect-adapter <adapter_name>
   → automated non-destructive checks against the running server
   ↓
owner live test (send a real message from the actual UI)
   ↓
expose URL (soft launch: share the Lightning port-5500 URL — see PRODUCTION_DEPLOYMENT.md §6)
```

Stop: `bash scripts/stop_rupsaa_production.sh`. Rollback: put the previous adapter path + SHA
back in `.env`, then repeat from the `--check` step.
