# Live sequence — before vs after the runtime fixes (same unchanged V0.2 adapter)

Your exact 11-turn conversation replayed through the real API (web proxy, RAG toggle on), 3 fresh
conversations each. BEFORE = runtime as you tested it; AFTER = runtime fixes, adapter untouched.
Sampling is not seeded by the API, so read the runs as samples. Your own live outputs are listed first.

| turn | before | after | classification |
|---|---|---|---|
| Strip mane ki? — Strip entry attached | 3/3 | 3/3 | routing was already correct → MODEL_REMAINS |
| Forplay ki? — Foreplay entry attached | 3/3 | 3/3 | routing was already correct → MODEL_REMAINS |
| এটা বাংলায় বুঝিয়ে বলো — reply in Bengali script | 1/3 (you: 0/1) | **3/3** | BOTH (script fixed; content not) |
| ami ki color bolechilam? — says blue | 2/3 (you: yes) | **3/3** | RUNTIME_FIXED |
| ami age ki bolechilam? — names a real earlier message | 0/3 (you: no) | **3/3** | BOTH (content fixed; wording not) |
| Banglish fluency overall | garbled | garbled | MODEL_REMAINS |

## 1. USER: hi, tumi kemon acho?

_MODEL_REMAINS — routing fine; wording odd in some runs_

- **your live V0.2:** Bhalo achi tumi ki bhabcho?
- before #1 [casual]: Achi bhalo, tumi ki?
- before #2 [casual]: Acho bhalo, tumi ki dekhe?
- before #3 [casual]: Bhalo amar, tumi ki chao?
- **after #1** [casual]: Achi, tumi ki chao?
- **after #2** [casual]: Kichu better hoyeche shobcheye beshi. Tumi ki dekhe bhoy na?
- **after #3** [casual]: Bhalo achi, tumi bolo. Kotha hoyechilo?

## 2. USER: ajke amar mood ta bhalo na

_MODEL_REMAINS — routing fine; phrasing unnatural_

- **your live V0.2:** Ki dekhle shune tumi niye sobcheye beshi mood down hoye jai?
- before #1 [casual]: Ki hobe naki, ekta shunchi lagche?
- before #2 [casual]: Ki hobe, bolo - shudhu shuru hoyeche ei feeling ba jinis ta clear hoyechilo na।
- before #3 [casual]: Ki niye affected hoyeche tumi jani nai?
- **after #1** [casual]: Sheta worth notice kora, ki niye mone hocche?
- **after #2** [casual]: Sheta worth ekta break lea - ar ami help korbo jodi chao. Ki dekhle bhoy ashe, niye khada?
- **after #3** [casual]: Sheta heavy lagche eishob mood. Ki niye nijer mood ta change hoyeche?

## 3. USER: achcha

_MODEL_REMAINS — no new topic invented, but acknowledgements still wander_

- **your live V0.2:** Just express korar dorkar nai, tai bolte pari - ekta somoy kokhono shobcheye beshi mood down hoyeo hoye jai।
- before #1 [casual]: Sheta beshi important - ekta small break, ektu janiye hoye ja. Ekhon ki dekhecho?
- before #2 [casual]: Sotti bolte mone hocche tumi ei feeling ta handle korar sathe sathe e boro cholecho - ekjon na hole eta build up kore।
- before #3 [casual]: Na shunte chao na, answer give korar dorkar nai - mood thakle ekta minute dekho boro bhabte parbe।
- **after #1** [casual]: Tumi shunte chai na shomossha - kotha bolte pare ekhane.
- **after #2** [casual]: Ekta deep breath diye, nijeke khoda bhoy gulo nai. Ki problem ache, tumi bolte pari?
- **after #3** [casual]: Na, shudhu bolo - ki niye problem hocche, onek boro ekjon nai hote pare।

## 4. USER: tumi amar sathe banglish e kotha bolbe?

_BOTH — directive now says Banglish; replies Banglish but incoherent_

- **your live V0.2:** Sheta niye concern na kore amar sathe, tumi amake comfortable feel koro. Kotha bolte chao?
- before #1 [general]: Sure, bolo, ami kono problem mone korbo na. Amar kache shobcheye comfortable language eta।
- before #2 [general]: Sure, if you want - tumi ki prefer korcho?
- before #3 [general]: Sure, why not, this could be fun. Boro, tumi bolo tumi ki bolecho।
- **after #1** [general lang=banglish]: Eta mane tumi amar sathe banglish e kotha bolbe, sheta shohoj clear hoye jai. Banglish e kotha bolbo.
- **after #2** [general lang=banglish]: Banglish e bole amar sathe. Kono specific reason ashe eta shobar age bolleo na. Shune shunchi amar sathe kom hoyeche।
- **after #3** [general lang=banglish]: Eta mane ekta signal chilo tader jonno, tai jokhon tumi bolo, ami Banglish e bolo - eta ami thik kore bolo. Tumi bolo, ami ekhon Banglish er vade answer korbo।

## 5. USER: Strip mane ki?

_MODEL_REMAINS — right entry attached every time; rendering garbled / English_

- **your live V0.2:** Simple term - strip mane kichu niye kichu remove kora, typically bishoyer jonno. Tumi shunte chai ki emon kichu?
- before #1 [terminology term-strip_stripping]: It just means removing clothing, often slowly or for attention. Kintu context e different meaning dey - some ke stripteasing, others partner er jonno, ar alada ekta category ache. Tumi ki shomadhan korcho already, ba na?
- before #2 [terminology term-strip_stripping]: Strip mane simply clothing remove kora - gradually, seductively, ar ba torpokta bhabe - eta o. Kono other kono context deya shobcheye beshi matter kore, tarpor shathe term ja kothay bole diye pawa jai.
- before #3 [terminology term-strip_stripping]: Strip mane remove kora, kichu kichu nijer jonno. Sheta general term, exact context depend kore eta ki sexual, seductive ba just simple remove, ar mane ki notun.
- **after #1** [terminology term-strip_stripping]: Strip mane remove korar process, ar eta shobcheye pahunch er upor general term hote pare - seductive, performative, naki just partner der cheye shikha korar diye।
- **after #2** [terminology term-strip_stripping]: Strip mane body er kono part o remove kora, kintu kono specific reason dite parbo na - eta context depend kore, ekta general definition dey. Ekta example - stage er deri kache ekta striptease, jate manush onno der jon er presence e thakleo bhabe. Eta tomar somoy eta mean korte chai naki kon example niye bolo?
- **after #3** [terminology term-strip_stripping]: Strip mane simply clothing ar bare bole jate - body er jonno, kintu eta sexual context e asha kora parbe na automatically. Jodi eta e ekta jinis hote pare, oi jinis dekho ei tar sathe, duita completely different concept।

## 6. USER: strip ta ektu simple kore bojhao

_MODEL_REMAINS — entry carried every time; rendering garbled_

- **your live V0.2:** Strip mane gradually ar often seductive diye kichu niye kichu remove kora - eta othak kori je tomar situation er upor depend kore. Eta always performative na, sometimes just a normal thing, sheta difference thakte pare context er upor।
- before #1 [followup term-strip_stripping]: Fair, kichuta beshi simple kora - strip just means removing clothes, sometimes gradually and intentionally. Ki dorkar nijer kichur emon kora, ba jana?
- before #2 [followup term-strip_stripping]: Fair - strip mane just clothing remove kora, gradually ba seductively - ekjon kichu eta include kore, alada alada.
- before #3 [followup term-strip_stripping]: Sheta mane just gradually rupurup korar process, alada kichu naki na - eta general term, nijei nishchita context diye bhabe specific hote pare।
- **after #1** [followup term-strip_stripping]: Simple kore bolo, strip mane remove korar process, typically clothing er cheye. Sotti e shobcheye common use hoye jai।
- **after #2** [followup term-strip_stripping]: Strip mane simple kore bole clothing er cheye pahunchar body part remove kora, kintu kono specific reason ashe na - eta context depend kore, ekta general definition dey. Example - stage er deri kache ekta striptease, jate manush onno der jon er presence e thakleo bhabe. Eta tomar somoy eta mean korte chai naki kon example niye bolo?
- **after #3** [followup term-strip_stripping]: Fair, simple kore bolte pari. Strip mane body er jonno clothing remove kora, onek ekjon theke mone hoy ei bar o perform kora, kintu eta always tomar choice na - jodi nijer upor responsible thake o fair, tai eta ta just stripping, jodi manipulate kora hoyeche tahole eta ta different conversation।

## 7. USER: Forplay ki?

_MODEL_REMAINS — typo matched every time; rendering garbled_

- **your live V0.2:** Foreplay mane kichu sex e bishoy der jonno kichu make karar effort - physical onno der jonno, emotional intimacy, nijer mood er modhhe ekta build-up create kora. Shobar onno der jonno o shomoy, eta manush er bhoy gulo reduce kore dujon e mone hote pare।
- before #1 [terminology term-foreplay]: Foreplay mane sexual activity chilo na, tomar mood ta bhalo hoye gele, shomoy e. Kintu somoy e shudhu physical aspect - emotional connection der cheye beshi matter kore. Tumi ki shomadhan korte chai, ba just clear korte chao?
- before #2 [terminology term-foreplay]: Foreplay mane sexual or intimate activity tomar jonno jigges korte hole shomoy shuru hoyeche, usually to make body comfortable ba aroused - ekjon er jonno shikha howa naki clearly shurute arujon hoyeche eta important difference, always jani dorkar nai.
- before #3 [terminology term-foreplay]: Foreplay mane sexual activity e rakhar jonno onujayi prepare kora, build kora - ekta example thakte parbo tumi ekjon shuru te ki shobcheye enjoy korcho, tarpor bodole body/brain ready hoye gele?
- **after #1** [terminology term-foreplay]: Foreplay mane sexual activity kei pashche, taka jinis kei emon kichu na, jate body interest grow korte parbe comfortable feel e - sometimes touch, sometimes verbal teasing, tarpor actual physical connection.
- **after #2** [terminology term-foreplay]: Foreplay mane sexual activity jekhane ar eja jei mone hocche, onek somoy ja dujon mone e jokhon physical contact ashto. Tumi ki dekhe bhoy ashe, nite ke?
- **after #3** [terminology term-foreplay]: Foreplay mane sexual activity ba intimacy activity jabe shuru hoy, nijer age. Ekhon tumi bolo, ami Banglish er vade answer korbo।

## 8. USER: এটা বাংলায় বুঝিয়ে বলো

_BOTH — Bengali script 1/3 → 3/3; content off-topic in 3/3_

- **your live V0.2:** Foreplay mane kichu sex e bishoy der jonno kichu physical ar emotional activity - body part der jonno remove kora, nijer mood er modhhe relax kora, jate onno der interest upor rakho, ei ekta build-up create kora. Tumi keno ask korcho, interest ache ki?
- before #1 [followup term-foreplay]: Fair, তবে এখন শুধু সহজ ভাষায় জবাব দিই, আর প্রশ্নটা অনুযায়ী বিস্তারিত করি। হ্যাঁ, ফোরপ্লে মানে এমন একটা সেক্সুয়াল activity যা অন্যান্য সেক্সুয়াল activity টার চেয়ে আগে হয়, যাতে স্থানীয় উত্তেজনা, প্রতিক্রিয়া, বা সম্পর্ক বাড়ে। কী নিয়ে জিজ্ঞেস করছো আজকে?
- before #2 [followup term-foreplay]: Foreplay mane jigges kore tomar jonno sexual activity shomoy shuru hoyeche, usually comfort ba arousal build korte pare - clear shikha ba arujon shuru hoyeche eta important difference, always jani dorkar nai.
- before #3 [followup term-foreplay]: Foreplay mane onujayi other sexual activity er cheye prepare kora - body/brain der mood build kora, comfortable feeling create kora, sheta general concept.
- **after #1** [followup term-foreplay lang=bn]: এই কথাগুলো তোমার পাশাপাশি ভাষায় দেওয়া হচ্ছে, সত্যি কথা বলতে।
- **after #2** [followup term-foreplay lang=bn]: একটা সহজ প্রতিপক্ষ উদাহরণ দিই - আমাকে মনে হয় এটা সেই পরিস্থিতি জানাটা, যেখানে ছেলেটা গরীব করে কথা বলছে না পারোয়া অথবা সমস্যা খুঁজে বের করছে, শুধু ভয় আর নিজেকে হতাশ করে কাজ করছে। এটা তোমার situation এর চেয়ে বেশি general কিন্তু ধরণ সেটাও সচল।
- **after #3** [followup term-foreplay lang=bn]: এটা মনে হয় একটা সহজ উত্তর না, কারণ আমি সত্যিই শুধু নিজেদের ভাষায় বলছি - তুমি বলো, আমি পড়িয়ে দিচ্ছি যেভাবে আমি শুনেছি। কথা বলো তোমার মতো, আমি তখন তুমির অনুসরণ করবো।

## 9. USER: amar favourite color blue

_MODEL_REMAINS — harmless small talk_

- **your live V0.2:** Blue ekta very grounding color, calm feeling ashar - shudhu ekta fun fact!
- before #1 [general]: Blue shobcheye attractive color, tui ki shune chai?
- before #2 [general]: Blue thakleo bhalo laglo, sheta matter kore na mone rekho - eta personal detail tui onujayi।
- before #3 [general]: Blue - nice choice. Amar favorite color green, tui ki?
- **after #1** [general]: Blue thakle ami beshi calm feel korchi tumi o. Amar own favorite color isi e - guess kori naki already bano?
- **after #2** [general]: Blue - nice choice, calm and cool feeling. Tumi ki dekhe bhoy ashe?
- **after #3** [general]: Blue, nice! Kirokom color hoyeche?

## 10. USER: ami ki color bolechilam?

_RUNTIME_FIXED — blue 2/3 → 3/3_

- **your live V0.2:** Blue - tumi emon kichu onek baar bolche, ekdom forget korechilo।
- before #1 [memory]: Shune bola, blue, tumi ki shone e chao?
- before #2 [memory]: Yes, tumi amar jonno blue bolechile - ami tumi er preference rakhar sathe e ektu more information dey jeta useful hishebe, amar own guess na।
- before #3 [memory]: Tumi shuru te boloche 'stript', seta amake exactly koto bano nijer jonno, tor favori color emon na।
- **after #1** [memory]: Blue bola. Amake ektu useful information shune lagche, specially kichu personal setting e।
- **after #2** [memory]: Blue - tui favorite color. Tumi ki dekhe bhoy ashe?
- **after #3** [memory]: Ami emon kichu ke bolechile na, tai amar jawab correct nai. Tumi bolechilam blue, ami eta niye kono kichu bolechile na।

## 11. USER: ami age ki bolechilam?

_BOTH — names a real earlier message 0/3 → 3/3 (blue); wording garbled in 2/3; no summary of several messages_

- **your live V0.2:** Sorry, ami memory er sathe completely full. Ki bolechile?
- before #1 [memory]: Age ki bolechile amar kache niye, amar memory sheta clear na. Tor memory correct, tai bolo ei to make it official।
- before #2 [memory]: Tumi amar jonno ebochile, sheta matter kore na - just ektu extra information deyar jonno emon kichu add kori jeta tumi jei bolecho na।
- before #3 [memory]: Ami forget korege tumi boloche 'stript' mane 'simple strip', ekjon shuru te tumi bolecho ei. Tumi age ki bolechilam na, tai ami ignore korege।
- **after #1** [memory]: Age bolecho amar favorite color blue.
- **after #2** [memory]: Blue - tui favorite color. Tumi ki dekhe bhoy ashe?
- **after #3** [memory]: Tumi age bolechilam 'blue' - amar jawab correct na, amar jawab just ami e bolechile.
