"""Rupsaa V0.3 FINAL corrective set — PART A: definitions / terminology / dance in natural Banglish.

Written from data/production/reports/rupsaa_v0.3_gemma/BANGLISH_ROOT_CAUSE.md: Gemma's romanisation leans
Hindi ("kapde"), and the V1 corpus had almost no Banglish definition answers ("kapor" 3x). Facts come only
from the owner's terminology/dance records (knowledge/terminology, knowledge/dance); every conversation is
replayed through the real runtime by scripts/v03_build_final.py so its system prompt is exactly what the
app sends. The owner's exact test prompts are deliberately NOT used verbatim.

Spelling (one form per word): bhalo, shob, kivabe, ekhon, sotti, jigges, kharap, ektu, shomoy, sathe, bhabe,
bujhte, hocche, lagche, kichu, shorir, chhowa, kapor, shesh, shuru, bhoy, bhul, theke, dhire dhire.
"""

T = "term-"
D = "dance-"


def c(cid, turns, expect=(), category="banglish_definition", language="banglish"):
    return {"id": cid, "category": category, "language": language, "turns": list(turns), "expect_terms": list(expect)}


DEFINITIONS = [
    # ---------------------------------------------------------------- Strip (the clearest V1 failure)
    c("f03-a001", [("stripping mane ki?",
                    "Stripping mane holo dhire dhire kapor khola — beshirbhag shomoy ekta performance hishebe, jemon stage e ba "
                    "kono show te. Tobe context er upor depend kore, partner er shamne private bhabeo hote pare.")],
      [T + "strip_stripping"]),
    c("f03-a002", [("strip ki jinish?",
                    "Strip generally performance-er moddhe dhire dhire kapor khola. Kokhono eta stage e hoy, kokhono video te, "
                    "abar kokhono partner er jonno ekdom private moment e.")],
      [T + "strip_stripping"]),
    c("f03-a003", [("strip bolte ki bojhay?",
                    "Simple kore bolle, strip mane kapor kholar ekta performance. Ektu ektu kore, attention dhore rekhe kapor "
                    "khola — seductive bhabe o hote pare, abar shudhu show hishebe o.")],
      [T + "strip_stripping"]),
    c("f03-a004", [("striptease mane ki?",
                    "Striptease holo ekta performance jekhane keu gaan er sathe dhire dhire kapor khole. Club, stage ba show te "
                    "eta beshi dekha jay — ashol jinish ta holo tease kore, shomoy niye kapor khola.")],
      [T + "strip_stripping"]),
    c("f03-a005", [("strip ta ki?", "Strip mane holo kapor khola, dhire dhire ar intention niye. Context bujhe eta performance, "
                                    "seductive moment, ba shudhu casual undressing o hote pare."),
                   ("arektu simple kore bolo", "Shohoj kotha: strip = dhire dhire kapor khola. Beshirbhag shomoy eta ekta performance.")],
      [T + "strip_stripping"]),
    c("f03-a006", [("stripping bolte ki bojhano hoy?",
                    "Stripping bolte bojhano hoy dhire dhire kapor khola, often ekta show ba performance er part hishebe."),
                   ("bujhlam na", "Onno bhabe bolchi: keu ekta ekta kore nijer kapor khule, ar shei khola tai hocche performance. "
                                  "Etai strip.")],
      [T + "strip_stripping"]),
    c("f03-a007", [("strip mane ki jinish, ektu bolo",
                    "Strip mane kapor khola — kintu hurobhabe na, dhire dhire. Stage e dancer ra eta performance hishebe kore, "
                    "abar dujon manush er private moment eo eta hote pare."),
                   ("tar mane eta shudhu stage e hoy?", "Na, shudhu stage e na. Stage, club, video — ar partner er shamne private "
                                                        "bhabeo hote pare. Context ta shob theke important.")],
      [T + "strip_stripping"]),
    c("f03-a008", [("stripping ki?", "Stripping holo dhire dhire kapor kholar ekta performance — beshirbhag shomoy music er sathe, "
                                     "tease kore."),
                   ("English e bolo", "Stripping means taking clothes off slowly, usually as a performance and often to music. "
                                      "Depending on context, it can also be something private between partners.")],
      [T + "strip_stripping"]),

    # ---------------------------------------------------------------- other terminology (direct + follow-ups)
    c("f03-a010", [("foreplay mane ki jinish?",
                    "Foreplay holo main intimacy er age ja kora hoy — kiss, chhowa, jorie dhora, kotha bola. Eta dujon ke "
                    "comfortable kore, mood toiri kore, arousal barate help kore.")],
      [T + "foreplay"]),
    c("f03-a011", [("foreplay bolte ki bojhay?", "Foreplay mane shuru-r intimate moment gulo — jemon chumu, shorir e halka chhowa, "
                                                 "romantic kotha — ja ashol intimacy er age hoy."),
                   ("eta keno important?", "Karon eta dujon ke relaxed ar connected kore. Hurobhabe na giye dhire dhire shuru "
                                           "korle comfort o bare, anondo o bare.")],
      [T + "foreplay"]),
    c("f03-a012", [("aftercare mane ki?", "Aftercare holo intimacy er pore partner er jotno newa — jorie dhora, pani dewa, "
                                          "jigges kora 'tumi thik acho?' — jate dujonei emotionally ar physically comfortable thake.")],
      [T + "aftercare"]),
    c("f03-a013", [("aftercare ki jinish?", "Intimacy shesh howar por ektu care kora — kotha bola, cuddle kora, reassure kora. "
                                            "Etai aftercare."),
                   ("arektu easy kore bolo", "Shohoj bhabe: kaj shesh, kintu jotno shesh na. Pore ektu adar ar kheyal rakhai aftercare.")],
      [T + "aftercare"]),
    c("f03-a014", [("consent mane ki?", "Consent mane dujoner shommoti — intimacy te kichu korar age poriskar bhabe raji thaka. "
                                        "Ar mone rekho, je kono shomoy mon bodlano jay, tokhon thamte hoy.")],
      [T + "consent"]),
    c("f03-a015", [("consent bolte ki bojhay?", "Consent mane permission ar agreement — dujonei jante chay ar raji ache, emon."),
                   ("mane?", "Mane, keu 'hae' bolle tobei kichu hobe. Chup thaka ba doubt thaka mane hae na. Ar hae bolar poreo "
                             "je kono shomoy 'na' bola jay.")],
      [T + "consent"]),
    c("f03-a016", [("cuddling mane ki?", "Cuddling holo partner ke kache tene aram kore jorie dhora — affectionate, comfortable ekta "
                                         "moment.")],
      [T + "cuddling"]),
    c("f03-a017", [("spooning ki jinish?", "Spooning ekta cuddle position — dujon pashapashi shuye thake, ekjon arekjoner pichone, "
                                          "shorir ekdom kache. Chamoch er moto shape hoy bole nam spooning.")],
      [T + "spooning"]),
    c("f03-a018", [("deep kissing mane ki?", "Deep kissing holo passionate chumu, jekhane jib o thake ar dujon khub kache thake. "
                                             "Onek e eta ke French kiss o bole.")],
      [T + "deep_kissing"]),
    c("f03-a019", [("slow kiss ki?", "Slow kiss mane tarahura chhara, aram kore deya chumu — jeta dhire dhire intimacy ar tension "
                                     "barae.")],
      [T + "slow_kiss"]),
    c("f03-a020", [("neck kissing mane ki?", "Neck kissing mane gola te chumu dewa ba halka bhabe gola chhowa, intimacy er shomoy. "
                                             "Onek manush er jonno gola khub sensitive jayga.")],
      [T + "neck_kissing"]),
    c("f03-a021", [("lip biting mane ki?", "Lip biting holo chumur shomoy partner er thot halka kore kamra dewa — gently, bytha dewa "
                                           "noy.")],
      [T + "lip_biting"]),
    c("f03-a022", [("gentle bite mane ki?", "Gentle bite mane intimacy te partner er chamra te khub halka kamor — playful, kintu bytha "
                                            "dewar moto na.")],
      [T + "bite_gentle"]),
    c("f03-a023", [("dirty talk mane ki?", "Dirty talk holo intimate moment e sexy, uttejok kotha bola — jeta mood gorom kore. Dujon "
                                           "comfortable thakle tobei eta bhalo kaj kore.")],
      [T + "dirty_talk"]),
    c("f03-a024", [("dirty whisper ki jinish?", "Dirty whisper mane partner er kaner kache fish fish kore sexy kotha bola. Awaj kom, "
                                                "kintu effect beshi.")],
      [T + "dirty_whisper"]),
    c("f03-a025", [("whispering mane ki?", "Whispering mane partner er kaner kache ashte kotha bola — intimacy ba attraction toiri "
                                           "korar jonno.")],
      [T + "whispering"]),
    c("f03-a026", [("edging mane ki?", "Edging holo climax er ekdom kache giye thema jawa ba stimulation komano, jate climax deri te "
                                       "hoy ar pore feeling ta aro intense lage.")],
      [T + "edging"]),
    c("f03-a027", [("sensation denial bolte ki bojhay?", "Sensation denial mane release ichchha kore pichiye dewa ba atkano, jate "
                                                         "opekkha ar intensity bare."),
                   ("eta ar edging ek?", "Kache-kachi, kintu ekdom ek na. Edging holo climax er kache giye thema jawa; sensation "
                                         "denial ektu broad — release ta deri kora ba deya na, anticipation barano-i ashol uddeshyo.")],
      [T + "sensation_denial"]),
    c("f03-a028", [("erotic massage mane ki?", "Erotic massage holo sensual ekta massage — shorir relax korano ar shathe arousal "
                                               "barano, dujoner uddeshyoi.")],
      [T + "erotic_massage"]),
    c("f03-a029", [("eye contact mane ki intimacy te?", "Intimate moment e partner er chokhe chokh rakha — eta connection ar "
                                                        "desire dutoi barae.")],
      [T + "eye_contact"]),
    c("f03-a030", [("grinding mane ki?", "Grinding mane partner er shorir er sathe komor ba shorir ghoshano, friction ar arousal "
                                         "toiri korar jonno.")],
      [T + "grinding"]),
    c("f03-a031", [("hair pulling mane ki?", "Hair pulling holo intimacy er shomoy partner er chul halka ba ektu jore tana. Dujoner "
                                             "comfort ar consent thakle tobei.")],
      [T + "hair_pulling"]),
    c("f03-a032", [("hair stroking ki jinish?", "Hair stroking mane partner er chule hat bulano ba chul niye khela — shanti dey, "
                                                "kacher feeling ta barae.")],
      [T + "hair_stroking"]),
    c("f03-a033", [("bondage mane ki?", "Bondage mane dujoner shommoti niye handcuff, dori ba emon kichu diye partner ke bendhe rakha "
                                        "intimacy te. Consent ar safety ekhane shob cheye important.")],
      [T + "handcuffs_bondage"]),
    c("f03-a034", [("lap dance mane ki?", "Lap dance holo boshe thaka kauke ekdom kache theke ba tar kole boshe dance kora — beshirbhag "
                                          "adult entertainment e private ba semi-private bhabe hoy.")],
      [T + "lap_dance"]),
    c("f03-a035", [("mirror play ki?", "Mirror play mane ayna-r shamne intimate hoya — nijeder dekhte pawa visual excitement ar "
                                       "connection dutoi barae.")],
      [T + "mirror_play"]),
    c("f03-a036", [("oral play mane ki?", "Oral play holo intimacy te mukh diye partner er shorir e pleasure dewa — mane oral sex ar "
                                          "tar kache-kachi jinish.")],
      [T + "oral_play"]),
    c("f03-a037", [("power play mane ki?", "Power play holo dujoner shommoti te intimacy e control er khela — ekjon dominant, ekjon "
                                           "submissive. Boundary age theke thik kore newa dorkar."),
                   ],
      [T + "power_play"]),
    c("f03-a038", [("public teasing ki jinish?", "Public teasing mane lokjon er majhe gopone, karo chokhe na pore partner ke tease "
                                                 "kora — ekta ishara, ekta chhowa, ekta line.")],
      [T + "public_teasing"]),
    c("f03-a039", [("roleplay mane ki?", "Roleplay holo intimacy te kono character ba kalponik scene e abhinoy kora — dujon mile ekta "
                                         "golpo toiri kore.")],
      [T + "roleplay"]),
    c("f03-a040", [("roleplay scenario mane ki?", "Roleplay scenario holo shei kalponik situation ta ja roleplay e abhinoy kora hoy — "
                                                  "jemon dujon ochena manusher prothom dekha.")],
      [T + "roleplay_scenario"]),
    c("f03-a041", [("roleplay aftercare ki?", "Roleplay ba khub intense kono moment er pore ekjon arekjon er jotno newa, reassure kora — "
                                              "character theke beriye abar nijeder moto connect kora.")],
      [T + "roleplay_aftercare", T + "aftercare"]),
    c("f03-a042", [("scratch mane ki intimacy te?", "Intimacy te scratch mane partner er chamra te halka nokh diye achor kata — "
                                                    "bytha na, sensation er jonno.")],
      [T + "scratch"]),
    c("f03-a043", [("sensory play mane ki?", "Sensory play holo alada alada texture, thanda-gorom ba onno sensation use kore intimate "
                                             "experience ta aro gobhir kora.")],
      [T + "sensory_play"]),
    c("f03-a044", [("temperature play ki jinish?", "Temperature play mane safe bhabe thanda ba gorom kichu shorir e use kora — jemon "
                                                   "borof ba gorom tel — sensation barano-r jonno.")],
      [T + "temperature_play"]),
    c("f03-a045", [("shower intimacy mane ki?", "Shower intimacy mane partner er sathe shower e intimate ba sensual shomoy kataono.")],
      [T + "shower_intimacy"]),
    c("f03-a046", [("slow dancing mane ki?", "Slow dancing holo partner er sathe khub kache, aste aste nacha — romantic mood ar tension "
                                             "toiri hoy.")],
      [T + "slow_dancing"]),
    c("f03-a047", [("slow undressing mane ki?", "Slow undressing mane intimacy te tease kore, dhire dhire kapor khola — tarahura chhara."),
                   ("eta ar strip er difference ki?", "Duitai dhire dhire kapor khola. Slow undressing beshirbhag dujoner private moment, "
                                                      "ar strip onek shomoy performance hishebe hoy — stage ba show te.")],
      [T + "slow_undressing"]),
    c("f03-a048", [("tantric breathing mane ki?", "Tantric breathing mane dujon mile dhire, eki taale nishash neya — ete connection ar "
                                                  "present thaka-r feeling gobhir hoy.")],
      [T + "tantric_breathing"]),
    c("f03-a049", [("tease mane ki?", "Tease mane mojar chhole kauke attract kora ba lobh dekhano — attention diye abar ektu dure "
                                      "shore giye interest bariye rakha.")],
      [T + "tease"]),
    c("f03-a050", [("blindfold mane ki?", "Blindfold mane partner er chokh bendhe dewa, jate dekha na jay ar onno sense gulo — chhowa, "
                                          "shobdo — aro tibro lage.")],
      [T + "blindfold"]),
    c("f03-a051", [("body worship ki jinish?", "Body worship mane partner er shorir ke respect ar admiration diye mono-jog dewa — "
                                               "chhowa, chumu ba prosongsha-r kotha diye.")],
      [T + "body_worship"]),
    c("f03-a052", [("cuddle mane ki?", "Cuddle mane kauke kache tene adar kore jorie dhora — comfort ar attachment er ekta shohoj "
                                       "prokash."),
                   ("Bengali te bolo", "কাডল মানে কাউকে কাছে টেনে আদর করে জড়িয়ে ধরা — আরাম আর ঘনিষ্ঠতার একটা সহজ প্রকাশ।")],
      [T + "cuddling"]),
    c("f03-a053", [("foreplay jinish ta ki?", "Foreplay holo ashol intimacy er age er moment gulo — chumu, chhowa, adar, kotha — jeta mood ar "
                                    "comfort toiri kore."),
                   ("Banglish e arektu shohoj kore bolo", "Main part er age je adar, chumu ar chhowa hoy — setai foreplay.")],
      [T + "foreplay"]),
    c("f03-a054", [("edging ki?", "Edging mane climax er kache giye ichchha kore theme jawa, jate shesh e feeling ta aro tibro lage."),
                   ("tar mane?", "Mane, shesh porjonto na giye majh pothe ektu brake — tarpor abar. Eta barbar kore anticipation bare.")],
      [T + "edging"]),
    c("f03-a055", [("consent ki jinish?", "Consent mane poriskar shommoti — dujonei raji, ar je kono shomoy thamte parbe."),
                   ("English e explain koro", "Consent means clear permission and agreement from everyone involved — and anyone can "
                                              "change their mind at any point.")],
      [T + "consent"]),
    c("f03-a056", [("aftercare ki?", "Aftercare mane intimate moment er pore partner er jotno newa — cuddle, pani, kotha, reassurance."),
                   ("Bengali te bolo", "আফটারকেয়ার মানে ঘনিষ্ঠ মুহূর্তের পরে সঙ্গীর যত্ন নেওয়া — জড়িয়ে ধরা, পানি দেওয়া, কথা বলা, আশ্বস্ত করা।")],
      [T + "aftercare"]),
    c("f03-a057", [("tease ki jinish?", "Tease mane playful bhabe kauke lobh dekhano — kache ashe, abar ektu dure jaoa."),
                   ("eta ki shudhu flirting?", "Onekta flirting er moto, kintu tease e ekta khelar bhab thake — attention dewa, tarpor "
                                              "ektu opekkha korano, jate interest bare.")],
      [T + "tease"]),
    c("f03-a058", [("slow kiss mane ki?", "Slow kiss mane aram kore, tarahura chhara chumu — dhire dhire kacher feeling ta bare."),
                   ("Bengali te bolo", "স্লো কিস মানে তাড়াহুড়ো ছাড়া, ধীরে ধীরে দেওয়া চুমু — এতে ঘনিষ্ঠতা আস্তে আস্তে বাড়ে।")],
      [T + "slow_kiss"]),

    # ---------------------------------------------------------------- dance (facts only from knowledge/dance)
    c("f03-b001", [("tango ki?", "Tango ekta dramatic partner dance, Argentina ar Uruguay theke. Close embrace, sharp leg movement ar "
                                 "intense musicality — eigulo-i tango-r porichoy.")], [D + "tango"], "dance"),
    c("f03-b002", [("salsa kothakar dance?", "Salsa-r shikor Cuba, Puerto Rico ar New York e. Lively partner dance — syncopated step, "
                                             "turn ar komorer movement.")], [D + "salsa"], "dance"),
    c("f03-b003", [("bhangra ki jinish?", "Bhangra Punjab er folk dance — India ar Pakistan duitai. Khub energetic, kandh ar komorer "
                                          "jore movement, utshob e beshi hoy.")], [D + "bhangra"], "dance"),
    c("f03-b004", [("flamenco kothakar?", "Flamenco Spain er Andalusia theke. Passionate dance — pa diye tal, hat tali, guitar ar "
                                          "expressive haat er movement.")], [D + "flamenco"], "dance"),
    c("f03-b005", [("hula dance ki?", "Hula Hawaii er traditional dance — hater nombo ishara, komorer movement, ar gaan ba chant diye "
                                      "golpo bola.")], [D + "hula"], "dance"),
    c("f03-b006", [("bharatanatyam kothakar nach?", "Bharatanatyam India-r Tamil Nadu theke. Classical dance — geometric pose, "
                                                    "expressive mudra, tal-er footwork ar golpo bola.")], [D + "bharatanatyam"],
      "dance"),
    c("f03-b007", [("samba ki?", "Samba Brazil er lively dance — druto pa, komorer movement ar Carnival er moto energy.")],
      [D + "samba"], "dance"),
    c("f03-b008", [("waltz kothakar dance?", "Waltz Austria ar Germany theke. Smooth ballroom dance, 3/4 time e — ghure ghure flowing "
                                             "turn ar otha-nama movement.")], [D + "waltz"], "dance"),
    c("f03-b009", [("ballet ki jinish?", "Ballet er shuru Italy te, pore France ar Russia te gore othe. Khub technical classical dance — "
                                         "pointe work, turn-out, grace ar golpo bola.")], [D + "ballet"], "dance"),
    c("f03-b010", [("haka ki?", "Haka New Zealand er Maori der powerful group dance — pa thukano, chant ar bhoyonkor mukher expression. "
                                "Swagot, juddho ba shomman janate kora hoy.")], [D + "haka"], "dance"),
    c("f03-b011", [("garba kothakar nach?", "Garba India-r Gujarat theke. Gol kore ghure kora devotional folk dance — tali ar shundor "
                                            "turn, beshi hoy Navratri te.")], [D + "garba"], "dance"),
    c("f03-b012", [("odissi ki?", "Odissi India-r Odisha-r classical dance — murti-r moto pose, torso-r flowing movement ar bhakti-r "
                                  "theme.")], [D + "odissi"], "dance"),
    c("f03-b013", [("kathakali kothakar?", "Kathakali India-r Kerala theke — classical dance-drama, bishal makeup, costume ar niyom "
                                           "mafik hater mudra.")], [D + "kathakali"], "dance"),
    c("f03-b014", [("hip hop dance kothay shuru hoyeche?", "Hip-hop dance er shuru United States e, New York er Bronx e. Hip-hop "
                                                           "culture er sathe jora — groove, freestyle, battle ar strong musicality.")],
      [D + "hip_hop"], "dance"),
    c("f03-b015", [("bachata ki dance?", "Bachata Dominican Republic er romantic partner dance — char step er rhythm, kache jorie dhora "
                                         "ar halka komorer movement.")], [D + "bachata"], "dance"),
    c("f03-b016", [("kathak ki jinish?", "Kathak India-r uttor bhag er classical dance — ghurni, jotil footwork ar expressive bhabe golpo "
                                         "bola."),
                   ("English e bolo", "Kathak is a classical dance from North India, known for its spins, intricate footwork and "
                                      "expressive storytelling.")], [D + "kathak"], "dance"),
    c("f03-b017", [("belly dance kothakar?", "Belly dance Middle East ar North Africa-r — Egypt, Turkey, Lebanon er moto desh. Torso ar "
                                             "komorer fluid, tal-mafik isolation e focus kore."),
                   ("Bengali te bolo", "বেলি ড্যান্স মধ্যপ্রাচ্য আর উত্তর আফ্রিকার নাচ — মিশর, তুরস্ক, লেবাননের মতো দেশের। শরীরের মাঝের অংশ "
                                       "আর কোমরের সাবলীল, তালে তালে নড়াচড়াই এর মূল।")], [D + "belly_dance"], "dance"),
    c("f03-b018", [("মাম্বো নাচ কী?", "মাম্বো কিউবা আর নিউ ইয়র্কের একটা ল্যাটিন নাচ — জোরালো সিনকোপেশন, দ্রুত স্টেপ আর প্রাণবন্ত ঘূর্ণি।"),
                   ("Banglish e bolo", "Mambo Cuba ar New York er ekta Latin dance — strong syncopation, druto step ar energetic "
                                       "turn.")], [D + "mambo"], "dance"),
    c("f03-b019", [("ট্যাঙ্গো কোথাকার নাচ?", "ট্যাঙ্গো আর্জেন্টিনা আর উরুগুয়ের নাচ — কাছাকাছি জড়িয়ে ধরা, পায়ের তীক্ষ্ণ চলন আর গভীর সংগীতবোধ।"),
                   ("Banglish e bolo", "Tango Argentina ar Uruguay er dance — close embrace, sharp leg movement ar intense "
                                       "musicality.")], [D + "tango"], "dance"),
    c("f03-b020", [("salsa ar bachata same?", "Na, alada. Salsa Cuba, Puerto Rico ar New York theke — lively, syncopated step ar "
                                              "onek turn. Bachata Dominican Republic er — beshi romantic, char step er rhythm, "
                                              "kache jorie dhora.")], [D + "salsa", D + "bachata"], "dance"),
    c("f03-b022", [("tap dance ki?", "Tap dance United States er ekta rhythm-dance — juta-r niche metal thake, pa diye tal toiri kore "
                                     "percussion er moto awaj.")], [D + "tap_dance"], "dance"),
    c("f03-b023", [("sufi whirling ki jinish?", "Sufi whirling Turkey-r Mevlevi Sufi tradition theke — dhyan-er moto ekta ghurni nach, "
                                                "adhyatmik anondo ar ishwarer sathe connection er jonno.")],
      [D + "sufi_whirling"], "dance"),
    c("f03-b024", [("lion dance kothakar?", "Lion dance China-r traditional nach — singho-r costume, dhol ar martial arts er moto "
                                            "movement, shubho kaamona ar bhaggo er jonno.")], [D + "lion_dance"], "dance"),
    c("f03-b025", [("rumba ki?", "Rumba Cuba-r slow, expressive Latin dance — komorer movement, connection ar romantic golpo bola.")],
      [D + "rumba"], "dance"),
    c("f03-b026", [("krump ki?", "Krump Los Angeles er high-energy street dance — aggressive, expressive movement, chest pop, stomp ar "
                                 "freestyle.")], [D + "krump"], "dance"),
    c("f03-b027", [("reggaeton dance kothakar?", "Reggaeton Puerto Rico, Panama ar Caribbean theke. Club dance, reggaeton gaan er "
                                                 "sathe — komorer movement, Latin rhythm ar urban street style mishano.")],
      [D + "reggaeton"], "dance"),
    c("f03-b028", [("voguing ki?", "Voguing New York er Harlem ballroom scene theke — model-er moto pose, line ar angle; Old Way, New "
                                   "Way er moto category ache.")], [D + "voguing"], "dance"),
]

DEFINITIONS += [
    # ---------------------------------------------------------------- second phrasings + follow-up patterns
    c("f03-a060", [("aftercare bolte ki bojhay?", "Intimacy er pore dujon dujon er kheyal rakha — jorie dhora, kotha bola, 'tumi thik "
                                                  "acho?' jigges kora. Etai aftercare."),
                   ("eta ki kore?", "Eta nirapotta ar bhalo lagar feeling dey. Intense moment er pore mon ar shorir dutoi shanto "
                                    "hote shomoy lage — aftercare shei shomoy ta dey.")], [T + "aftercare"]),
    c("f03-a061", [("cuddling bolte ki bojhay?", "Cuddling mane kache tene aram kore jorie dhora — adar ar comfort er ekta shohoj "
                                                 "moment."),
                   ("eta ki kore?", "Mon shanto kore, stress kome, ar dujoner majhe kacher feeling ta bare.")], [T + "cuddling"]),
    c("f03-a062", [("dirty talk ki?", "Dirty talk mane intimacy er shomoy sexy, uttejok kotha bola."),
                   ("Banglish e explain koro", "Mane, romantic moment e dujon dujon ke emon kotha bole jeta mood gorom kore — obosshoi "
                                               "dujon comfortable thakle.")], [T + "dirty_talk"]),
    c("f03-a063", [("roleplay ki jinish?", "Roleplay mane intimacy te dujon mile kono character ba kalponik golpo abhinoy kora."),
                   ("jemon?", "Jemon dhoro, dujon nijeder ochena manush hishebe dekha korlo, ba kono cinema-r scene er moto kore "
                              "khelo. Shob kichu dujoner shommoti te.")], [T + "roleplay"]),
    c("f03-a064", [("blindfold ki?", "Blindfold mane partner er chokh kapor diye dheke dewa, jate onno sense gulo aro tibro lage."),
                   ("easy kore bolo", "Chokh bondho, tai chhowa ar awaj beshi feel hoy. Etai ashol moja.")], [T + "blindfold"]),
    c("f03-a065", [("temperature play mane ki?", "Temperature play mane safe bhabe thanda ba gorom sensation shorir e use kora — "
                                                 "jemon borof ba halka gorom kichu."),
                   ("eta ki safe?", "Safe bhabe korle hae — khub beshi thanda ba gorom kichu na, ar dujon agei thik kore nile bhalo.")],
      [T + "temperature_play"]),
    c("f03-a066", [("spooning bolte ki bojhay?", "Spooning mane dujon pash firiye shuye thaka, ekjon arekjoner pichone ekdom kache — "
                                                 "cuddle er ekta position.")], [T + "spooning"]),
    c("f03-a067", [("neck kissing ki jinish?", "Neck kissing holo gola te chumu ba halka chhowa, intimacy er shomoy."),
                   ("keno eta eto popular?", "Karon gola onek manusher jonno khub sensitive jayga — halka chhowatei onek feeling "
                                             "hoy.")], [T + "neck_kissing"]),
    c("f03-a068", [("power play ki?", "Power play mane dujoner shommoti te control ar dominance-submission er khela."),
                   ("mane?", "Mane ekjon lead kore, arekjon follow kore — kintu shob boundary age theke thik kora thake, ar je kono "
                             "shomoy thama jay.")], [T + "power_play"]),
    c("f03-a069", [("lap dance ki?", "Lap dance holo boshe thaka manusher kache ba kole ekta private dance — adult entertainment e "
                                     "beshi dekha jay."),
                   ("tar mane club e hoy?", "Hae, beshirbhag club ba private room e hoy. Tobe partner er jonno ghore o keu korte "
                                            "pare.")], [T + "lap_dance"]),
    c("f03-a070", [("erotic massage ki jinish?", "Erotic massage holo sensual massage — shorir relax kore, shathe arousal o barae."),
                   ("Bengali te bolo", "ইরোটিক ম্যাসাজ হলো একটা ইন্দ্রিয়সুখের ম্যাসাজ — শরীরকে আরাম দেয়, সাথে উত্তেজনাও বাড়ায়।")],
      [T + "erotic_massage"]),
    c("f03-a071", [("grinding bolte ki bojhay?", "Grinding mane partner er shorir er sathe komor ghoshano — friction ar arousal toiri "
                                                 "korar jonno."),
                   ("arektu simple kore bolo", "Shorir e shorir ghoshe uttejona toiri kora — etai grinding.")], [T + "grinding"]),
    c("f03-a072", [("sensory play ki?", "Sensory play mane alada texture, thanda-gorom ba onno sensation diye intimacy aro gobhir kora."),
                   ("jemon ki?", "Jemon palok diye shorir e bulano, silk er kapor, borof ba halka gorom kichu — shob e sense gulo ke "
                                 "jagiye tole.")], [T + "sensory_play"]),
    c("f03-a073", [("hair pulling ki?", "Hair pulling mane intimacy te partner er chul tana — halka ba ektu jore, dujoner comfort "
                                        "onujayi."),
                   ("bytha lage na?", "Thik bhabe korle na — chul er gora theke dhore halka tana hoy. Tobe age jigges kore newa-i "
                                      "bhalo.")], [T + "hair_pulling"]),
    c("f03-a074", [("tantric breathing ki?", "Tantric breathing mane dujon mile dhire, eki taale nishash neya — connection gobhir "
                                             "hoy."),
                   ("eta ki kore?", "Mon shanto hoy, dujon ekshathe present thaka jay — ar kacher feeling ta onek beshi hoy.")],
      [T + "tantric_breathing"]),
    c("f03-a075", [("body worship bolte ki bojhay?", "Partner er shorir ke adar ar shomman diye mono-jog dewa — chhowa, chumu ar "
                                                     "prosongsha-r kotha diye."),
                   ("mane?", "Mane partner ke bujhiye dewa je tar shorir tomar kache kotota shundor ar priyo.")],
      [T + "body_worship"]),
    c("f03-a076", [("public teasing bolte ki bojhay?", "Lokjon er shamne gopone partner ke tease kora — ekta hashi, ekta ishara, keu "
                                                       "bujhbe na.")], [T + "public_teasing"]),
    c("f03-a077", [("mirror play bolte ki bojhay?", "Ayna-r shamne intimate hoya — nijeder dekhte pawa excitement ar connection "
                                                    "barae.")], [T + "mirror_play"]),
    c("f03-a078", [("slow undressing ki?", "Slow undressing mane tease kore, dhire dhire kapor khola — private moment e."),
                   ("Bengali te bolo", "স্লো আনড্রেসিং মানে খেলার ছলে, ধীরে ধীরে কাপড় খোলা — একান্ত মুহূর্তে।")],
      [T + "slow_undressing"]),
    c("f03-a079", [("স্ট্রিপ বলতে কী বোঝায়?", "স্ট্রিপ মানে ধীরে ধীরে কাপড় খোলা — বেশিরভাগ সময় একটা পারফরম্যান্স হিসেবে, মঞ্চে বা শো-তে। "
                                             "প্রেক্ষাপট অনুযায়ী এটা সঙ্গীর সামনে একান্তেও হতে পারে।"),
                   ("Banglish e bolo", "Strip mane dhire dhire kapor khola — beshirbhag shomoy performance hishebe, stage e ba show "
                                       "te. Context bujhe partner er shamne private bhabeo hote pare.")], [T + "strip_stripping"]),
    c("f03-a080", [("কনসেন্ট মানে কী?", "কনসেন্ট মানে দুজনের স্পষ্ট সম্মতি — ঘনিষ্ঠ কিছু করার আগে দুজনেই রাজি থাকা। আর যেকোনো সময় মত বদলানো যায়।"),
                   ("Banglish e bolo", "Consent mane dujoner poriskar shommoti — kichu korar age dujonei raji thaka. Ar je kono shomoy "
                                       "mon bodlano jay.")], [T + "consent"]),
    c("f03-a081", [("ফোরপ্লে বলতে কী বোঝায়?", "ফোরপ্লে হলো মূল ঘনিষ্ঠতার আগের মুহূর্তগুলো — চুমু, ছোঁয়া, আদর, কথা — যা মন আর শরীর দুটোকেই তৈরি করে।")],
      [T + "foreplay"], "bengali_definition", "bn"),
    c("f03-a082", [("এজিং মানে কী?", "এজিং মানে চরম মুহূর্তের একদম কাছে গিয়ে থেমে যাওয়া বা উত্তেজনা কমানো, যাতে পরে অনুভূতিটা আরো তীব্র হয়।")],
      [T + "edging"], "bengali_definition", "bn"),

    # ---------------------------------------------------------------- more dance
    c("f03-b030", [("cha cha ki dance?", "Cha-cha Cuba-r playful Latin ballroom dance — triple step ar tal-mafik komorer movement.")],
      [D + "cha_cha"], "dance"),
    c("f03-b031", [("merengue kothakar?", "Merengue Dominican Republic er — druto, shohoj partner dance, march er moto step ar jor "
                                          "komorer movement.")], [D + "merengue"], "dance"),
    c("f03-b032", [("kizomba ki jinish?", "Kizomba Angola theke — sensual partner dance, kache jorie dhora, dhire tal-er step, African "
                                          "ar Latin influence dutoi ache.")], [D + "kizomba"], "dance"),
    c("f03-b033", [("dabke ki?", "Dabke Levant er folk dance — Lebanon, Syria, Palestine, Jordan, Iraq. Line ba gol kore, haat dhore, "
                                 "pa thukiye ekshathe utshob.")], [D + "dabke"], "dance"),
    c("f03-b034", [("garba ar bhangra same?", "Na. Garba Gujarat er gol kore ghure kora devotional folk dance, Navratri te beshi hoy. "
                                              "Bhangra Punjab er — anek beshi energetic, kandh ar komorer jore movement.")],
      [D + "garba", D + "bhangra"], "dance"),
    c("f03-b035", [("kuchipudi kothakar?", "Kuchipudi India-r Andhra Pradesh theke — shundor movement, tal-er footwork ar natokiyo "
                                           "expression mishano classical dance.")], [D + "kuchipudi"], "dance"),
    c("f03-b036", [("lavani ki?", "Lavani Maharashtra-r traditional dance-drama — tal-er footwork, expressive ishara ar prano-chhol "
                                  "gaan.")], [D + "lavani"], "dance"),
    c("f03-b037", [("lindy hop ki jinish?", "Lindy Hop New York er Harlem theke — swing partner dance, energetic footwork, shunne "
                                            "tole dewar move ar improvisation.")], [D + "lindy_hop"], "dance"),
    c("f03-b038", [("breakdance ki?", "Breaking ba breakdance US er South Bronx, New York theke — athletic street dance: top rock, "
                                      "footwork, freeze ar power move, breakbeat er sathe."),
                   ("Bengali te bolo", "ব্রেকিং বা ব্রেকড্যান্স যুক্তরাষ্ট্রের সাউথ ব্রঙ্কস, নিউ ইয়র্ক থেকে — অ্যাথলেটিক স্ট্রিট ডান্স: টপ রক, ফুটওয়ার্ক, "
                                       "ফ্রিজ আর পাওয়ার মুভ, ব্রেকবিটের সাথে।")], [D + "breaking_breakdance"], "dance"),
    c("f03-b039", [("ওডিসি কোথাকার নাচ?", "ওডিসি ভারতের ওড়িশার শাস্ত্রীয় নাচ — ভাস্কর্যের মতো ভঙ্গি, শরীরের সাবলীল চলন আর ভক্তির ভাব।"),
                   ("Banglish e bolo", "Odissi India-r Odisha-r classical dance — murti-r moto pose, torso-r flowing movement ar "
                                       "bhakti-r theme.")], [D + "odissi"], "dance"),
]
