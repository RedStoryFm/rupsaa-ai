# Rupsaa — current release (Gemma, owner live test round 2)

This is the one page you need to rebuild the current Rupsaa on a fresh Lightning Studio. Older experiments (the
Qwen V0.1–V0.2.2 releases) keep their records under `release/` and `data/production/reports/`, but they are not
part of this release.

## What runs

```
google/gemma-3-12b-it                  base model, 4-bit NF4, bf16 compute   (Hugging Face, gated)
  + adapters/rupsaa-v0.3-gemma3-final  final Rupsaa LoRA                     (release record: release/rupsaa-v0.3-gemma3-final/)
  + v0.2 persona prompt                the prompt the adapter was trained with
  + serving notes                      identity + conversational style       (rupsaa/personality/system_prompt.py)
  + runtime knowledge (RAG)            owner records, NOT in the LoRA        (knowledge/terminology, knowledge/dance, knowledge/documents)
  + routing / language / recall        router, language directive, same-session memory note (rupsaa/rag, rupsaa/conversation)
  + Internet switch (per chat)         Wikipedia look-ups for questions owner knowledge can't answer (rupsaa/rag/web_search.py)
  + opt-in long-term memory            per-browser, user-controlled (rupsaa/conversation/user_memory.py)
  + FastAPI                            127.0.0.1:8000                        (api/)
  + web UI                             port 5500; proxies /api/* to 8000     (web/)
```

| Item | Value |
|---|---|
| Adapter SHA-256 | `3c79e394578261cdb04033867a9d6a96bb20784d5b0fc9d78d20e1b057724f05` |
| Training dataset | `rupsaa_v0.3_final`, 1,804 conversations, SHA-256 `6eedeb105c5ebd069d59aca751a4df849767a192ad96944c6de79fbe87fbdc69` (`data/production/exports/rupsaa_v0.3_final/`) |
| Generation | temperature 0.55, top-p 0.9, top-k 50, repetition penalty 1.1 (`configs/inference.yaml`) |
| Prompt | `RUPSAA_PROMPT_VERSION=v0.2`; serving notes on (`RUPSAA_SERVING_NOTES=0` restores the exact trained prompt) |
| Gemma serving fixes | explicit bf16 compute dtype (`rupsaa/model/loader.py`); stop on `<end_of_turn>` (`rupsaa/model/generation.py`) |
| Knowledge | 40 terminology records, 60 dance records (every dance has a Bengali-script alias), 5 General Knowledge test records, identity/FAQ documents |
| App layers (not weights) | Rupsaa Conversational Core V1 + Personal AI V1: General Knowledge, user memory, internet ASK/ALLOW/DENY with trusted source routing, in-chat Teacher Mode — see [PERSONAL_AI_V1.md](PERSONAL_AI_V1.md) |
| GPU | NVIDIA L4 (23 GB) is enough for inference: about 11.6 GB, about 8 s for a short reply |

## Fresh Studio: rebuild

```bash
git clone https://github.com/RedStoryFm/rupsaa-ai.git && cd rupsaa-ai
bash setup_rupsaa.sh                       # project environment, known words, folders
bash scripts/setup_gemma_stack.sh          # transformers 4.57.6 etc. into ../.gemma_stack (Gemma 3 support)
hf auth login                              # an account that has accepted the Gemma license
cp .env.example .env                       # then set OWNER_API_KEY (>= 32 chars) and CORS_ORIGINS — never commit .env
```

**Adapter.** Put the adapter folder at `adapters/rupsaa-v0.3-gemma3-final/`. It is not in git. There are two ways:
- Restore it from a backup copy: `python scripts/fetch_adapter.py --from-dir <copy>`.
- Download it from Hugging Face once it has been published: `python scripts/fetch_adapter.py`, which downloads to that folder.

Then confirm the files: `python scripts/fetch_adapter.py --check-only` should print `OK: 3 files match release checksums`. The launcher also refuses to start if the adapter's SHA-256 differs from `RUPSAA_ADAPTER_SHA256`.

`.env` (names only; the values for the current release are in `.env.example`):

| Variable | Purpose |
|---|---|
| `RUPSAA_ENV=production` | Fail-closed production checks |
| `RUPSAA_MODEL_PATH=google/gemma-3-12b-it` | Base model |
| `RUPSAA_ADAPTER_PATH` | Adapter folder |
| `RUPSAA_ADAPTER_SHA256` | Pinned adapter hash |
| `RUPSAA_PROMPT_VERSION=v0.2` | Persona prompt version |
| `OWNER_API_KEY` | Owner endpoints (secret) |
| `CORS_ORIGINS` | Allowed browser origins |
| `API_PORT=8000`, `WEB_PORT=5500` | Ports |
| `HUGGINGFACE_TOKEN` | Optional; secret |

## Operate

```bash
cd rupsaa-ai
bash scripts/start_rupsaa_production.sh --check   # validate only
bash scripts/start_rupsaa_production.sh           # start (foreground)
bash scripts/stop_rupsaa_production.sh            # stop
```

The start script puts `../.gemma_stack` (from `scripts/setup_gemma_stack.sh`) first on `PYTHONPATH` automatically
when it exists. Set `RUPSAA_GEMMA_STACK` to use another location. Without it, the older project transformers fails
with `model type gemma3 not recognized`.

To keep it running after the terminal closes:

```bash
setsid nohup bash scripts/start_rupsaa_production.sh > logs/production.log 2>&1 &
```

Loading the base model and adapter takes a few minutes on an L4. It is ready when `curl -s 127.0.0.1:8000/ready`
returns `"ready":true`. Then check:
- `/health`
- `/model/info` — shows `google/gemma-3-12b-it`, `rupsaa-v0.3-gemma3-final`, `prompt_version v0.2`, `cuda:0`

For the full post-start check, run `python scripts/production_smoke.py`.

Only **port 5500** is opened, through Lightning's port forwarding. Port 8000 stays on loopback.

## Knowledge order, Internet and memory
- **Knowledge order.** Owner records are used first: terminology and dance. Owner documents come next, then the web.
  The web is used only when the chat's **Internet** switch is on and the message is a real general-knowledge
  question. Greetings, questions about Rupsaa or the user, memory questions and follow-ups never go to the web.
- **What leaves the server.** Only the cleaned question does (e.g. "Taj Mahal kothay?" → `Taj Mahal`).
  Chat history and memory are never sent. Results go into the prompt as *untrusted* facts-only text, and sources
  appear under the reply as links. `RUPSAA_WEB_SEARCH_PROVIDER=none` turns web access off for the whole server.
- **Memory is off by default.** The user turns it on in the **Memory** dialog. The browser keeps a random
  ID; there is no login. Once memory is on, Rupsaa stores only:
  - self-statements (name, where the user lives, favourites, likes, work, study, pets, birthday)
  - things the user explicitly asks her to remember ("mone rekho …")
- **Reading and deleting memory.**
  - The Memory dialog lists what Rupsaa has stored.
  - Asking "what do you remember about me?" / "amar bishoye ki jano?" makes her answer from it.
  - "Forget everything", turning memory off, or "amake bhule jao" deletes it immediately.
  - The data lives in `data/user_memory/`, one file per SHA-256-hashed ID, and is git-ignored.

## Owner tools
- Chat: `<5500 URL>/`
- Knowledge Manager (documents, terminology, dance: create / edit / import / routing test): `<5500 URL>/knowledge.html`
- Teach (review examples): `<5500 URL>/teach.html`

Owner API calls need the `OWNER_API_KEY` header. Knowledge edits are live on the next message; no retraining is
needed. After changing documents, rebuild the RAG index from the Knowledge Manager.

## Owner live test
1. Start production (above) and wait for `/ready`.
2. Open the forwarded port-5500 URL and chat in Banglish, Bengali and English. Cover:
   - definitions (Strip, Foreplay)
   - dances, including a switch to Bengali ("এবার বাংলায় বলো")
   - memory ("amar favourite color blue" … "ami ki color bolechilam?")
   - identity ("tumi ke?", "tomake ke create koreche?")
3. Watch for the known soft spots:
   - occasional awkward Banglish phrasing
   - a question in response to a shared preference
4. Stop with `bash scripts/stop_rupsaa_production.sh`.

## Before any public release
- **Gemma terms.** `google/gemma-3-12b-it` is under the Gemma Terms of Use and Prohibited Use Policy. The policy
  forbids "sexually explicit content … (e.g. sexual chatbots)", except for scientific, educational, documentary or
  artistic purposes. Check that Rupsaa's use is compatible before publishing the adapter or launching publicly.
- **Visibility.** Both hosting locations are public. The GitHub repository `RedStoryFm/rupsaa-ai` includes the
  training datasets and knowledge. The Hugging Face repository `rstudioModel/rupsaa` is also public, and its adapter
  upload is prepared but waits for approval: `python scripts/release_gemma_final.py upload --yes`.
