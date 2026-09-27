import json,re,collections
R=json.load(open('bl.json'))
# manual reading, every reply (0-690). BAD = incoherent / wrong word / garbled order / corrupted spelling / fabricated user memory / tone-inverted
BAD={49:'meaning inverted calque',89:'wrong word nirvor (depends)',116:'non-sequitur',129:'fabricates user history',137:'garbled word order',
     204:'wrong verb person ("feleche")',205:'nonsense ("smile kore feri")',243:'calque "eki boat e"',244:'corrupted casing poRi/paI',255:'"tar site theke" (side) wrong word',
     289:'switches to Bengali script mid-sentence',297:'"Fair observation" to a sad disclosure',315:'"Special, shobar sathe na" incoherent',
     329:'garbled word order',342:'literal translation, unclear',348:'"beshirvag" + unclear',362:'answers a question never asked',
     402:'English/Banglish grammar collision ("valuable than fake expert hoya")',420:'corrupted "prthmbarer jnj"',437:'garbled',
     477:'garbled ("kono na kono tumar experience")',488:'Hindi "bhi"',497:'garbled',510:'calque, semantically odd'}
Q_MANUAL={7:'awkward',12:'awkward',20:'Hindi "thoda"',58:'awkward',117:'typo najore',180:'odd ("useful skill")',514:'catchphrase Heyy',515:'catchphrase bindaas',
          21:'',69:'',104:'',164:''}
HUMAN={90,99,113,154,170,194,195,206,225,236,244,250,263,276,280,284,289,309,310,319,320,338,344,347,380,396,410,422,435,437,464,479,491,504,513,558,565}
TEMPLATE=re.compile(r"^(fair\b|interesting (question|thought|observation|effect|pattern)|notice kora eta|(eta|sheta) khub common|sotti bolte|depend kore|that'?s|worth )",re.I)
def english_sentence(t):
    return any(len(s.split())>=7 and not re.search(r'\b(kore|korte|eta|sheta|ar|na|hoy|ache|mane|theke|er|e|ta|ki|kono|tumi|tomar|amar|jodi|tahole|kintu|hobe|lage)\b',s.lower()) for s in re.split(r'[.!?]\s',t))
lab=[];why=collections.Counter()
for i,r in enumerate(R):
    t=r['reply'];q=[]
    if i in BAD: lab.append('BAD');why['BAD: '+ ('script/Hindi' if i in(289,488) else 'semantic/grammar')]+=1;r['label']='BAD';r['why']=BAD[i];continue
    if i in HUMAN: q.append('claims human life/body')
    if TEMPLATE.search(t.strip()): q.append('template opener')
    if english_sentence(t): q.append('full English sentence')
    if '।' in t: q.append('Bengali danda in Latin')
    if i in Q_MANUAL and Q_MANUAL[i]: q.append(Q_MANUAL[i])
    r['label']='QUESTIONABLE' if q else 'GOOD'; r['why']='; '.join(q)
    for x in q: why['Q: '+x]+=1
    lab.append(r['label'])
json.dump(R,open('bl_labelled.json','w'),ensure_ascii=False)
print(collections.Counter(lab))
for k,v in why.most_common(): print('  ',k,v)
print('by source:')
for s in ('imported','synthetic_curated','human_authored','v021_corrective_handwritten','v021_dance_handwritten'):
    c=collections.Counter(r['label'] for r in R if r['src']==s); print('  ',s,dict(c),sum(c.values()))
# weighted (training rows actually seen)
c=collections.Counter()
for r in R: c[r['label']]+=r['weight']
print('weighted by training copies',dict(c))
