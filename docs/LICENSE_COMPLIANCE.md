# Base-model license check — Gemma (2026-09-30)

This is a factual summary for the owner. It is **not legal advice**; get qualified advice before launching publicly.

## Sources, fetched 2026-09-30
- Gemma Terms of Use, https://ai.google.dev/gemma/terms (last modified April 1, 2026)
- Gemma Prohibited Use Policy, https://ai.google.dev/gemma/prohibited_use_policy (last updated February 21, 2024)

## What applies to Rupsaa

**The terms cover the Rupsaa adapter.** Terms §1.1(e) defines "Model Derivatives" to include "(i) modifications
to Gemma, (ii) works based on Gemma". A LoRA adapter trained on `google/gemma-3-12b-it` falls under this.

**The usage restriction binds the product itself.** Terms §3.2 says you must not use Gemma Services for the
"restricted uses set forth in the Gemma Prohibited Use Policy". The policy begins: "You may not use nor allow others
to use Gemma or Model Derivatives to:" and one of its listed prohibitions is:

> "Generate sexually explicit content, including content created for the purposes of pornography or sexual
> gratification (e.g. sexual chatbots). Note that this does not include content created for scientific,
> educational, documentary, or artistic purposes."

**Rupsaa's documented purpose matches the prohibited example.**
- The README describes Rupsaa as "an 18+ adult-oriented … conversational AI companion".
- Its terminology store is mostly intimate or sexual terms, such as Foreplay, Oral Play, Edging and Strip.
- The final dataset contains `flirty_contextual_adult` (44) and `adult_terminology_education` (63) conversations.

Plain educational definitions may fall under the "educational" exception. A flirtatious adult companion is close to
the policy's own example, "sexual chatbots".

**Making the repositories private does not resolve this.** The restriction applies to *using* the model and its
derivatives, whether or not they are published. Privacy only affects distribution.

**Google can restrict usage.** §3.2 reserves Google's right to "restrict (remotely or otherwise) usage of any of the
Gemma Services" that it reasonably believes violates the agreement.

**Distributing the adapter carries obligations.** Under §3.1, anyone who distributes a derivative must:
- pass the §3.2 use restrictions on to recipients
- give recipients a copy of the Terms
- mark modified files
- include a `NOTICE` file with the text "Gemma is provided under and subject to the Gemma Terms of Use found at
  ai.google.dev/gemma/terms"

The public upload `rstudioModel/rupsaa/rupsaa-v0.3-gemma3-final/` includes that sentence in its README, but it has
**no NOTICE file** and **no copy of the Terms**.

**Other policy items the runtime already satisfies:**
- no content involving minors (hard boundary before generation)
- no impersonation of real people
- no claiming to be human — the serving notes make Rupsaa say it is an AI

## Owner decisions (nothing has been changed on Hugging Face)
1. Choose one:
   - Narrow Rupsaa's use to what the policy allows (non-sexual companion, plus educational definitions); or
   - Use a base model whose license has no such restriction. The Qwen2.5 base is Apache-2.0, but its Banglish quality
     failed evaluation; see `data/production/reports/`.
2. If the Hugging Face upload stays public:
   - add a `NOTICE` file and a copy of the Gemma Terms (§3.1); or
   - make the repository private, or remove `rupsaa-v0.3-gemma3-final/`.

The adapter stays available locally either way.
