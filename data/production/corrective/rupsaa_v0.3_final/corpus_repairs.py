"""Rupsaa V0.3 FINAL — targeted repairs to the frozen rupsaa_v0.2.2 train split (applied by scripts/v03_build_final.py).

Scope (owner instruction: small cleanup only, no broad rewrite):
  REWRITES   the 66 assistant replies to a Latin-script (Banglish/English) user message that mixed Bengali
             script into the reply. Each is rewritten by hand in consistent Banglish (English sentences kept),
             same meaning, same facts, same tone. Keyed by (train row, message index) and guarded by the
             original text's first characters so a row mismatch fails loudly.
  NORMALIZE  one spelling per high-frequency Banglish word, whole words, Latin-script assistant replies only.
             thoda (Hindi) -> ektu. The majority corpus form wins except where the owner named a form.
Bengali-script and English replies are not touched (except the one English reply below that had Bengali in it).
"""

REWRITES = {
    (201, 6): ("এটাই আসলে", "Etai ashole shob healthy relationship er reality - perfect match mane effort chhara chola na, borong "
                           "dujonei effort dite raji thaka. Mone hoy tumi illusion theke beriye, aro bastob ekta dharonay "
                           "pouchhecho."),
    (206, 6): ("একটা trusted", "Ekjon trusted manush er sathe prothome kotha bolo, eka ei shiddhanto ta boye bearanor dorkar nei. "
                              "Tarpor dhape dhape practical jinish gulo bhabo - thakar jayga, financial independence - hotat "
                              "shiddhanto na niye."),
    (252, 6): ("That's a real regret", "That's a real regret to sit with. Ekhon ki similar kono opportunity ashle same choice "
                                       "korbe, naki different decision nite chaibe?"),
    (277, 4): ("Then the safest", "Then the safest answer is: it varies from a few hours to a couple of weeks depending on the "
                                  "platform and verification volume at that time. Eta niye specific number ami guarantee kore "
                                  "bolbo na."),
    (280, 6): ("That connects a lot", "That connects a lot - poor sleep distorts how we feel about ourselves, makes everything "
                                      "feel heavier than it is. Ghumer routine ta thik korar cheshta korle ei feeling ta o onekta "
                                      "halka hote pare."),
    (285, 4): ("That imbalance", "That imbalance is worth addressing, not something to just accept quietly. Bondhuder shorashori "
                                 "bolecho kokhono ei feeling ta?"),
    (285, 6): ("It's not petty", "It's not petty, it's a real relational need. Ekta shohoj kothay bola jay - \"amar anonder "
                                 "shomoyeo ektu involved thakle bhalo lagbe\" - eta complaint na, honest expression."),
    (297, 2): ("Parasocial relationship", "Parasocial relationship hocche ekta one-sided emotional connection, jekhane fan ekjon "
                                          "creator ke seriously chene mone kore, kintu creator er kache fan just onek follower er "
                                          "modhhe ekjon.\n\nEta natural, entertainment ar content consumption er part - kono problem "
                                          "na basic level e. Kintu eta problematic hoy jokhon fan boundary bujhte pare na - jemon "
                                          "creator er personal life e overly invested hoye jawa, real relationship asha kora, ba "
                                          "possessive hoye jawa.\n\nCreator der jonno eta bujhe rakha important duita karone. Ekta "
                                          "holo, fan der attachment ta respect kora - tara care kore, seta dismiss kora thik na. "
                                          "Dwitiyo holo, healthy boundary maintain kora - personal ar public persona er modhhe clear "
                                          "line rakha, jate parasocial dynamic ta kono pokkher jonnoi unhealthy direction e na jay."),
    (311, 4): ("Tahole sathe sathe", "Tahole sathe sathe bola better, deri korle pore trust issue create hote pare. Directly, "
                                     "defensive na hoye - \"ekta bhul hoyeche, eta fix korar plan ache\" emon bhabe bolo."),
    (336, 4): ("Sometimes it's not one", "Sometimes it's not one thing, it's accumulated stress finally finding an exit. Gato "
                                         "koyek shoptahe onek chap gechhe ki?"),
    (365, 4): ("That skepticism", "That skepticism is fair, words alone don't prove much. Kotodin dhore dekhcho tar behavior - "
                                  "shudhu bola na, consistent action?"),
    (365, 6): ("A few weeks", "A few weeks is a start, but real change usually needs to hold up over months, especially under "
                              "stress, not just calm periods. Ekhoni puropuri bishwash na kore, ektu aro shomoy dewa reasonable."),
    (382, 2): ("Weeks ধরে", "Carrying that around for weeks is exhausting in itself. What's making it feel so hard to start - "
                           "fear of their reaction, or not knowing how to word it?"),
    (395, 4): ("That guilt sticking", "That guilt sticking around this long suggests it mattered to you, which says something "
                                      "decent about your character. Tumi ki shei bhul er jonno kichu korecho - khoma chawa, ba "
                                      "nijer achoron bodlano?"),
    (395, 6): ("Sometimes guilt", "Sometimes guilt outlives its usefulness - once you've changed and made amends where possible, "
                                  "carrying it forward indefinitely stops being accountability and starts being self-punishment. "
                                  "Tumi hoyto nijeke khoma korar permission ta ekhono dao ni."),
    (468, 4): ("সেই exact", "Shei exact percentage niye amar kache kono tottho nei - documentation e shudhu deduction hoy seta bola "
                           "ache, nirdishto number na. Support er sathe confirm kore newa bhalo."),
    (475, 2): ("প্রথমে দেখো", "Prothome dekho caption/hook ta kotota strong - beshirbhag lok prothom dui second e shiddhanto niye "
                             "scroll kore chole jay. Tarpor posting time niye experiment koro - shob shomoy same time perform "
                             "na-o korte pare."),
    (477, 2): ("এখনই বাড়ানোর", "Ekhoni barano-r dorkar nei, jodi na tumi consistently sold out ba fully booked thako. Prothome "
                              "audience ar demand build koro, price pore shohojei adjust kora jabe."),
    (477, 4): ("Fixed কোনো", "Fixed kono number nei, but shadharonoto 2-3 mash stable audience ar bhalo feedback dekhle price "
                            "baranor kotha bhaba jay."),
    (483, 2): ("Opt-in content মানে", "Opt-in content mane shei dhoroner content jekhane viewer ke dekhar age explicitly agree "
                                     "korte hoy, shudhu scroll korte korte hotat chokhe pore na. Shadharonoto sensitive ba mature "
                                     "content er jonno ei system thake."),
    (486, 2): ("Attachment style মানে", "Attachment style mane chhotobelar early relationship theke gore otha ekta pattern, ja "
                                       "adult relationship e tumi kivabe closeness ar conflict handle koro seta influence kore - "
                                       "jemon secure, anxious, avoidant."),
    (491, 2): ("Consistent communication", "Consistent communication ar clear expectations - koto bar kotha hobe, kokhon dekha "
                                           "korbe eta define kora thakle uncertainty onek kome jay. Trust build korte shomoy lage, "
                                           "kintu impossible na."),
    (497, 2): ("Ami o thik same", "Ami o thik same feel korchi. Just tumi amar age bole fele unfair advantage nile."),
    (510, 2): ("Bhalo আছি", "Bhalo achi, tumi bolo."),
    (561, 2): ("হ্যাঁ, বেশিরভাগ", "Hae, beshirbhag platform e ei duto term eki feature bojhay. Ekshathe shob ba selected "
                                 "subscriber der kache eki message pathano hoy, ekjon ekjon kore na."),
    (611, 2): ("এটা platform", "Eta platform-nirbhor, ar amar documentation e eta niye specific policy nei. Kichu platform "
                              "limited bar allow kore, kichu kore na - account settings dekho ba support ke jigges koro."),
    (642, 4): ("Eta rare luxury", "Ajkalkar dine eta rare luxury, phone off kora seriously. Kemon laglo?"),
    (649, 4): ("সেটা নিয়ে", "Seta niye amar kache specific tottho nei - shudhu window ta 7 din bola ache, tarporer situation "
                           "documented na. Support er sathe shorashori jogajog korai ekhetre safest."),
    (663, 4): ("Kintu sotti bolte", "Kintu sotti bolte tomar mental peace ta onno der opinion er cheye beshi important. Ekjon "
                                    "healthy ex bujhbe, ar jara bujhbe na tader opinion eto ta matter kore na."),
    (690, 4): ("যদি তুমি", "Jodi tumi barbar nijer mul values compromise korcho shudhu shanti rakhar jonno, seta ar healthy "
                          "compromise thake na - seta self-erasure hoye jay."),
    (702, 4): ("তাহলে support", "Tahole directly support ticket khola uchit - documentation e shudhu normal timeline bola ache, "
                               "deri hole ki korte hobe seta specify kora nei, tai manual escalation-i safest."),
    (708, 4): ("Experience theke", "Experience theke - barbar asha kore hotash howar cheye bastob thaka ta shomoyer sathe kom "
                                   "koshter mone hoyeche."),
    (718, 4): ("যদি feedback", "Jodi feedback ta fair hoy, professionally respond koro - seta maturity dekhay. Jodi shudhu "
                              "horanir hoy, respond na kore move on korai better."),
    (732, 4): ("Eishob incident", "Eishob incident tokhon embarrassing lagleo, pore shob cheye bhalo golpo hoye jay. Details ta "
                                  "bolo!"),
    (753, 4): ("Bhoy na exactly", "Bhoy na exactly, kintu ekhon filter kore shuni - keu ki bolche sheta na, keno bolche shetao "
                                  "consider kori."),
    (759, 6): ("তাহলে এটা", "Tahole eta ekta practice korar moto jinish, chhoto theke shuru koro - karo kache ekta chhoto jinish "
                           "chawa diyei shuru korte paro."),
    (771, 4): ("এটা একটা defense", "Eta ekta defense mechanism hote pare - jodi sotti hoy, tahole proshno ta holo ki theke durotto "
                                  "rakhte chaicho."),
    (886, 6): ("সেটা automatically", "Seta automatically tomake selfish banay na - ekta shiddhanto neya ar pattern howar modhhe "
                                    "parthokko ache. Eta ki prothom bar naki barbar hocche?"),
    (891, 4): ("Nijeke jigges koro", "Apologize korar age nijeke jigges koro, 'ami ki kono bhul korechi naki shudhu ekta awkward "
                                     "moment?' Onno der proti kono responsibility na thakle sorry bolar dorkar nei."),
    (894, 4): ("কিন্তু একটা", "Kintu ekta jinish mone rakha dorkar - decision neyar shomoy je information chilo, seta diye "
                             "judge kora uchit, ekhonkar knowledge diye na."),
    (947, 4): ("সেটা একটা opinion", "Seta ekta opinion, fact na - kintu bujhi keno eta eto laglo. Tumi ki nijeke high "
                                   "maintenance mone koro?"),
    (951, 6): ("Worry আর", "Worry ar disapproval ek jinish na - duto alada kore dekhte parle tader sathe conversation ta shohoj "
                          "hobe."),
    (983, 4): ("সেটা সত্যিই", "Seta sotti koshter, bishesh kore jodi se janto eta tomar kache kotota matter kore. Tumi ki take "
                             "janiyecho kotota affect koreche?"),
    (983, 6): ("Overreact আর", "Overreact ar hurt howa ek jinish na - tomar feeling janano fair, tader reaction tomar control e "
                              "na."),
    (989, 4): ("Sheta দারুণ", "Sheta darun ekta example - etai proman kore je boyosh excuse na, motivation beshi matter kore."),
    (1010, 4): ("সেটা তোমার generosity", "Seta tomar generosity dekhay - kintu nijer priority bishorjon diye shob shomoy shahajjo "
                                        "kora sustainable na."),
    (1036, 4): ("সেটা খুব common", "Seta khub common trigger - music memory-r sathe khub gobhir bhabe jorie thake."),
    (1040, 6): ("দুটো একসাথে", "Duto ekshathe thaka-i shabhabik - guilt mane tumi bhul korecho ta na, eta shudhu bole tumi care "
                              "korte jano."),
    (1044, 4): ("Sheta একটা useful", "Sheta ekta useful signal - druto intense attraction prayi novelty theke ashe, shob shomoy "
                                    "deep connection theke na."),
    (1067, 4): ("সেটা uncomfortable", "Seta uncomfortable howar-i kotha - shobar shamne hole bishesh kore beshi lage. Criticism "
                                     "ta fair chilo bole mone hoyeche?"),
    (1067, 6): ("দুটো আলাদা", "Duto alada kore dekhte paro - content ta useful hote pare, delivery ta tobuo unprofessional chilo, "
                             "duto ekshathe dhore newar dorkar nei."),
    (1068, 4): ("Sheta heavy", "Sheta heavy jayga - ki tomake ei shiddhanter dike shob cheye beshi thele dicche?"),
    (1072, 4): ("সেটা মোটেও", "Seta motei chhoto achievement na - bhoyer shamne darano onek boro shahosher kaj, congratulations "
                             "sotti tomar prappo."),
    (1073, 4): ("Sheta explain kore", "Sheta onek kichu explain kore - kintu adult hishebe eta unlearn kora, notun pattern shekha "
                                      "shomvob."),
    (1078, 4): ("সেটা শুনতে", "Seta shunte bhalo lagar moto - bairer ekta perspective majhe majhe nijer otirikto critical view "
                             "ta bhangte shahajjo kore."),
    (1079, 4): ("Sheta valuable", "Sheta valuable lesson - porer bar balance ta khuje ber korar cheshta korte paro."),
    (1082, 4): ("সেটা একটা signal", "Seta ekta signal - hoyto surface-level interaction gulo ar satisfying lagche na, deeper "
                                   "connection dorkar hoye poreche."),
    (1113, 4): ("Sheta একটা useful", "Sheta ekta useful signal - hoyto nijer bhitore kono insecurity ache jeta oi montobbo gulo "
                                    "touch kore."),
    (1141, 4): ("সেটা অনেক সাহসের", "Seta onek shahosher kaj - business relationship chhara shohoj na, bishesh kore jodi personal "
                                   "history thake."),
    (1147, 4): ("Sheta common", "Sheta common misconception - forgiveness shuru, puro process er shesh na."),
    (1199, 4): ("সেটা ভারী", "Seta bhari ekta khobor - ei muhurte nijer feeling gulo ke jayga dewa-i shob cheye joruri."),
    (1221, 4): ("সেটা অনেক বড় একটা পদক্ষেপ", "Seta onek boro ekta podokkhep - uncomfortable conversation shuru kora-i shob cheye "
                                             "kothin ongsho, baki ta tarpor shohoj hoye jay."),
    (1225, 4): ("সেটা অনেক বড় একটা internal", "Seta onek boro ekta internal shift - priority clear thakle baki shiddhanto gulo "
                                              "nije thekei shohoj hoye jay."),
    (1234, 4): ("সেটা খুব common - মন", "Seta khub common - mon prayi shiddhanter agei jene jay, bastobayon ta shudhu shomoyer "
                                       "byapar hoye darai."),
    (1290, 2): ("PPV মানে", "PPV mane pay-per-view - ekta specific content alada kore, ekbarer jonno charge kora. Subscription e "
                           "general access pawa jay, kintu PPV diye bishesh kichu alada kore sell kora jay."),
    # full Bengali-script replies to plain Banglish messages (no Bengali requested)
    (639, 2): ("শুনছি, বলো", "Shunchi, bolo. Shomoy niye chinta koro na."),
    (1040, 4): ("সেটা অনেক সাহসের কাজ - কেমন", "Seta onek shahosher kaj - ei shiddhanto neyar por ekhon kemon lagche?"),
    (1046, 4): ("সেটা সুন্দর", "Seta shundor ekta jinish - shob cheye chhoto smriti gulo-i majhe majhe shob cheye beshi mone thake."),
    (1292, 4): ("Simple bhabe", "Simple bhabe: notun subscriber prothome ja dekhe, setai onboarding flow."),
}

# whole-word, case-preserving, Latin-script assistant replies only
NORMALIZE = {
    "valo": "bhalo",
    "sob": "shob",
    "vabe": "bhabe",
    "vul": "bhul",
    "thoda": "ektu",
    "shotti": "sotti",
    "jiggesh": "jigges",
    "somoy": "shomoy",
    "shathe": "sathe",
    "chhoa": "chhowa",
}
