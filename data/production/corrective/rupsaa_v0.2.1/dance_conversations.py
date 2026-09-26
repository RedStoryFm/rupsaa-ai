"""Rupsaa V0.2.1 R2 — dance conversations (hand-written, grounded ONLY in the owner's records).

Facts come from knowledge/dance/ (owner list data/owner/dance_knowledge_owner_60.txt). The LoRA
learns HOW to use a retrieved dance entry (answer first, right language, right length, no invented
steps); the 60 facts themselves stay in RAG. Built by scripts/v021_build_corrective.py with the real
runtime, so each record's system prompt carries the dance block exactly as the app sends it.

Selection:
  * the owner's showcase dances (Belly Dance, Ballet, Kathak, Voguing, Breaking, Haka, Bhangra) are
    in NEITHER set — owner live tests measure generalisation
  * DANCE_HOLDOUT dances never occur in DANCE_TRAIN (checked by v021_leakage_check.py)
Style: BANGLISH_STYLE_GUIDE.md.
"""

DANCE_TRAIN = [
    {"id": "d021-01", "category": "dance_definition", "language": "banglish", "expect_terms": ["dance-salsa"], "turns": [
        ("salsa ki?", "Salsa ekta lively partner dance — syncopated steps, turn ar hip motion diye nacha hoy, salsa music er sathe. "
                      "Eta Cuba, Puerto Rico ar New York theke esheche.")]},
    {"id": "d021-02", "category": "dance_definition", "language": "bn", "expect_terms": ["dance-bharatanatyam"], "turns": [
        ("ভরতনাট্যম কী?", "ভরতনাট্যম ভারতের তামিলনাড়ুর একটি ধ্রুপদী নাচ। এতে জ্যামিতিক ভঙ্গি, অভিব্যক্তিপূর্ণ অঙ্গভঙ্গি, "
                         "ছন্দময় পায়ের কাজ আর গল্প বলা — সব একসাথে থাকে।")]},
    {"id": "d021-03", "category": "dance_definition", "language": "en", "expect_terms": ["dance-waltz"], "turns": [
        ("What is a waltz?", "A smooth ballroom dance in 3/4 time — lots of flowing turns and a rise-and-fall movement. "
                             "It comes from Austria and Germany.")]},
    {"id": "d021-04", "category": "dance_origin", "language": "banglish", "expect_terms": ["dance-samba"], "turns": [
        ("samba kothakar dance?", "Samba Brazil er dance. Khub lively — druto footwork, hip er movement ar ekdom Carnival er moto energy.")]},
    {"id": "d021-05", "category": "dance_origin", "language": "bn", "expect_terms": ["dance-kathakali"], "turns": [
        ("কথাকলি কোথাকার নাচ?", "কথাকলি ভারতের কেরালার। এটা একটা ধ্রুপদী নৃত্যনাট্য — জমকালো মেকআপ, পোশাক আর নিয়মে বাঁধা "
                               "অঙ্গভঙ্গি এর বিশেষত্ব।")]},
    {"id": "d021-06", "category": "dance_origin", "language": "en", "expect_terms": ["dance-kabuki"], "turns": [
        ("Where is Kabuki from?", "Japan. It's a classical Japanese dance-drama, known for stylized movement, elaborate costumes "
                                  "and dramatic makeup.")]},
    {"id": "d021-07", "category": "dance_simplify", "language": "banglish", "expect_terms": ["dance-popping"], "turns": [
        ("popping ki?", "Popping ekta funk street dance style, United States er California theke. Muscle khub druto contract ar "
                        "relax kore ekta 'pop' ba hit toiri kora — etai er mul kotha."),
        ("aro simple kore bolo", "Muscle ek jhatkay tight kore abar chhere dile shorire ekta hit dekha jay. Oi hit tai popping.")]},
    {"id": "d021-08", "category": "dance_detail", "language": "banglish", "expect_terms": ["dance-hip_hop"], "turns": [
        ("hip hop dance niye ektu detail e bolo", "Hip-Hop ekta street dance style, United States er Bronx, New York theke, ar "
                                                   "hip-hop culture er sathe jora. Ei dance e char ta jinis khub gurutto pay — groove, "
                                                   "freestyle, battle ar shokto musicality. Mane shudhu step na, gaan er sathe shorir "
                                                   "ta kotota mile jacche, shetai ashol.")]},
    {"id": "d021-09", "category": "dance_comparison", "language": "banglish", "expect_terms": ["dance-bachata", "dance-merengue"], "turns": [
        ("bachata ar merengue er modhhe tofat ki?", "Dutoi Dominican Republic er partner dance, kintu mejaj alada. Bachata romantic — "
                                                     "four-step rhythm, close embrace ar halka hip movement. Merengue druto ar shohoj — "
                                                     "marching step er moto chola, sathe shokto hip action.")]},
    {"id": "d021-10", "category": "dance_comparison", "language": "en", "expect_terms": ["dance-rumba", "dance-cha_cha"], "turns": [
        ("What's the difference between rumba and cha-cha?", "Both come from Cuba. Rumba is slow and expressive — the focus is hip "
                                                              "movement, connection and romantic storytelling. Cha-cha is more playful: "
                                                              "a Latin ballroom dance built on a triple step with rhythmic hip motion.")]},
    {"id": "d021-11", "category": "dance_comparison", "language": "bn", "expect_terms": ["dance-lion_dance", "dance-dragon_dance"], "turns": [
        ("lion dance আর dragon dance এর পার্থক্য কী?", "দুটোই চীনের নাচ, তবে ধরন আলাদা। লায়ন ডান্সে সিংহের পোশাক পরে, ঢোলের "
                                                       "তালে মার্শাল আর্টের মতো নড়াচড়া করা হয় — সৌভাগ্য আর উৎসবের জন্য। "
                                                       "ড্রাগন ডান্স উৎসবের নাচ, যেখানে কয়েকজন মিলে একটা লম্বা ড্রাগন পাপেটকে তালে তালে "
                                                       "ঢেউয়ের মতো দুলিয়ে আর ঘুরিয়ে নিয়ে যায়।")]},
    {"id": "d021-12", "category": "dance_alias", "language": "banglish", "expect_terms": ["dance-forro"], "turns": [
        ("forro dance ta ki?", "Forró Brazil er ekta partner dance. Close embrace e nacha hoy, steps gulo shohoj, sathe rhythmic turn.")]},
    {"id": "d021-13", "category": "dance_alias", "language": "banglish", "expect_terms": ["dance-cha_cha"], "turns": [
        ("chacha dance kemon?", "Cha-Cha ekta playful Latin ballroom dance, Cuba theke. Eta chena jay triple step ar rhythmic hip motion diye.")]},
    {"id": "d021-14", "category": "dance_typo", "language": "banglish", "expect_terms": ["dance-kuchipudi"], "turns": [
        ("kuchipuri ki?", "Kuchipudi er kotha bolcho mone hoy — eta India er Andhra Pradesh er ekta classical dance. Graceful movement, "
                          "rhythmic footwork ar dramatic expression — ei tin ta mile Kuchipudi.")]},
    {"id": "d021-15", "category": "dance_typo", "language": "en", "expect_terms": ["dance-mazurka"], "turns": [
        ("what's a mazurca?", "You mean the mazurka — a traditional Polish dance in triple time, with lively turns, heel clicks and "
                              "a folk character.")]},
    {"id": "d021-16", "category": "dance_language_switch", "language": "en", "expect_terms": ["dance-krump"], "turns": [
        ("krump ki?", "Krump ekta high-energy street dance style, United States er Los Angeles theke. Movement gulo aggressive ar "
                      "expressive — chest pop, stomp ar freestyle expression er upor bhor kore."),
        ("english e bolo", "Krump is a high-energy street dance style from Los Angeles in the United States. It uses aggressive, "
                           "expressive movement — chest pops, stomps and freestyle expression.")]},
    {"id": "d021-17", "category": "dance_language_switch", "language": "bn", "expect_terms": ["dance-lavani"], "turns": [
        ("lavani ki?", "Lavani India er Maharashtra er ekta traditional dance-drama. Rhythmic footwork, expressive gesture ar lively "
                       "music — ei niyei Lavani."),
        ("banglay bolo", "লাবণী ভারতের মহারাষ্ট্রের একটি ঐতিহ্যবাহী নৃত্যনাট্য। ছন্দময় পায়ের কাজ, ভাবপ্রকাশক অঙ্গভঙ্গি আর "
                         "প্রাণবন্ত সংগীত — এই নিয়েই লাবণী।")]},
    {"id": "d021-18", "category": "dance_comparison", "language": "banglish", "expect_terms": ["dance-sufi_whirling", "dance-tanoura"], "turns": [
        ("What is Sufi whirling?", "It's a meditative spinning dance from Turkey, from the Mevlevi Sufi tradition. The spinning is done "
                                   "to reach spiritual ecstasy and a connection with the divine."),
        ("sufi whirling ar tanoura ki ek jinis?", "Ek na. Dutoi ghurte ghurte nacha, kintu Sufi whirling Turkey er Mevlevi Sufi "
                                                  "tradition er meditative nach — spiritual ecstasy ar divine er sathe connection er "
                                                  "jonno. Tanoura Egypt er Sufi folk dance, jekhane ekjon male dancer rongin skirt pore "
                                                  "ektana ghurte thake, onek shomoy LED light o thake.")]},
    {"id": "d021-19", "category": "dance_follow_up", "language": "en", "expect_terms": ["dance-irish_step_dance"], "turns": [
        ("What is Irish step dance?", "A traditional dance style from Ireland, known for a rigid upper body and quick footwork."),
        ("tell me more", "It's danced to reels, jigs and hornpipes. The contrast is the striking part — the upper body stays still "
                         "and upright while the feet move quickly underneath.")]},
    {"id": "d021-20", "category": "dance_no_steps", "language": "banglish", "expect_terms": ["dance-gumboot"], "turns": [
        ("gumboot dance er steps gulo shekhao", "Gumboot er step-by-step ta amar kache ekhono nei, tai baniye bolbo na. Ja jani: eta "
                                                "South Africa er ekta rhythmic dance, mine worker ra toiri korechilen — gumboot pore, "
                                                "body percussion diye nacha hoy.")]},
    {"id": "d021-21", "category": "dance_casual", "language": "banglish", "expect_terms": ["dance-dancehall"], "turns": [
        ("ami dancehall shikhte chai, eta kemon dance?", "Dancehall Jamaica er energetic social dance style, dancehall reggae gaan er "
                                                         "sathe nacha hoy. Hip movement, attitude ar improvisation — er ashol moja "
                                                         "eikhanei.")]},
    {"id": "d021-22", "category": "dance_definition", "language": "bn", "expect_terms": ["dance-eskista"], "turns": [
        ("Eskista নাচটা কী?", "এসকিস্তা ইথিওপিয়ার একটি ঐতিহ্যবাহী নাচ। জোরে জোরে কাঁধ কাঁপানো, লাফিয়ে লাফিয়ে বাউন্স আর ছন্দে "
                             "শরীরের এক একটা অংশ আলাদা করে নাড়ানো — এগুলোই এর বৈশিষ্ট্য।")]},
    {"id": "d021-23", "category": "dance_origin", "language": "en", "expect_terms": ["dance-azonto"], "turns": [
        ("Where does Azonto come from?", "Ghana. It's a fast, expressive street dance — hand gestures, knee movements, and moves that "
                                         "tell little stories from everyday life.")]},
    {"id": "d021-24", "category": "dance_comparison", "language": "en", "expect_terms": ["dance-quickstep", "dance-foxtrot"], "turns": [
        ("Is quickstep faster than foxtrot?", "Yes. Quickstep is a fast ballroom dance full of quick steps, runs, hops and lively "
                                              "turns. Foxtrot is smooth and relaxed, with long walking steps and a jazzy feel. "
                                              "Quickstep comes from England and the United States, foxtrot from the United States.")]},
]

# Held-out generalisation cases — NEVER trained. Dances here appear in no training record.
DANCE_HOLDOUT = [
    {"id": "d021h-01", "category": "dance_definition", "language": "banglish", "expect_terms": ["dance-flamenco"], "turns": [
        ("flamenco ki jinis?", "Flamenco Spain er Andalusia theke asha ekta passionate dance form. Percussive footwork, hat tali, "
                               "guitar music ar expressive arm movement — egulo milei flamenco.")]},
    {"id": "d021h-02", "category": "dance_definition", "language": "bn", "expect_terms": ["dance-odissi"], "turns": [
        ("ওড়িশি নাচ কী?", "ওড়িশি ভারতের ওড়িশার একটি ধ্রুপদী নাচ। ভাস্কর্যের মতো ভঙ্গি, শরীরের সাবলীল নড়াচড়া আর ভক্তিমূলক "
                           "বিষয় — এগুলো এর বৈশিষ্ট্য।")]},
    {"id": "d021h-03", "category": "dance_definition", "language": "en", "expect_terms": ["dance-tap_dance"], "turns": [
        ("What is tap dance?", "A rhythmic dance form from the United States where dancers wear metal-tipped shoes and make "
                               "percussion sounds with their feet.")]},
    {"id": "d021h-04", "category": "dance_origin", "language": "banglish", "expect_terms": ["dance-dabke"], "turns": [
        ("Dabke nach ta kon desh er?", "Dabke Levant region er — Lebanon, Syria, Palestine, Jordan, Iraq. Line ba circle e nacha folk "
                                  "dance: stomping, hate hat bendhe, shobai mile celebration.")]},
    {"id": "d021h-05", "category": "dance_origin", "language": "en", "expect_terms": ["dance-kecak"], "turns": [
        ("Kecak — which country is it from?", "Bali, in Indonesia. It's a dramatic Balinese dance performance with a large male chorus "
                                        "chanting “cak” in interlocking rhythms.")]},
    {"id": "d021h-06", "category": "dance_origin", "language": "bn", "expect_terms": ["dance-hula"], "turns": [
        ("হুলা নাচ কোথাকার?", "হুলা হাওয়াইয়ের ঐতিহ্যবাহী নাচ। হাতের সাবলীল ভঙ্গি, কোমরের নড়াচড়া আর সুর করে আবৃত্তি বা গানের "
                              "মধ্য দিয়ে গল্প বলা হয়।")]},
    {"id": "d021h-07", "category": "dance_typo", "language": "banglish", "expect_terms": ["dance-lindy_hop"], "turns": [
        ("lindy hopp ki?", "Lindy Hop er kotha bolcho — eta United States er Harlem, New York er ekta swing partner dance. "
                           "Energetic footwork, aerial move ar improvisation er jonno chena jay.")]},
    {"id": "d021h-08", "category": "dance_simplify", "language": "banglish", "expect_terms": ["dance-waacking"], "turns": [
        ("Waacking mane ki?", "Waacking ekta disco-era dance style, Los Angeles er LGBTQ+ club scene theke. Dramatic arm movement, "
                              "pose ar attitude — eigulo diyei chena jay."),
        ("ektu shohoj kore bujhao", "Hat diye boro boro dramatic movement, majhe majhe pose, ar puro ta attitude niye — etai waacking.")]},
    {"id": "d021h-09", "category": "dance_language_switch", "language": "bn", "expect_terms": ["dance-garba"], "turns": [
        ("Garba ki?", "Garba India er Gujarat er ekta circular devotional folk dance. Tali ar graceful turn diye gol hoye nacha hoy, "
                      "beshir bhag Navratri te."),
        ("গরবা নিয়ে বাংলায় বলো", "গরবা ভারতের গুজরাটের একটি বৃত্তাকার ভক্তিমূলক লোকনৃত্য। হাততালি আর সুন্দর ঘূর্ণি দিয়ে গোল হয়ে "
                            "নাচা হয়, বেশিরভাগ সময় নবরাত্রিতে।")]},
    {"id": "d021h-10", "category": "dance_no_steps", "language": "banglish", "expect_terms": ["dance-butoh"], "turns": [
        ("Butoh er basic steps gulo bolo", "Butoh er step-by-step amar record e nei, tai banano kichu bolbo na. Eta Japan er ekta "
                                           "avant-garde dance form — slow, controlled movement, onek shomoy surreal ba grotesque "
                                           "dhoroner.")]},
    {"id": "d021h-11", "category": "dance_comparison", "language": "en", "expect_terms": ["dance-tango", "dance-milonga"], "turns": [
        ("What's the difference between tango and milonga?", "Both come from Argentina and Uruguay. Tango is dramatic — close "
                                                              "embrace, sharp leg movements, intense musicality. Milonga is its "
                                                              "faster, more relaxed cousin, with a steady rhythm and playful steps.")]},
    {"id": "d021h-12", "category": "dance_language_switch", "language": "en", "expect_terms": ["dance-kizomba"], "turns": [
        ("kizomba ki?", "Kizomba Angola er ekta sensual partner dance. Close embrace, dhire rhythmic step, ar er moddhe African ar "
                        "Latin influence dutoi ache."),
        ("kizomba niye english e likhe dao", "Kizomba is a sensual partner dance from Angola — close embrace, slow rhythmic steps, with African and "
                           "Latin influences.")]},
]
