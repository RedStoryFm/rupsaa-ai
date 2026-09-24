# Rupsaa: backup and restore

## What lives where

| What | Backed up in | Restored by |
|---|---|---|
| Code: API, web UI, `rupsaa/` package, scripts, tests | GitHub repo | `git clone` |
| Configs: model, inference, RAG, dataset, training, release | GitHub (`configs/`) | `git clone` |
| Known-working environment | GitHub: `requirements.txt` (pinned direct deps), `configs/environment/rupsaa-v0.1-environment.txt` (full `pip freeze` reference), `scripts/setup_llamafactory.sh` (LLaMA-Factory 0.7.1 plus its gradio patches) | `bash setup_rupsaa.sh` |
| **Rupsaa V0.1 LoRA adapter** | **Hugging Face model repo**, folder `rupsaa-v0.1/`, tag `rupsaa-v0.1` | `setup_rupsaa.sh` → `scripts/fetch_adapter.py` (checksum-verified) |
| Base model `Qwen/Qwen2.5-7B-Instruct` | Not backed up (public on the Hub) | Downloaded by the app on the first chat |
| Frozen V0.1 dataset: snapshot records, approved/draft corpus, train/validation/test split | GitHub (`data/production/`), about 10 MB | `git clone`, verified by `verify_installation.py` |
| Dataset identity | `release/rupsaa-v0.1/manifest.json` (SHA-256 `2df53399…6fa2a`) and `checksums.sha256` | Verified, never regenerated |
| Voice Bible, audit, evaluation and V0.2 preparation reports | GitHub (`data/production/`) | `git clone` |
| Knowledge documents | GitHub (`knowledge/documents/`) | `git clone` |
| **Terminology records** | GitHub (`knowledge/terminology/term-*.json`) | `git clone`; used as-is, no rebuild |
| RAG vector index | Not backed up (generated) | `setup_rupsaa.sh` rebuilds it from `knowledge/documents` |
| Release record: manifest, checksums, model card | GitHub (`release/rupsaa-v0.1/`) | `git clone` |

**Intentionally not backed up**

| Item | Why it's excluded |
|---|---|
| `.env`, tokens, `OWNER_API_KEY` values | Secrets |
| `checkpoints/`, `adapters/*/checkpoint-*`, optimizer and scheduler state, `training_args.bin` | Training intermediates. They stay on the Studio disk and are never deleted by any script. |
| Tokenizer copies inside the adapter folder | Identical to the base model's tokenizer |
| `merged_model/` | The adapter is never merged |
| `~/.cache/huggingface` | 15 GB base-model cache |
| `knowledge/index/` | Rebuilt from documents |
| `cache/`, `config/`, `saves/` | LLaMA-Factory GUI and runtime state |
| `*.log`, `__pycache__`, `.pytest_cache` | Logs and caches |
| Timestamped `audit_*` / `stats_*` report runs | Regenerable with the dataset scripts |
| Chat conversations | Kept in memory only, never written to disk |

## Restore on a brand-new Lightning Studio

```bash
git clone <YOUR-GITHUB-REPO-URL> rupsaa-ai
cd rupsaa-ai
hf auth login                  # only if the Hugging Face model repo is PRIVATE (paste a read token when asked)
bash setup_rupsaa.sh
bash scripts/start_rupsaa_v01.sh
```

Then open **port 5500** in the Studio's port viewer. Leave 8000 closed; it's the internal API.

**What `setup_rupsaa.sh` does:**
1. Checks for Linux, Python 3.10–3.12 and the GPU.
2. Installs torch 2.8.0+cu128 only if torch is missing.
3. Installs the pinned requirements and the LLaMA-Factory GUI with its patches.
4. Downloads the V0.1 adapter from the Hugging Face repo in `configs/release.yaml`.
5. Verifies every adapter file against `release/rupsaa-v0.1/checksums.sha256`.
6. Rebuilds the RAG index.
7. Runs the unit tests and `scripts/verify_installation.py`.

It's safe to re-run.

**What it deliberately skips:** it doesn't download the 15 GB Qwen weights. The first chat message does that once, so that reply can take several minutes.

**Options**

| Variable | Effect |
|---|---|
| `RUPSAA_HF_REPO=<user>/<repo>` | Adapter repository (default: `hf_repo_id` in `configs/release.yaml`) |
| `RUPSAA_HF_REVISION=<tag/branch/sha>` | Which revision to download (default: the release tag `rupsaa-v0.1`) |
| `RUPSAA_ADAPTER_PATH=<dir>` | Where the adapter lives (default `adapters/rupsaa-v0.1`; the app reads the same variable) |
| `RUPSAA_ADAPTER_FROM_DIR=<dir>` | Restore from a local copy (e.g. a downloaded backup) instead of the Hub; still checksum-verified |
| `RUPSAA_ALLOW_NO_ADAPTER=1` | Finish setup without an adapter (base model only) |
| `RUPSAA_INSTALL_TORCH=1` | Force the known-good torch build |
| `RUPSAA_SKIP_PIP`, `RUPSAA_SKIP_LLAMAFACTORY`, `RUPSAA_SKIP_RAG`, `RUPSAA_SKIP_TESTS` | Set to `1` to skip that step |

**Hugging Face authentication:**
- Run `hf auth login` once in the Studio terminal and paste a **read** token created at huggingface.co → Settings → Access Tokens.
- Alternatively, export `HF_TOKEN` in your shell for one session.
- Never write a token into this repository, `.env.example` or any config file.

## Verify the trained model is loaded

1. Start the app with `bash scripts/start_rupsaa_v01.sh`.
2. Send one chat message; the model loads lazily.
3. Open `<your 5500 URL>/api/model/info`. It should return:

```json
{
  "base_model_id": "Qwen/Qwen2.5-7B-Instruct",
  "adapter_path": ".../adapters/rupsaa-v0.1",
  "quantized": true,
  "adapter_loaded": true,
  "configured_adapter_exists": true
}
```

Before the first message, `adapter_loaded` is `false` and `configured_adapter_exists` is `true`. That's expected.

**Offline check (no model load):**

```bash
python scripts/verify_installation.py
python scripts/fetch_adapter.py --check-only
```

## Keep GitHub up to date safely

```bash
bash scripts/sync_project.sh                                  # status + tests + secret/large-file audit (read-only)
bash scripts/sync_project.sh --commit "describe the change"   # stage + re-audit + commit
bash scripts/sync_project.sh --push                           # push current branch + new tags (asks first; never --force)
```

`scripts/repo_audit.py` blocks secrets, files over 5 MB, weights, checkpoints, caches and logs.

**First push only:**
1. Create the GitHub repository. **Private** is recommended, because the dataset is 18+ content.
2. Run `git remote add origin <url>`.
3. Run `gh auth login`.

## Publish a future version (e.g. V0.2) without touching V0.1

```bash
# 1. add a "v0.2" entry to VERSION_INFO in scripts/release_model.py (dataset identity, configs, limitations)
# 2. add releases.rupsaa-v0.2 to configs/release.yaml (revision/subfolder/local path/manifest/checksums)
python scripts/release_model.py prepare v0.2 adapters/rupsaa-v0.2          # manifest + checksums + model card
python scripts/release_model.py upload  v0.2 --repo <user>/<repo>          # dry run: shows exactly what would upload
python scripts/release_model.py upload  v0.2 --repo <user>/<repo> --yes    # upload to rupsaa-v0.2/ + tag rupsaa-v0.2
bash scripts/sync_project.sh --commit "release: rupsaa v0.2 record" && git tag rupsaa-v0.2
```

**Safeguards:**
- Each version goes to its own subfolder with its own tag.
- The upload refuses if that folder or tag already exists, and refuses if the local adapter no longer matches its manifest.
- It never creates repos or changes visibility.
- It publishes only the adapter weights and config, small training metadata, the model card, the manifest and the checksums. Never checkpoints, optimizer state, base weights or credentials.

**Switching the app to V0.2:** set `current_release: rupsaa-v0.2` in `configs/release.yaml`, then run `RUPSAA_ADAPTER_PATH=adapters/rupsaa-v0.2 bash scripts/start_rupsaa_v01.sh` (or add a V0.2 launcher). V0.1 stays downloadable from its tag.

## Publish V0.1 for the first time

This is the one-time step that needs your accounts.

1. On huggingface.co, create a **model** repository, Private recommended, e.g. `<you>/rupsaa`.
2. Put its id in `configs/release.yaml` (`hf_repo_id: "<you>/rupsaa"`).
3. Log in and upload:

```bash
hf auth login
python scripts/release_model.py upload v0.1 --repo <you>/rupsaa          # review the dry run
python scripts/release_model.py upload v0.1 --repo <you>/rupsaa --yes
```

4. Commit the updated `configs/release.yaml` and `release/rupsaa-v0.1/manifest.json` (the manifest now records the upload) with `scripts/sync_project.sh`.
