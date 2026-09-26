# V0.2 live failures — root cause

Source evidence (all in this folder): your live session's server log (route/terms per turn), a replay
of your exact 11-turn conversation through the real API before and after the runtime fixes
(`live_replay_before.json`, `live_replay_after.json`, 3 runs each), a full per-turn trace of what the
model received (`trace_after.jsonl`: route, terms, RAG, history, final system prompt, generation
settings), an adapter on/off ablation on those exact inputs (`adapter_ablation.json`), and a
read-only analysis of the frozen V0.2 training set.

## What the runtime did in your session (server log)

| turn | route | terminology | RAG docs |
|---|---|---|---|
| hi, tumi kemon acho? · ajke amar mood ta bhalo na · achcha | casual | – | 0 |
| tumi amar sathe banglish e kotha bolbe? | general | – | 0 |
| Strip mane ki? | terminology | term-strip_stripping | 0 |
| strip ta ektu simple kore bojhao | followup | term-strip_stripping (carried) | 0 |
| Forplay ki? | terminology | term-foreplay (typo matched) | 0 |
| এটা বাংলায় বুঝিয়ে বলো | followup | term-foreplay (carried) | 0 |
| amar favourite color blue | general | – | 0 |
| ami ki color bolechilam? · ami age ki bolechilam? | memory | – | 0 |

Every route was correct, no documents were attached anywhere, and the full conversation history
(up to 20 messages) reached the model every turn. Generation: temperature 0.8, top-p 0.9, top-k 50,
repetition penalty 1.1, max 512 tokens (`configs/inference.yaml`).

## The five questions

1. **"Strip mane ki?" did not reliably use the Strip record — it did.** The router extracted "Strip",
   the store matched `term-strip_stripping` exactly, and the system prompt contained its full entry
   (definition "Removing clothing, sometimes gradually…", details, owner guidance). The model received
   the right knowledge and rendered it as garbled Banglish ("kichu niye kichu remove kora, typically
   bishoyer jonno") or switched to English. **MODEL.**
2. **"Forplay ki?"** — the router extracted "Forplay"; no exact key; the fuzzy matcher scored it
   against "foreplay" (ratio 0.94 ≥ 0.85) and attached `term-foreplay`. Routing worked. The reply
   quality ("kichu sex e bishoy der jonno kichu make karar effort") is the model. While tracing,
   the fuzzy matcher itself was too loose on real words ("content"→Consent, "testing"→Tease,
   "soon"→Spooning, "tripping"→Strip): fixed (see below). **Routing OK; reply MODEL.**
3. **Bengali request stayed Banglish.** The turn routed as a follow-up and carried the Foreplay entry,
   but nothing in the prompt said *which* language the user had asked for — only V0.2's general
   "mirror the user's language … only switch fully if asked". The terminology block and the whole
   history were Banglish/English, and V0.2's training set has **5 language-switch turns in 1,938**
   (one towards Bengali script, and it doesn't re-explain anything). **BOTH:** missing runtime
   directive + no training signal.
4. **"ami ki color bolechilam?" succeeded** because the fact was in the history two turns earlier and
   the question names it. It is also literally in the V0.2 training set: the only memory example
   there is `rup-001500` "ami ki color bolechilam?" → "Blue bolechile." (1 of 1,938 turns).
5. **"ami age ki bolechilam?" failed.** Routed to memory correctly, but the runtime note said "the
   conversation so far is above" — wrong (history comes *after* the system prompt) — and gave the
   model nothing structured to answer from. Zero training examples of generic recall. The ablation
   shows the base model without the adapter is no better. **BOTH.**

## Banglish quality — MODEL

- The V0.2 training Banglish is mostly natural (spot-read of 22 random replies; 0 mixed-script
  corruption in 1,938 replies). The garbled phrasing is not copied from the data.
- But the Banglish signal is small (~880 Banglish/mixed replies, ~125 chars each ≈ 40K tokens) and its
  romanization is split ~50/50 on common words (shobcheye 19 / sobcheye 15, bhalo 23 / valo 19,
  shomoy 27 / somoy 31, sheta 130 / seta 33), which spreads probability over variants.
- **Adapter ablation (same inputs, adapter off):** base Qwen2.5-7B is *worse* at Banglish ("Strip mane
  ki dui fashan o proyaktik rolik kora jay", "Ami jiboner upaj, ghashon er daptor hoil") and corrupts
  Bengali script ("সexoয়াল"). V0.2 improved Banglish over the base; the remaining gap is the base
  model's weak Banglish plus too little targeted data — not damage done by the LoRA.

## Why training loss improved while Banglish generation stayed poor

Clean-test loss by language (V0.2 / base): Bengali 0.74 / 1.33, mixed 1.49 / 2.99, English 1.70 / 4.09,
**Banglish 3.00 / 5.72**. Banglish improved the most in absolute terms, but its per-token loss is
still ≈ 3.0 (perplexity ≈ 20) — the model remains very unsure of the next Banglish word. Much of the
gain is format and register (short replies, persona, ending on time), which loss rewards heavily.
With sampling at temperature 0.8 from such a flat distribution, fluent-looking but semantically empty
Banglish is the expected result. A decoding probe (post-training report) showed temperature 0.5 gives
somewhat cleaner Banglish but does not fix switching or recall.

## Training-data coverage of the failing behaviours (frozen V0.2 train, 1,938 user→assistant turns)

| behaviour | examples |
|---|---|
| explicit language-switch requests | 5 (1 towards Bengali script) |
| generic "what did I say earlier" recall | 0 (1 specific: the colour question) |
| bare acknowledgements ("achcha", "hmm", "bujhlam") | 1 ("achcha" → "Achcha, bolo? Ki mone ache?") |
| definition questions (router → terminology) | 36 (14 Banglish) |
| records with a terminology block in the system prompt | 30 |
| replies ending with a question | 28% overall (Banglish 32%) — the "always ask back" habit |

## Runtime fixes made (generic; no hard-coded answers)

- **Language control** (`rupsaa/conversation/language_control.py`): explicit requests ("banglay bolo",
  "বাংলায় বলো", "bengali te bolo", "banglish e bolo", "english e bolo", "in English", "…-i" forms) set the
  reply language for that turn and its follow-ups ("from now on" makes it stick); ordinary messages
  resume mirroring. The system prompt gets one quoted directive, last, e.g. *Response language: in the
  message "এটা বাংলায় বুঝিয়ে বলো" the user explicitly asked for Bengali. From that message on, write in
  Bengali script …*. Mentions of a language ("ami bangla bhalo bujhi na") are not requests.
- **Conversation recall** (`rupsaa/rag/context_builder.py`): memory questions get the user's own
  earlier messages as a numbered, oldest-first list (up to 12, quoted question, never documents),
  replacing the misleading "above" note. The answer is not computed — the model picks it.
  Router now also catches "ami age ki bolechi", "ager message e ki bolechilam", "ami kar/keno/kothay …
  bolechilam", "আমার … কী বলেছিলাম".
- **Terminology**: typo matching now skips real English words (whole-word Qwen vocabulary list,
  `rupsaa/rag/known_words.txt`) and requires the same first letter; one-edit typos (stirp, consnet)
  still match. An exact term match no longer drags in a second term through a sub-phrase alias
  ("lip biting" ↛ Bite, "public teasing" ↛ Tease, "dirty whisper" ↛ Whispering).
- **Router**: "bujhlam" (= got it) is no longer treated as "didn't understand"; "শর্ট করে", "chhoto
  kore", "বুঝিয়ে দাও", "likhe dao" follow-ups recognised.
- **Diagnostics**: `RUPSAA_TRACE_FILE=<file.jsonl>` records exactly what the model receives per turn
  (off by default); `/chat` returns `response_language`.
