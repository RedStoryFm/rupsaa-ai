import json,re,collections
R=json.load(open('bn.json'))
BN=re.compile(r'[ঀ-৿]')
FUNC=r'\b(ar|kore|korte|kora|eta|sheta|kichu|na|hoy|ache|niye|bhoy|theke|sathe|ta|ki|koro|hobe|lage|mone|tumi|tomar|amar|kintu|shob|jodi|bolo|ekhono|ekta|chilo)\b'
BAD_MANUAL={148:'ungrammatical ("সেটাই মানুষকে বেশি ভয় পায়")',187:'garbled ("তোমার পছন্দ পছন্দ না তার")',332:'misspelling shecond'}
HUMAN={7,11,58,74,148,161,179,211,226,227,228,229,241,250,272,289,303,356,427,489}
out=collections.Counter();bysrc=collections.defaultdict(collections.Counter);why=collections.Counter()
for i,r in enumerate(R):
    t=r['reply'];b=len(BN.findall(t));lat=re.findall(r'[A-Za-z]+',t)
    if not b:
        r['label']='BANGLISH_IN_BN_CONVO';r['why']='Latin reply to a Banglish user turn inside a bn-labelled conversation'
    elif i in BAD_MANUAL: r['label']='BAD';r['why']=BAD_MANUAL[i]
    elif len(re.findall(FUNC,t))>=2:
        r['label']='BAD';r['why']='Latin Banglish clauses spliced into Bengali-script reply'
    else:
        q=[]
        if i in HUMAN: q.append('claims human life/body')
        if len(lat)>=4: q.append('4+ Latin-script English words inside Bengali')
        if re.search(r'[ঀ-৿][A-Za-z]|[A-Za-z][ঀ-৿]',t): q.append('intra-word script switch')
        r['label']='QUESTIONABLE' if q else 'GOOD';r['why']='; '.join(q)
    out[r['label']]+=1;bysrc[r['src']][r['label']]+=1;why[r['label']+': '+r['why'].split(';')[0][:60]]+=1
json.dump(R,open('bn_labelled.json','w'),ensure_ascii=False)
print(dict(out));
for s,c in bysrc.items(): print('  ',s,dict(c))
for k,v in why.most_common(12): print('   ',v,k)
