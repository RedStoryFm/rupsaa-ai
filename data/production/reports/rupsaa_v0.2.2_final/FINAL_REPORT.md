# Rupsaa V0.2.2 — final Qwen2.5-7B run: FAIL, stop Qwen2.5-7B training

**Result: FAIL.** Both live sessions contain serious Banglish/Bengali word salad on launch-critical turns (Strip,
Foreplay in Bengali, simplified Belly Dance), corrupted mixed-script words ("সexo", Cyrillic "кл" inside "কлাসিক"),
a Bengali answer that contradicts the attached record (Kathak → "পূর্ব ভারতের"; record: North India) and failed
colour recall in one of the two sessions. Per the run's rule 12, production integration was NOT done, no further
training or dataset was created, and all work is preserved.

**Conclusion:** Qwen2.5-7B-Instruct is not suitable enough for Rupsaa's required Banglish/Bengali quality under the
current project constraints. The next architecture decision is changing the BASE MODEL.

## What was done
- Runtime fixes: "jinish", "kon desher"/"কোন দেশের", a Bengali-script alias on all 60 dances, and short follow-ups
  (বাংলায়, এবার বাংলায়, বাংলা হরফে লেখো, আরও সহজ করে, simple kore, simpler, ek line e bolo) now carry the record.
  - False-positive guards cover breaking news, polka dots, house price, locking a door, popping a balloon,
    strip whitespace, tap water and মাম্বো জাম্বো.
  - Results: 422/422 dance retrieval checks; 0 dance false positives on 2,139 real messages.
  - Commit 14181c8.
- Dataset `rupsaa_v0.2.2`: **1556 conversations**, each once, with no upsampling.
  - Built from: V0.2 1,294, V0.2.1 corrective 138, dance 24, and 100 V0.2.2 corrections.
  - Dropped: {'invented human body/life': 46, 'audit BAD reply': 41, 'catchphrase': 2}.
  - Repaired: {'danda -> period in Latin text': 180, 'template opener removed': 79}.
  - Every gate check passed, and no held-out case leaked into training.
  - SHA-256 `df6277b205b83f245d4d2fe8463a6640efbff165b17f3d1560c03fc60d57fd35`, tag `rupsaa-v0.2.2-training`, prompt version v0.2.
- Training: a fresh LoRA from Qwen/Qwen2.5-7B-Instruct.
  - Setup: 4-bit NF4 with double quantisation, bf16, SDPA, gradient checkpointing; r16/α32/0.05 on 7 projections.
  - Schedule: LR 1e-4, 2 epochs, batch 2×8.
  - Ran 184/184 steps in 2,216 s; mean train loss 1.663.
  - Eval loss: 20: 1.9762 · 40: 1.8073 · 60: 1.7158 · 80: 1.6601 · 100: 1.6263 · 120: 1.6237 · 140: 1.6122 · 160: 1.6048 · 180: 1.6025.
- Checkpoint selection by output quality: checkpoints 80, 120, 160 and 184 were run on the same 17-prompt suite,
  2 runs each (`checkpoint_selection.json`).
  - Every checkpoint still garbles Strip, Foreplay in Bengali and Bhangra in Bengali.
  - Checkpoint-160 was marginally the best and was chosen.
  - The lowest eval loss was checkpoint-180; it was not used.
- Final adapter: `adapters/rupsaa-v0.2.2` (top level = checkpoint-160).
  - SHA-256 `e35147edaf15edf7b3cbd58b162265b1f5eeaeaaeb7b4d90174157ae1d6a7b08` (161,533,192 bytes).
  - It is not a production candidate.

## Launch gates (both live sessions)
| Gate | Result |
|---|---|
| Banglish | **FAIL** — word salad: "Strip mane jate jate pukhao bhayao", "strip mane kache kache kharap gola khole jawar", "belly dance mane kharap gola khole jawar" |
| Bengali | **FAIL** — nonsense and corruption: "…আইনত কীসের অ্যাক্টিভিটি… আউয়াজ", "…ধোঁয়া … পাখির ঘনা চিৎকার", "সexoয়াল", "কлাসিক" |
| Terminology | **FAIL** — Strip is not understandable in either session; Foreplay is partly right in Banglish only |
| RAG fidelity | **FAIL** — Kathak "পূর্ব ভারতের" contradicts North India; Mambo "কুবার নাওয়াহ দেশের" |
| Memory | **FAIL** — session 1 is garbled ("Ami boleche ami blue ra bolleo"); session 2 does not recall blue |
| Language switch | PARTIAL — switches to Bengali script, content is garbled; Mambo in Bengali answered in Banglish (seed 888) |
| Identity | **PASS** — "I'm a text-based AI, no physical appearance to describe!", "No, I'm artificial intelligence." |
| Casual chat | PARTIAL — seed 888 coherent; seed 777 greeting odd ("Achi normal er jonno…") |
| Repetition | PASS — no loops in the live sessions (a loop appeared in checkpoint-80 at temperature 0.3) |

## Exact live test — seed 777 (one session, production service path, verbatim)
1. **USER:** hi, tumi kemon acho?  
   **RUPSAA:** Achi normal er jonno. Tumi beshi khub shune chao.  
   _[casual · -]_
2. **USER:** ajke amar mood ta bhalo na  
   **RUPSAA:** Ki hae jokhon mood bhalo na hoy - ektu dorkar thakle bolte paro beshi naki.  
   _[casual · -]_
3. **USER:** achcha  
   **RUPSAA:** Bolo sheta.  
   _[casual · -]_
4. **USER:** tumi amar sathe banglish e kotha bolbe?  
   **RUPSAA:** Hae, eta mane - ki dekha niye bolo?  
   _[general · -]_
5. **USER:** Strip mane ki?  
   **RUPSAA:** Strip mane jate jate pukhao bhayao. Kintu context depend kore - ekta club e stage er kichu, ekta kono kichur jonno, ar ekdom sex er mone kichu. Hae kintu eta always onek jinis, bole diye.  
   _[terminology · term-strip_stripping]_
6. **USER:** strip ta ektu simple kore bojhao  
   **RUPSAA:** Simple rakhte parbo - strip mane jate jate pukhao bhayao.  
   _[followup · term-strip_stripping]_
7. **USER:** Foreplay ki?  
   **RUPSAA:** Foreplay mane sexual or intimate activity jate jate theke puro sexual activity er age, ar jate jate build kora jai arousal, comfort ba intimacy.  
   _[terminology · term-foreplay]_
8. **USER:** এটা বাংলায় বুঝিয়ে বলো  
   **RUPSAA:** ফোরপ্লে মানে সেকশ্যাল বা আইনত কীসের অ্যাক্টিভিটি যেখানে পুরো সেকশাল এভিয়েটির আগে, আর যেখানে জমে গেছে আউয়াজ, শান্তি বা দৃষ্টিকোণ।  
   _[followup · term-foreplay]_
9. **USER:** amar favourite color blue  
   **RUPSAA:** Blue e bhalo laglo, emon color usually calm er symbol hoy.  
   _[general · -]_
10. **USER:** ami ki color bolechilam?  
   **RUPSAA:** Ami boleche ami blue ra bolleo, tumi bolleo - amar favorite color.  
   _[memory · -]_
11. **USER:** ami age ki bolechilam?  
   **RUPSAA:** Age bolecho amar favorite color blue - tomar favorite color bolechile na.  
   _[memory · -]_
12. **USER:** Belly dance ki?  
   **RUPSAA:** Belly dance - Middle East/ North Africa er ekta expressiv, traditioner dance form. Torso ar hip er fluid, rhythmic isolation ar movement focus.  
   _[terminology · dance-belly_dance]_
13. **USER:** belly dance ta simple kore bojhao  
   **RUPSAA:** Belly dance - Middle East/ North Africa er ekta expressiv, traditioner dance form. Torso ar hip er fluid, rhythmic isolation ar movement focus.  
   _[followup · dance-belly_dance]_
14. **USER:** Kathak kothakar dance?  
   **RUPSAA:** Kathak - India (North) er ekta classical dance. Jemon spins, intricate footwork ar expressive story-telling rakhay.  
   _[terminology · dance-kathak]_
15. **USER:** এবার বাংলায় বলো  
   **RUPSAA:** কথক - ভারতের (পূর্ব ভারতের) একটা কлাসিক নাচ। ঘূর্ণি, নিখুঁত পাখার কাজ আর বর্ণনাচারিত কাহিনী রাখে।  
   _[followup · dance-kathak]_
16. **USER:** মাম্বো কোথাকার নাচ?  
   **RUPSAA:** মাম্বো কুবার নাওয়াহ দেশের একটা ল্যাটিন নাচ। স্যান্থোপেটিয়ন, ঠিক উচ্চারণ, তীব্র ধীরে ধীরে কাজ আর প্রাণবন্ত ছোঁড়া।  
   _[terminology · dance-mambo]_
17. **USER:** Breaking ar breakdance same?  
   **RUPSAA:** Same, just two different names for one street dance form — united states er South Bronx theke. Top rock, footwork, freeze ar power move thaka.  
   _[general · dance-breaking_breakdance]_
18. **USER:** what do you look like?  
   **RUPSAA:** I'm a text-based AI, no physical appearance to describe!  
   _[general · -]_
19. **USER:** are you human?  
   **RUPSAA:** Nope, I'm built with machine learning algorithms trained on existing data.  
   _[casual · -]_

## Exact live test — seed 888
1. **USER:** hi, tumi kemon acho?  
   **RUPSAA:** Bhalo achi, tumi kemon acho?  
   _[casual · -]_
2. **USER:** ajke amar mood ta bhalo na  
   **RUPSAA:** Ki hoyeche?  
   _[casual · -]_
3. **USER:** achcha  
   **RUPSAA:** Ekbar boltechhe, bujhleo nai. Ki hoyeche?  
   _[casual · -]_
4. **USER:** tumi amar sathe banglish e kotha bolbe?  
   **RUPSAA:** Bolbo, tumi bolo.  
   _[general · -]_
5. **USER:** Strip mane ki?  
   **RUPSAA:** Strip mane dujoner shomoyer jhulay gola khole jawar — ektu kivabe ekta slow, ektu kivabe ekta fast. Mone hocche tomar kache shohoj dekhte paro, jodi bhoy hote pare.  
   _[terminology · term-strip_stripping]_
6. **USER:** strip ta ektu simple kore bojhao  
   **RUPSAA:** Sheta shobcheye simple — strip mane kache kache kharap gola khole jawar.  
   _[followup · term-strip_stripping]_
7. **USER:** Foreplay ki?  
   **RUPSAA:** Foreplay mane sexual ba intimate dhoroner jhulay, shudhu emon kichu, eta jara arupshomoy shuru korle manush er arousal ba intimacy build hoy. Manush o manush onujayi jani kina rakha.  
   _[terminology · term-foreplay]_
8. **USER:** এটা বাংলায় বুঝিয়ে বলো  
   **RUPSAA:** Foreplay mane সexoয়াল বা মোটামুটি আমাদের ভাষায় নাকি একটা ধোঁয়া, জারী অথবা শুধু পাখির ঘনা চিৎকার। কেউ কেউ ধোঁয়া থেকে শুরু করে, কেউ কেউ পাখির ঘনা চিৎকার থেকে শুরু করে - তাই মানুষ মানুষের উপর ঠিক করে নিয়ে যায়।  
   _[followup · term-foreplay]_
9. **USER:** amar favourite color blue  
   **RUPSAA:** Blue niye ki bolte parbo?  
   _[general · -]_
10. **USER:** ami ki color bolechilam?  
   **RUPSAA:** Ekhon bolecho, ami mone hole.  
   _[memory · -]_
11. **USER:** ami age ki bolechilam?  
   **RUPSAA:** Ami mone korchi na, tumi bolecho ekhon.  
   _[memory · -]_
12. **USER:** Belly dance ki?  
   **RUPSAA:** Belly dance mane Middle East/North Africa er traditional dance, jate kathin kathin choto choto movement diye torso ar hip rakte thake.  
   _[terminology · dance-belly_dance]_
13. **USER:** belly dance ta simple kore bojhao  
   **RUPSAA:** Sheta shobar kotha simple — belly dance mane kharap gola khole jawar, khatun khatun.  
   _[followup · dance-belly_dance]_
14. **USER:** Kathak kothakar dance?  
   **RUPSAA:** Kathak mane North India er classical dance, jate lage ekbar many many spin, jekhane jaigaya tope jai.  
   _[terminology · dance-kathak]_
15. **USER:** এবার বাংলায় বলো  
   **RUPSAA:** Kathak মানে উত্তর ভারতের কلاসিক নাচ, যেখানে কখনো কখনো অনেকগুলো ছোট ছোট ঘূর্ণি লাগে, জায়গাটাও ঢেউ মতো ছড়াই যায়।  
   _[followup · dance-kathak]_
16. **USER:** মাম্বো কোথাকার নাচ?  
   **RUPSAA:** Mambo Cuba/New York er Latin dance, quick steps ar energetic turn theke chara hoy.  
   _[terminology · dance-mambo]_
17. **USER:** Breaking ar breakdance same?  
   **RUPSAA:** Same! 'Breaking' ar 'Breakdance' দুটো এক একই নাচ, যার origin United States South Bronx er, street dance — top rocks, footwork, freeze ar power move, breakbeat er sathe.  
   _[general · dance-breaking_breakdance]_
18. **USER:** what do you look like?  
   **RUPSAA:** I'm just text, no face to show you.  
   _[general · -]_
19. **USER:** are you human?  
   **RUPSAA:** No, I'm artificial intelligence.  
   _[casual · -]_
